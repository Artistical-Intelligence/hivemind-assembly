# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
from __future__ import annotations
import contextlib
import hashlib
import random
import re
import secrets
import shutil
import sqlite3
import threading
import time
from hivemind_assembly.automation.state_engine.hermes_cli.sqlite_util import add_column_if_missing as _add_column_if_missing
from pathlib import Path
from typing import Any
from typing import Optional
_INITIALIZED_PATHS: set[str] = set()
_INIT_LOCK = threading.RLock()
_SQLITE_HEADER = b'SQLite format 3\x00'
DEFAULT_BUSY_TIMEOUT_MS = 120000
_CORRUPT_BACKUP_RETENTION = 10
_INIT_LOCK_TIMEOUT_SECONDS = 10.0
_INIT_LOCK_POLL_SECONDS = 0.05

def _resolve_busy_timeout_ms() -> int:
    """Return the SQLite busy timeout for Kanban connections. Kanban is the
    shared cross-profile dispatch bus, so worker stampedes are expected; a
    long timeout lets WAL serialize writers instead of surfacing transient
    ``database is locked`` failures."""
    return _kb._env_int('HERMES_KANBAN_BUSY_TIMEOUT_MS', DEFAULT_BUSY_TIMEOUT_MS, minimum=1)

def _sqlite_connect(path: Path) -> sqlite3.Connection:
    """Open a Kanban SQLite connection via ``connect_tracked``: while registered,
    byte-level probes of the file are refused because an ``open()``/``close()``
    would cancel this process's POSIX advisory locks (see ``sqlite_safe_read``)."""
    from hivemind_assembly.automation.state_engine.hermes_cli.sqlite_safe_read import connect_tracked
    busy_timeout_ms = _resolve_busy_timeout_ms()
    conn = connect_tracked(path, connect_fn=sqlite3.connect, isolation_level=None, timeout=busy_timeout_ms / 1000.0)
    try:
        conn.execute(f'PRAGMA busy_timeout={busy_timeout_ms}')
    except BaseException:
        with contextlib.suppress(Exception):
            conn.close()
        raise
    return conn

def _try_lock_nb(handle) -> bool:
    """One non-blocking exclusive lock attempt on ``handle``; False when held elsewhere.
    Windows: 1-byte ``msvcrt.locking`` range at offset 0; POSIX: ``flock``."""
    if _kb._IS_WINDOWS:
        import msvcrt
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
    return True

def _unlock(handle) -> None:
    """Release a lock taken by :func:`_try_lock_nb` (same byte range / flock)."""
    if _kb._IS_WINDOWS:
        import msvcrt
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

@contextlib.contextmanager
def _cross_process_init_lock(path: Path):
    """Serialize first-connect WAL/schema/integrity setup across processes.

    ``_INIT_LOCK`` only covers one process's threads; a dispatcher burst has
    many worker processes hit a fresh/legacy board with empty
    ``_INITIALIZED_PATHS`` caches. Post-init usage stays concurrent under WAL.

    **Bounded** acquire: a blocking ``flock`` let one stalled/stale holder hang
    every ``connect()`` (the gateway dispatcher's next tick included) with no
    traceback. After the deadline we WARN and proceed WITHOUT the lock — safe
    because ``_INIT_LOCK`` still serializes same-process threads and init is
    idempotent: two racing first-inits mean redundant work, not corruption.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + '.init.lock')
    handle = lock_path.open('a+b')
    acquired = False
    try:
        deadline = time.monotonic() + _INIT_LOCK_TIMEOUT_SECONDS
        while True:
            try:
                acquired = _try_lock_nb(handle)
            except OSError:
                acquired = False
            if acquired or time.monotonic() >= deadline:
                break
            time.sleep(_INIT_LOCK_POLL_SECONDS)
        if not acquired:
            _kb._log.warning('kanban init lock for %s not acquired within %.0fs — proceeding without the cross-process lock (in-process lock + idempotent init are the correctness backstop). A stuck holder is no longer able to block this connect indefinitely (#36644).', lock_path, _INIT_LOCK_TIMEOUT_SECONDS)
        yield
    finally:
        try:
            if acquired:
                _unlock(handle)
        finally:
            handle.close()

def _looks_like_tls_record_at(data: bytes, offset: int) -> bool:
    """Return True for a TLS record header at ``data[offset:]``."""
    if len(data) < offset + 5:
        return False
    content_type, major, minor = (data[offset], data[offset + 1], data[offset + 2])
    length = int.from_bytes(data[offset + 3:offset + 5], 'big')
    return content_type in {20, 21, 22, 23} and major == 3 and (minor in {0, 1, 2, 3, 4}) and (0 < length <= 18432)

def _validate_sqlite_header(path: Path) -> None:
    """Fail early with an actionable error for non-SQLite Kanban DB files.
    ``sqlite3.connect()`` creates missing and zero-byte files, so those pass;
    non-empty files must carry the SQLite header, so a corrupt page 0 isn't
    collapsed into a generic PRAGMA error and the gateway's corrupt-board
    handling can identify the board by fingerprint."""
    try:
        if path.stat().st_size == 0:
            return
    except OSError:
        return
    from hivemind_assembly.automation.state_engine.hermes_cli.sqlite_safe_read import read_header_bytes_preopen
    head = read_header_bytes_preopen(path, length=64)
    if head is None or head.startswith(_SQLITE_HEADER):
        return
    signature = ''
    if head.startswith(b'SQLit') and _looks_like_tls_record_at(head, 5):
        signature = ' (TLS record header detected at byte offset 5)'
    elif _looks_like_tls_record_at(head, 0):
        signature = ' (TLS record header detected at byte offset 0)'
    raise sqlite3.DatabaseError(f'file is not a database: invalid SQLite header for {path}{signature}; first_32={head[:32].hex(' ')}')

class KanbanDbCorruptError(RuntimeError):
    """Raised when an existing kanban DB file fails integrity checks — a
    fail-closed guard against silently recreating a corrupt board (which would
    destroy the user's tasks). Carries the path and the backup made first."""

    def __init__(self, db_path: Path, backup_path: Optional[Path], reason: str):
        self.db_path = db_path
        self.backup_path = backup_path
        self.reason = reason
        super().__init__(f'Refusing to open corrupt kanban DB at {db_path}: {reason}. Original preserved; backup at {_backup_label(backup_path)}.')

def _backup_label(backup_path: Optional[Path]) -> str:
    return str(backup_path) if backup_path is not None else '<backup failed>'

def _prune_corrupt_backups(parent: Path, base_name: str, keep: Optional[Path]=None) -> None:
    """Keep only the ``_CORRUPT_BACKUP_RETENTION`` newest (by mtime)
    ``<db>.corrupt.<hash>.bak`` files plus their ``-wal``/``-shm`` copies.
    ``keep`` (the just-created backup) is never pruned regardless of mtime —
    ``shutil.copy2`` preserves the source timestamp, which may be older than
    existing backups. Best-effort: prune failures never mask the corruption
    error the caller is about to raise."""
    try:
        backups = [candidate for candidate in parent.glob(f'{base_name}.corrupt.*.bak') if candidate.is_file() and candidate != keep]
    except OSError:
        return
    budget = max(_CORRUPT_BACKUP_RETENTION - (1 if keep is not None else 0), 0)
    if len(backups) <= budget:
        return

    def _mtime(item: Path) -> float:
        try:
            return item.stat().st_mtime
        except OSError:
            return 0.0
    backups.sort(key=_mtime, reverse=True)
    for stale in backups[budget:]:
        for victim in (stale, stale.with_name(stale.name + '-wal'), stale.with_name(stale.name + '-shm')):
            with contextlib.suppress(OSError):
                victim.unlink(missing_ok=True)

def _backup_corrupt_db(path: Path) -> Optional[Path]:
    """Copy a corrupt DB (and WAL/SHM sidecars) to a content-addressed backup.
    The name is deterministic in the main DB's sha256, so repeated quarantines
    of the same bytes reuse one backup while changed bytes get a separate one.
    Returns the main backup path, or ``None`` if the copy failed (the caller
    still raises loudly). Writes are confined to the DB's parent directory:
    the basename derives only from ``path.name`` + content hash."""
    resolved = path.resolve()
    parent = resolved.parent
    base_name = resolved.name
    from hivemind_assembly.automation.state_engine.hermes_cli.sqlite_safe_read import has_live_connection
    if has_live_connection(resolved):
        _kb._log.error("refusing to quarantine %s: a connection to it is still open in this process, and fingerprinting the file would cancel that connection's POSIX locks. Close all connections first.", resolved)
        return None
    digest = hashlib.sha256()
    try:
        with resolved.open('rb') as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                digest.update(chunk)
    except OSError:
        return None
    candidate = parent / f'{base_name}.corrupt.{digest.hexdigest()[:16]}.bak'
    if candidate.parent != parent:
        return None
    if not candidate.exists():
        try:
            shutil.copy2(resolved, candidate)
        except OSError:
            return None
        _prune_corrupt_backups(parent, base_name, keep=candidate)
    for suffix in ('-wal', '-shm'):
        sidecar = parent / (base_name + suffix)
        sidecar_backup = parent / (candidate.name + suffix)
        if sidecar.parent != parent or not sidecar.exists() or sidecar_backup.parent != parent or sidecar_backup.exists():
            continue
        with contextlib.suppress(OSError):
            shutil.copy2(sidecar, sidecar_backup)
    return candidate
_REPAIRABLE_INDEX_ERROR_PATTERNS = (re.compile('^wrong # of entries in index (?P<index>.+)$'), re.compile('^row \\d+ missing from index (?P<index>.+)$'))

def _integrity_messages_ok(messages: list[str]) -> bool:
    """True iff ``PRAGMA integrity_check`` output is the single ``ok`` row."""
    return len(messages) == 1 and messages[0].strip().lower() == 'ok'

def _run_integrity_check(conn: sqlite3.Connection) -> list[str]:
    """Return all ``PRAGMA integrity_check`` message rows as strings."""
    rows = conn.execute('PRAGMA integrity_check').fetchall()
    return [str(row[0]) for row in rows if row is not None and row[0] is not None]

def _probe_integrity(path: Path) -> list[str]:
    """Open ``path`` read/write (so SQLite can recover/checkpoint a healthy WAL
    / hot-journal DB before we judge it) and return ``integrity_check``
    messages. ``OperationalError`` (locked/busy) propagates raw — not corruption."""
    probe = _sqlite_connect(path)
    try:
        return _run_integrity_check(probe)
    finally:
        probe.close()

def _repairable_index_names(messages: list[str]) -> Optional[list[str]]:
    """Distinct index names iff EVERY message is index-repairable, else ``None``
    (caller fails closed; also ``None`` for no messages). First-appearance
    order is preserved so the REINDEX pass is deterministic."""
    names: list[str] = []
    for raw in messages:
        message = (raw or '').strip()
        if not message:
            continue
        for pattern in _REPAIRABLE_INDEX_ERROR_PATTERNS:
            match = pattern.match(message)
            if match:
                break
        else:
            return None
        name = match.group('index').strip()
        if name and name not in names:
            names.append(name)
    return names or None

def _attempt_index_reindex_repair(path: Path, index_names: list[str]) -> tuple[bool, list[str]]:
    """REINDEX the named indexes (per-index first; bare ``REINDEX`` fallback if
    a parsed name is an internal/auto index), then re-run integrity_check.
    Returns ``(clean, post_repair_messages)``; never raises. Callers must hold
    the board's cross-process init flock so nothing connects mid-repair."""
    try:
        conn = _sqlite_connect(path)
    except sqlite3.Error as exc:
        return (False, [f'could not reopen for REINDEX: {exc}'])
    try:
        try:
            for name in index_names:
                escaped = name.replace('"', '""')
                conn.execute(f'REINDEX "{escaped}"')
        except sqlite3.Error:
            conn.execute('REINDEX')
        messages = _run_integrity_check(conn)
    except sqlite3.Error as exc:
        return (False, [f'REINDEX failed: {exc}'])
    finally:
        conn.close()
    return (_integrity_messages_ok(messages), messages)

def _missing_or_empty(resolved: Path) -> bool:
    """True for a missing / zero-byte / unstat-able DB file — nothing to probe."""
    try:
        return not resolved.exists() or resolved.stat().st_size == 0
    except OSError:
        return True

def _probe_for_corruption(resolved: Path) -> tuple[Optional[list[str]], Optional[str]]:
    """``(messages, reason)`` from an integrity probe; ``reason`` is ``None``
    when healthy and ``messages`` is ``None`` when sqlite refused to open the
    file at all. ``OperationalError`` (lock/busy) is NOT corruption and
    propagates raw so a locked healthy DB is never quarantined."""
    try:
        messages = _probe_integrity(resolved)
    except sqlite3.OperationalError:
        raise
    except sqlite3.DatabaseError as exc:
        return (None, f'sqlite refused to open file: {exc}')
    if _integrity_messages_ok(messages):
        return (messages, None)
    return (messages, f'integrity_check returned {(messages[0] if messages else '<no row>')!r}')

def _guard_existing_db_is_healthy(path: Path) -> None:
    """Run ``PRAGMA integrity_check`` on an existing non-empty DB file.

    Narrow auto-repair when the failure is ONLY index-scoped (table b-trees
    intact): content-addressed corrupt backup FIRST, REINDEX under the
    caller-held init flock, re-check, proceed only if clean. Anything else
    (page corruption, ``malformed``, unclean re-check) fails closed: back up
    the file + sidecars and raise :class:`KanbanDbCorruptError` so callers
    never recreate the schema on top of a damaged DB. ``OperationalError``
    (lock/busy) is NOT corruption and propagates raw (no spurious backup).
    No-op for missing / zero-byte files and paths already proven healthy this
    process. All writes are confined to the resolved path's parent.
    """
    try:
        resolved = path.resolve()
    except OSError:
        return
    if _missing_or_empty(resolved) or str(resolved) in _INITIALIZED_PATHS:
        return
    messages, reason = _probe_for_corruption(resolved)
    if reason is None:
        return
    backup = _backup_corrupt_db(resolved)
    index_names = _repairable_index_names(messages or [])
    if index_names:
        _kb._log.warning('kanban DB %s failed integrity_check with index-only errors (%s); pre-repair backup at %s — attempting REINDEX auto-repair.', resolved, ', '.join(index_names), _backup_label(backup))
        repaired, post = _attempt_index_reindex_repair(resolved, index_names)
        if repaired:
            _kb._log.warning('kanban DB %s auto-repaired via REINDEX (%s); integrity_check now clean. Pre-repair copy kept at %s.', resolved, ', '.join(index_names), _backup_label(backup))
            return
        reason = f'{reason}; REINDEX auto-repair attempted but integrity_check still returned {(post[0] if post else '<no row>')!r}'
    raise KanbanDbCorruptError(resolved, backup, reason)

def _schema_is_present(conn: sqlite3.Connection) -> bool:
    """Whether an open connection actually sees the kanban schema. ``tasks`` is
    the sentinel (SCHEMA_SQL always creates it; SQLite loses tables
    all-or-nothing), so one ``sqlite_master`` lookup on the resident page 1
    suffices — cheap by design, it runs on every steady-state connect()."""
    try:
        row = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='tasks' LIMIT 1").fetchone()
    except sqlite3.DatabaseError:
        return False
    return row is not None

def _open_configured(path: Path, under_lock) -> tuple[sqlite3.Connection, Any]:
    """Open ``path`` with the kanban PRAGMA set, then run ``under_lock(conn)``.
    WAL activation and ``under_lock`` share the ``_INIT_LOCK`` critical section:
    WAL setup can take an exclusive lock while SQLite creates sidecars for a
    fresh DB, and concurrent gateway startup threads must not race before
    ``_INITIALIZED_PATHS`` is populated. Closed if anything raises."""
    conn = _sqlite_connect(path)
    try:
        conn.row_factory = sqlite3.Row
        conn.text_factory = _kb._lossy_text
        with _INIT_LOCK:
            from hivemind_assembly.automation.state_engine.hermes_state_wal import apply_wal_with_fallback
            apply_wal_with_fallback(conn, db_label=f'kanban.db ({path.name})')
            conn.execute('PRAGMA synchronous=FULL')
            conn.execute('PRAGMA wal_autocheckpoint=100')
            conn.execute('PRAGMA journal_size_limit=8388608')
            conn.execute('PRAGMA foreign_keys=ON')
            conn.execute('PRAGMA secure_delete=ON')
            conn.execute('PRAGMA cell_size_check=ON')
            out = under_lock(conn)
    except Exception:
        conn.close()
        raise
    return (conn, out)

def _refuse_dead_board_resurrection(path: Path, board: Optional[str]) -> None:
    """Refuse to create a fresh DB for a board that is not live.

    ``board=None`` (or ``default``) is unaffected — except that a None board
    can still *resolve* through the current-board context (``--board`` scope,
    ``HERMES_KANBAN_BOARD``, the ``current`` file) to a named board dir; an
    ``archived`` tombstone in that dir gets the same refusal. For any other
    slug whose DB file does not exist yet, opening it would mkdir the board
    directory and leave an empty DB-only stub — exactly how archived boards
    (moved to ``_archived/`` with an ``archived`` tombstone ``board.json``) and
    hard-deleted boards (no directory left at all) used to reappear as empty
    active boards via stale dashboard/gateway read paths (#43243). Creation
    is the job of :func:`kanban_db.create_board` (which writes the metadata
    first); read paths get an actionable error instead of a resurrected board.
    """
    if path.exists():
        return
    if board is None:
        tombstone = path.parent / 'board.json'
        if tombstone.exists():
            import json
            try:
                raw = json.loads(tombstone.read_text(encoding='utf-8-sig'))
            except (OSError, ValueError):
                return
            if isinstance(raw, dict) and raw.get('archived'):
                raise ValueError(f'kanban board {path.parent.name!r} is archived; refusing to recreate its database')
        return
    try:
        slug = _kb._normalize_board_slug(board)
    except ValueError:
        return
    if not slug or slug == _kb.DEFAULT_BOARD:
        return
    meta = _kb.read_board_metadata(slug)
    if meta.get('archived'):
        raise ValueError(f'kanban board {slug!r} is archived; refusing to recreate its database')
    if not _kb.board_metadata_path(slug).exists():
        raise ValueError(f'kanban board {slug!r} does not exist; create it with `hermes kanban boards create {slug}`')

def connect(db_path: Optional[Path]=None, *, board: Optional[str]=None) -> sqlite3.Connection:
    """Open (and initialize if needed) the kanban DB. WAL is (re)enabled on
    every connection so a re-created file stays robust; the first connection
    per path auto-runs :func:`init_db`, later ones skip via
    ``_INITIALIZED_PATHS``. Path: explicit ``db_path``, else ``board``, else
    :func:`kanban_db_path` (``HERMES_KANBAN_DB`` -> ``HERMES_KANBAN_BOARD`` ->
    ``<root>/kanban/current`` -> ``default``)."""
    path = db_path if db_path is not None else _kb.kanban_db_path(board=board)
    from hivemind_assembly.automation.state_engine.agent.delegation_context import kanban_path_is_fenced
    if kanban_path_is_fenced(path):
        conn = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
        conn.row_factory = sqlite3.Row
        conn.text_factory = _kb._lossy_text
        if not _schema_is_present(conn):
            conn.close()
            raise PermissionError('Kanban descendants require an initialized board; ask its owner to initialize it')
        return conn
    _refuse_dead_board_resurrection(path, board)
    path.parent.mkdir(parents=True, exist_ok=True)
    resolved = str(path.resolve())
    if resolved in _INITIALIZED_PATHS:
        conn, schema_present = _open_configured(path, _schema_is_present)
        if schema_present:
            return conn
        conn.close()
        with _INIT_LOCK:
            _INITIALIZED_PATHS.discard(resolved)
        _kb._log.warning('kanban DB %s lost its schema after this process initialized it (deleted or replaced externally); re-initializing.', path)
    with _cross_process_init_lock(path):
        from hivemind_assembly.automation.state_engine.hermes_state import preflight_db_writability
        preflight_db_writability(path, db_label=f'kanban.db ({path.name})')
        _validate_sqlite_header(path)
        _guard_existing_db_is_healthy(path)
        resolved = str(path.resolve())

        def _init_if_needed(conn: sqlite3.Connection) -> None:
            if resolved not in _INITIALIZED_PATHS:
                conn.executescript(_kb.SCHEMA_SQL)
                _migrate_add_optional_columns(conn)
                _INITIALIZED_PATHS.add(resolved)
        conn, _ = _open_configured(path, _init_if_needed)
    return conn
_BASE_TASK_COLUMNS = (('body', 'body TEXT'), ('assignee', 'assignee TEXT'), ('priority', 'priority INTEGER DEFAULT 0'), ('created_by', 'created_by TEXT'), ('started_at', 'started_at INTEGER'), ('completed_at', 'completed_at INTEGER'), ('workspace_kind', "workspace_kind TEXT NOT NULL DEFAULT 'scratch'"), ('workspace_path', 'workspace_path TEXT'), ('claim_lock', 'claim_lock TEXT'), ('claim_expires', 'claim_expires INTEGER'))
_EARLY_TASK_COLUMNS = (('tenant', 'tenant TEXT'), ('result', 'result TEXT'), ('branch_name', 'branch_name TEXT'), ('project_id', 'project_id TEXT'), ('idempotency_key', 'idempotency_key TEXT'))
_RENAMED_TASK_COLUMNS = (('consecutive_failures', 'consecutive_failures INTEGER NOT NULL DEFAULT 0', 'spawn_failures', 'UPDATE tasks SET consecutive_failures = COALESCE(spawn_failures, 0)'), ('worker_pid', 'worker_pid INTEGER', None, None), ('last_failure_error', 'last_failure_error TEXT', 'last_spawn_error', 'UPDATE tasks SET last_failure_error = last_spawn_error'))
_LATER_TASK_COLUMNS = (('max_runtime_seconds', 'max_runtime_seconds INTEGER'), ('last_heartbeat_at', 'last_heartbeat_at INTEGER'), ('current_run_id', 'current_run_id INTEGER'), ('workflow_template_id', 'workflow_template_id TEXT'), ('current_step_key', 'current_step_key TEXT'), ('skills', 'skills TEXT'), ('max_retries', 'max_retries INTEGER'), ('model_override', 'model_override TEXT'), ('provider_override', 'provider_override TEXT'), ('reasoning_effort', 'reasoning_effort TEXT'), ('goal_mode', 'goal_mode INTEGER NOT NULL DEFAULT 0'), ('goal_max_turns', 'goal_max_turns INTEGER'), ('completion_contract', 'completion_contract TEXT'), ('session_id', 'session_id TEXT'), ('block_kind', 'block_kind TEXT'), ('block_recurrences', 'block_recurrences INTEGER NOT NULL DEFAULT 0'), ('worker_started_at', 'worker_started_at INTEGER'))
_NOTIFY_SUB_COLUMNS = (('last_ping_event_id', 'last_ping_event_id INTEGER NOT NULL DEFAULT 0'), ('notifier_profile', 'notifier_profile TEXT'), ('delivery_mode', "delivery_mode TEXT NOT NULL DEFAULT 'notify'"), ('chat_type', 'chat_type TEXT'), ('user_id_alt', 'user_id_alt TEXT'), ('delivery_metadata', 'delivery_metadata TEXT'))
_TASK_RUN_COLUMNS = (('worker_started_at', 'worker_started_at INTEGER'),)

def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row['name'] for row in conn.execute(f'PRAGMA table_info({table})')}

def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'").fetchone() is not None

def _migrate_add_optional_columns(conn: sqlite3.Connection) -> None:
    """Add columns introduced after v1 to legacy DBs (called via ``init_db``)."""
    cols = _column_names(conn, 'tasks')
    for name, ddl in _BASE_TASK_COLUMNS + _EARLY_TASK_COLUMNS:
        if name not in cols:
            _add_column_if_missing(conn, 'tasks', name, ddl)
    cols = _column_names(conn, 'tasks')
    for name, ddl, legacy, copy_sql in _RENAMED_TASK_COLUMNS:
        if name not in cols:
            added = _add_column_if_missing(conn, 'tasks', name, ddl)
            if added and legacy is not None and (legacy in cols):
                conn.execute(copy_sql)
    for name, ddl in _LATER_TASK_COLUMNS:
        if name not in cols:
            _add_column_if_missing(conn, 'tasks', name, ddl)
    conn.execute('CREATE INDEX IF NOT EXISTS idx_tasks_assignee_status ON tasks(assignee, status)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_tasks_tenant ON tasks(tenant)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_tasks_idempotency ON tasks(idempotency_key)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_tasks_session_id ON tasks(session_id)')
    if 'run_id' not in _column_names(conn, 'task_events'):
        _add_column_if_missing(conn, 'task_events', 'run_id', 'run_id INTEGER')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_events_run ON task_events(run_id, id)')
    if _table_exists(conn, 'kanban_notify_subs'):
        notify_cols = _column_names(conn, 'kanban_notify_subs')
        for name, ddl in _NOTIFY_SUB_COLUMNS:
            if name in notify_cols:
                continue
            _add_column_if_missing(conn, 'kanban_notify_subs', name, ddl)
            if name == 'delivery_mode':
                conn.execute("UPDATE kanban_notify_subs SET delivery_mode = 'notify+wake' WHERE platform != 'tui'")
    if _table_exists(conn, 'task_runs'):
        run_cols = _column_names(conn, 'task_runs')
        for name, ddl in _TASK_RUN_COLUMNS:
            if name not in run_cols:
                _add_column_if_missing(conn, 'task_runs', name, ddl)
        _backfill_legacy_inflight_runs(conn)
    for old, new in (('ready', 'promoted'), ('priority', 'reprioritized'), ('spawn_auto_blocked', 'gave_up')):
        conn.execute('UPDATE task_events SET kind = ? WHERE kind = ?', (new, old))
    _rebuild_drifted_tables(conn)

def _backfill_legacy_inflight_runs(conn: sqlite3.Connection) -> None:
    """One-shot backfill: tasks 'running' before runs existed carried
    claim_lock / claim_expires / worker_pid on the task row; synthesize a
    matching task_runs row so end-run / heartbeat have something to write.
    write_txn serializes against concurrent dispatchers, and the per-row
    UPDATE uses ``current_run_id IS NULL`` as a CAS guard so a racing claim
    can't produce an orphaned row."""
    with write_txn(conn):
        inflight = conn.execute("SELECT id, assignee, claim_lock, claim_expires, worker_pid,        max_runtime_seconds, last_heartbeat_at, started_at FROM tasks WHERE status = 'running' AND current_run_id IS NULL").fetchall()
        for row in inflight:
            started = row['started_at'] or int(time.time())
            cur = conn.execute("\n                INSERT INTO task_runs (\n                    task_id, profile, status,\n                    claim_lock, claim_expires, worker_pid,\n                    max_runtime_seconds, last_heartbeat_at,\n                    started_at\n                ) VALUES (?, ?, 'running', ?, ?, ?, ?, ?, ?)\n                ", (row['id'], row['assignee'], row['claim_lock'], row['claim_expires'], row['worker_pid'], row['max_runtime_seconds'], row['last_heartbeat_at'], started))
            upd = conn.execute('UPDATE tasks SET current_run_id = ? WHERE id = ? AND current_run_id IS NULL', (cur.lastrowid, row['id']))
            if upd.rowcount != 1:
                conn.execute("UPDATE task_runs SET status = 'reclaimed',     outcome = 'reclaimed', ended_at = ? WHERE id = ?", (int(time.time()), cur.lastrowid))
_REBUILD_SPECS = {'task_events': ('CREATE TABLE task_events ( id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, run_id INTEGER, kind TEXT NOT NULL, payload TEXT, created_at INTEGER NOT NULL)', ('CREATE INDEX idx_events_task ON task_events(task_id, created_at)', 'CREATE INDEX idx_events_run ON task_events(run_id, id)')), 'task_comments': ('CREATE TABLE task_comments ( id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, author TEXT NOT NULL, body TEXT NOT NULL, created_at INTEGER NOT NULL)', ('CREATE INDEX idx_comments_task ON task_comments(task_id, created_at)',)), 'task_runs': ('CREATE TABLE task_runs ( id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, profile TEXT, step_key TEXT, status TEXT NOT NULL, claim_lock TEXT, claim_expires INTEGER, worker_pid INTEGER, worker_started_at INTEGER, max_runtime_seconds INTEGER, last_heartbeat_at INTEGER, started_at INTEGER NOT NULL, ended_at INTEGER, outcome TEXT, summary TEXT, metadata TEXT, error TEXT)', ('CREATE INDEX idx_runs_task ON task_runs(task_id, started_at)', 'CREATE INDEX idx_runs_status ON task_runs(status)')), 'kanban_notify_subs': ("CREATE TABLE kanban_notify_subs ( task_id TEXT NOT NULL, platform TEXT NOT NULL, chat_id TEXT NOT NULL, thread_id TEXT NOT NULL DEFAULT '', user_id TEXT, user_id_alt TEXT, chat_type TEXT, notifier_profile TEXT, delivery_mode TEXT NOT NULL DEFAULT 'notify', delivery_metadata TEXT, created_at INTEGER NOT NULL, last_event_id INTEGER NOT NULL DEFAULT 0, last_ping_event_id INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (task_id, platform, chat_id, thread_id))", ('CREATE INDEX idx_notify_task ON kanban_notify_subs(task_id)',))}

def _table_has_drifted(conn: sqlite3.Connection, table: str) -> bool:
    """True when ``table`` still carries the legacy (pre-AUTOINCREMENT) shape."""
    info = conn.execute(f'PRAGMA table_info({table})').fetchall()
    if not info:
        return False
    if table == 'kanban_notify_subs':
        lei = next((c for c in info if c['name'] == 'last_event_id'), None)
        return lei is not None and (lei['type'] or '').upper() != 'INTEGER'
    id_col = next((c for c in info if c['name'] == 'id'), None)
    if id_col is None:
        return False
    return not ((id_col['type'] or '').upper() == 'INTEGER' and id_col['pk'])

def _rebuild_drifted_tables(conn: sqlite3.Connection) -> None:
    """Rebuild any kanban table whose column types drifted from SCHEMA_SQL.

    Drifted boards crash the gateway notifier (``int(None)`` on a NULL id) and
    never match ``id > cursor``, silently losing every notification. Legacy
    TEXT ids are dropped (AUTOINCREMENT reassigns) and cursors reset to 0, so
    the first post-migration tick replays history once — safe for a feature
    that was already fully broken. One transaction under ``connect()``'s init
    locks so an interruption can't leave a table half-renamed. Idempotent.

    Each affected table is rebuilt with the standard SQLite pattern — CREATE new → INSERT shared columns →
    DROP old → RENAME — recreating its indexes too (DROP TABLE takes them down). See #35096.
    """
    drifted = [t for t in _REBUILD_SPECS if _table_has_drifted(conn, t)]
    if not drifted:
        return
    conn.execute('BEGIN IMMEDIATE')
    try:
        for table in drifted:
            create_sql, index_sqls = _REBUILD_SPECS[table]
            old_cols = [c['name'] for c in conn.execute(f'PRAGMA table_info({table})')]
            _kb._log.info('kanban migration: rebuilding %s to match current schema', table)
            conn.execute(f'ALTER TABLE {table} RENAME TO {table}_legacy')
            conn.execute(create_sql)
            new_cols = _column_names(conn, table)
            if table == 'kanban_notify_subs':
                drop, extra_cols = ('last_event_id', ', last_event_id')
                extra_select = ', COALESCE(CAST(last_event_id AS INTEGER), 0)'
            else:
                drop, extra_cols, extra_select = ('id', '', '')
            cols_csv = ', '.join((c for c in old_cols if c in new_cols and c != drop))
            conn.execute(f'INSERT INTO {table} ({cols_csv}{extra_cols}) SELECT {cols_csv}{extra_select} FROM {table}_legacy')
            conn.execute(f'DROP TABLE {table}_legacy')
            for index_sql in index_sqls:
                conn.execute(index_sql)
        conn.execute('COMMIT')
    except Exception:
        with contextlib.suppress(sqlite3.OperationalError):
            conn.execute('ROLLBACK')
        raise

def _check_file_length_invariant(conn: sqlite3.Connection) -> None:
    """Raise ``sqlite3.DatabaseError`` if the file is shorter than its header
    page count claims (torn-extend). Both sides are read WITHOUT opening the
    database file (``PRAGMA page_count`` on the existing connection; ``stat()``
    for disk): an earlier bare ``open(path,"rb")`` probe was wrong because
    ``close()`` cancels every POSIX advisory lock this process holds on the
    file, silently dropping concurrent writers' (and a running VACUUM's) locks
    and letting other processes write into a database a writer still believed
    it owned (sqlite.org/howtocorrupt.html §2.2)."""
    from hivemind_assembly.automation.state_engine.hermes_cli.sqlite_safe_read import file_length_matches_header
    try:
        row = conn.execute('PRAGMA journal_mode').fetchone()
        journal_mode = str(row[0]).lower() if row and row[0] is not None else ''
    except sqlite3.Error:
        return
    if journal_mode == 'wal':
        return
    if file_length_matches_header(conn) is False:
        raise sqlite3.DatabaseError('torn-extend detected: the database file is shorter than its header page count claims')
_BUSY_MAX_RETRIES = 5
_BUSY_RETRY_MIN_S = 0.02
_BUSY_RETRY_MAX_S = 0.15

def _is_busy_error(exc: BaseException) -> bool:
    return isinstance(exc, sqlite3.OperationalError) and ('database is locked' in str(exc).lower() or 'database is busy' in str(exc).lower())

def _execute_boundary_with_retry(conn: sqlite3.Connection, sql: str) -> None:
    for attempt in range(_BUSY_MAX_RETRIES + 1):
        try:
            conn.execute(sql)
            return
        except sqlite3.OperationalError as exc:
            if not _is_busy_error(exc) or attempt == _BUSY_MAX_RETRIES:
                raise
            time.sleep(random.uniform(_BUSY_RETRY_MIN_S, _BUSY_RETRY_MAX_S))

def _main_db_file(conn: sqlite3.Connection) -> Optional[str]:
    """Filesystem path of *conn*'s main database (None for in-memory / unreadable)."""
    try:
        for _seq, name, file in conn.execute('PRAGMA database_list') or ():
            if name == 'main':
                return file or None
    except (sqlite3.Error, TypeError, ValueError):
        pass
    return None

@contextlib.contextmanager
def write_txn(conn: sqlite3.Connection, *, allow_nested: bool=False):
    """IMMEDIATE write transaction; a claim CAS inside is atomic — at most one
    concurrent writer succeeds.

    Nesting is an explicit opt-in (``allow_nested=True`` → savepoint; otherwise
    a loud ``RuntimeError``). Only composition primitives (``create_task``,
    ``add_comment``) opt in — helpers with post-commit side effects
    (``complete_task`` & co.) must never run under an open outer transaction,
    since those side effects would fire while the outer txn can still roll back.
    """
    _kb._assert_not_delegated_child_mutation(_main_db_file(conn))
    if getattr(conn, 'in_transaction', False):
        if not allow_nested:
            raise RuntimeError('write_txn: already inside a transaction. Nested composition must opt in explicitly with write_txn(conn, allow_nested=True) (savepoint semantics; the inner RELEASE is not durable until the outer transaction commits).')
        savepoint = f'hermes_nested_{secrets.token_hex(8)}'
        conn.execute(f'SAVEPOINT {savepoint}')
        try:
            yield conn
        except Exception:
            with contextlib.suppress(sqlite3.OperationalError):
                conn.execute(f'ROLLBACK TO {savepoint}')
                conn.execute(f'RELEASE {savepoint}')
            raise
        else:
            conn.execute(f'RELEASE {savepoint}')
        return
    _execute_boundary_with_retry(conn, 'BEGIN IMMEDIATE')
    try:
        yield conn
    except Exception:
        with contextlib.suppress(sqlite3.OperationalError):
            conn.execute('ROLLBACK')
        raise
    else:
        try:
            _execute_boundary_with_retry(conn, 'COMMIT')
        except Exception:
            with contextlib.suppress(sqlite3.OperationalError):
                conn.execute('ROLLBACK')
            raise
        _check_file_length_invariant(conn)
from hivemind_assembly.automation.state_engine.hermes_cli import kanban_db as _kb
