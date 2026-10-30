# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
from __future__ import annotations
import contextlib
import functools
import logging
import os
import sqlite3
import sys
import threading
import time
from typing import Any, Optional
from hivemind_assembly.automation.state_engine.hermes_cli.sqlite_runtime import is_sqlite_wal_reset_vulnerable as _is_sqlite_wal_reset_vulnerable
from hivemind_assembly.automation.state_engine.hermes_state_errors import is_sqlite_lock_error
logger = logging.getLogger('hermes_state')
_WAL_INCOMPAT_MARKERS = ('locking protocol', 'not authorized', 'disk i/o error')
_WAL_SIZE_LIMIT_BYTES = 64 * 1024 * 1024
_wal_fallback_warned_paths: set[str] = set()
_wal_fallback_warned_lock = threading.Lock()
_wal_delete_fallback_failed_paths: set[str] = set()
_wal_delete_fallback_failed_lock = threading.Lock()
_wal_probe_unknown_paths: set[str] = set()
_wal_probe_unknown_lock = threading.Lock()
_wal_reset_bug_warned_paths: set[str] = set()
_wal_reset_bug_warned_lock = threading.Lock()
_delete_overridden_warned_paths: set[str] = set()
_delete_overridden_warned_lock = threading.Lock()
_journal_upgrade_warned_paths: set = set()
_journal_upgrade_warned_lock = threading.Lock()
_CANNOT_VERIFY_DELETE_MSG = 'could not verify journal mode before applying configured journal_mode=delete (database is locked — possible concurrent openers); refusing to downgrade a database this process does not exclusively own'

def _mode_from_row(row) -> str:
    """Lower-cased mode from a ``PRAGMA journal_mode`` row, ``""`` if no row."""
    return str(row[0]).strip().lower() if row and row[0] is not None else ''

def _on_disk_journal_mode(conn: sqlite3.Connection) -> Optional[str]:
    """Read the journal mode from the DB header; ``None`` if undeterminable (new DB, or PRAGMA failed) ->
    callers take their fail-closed "refuse to downgrade" branch. ``disk i/o error`` can be transient on
    virtualized block devices (XFS on cloud hosts), so it is retried a few times first."""
    for _ in range(4):
        try:
            row = conn.execute('PRAGMA journal_mode').fetchone()
        except sqlite3.OperationalError as exc:
            if 'disk i/o error' not in str(exc).lower():
                return None
            last_exc = exc
            time.sleep(0.05)
            continue
        mode = row[0] if row else None
        if isinstance(mode, bytes):
            try:
                mode = mode.decode('ascii')
            except UnicodeDecodeError:
                return None
        return str(mode).strip().lower() if mode is not None else None
    logger.debug('_on_disk_journal_mode: retries exhausted on disk read (%s)', last_exc)
    return None

def _apply_wal_size_limit(conn: sqlite3.Connection) -> None:
    """Bound the WAL so it returns space after big transactions. With the default (-1) a checkpointed WAL is
    reused in place, never truncated, so ``state.db-wal`` keeps the high-water mark of the largest
    transaction ever (a 3 GB optimize left a 3 GB WAL). Best-effort: failure only costs disk slack."""
    try:
        conn.execute(f'PRAGMA journal_size_limit={_WAL_SIZE_LIMIT_BYTES}')
    except sqlite3.OperationalError as exc:
        logger.debug('journal_size_limit not applied: %s', exc)

def _darwin_pragma(conn: sqlite3.Connection, pragma: str) -> None:
    """Best-effort PRAGMA on macOS only (no-op elsewhere, never raises)."""
    if sys.platform == 'darwin':
        with contextlib.suppress(sqlite3.OperationalError):
            conn.execute(pragma)

def _apply_macos_checkpoint_barrier(conn: sqlite3.Connection) -> None:
    """Enable ``PRAGMA checkpoint_fullfsync`` on macOS. Apple's ``fsync(2)`` guarantees neither data-on-platter nor
    ordering, so without ``F_FULLFSYNC`` a launchd shutdown can turn a "durable" checkpoint into a malformed
    ``state.db``. Checkpoint boundaries only (~+0.1 ms/commit vs ~+4 ms for ``fullfsync=1``).

    During a launchd *system* shutdown/reboot the OS page cache is dropped (effectively a power-loss event
    for in-flight pages), so a WAL checkpoint whose ``fsync()`` "reported" durable may never have hit the
    platter — corrupting ``state.db`` with a malformed image. This is the trigger in issue #30636 ("SIGTERM
    during launchd shutdown under high load"), distinct from a plain in-session kill (which the page cache
    survives and SQLite recovers from).
    """
    _darwin_pragma(conn, 'PRAGMA checkpoint_fullfsync=1')

def _enforce_macos_synchronous_full(conn: sqlite3.Connection) -> None:
    """Enforce ``PRAGMA synchronous=FULL`` on macOS: with NORMAL a WAL checkpoint
    racing process termination leaves half-written btree pages (``btreeInitPage
    error 11``). Called after every WAL activation so a prior NORMAL never sticks."""
    _darwin_pragma(conn, 'PRAGMA synchronous=FULL')

def _apply_wal_companions(conn: sqlite3.Connection) -> None:
    """The settings every WAL activation carries: size limit + macOS barriers."""
    _apply_wal_size_limit(conn)
    _apply_macos_checkpoint_barrier(conn)
    _enforce_macos_synchronous_full(conn)

def is_sqlite_wal_reset_vulnerable(version_info: Optional[tuple]=None) -> bool:
    """True when the linked SQLite has the WAL-reset bug (3.7.0–3.51.2; fixed 3.51.3+, backports 3.50.7 /
    3.44.6). Pre-WAL libraries are safe. https://sqlite.org/wal.html#walresetbug"""
    return _is_sqlite_wal_reset_vulnerable(sqlite3.sqlite_version_info if version_info is None else version_info)

def _database_has_content(conn: sqlite3.Connection) -> bool:
    """Whether the file already holds pages (existing vs brand-new DB); lock-free header read. Fail-quiet False: the
    only caller gates a warning on this and an unknown-answer warning would fire on every fresh database."""
    try:
        row = conn.execute('PRAGMA page_count').fetchone()
        return bool(row) and row[0] is not None and (int(row[0]) > 0)
    except (sqlite3.Error, TypeError, ValueError):
        return False

def resolve_journal_mode() -> str:
    """The configured ``database.journal_mode`` (``wal`` default; ``delete`` for filesystems without WAL-safe
    durability: macOS virtiofs, NFS, SMB). Invalid values fail safe to ``wal``."""
    try:
        from hivemind_assembly.automation.state_engine.hermes_cli.config import load_config_readonly
        database = (load_config_readonly() or {}).get('database', {})
        raw = database.get('journal_mode', 'wal') if isinstance(database, dict) else 'wal'
    except Exception:
        return 'wal'
    mode = raw.strip().lower() if isinstance(raw, str) else ''
    return mode if mode in ('wal', 'delete') else 'wal'

class WalUnsupportedError(sqlite3.OperationalError):
    """Raised by :func:`apply_wal_with_fallback` under ``require_wal=True`` when
    the filesystem cannot provide WAL (SQLITE_PROTOCOL raised, or macOS-NFS silent
    refusal) or the on-disk mode cannot be verified (probe blocked by a concurrent
    opener). Subclasses ``OperationalError`` so DB-init handlers still catch it."""
_CROSS_VM_FSTYPES = frozenset({'virtiofs', 'fuse.virtiofs', '9p', '9p2000', '9p2000.l', '9p2000.u'})
_cross_vm_fs_cache: dict[str, bool] = {}
_cross_vm_fs_cache_lock = threading.Lock()
_cross_vm_warned_paths: set[str] = set()
_cross_vm_warned_lock = threading.Lock()
_cross_vm_existing_wal_warned_paths: set[str] = set()
_cross_vm_existing_wal_warned_lock = threading.Lock()

def _mountinfo_fstype(directory: str, mountinfo_path: str='/proc/self/mountinfo') -> str:
    """fstype of the longest mount point that is a prefix of ``directory`` (``""`` if unreadable / no match)."""
    try:
        with open(mountinfo_path, 'r', encoding='utf-8', errors='replace') as fh:
            lines = fh.read().splitlines()
    except OSError:
        return ''
    best_len, best_fstype = (-1, '')
    for line in lines:
        fields, _, tail = line.partition(' - ')
        parts = fields.split()
        if len(parts) < 5 or not tail:
            continue
        mount_point = parts[4]
        if '\\' in mount_point:
            mount_point = mount_point.encode('latin-1', 'ignore').decode('unicode_escape')
        if directory == mount_point or directory.startswith(mount_point.rstrip('/') + '/'):
            if len(mount_point) > best_len:
                best_len, best_fstype = (len(mount_point), tail.split()[0])
    return best_fstype.lower()

def _detect_cross_vm_fs(directory: str, mountinfo_path: str='/proc/self/mountinfo') -> bool:
    """True only when ``directory`` sits on a virtiofs/9p mount per ``mountinfo_path``."""
    if sys.platform != 'linux':
        return False
    return _mountinfo_fstype(directory, mountinfo_path) in _CROSS_VM_FSTYPES

def _path_on_cross_vm_fs(path: str) -> bool:
    """True when ``path`` resides on a virtiofs/9p (cross-VM) filesystem; cached per resolved directory."""
    try:
        directory = os.path.dirname(os.path.realpath(path)) or '/'
    except (OSError, ValueError):
        return False
    with _cross_vm_fs_cache_lock:
        cached = _cross_vm_fs_cache.get(directory)
    if cached is None:
        cached = _detect_cross_vm_fs(directory)
        with _cross_vm_fs_cache_lock:
            _cross_vm_fs_cache[directory] = cached
    return cached

def _connection_db_file(conn: sqlite3.Connection) -> str:
    """Filesystem path of the ``main`` database, ``""`` for in-memory / unknown."""
    try:
        row = conn.execute('PRAGMA database_list').fetchone()
        return str(row[2]) if row and row[2] else ''
    except (sqlite3.OperationalError, IndexError, TypeError):
        return ''

def _verify_configured_delete(actual: str) -> str:
    """Raise unless SQLite reported ``delete`` for an explicit operator request."""
    if actual != 'delete':
        raise sqlite3.OperationalError(f'could not set configured journal_mode=delete (got {actual or 'no result'})')
    return actual

def apply_wal_with_fallback(conn: sqlite3.Connection, *, db_label: str='state.db', require_wal: bool=False) -> str:
    """Set ``journal_mode=WAL`` on ``conn``, falling back to DELETE on failure.

    Returns the mode actually set — or, when the read-only mode probe is blocked by a concurrent opener, ``"wal"``
    as the assumed mode with nothing touched (``require_wal=True`` raises instead). Shared by :class:`SessionDB`
    and ``hermes_cli.kanban_db_connect.connect``. WAL-incompatible filesystems either raise ``OperationalError`` ("locking protocol" / "disk I/O error") or —
    macOS NFS / SMB / AgentFS — silently refuse and stay in DELETE; either way log ERROR once per process per
    ``db_label`` and fall back. ``require_wal=True`` raises :class:`WalUnsupportedError` instead. WAL-reset-bug
    builds (https://sqlite.org/wal.html#walresetbug) never enable WAL on non-WAL files; an already-WAL DB keeps WAL
    with a warning. Gate deliberately RETAINED: re-measured on the bundled 3.50.4 there is no evidence WAL is safer.

    Invariant on every path: never downgrade to DELETE if the on-disk header reports WAL or cannot be read — other
    gateway/cron/worker connections may hold the DB open, and a live downgrade destroys their uncheckpointed
    commits.

    An earlier revision of the lock-cancellation fix (#71724) reverted it on the theory that DELETE was "the
    mode that corrupts", but that comparison was confounded: the clean WAL result came from SQLite 3.53.1,
    which carries BOTH the WAL-reset fix AND 3.51.0's defenses against close()-broken POSIX locks, so it
    says nothing about 3.50.4. Re-measured on the actually-bundled 3.50.4 with the lock fix in place, WAL
    and DELETE are both clean (0/3 each) — i.e. there is no evidence that WAL is safer here, and upstream
    still documents the WAL-reset bug as real through 3.51.2 with serious consequences. Until a fixed
    runtime is delivered, keep new databases out of WAL.
    """
    config_module = sys.modules.get('hermes_cli.config')
    if getattr(getattr(config_module, '__spec__', None), '_initializing', False):
        config_module = None
    config_lock = getattr(config_module, '_CONFIG_LOCK', None)
    acquired = config_lock is not None and config_lock.acquire(blocking=False)
    try:
        if config_lock is not None and (not acquired):
            current_mode = _on_disk_journal_mode(conn)
            if current_mode == 'wal':
                if is_sqlite_wal_reset_vulnerable():
                    return _apply_delete_for_wal_reset_bug(conn, db_label=db_label)
                _apply_wal_companions(conn)
                return 'wal'
            if current_mode == 'delete' and (not require_wal) and _database_has_content(conn):
                if is_sqlite_wal_reset_vulnerable():
                    _log_wal_reset_bug_once(db_label, kept_wal=False)
                return 'delete'
        configured = resolve_journal_mode()
    finally:
        if acquired:
            config_lock.release()
    if is_sqlite_wal_reset_vulnerable():
        return _apply_delete_for_wal_reset_bug(conn, db_label=db_label, require_delete=configured == 'delete')
    current_mode = _on_disk_journal_mode(conn)
    if current_mode == 'wal':
        if configured == 'delete':
            _log_configured_delete_overridden_once(db_label)
        _warn_existing_wal_on_cross_vm_fs(conn)
        _apply_wal_companions(conn)
        return 'wal'
    if configured == 'delete':
        if current_mode is None:
            raise sqlite3.OperationalError(_CANNOT_VERIFY_DELETE_MSG)
        return _verify_configured_delete(_set_journal_mode_no_wait(conn, 'DELETE'))
    if current_mode is None:
        if require_wal:
            raise WalUnsupportedError('could not verify the on-disk journal mode (database is locked — possible concurrent openers); cannot guarantee WAL')
        _log_once('wal_probe_unknown', db_label)
        return 'wal'
    db_file = _connection_db_file(conn)
    if db_file and _path_on_cross_vm_fs(db_file):
        if require_wal:
            raise WalUnsupportedError('journal_mode=WAL refused: database is on a cross-VM filesystem (virtiofs/9p) where WAL shared-memory silently corrupts')
        _log_once('cross_vm_fs', db_label)
        return _set_journal_mode_no_wait(conn, 'DELETE') or 'delete'
    return _enable_wal(conn, db_label, require_wal, current_mode)

def _enable_wal(conn: sqlite3.Connection, db_label: str, require_wal: bool, current_mode: Optional[str]) -> str:
    """Flip a non-WAL, non-vulnerable connection to WAL, or fall back to DELETE."""
    upgrading_existing_db = current_mode is not None and current_mode != 'wal' and _database_has_content(conn)

    def _wal_activated() -> str:
        if upgrading_existing_db:
            _log_journal_mode_upgrade_once(db_label, current_mode)
        _apply_wal_companions(conn)
        return 'wal'
    try:
        mode = _mode_from_row(conn.execute('PRAGMA journal_mode=WAL').fetchone())
        if mode == 'wal':
            return _wal_activated()
        silent_exc = WalUnsupportedError(f'journal_mode=WAL refused without raising (still {mode!r})')
        if require_wal:
            raise silent_exc
        _log_wal_fallback_once(db_label, silent_exc)
        return mode or 'delete'
    except WalUnsupportedError:
        raise
    except sqlite3.OperationalError as exc:
        msg = str(exc).lower()
        if not any((marker in msg for marker in _WAL_INCOMPAT_MARKERS)):
            raise
        if 'disk i/o error' in msg:
            for _ in range(2):
                time.sleep(0.05)
                try:
                    row = conn.execute('PRAGMA journal_mode=WAL').fetchone()
                except sqlite3.OperationalError as retry_exc:
                    if 'disk i/o error' not in str(retry_exc).lower():
                        raise
                    exc = retry_exc
                    continue
                if _mode_from_row(row) == 'wal':
                    return _wal_activated()
                break
        if _on_disk_journal_mode(conn) in ('wal', None):
            raise
        if require_wal:
            raise WalUnsupportedError(str(exc)) from exc
        _log_wal_fallback_once(db_label, exc)
        try:
            _set_journal_mode_no_wait(conn, 'DELETE')
        except sqlite3.OperationalError as delete_exc:
            _log_once('wal_delete_fallback_failed', db_label, exc, delete_exc)
            try:
                read_back = _mode_from_row(conn.execute('PRAGMA journal_mode').fetchone())
            except sqlite3.OperationalError:
                read_back = ''
            return read_back or 'delete'
        return 'delete'

def _set_journal_mode_no_wait(conn: sqlite3.Connection, mode: str) -> str:
    """Execute ``PRAGMA journal_mode=<mode>`` without waiting on other openers.

    The ONLY place a non-WAL journal-mode switch may be issued. ``busy_timeout=0`` turns SQLite's exclusivity
    requirement into a concurrent-opener detector: leaving WAL needs exclusive access, so if ANY other connection
    holds the DB the pragma fails immediately with ``database is locked`` instead of sneaking the flip between a
    writer's transactions (how uncheckpointed WAL commits die). Callers must treat a raised ``OperationalError`` as
    "not exclusively owned: leave the mode alone", never as retryable. Returns the reported mode, ``""`` if no row."""
    try:
        row = conn.execute('PRAGMA busy_timeout').fetchone()
        previous_timeout = int(row[0]) if row and row[0] is not None else 0
    except (sqlite3.OperationalError, TypeError, ValueError):
        previous_timeout = 0
    conn.execute('PRAGMA busy_timeout=0')
    try:
        return _mode_from_row(conn.execute(f'PRAGMA journal_mode={mode}').fetchone())
    finally:
        with contextlib.suppress(sqlite3.OperationalError):
            conn.execute(f'PRAGMA busy_timeout={previous_timeout}')

def _warn_existing_wal_on_cross_vm_fs(conn: sqlite3.Connection) -> None:
    """#110848: the fresh-DB cross-VM refusal never sees a DB that was already WAL before the check existed (or was
    created on a native volume and then moved). Keeping WAL is right (never live-downgrade); staying silent is not.
    Both the vulnerable-SQLite and the regular already-WAL paths return early, so both must call this."""
    db_file = _connection_db_file(conn)
    if db_file and _path_on_cross_vm_fs(db_file):
        _log_once('cross_vm_fs_existing_wal', db_file)

def _apply_delete_for_wal_reset_bug(conn: sqlite3.Connection, *, db_label: str, require_delete: bool=False) -> str:
    """Avoid enabling WAL when the linked SQLite has the WAL-reset bug.

    Already-WAL on disk: keep WAL (no live downgrade) and warn. Mode unreadable (probe blocked by a concurrent
    opener): not provably exclusive — leave it and warn; treating "could not read" as "not WAL" once flipped a live
    WAL state.db to DELETE under a writer, destroying its uncheckpointed commits. Otherwise set DELETE without
    waiting out openers and warn; an explicit operator request additionally verifies SQLite accepted DELETE."""
    current = _on_disk_journal_mode(conn)
    if current == 'wal':
        _log_wal_reset_bug_once(db_label, kept_wal=True)
        if require_delete:
            _log_configured_delete_overridden_once(db_label)
        _warn_existing_wal_on_cross_vm_fs(conn)
        _apply_wal_companions(conn)
        return 'wal'
    if current is None:
        if require_delete:
            raise sqlite3.OperationalError(_CANNOT_VERIFY_DELETE_MSG)
        _log_wal_reset_bug_once(db_label, kept_wal=True, indeterminate=True)
        return 'wal'
    actual = ''
    try:
        actual = _set_journal_mode_no_wait(conn, 'DELETE')
    except sqlite3.OperationalError as exc:
        if require_delete:
            raise
        if is_sqlite_lock_error(exc):
            _log_wal_reset_bug_once(db_label, kept_wal=True, indeterminate=True)
            return current or 'delete'
    if require_delete:
        _verify_configured_delete(actual)
    _log_wal_reset_bug_once(db_label, kept_wal=False)
    return 'delete'

def _wal_reset_repair_hint() -> str:
    """Repair hint matching what ``hermes update`` can actually do for this install type.

    See #75153.
    """
    try:
        from hivemind_assembly.automation.state_engine.hermes_cli.config import detect_install_method, get_project_root, recommended_update_command_for_method
        method = detect_install_method(get_project_root())
        cmd = recommended_update_command_for_method(method)
        if method in {'git', 'unknown'}:
            return f'Hermes-managed installs can repair the embedded runtime with `{cmd}`'
        return f'update the container image with `{cmd}`' if method == 'docker' else cmd
    except Exception:
        return 'install a Python build bundled with SQLite 3.51.3+ (or backports 3.50.7 / 3.44.6) and restart HA'
_WAL_RESET_BUG_ACTIONS = {'indeterminate': 'journal mode could not be verified or exclusively switched (database is locked — possible concurrent openers); leaving the journal mode untouched (no live downgrade under concurrent openers)', 'kept_wal': 'is already in WAL mode — leaving WAL in place (no live downgrade under concurrent openers)', 'delete': 'using journal_mode=DELETE instead of enabling WAL'}
_ONCE_LOGS = {'wal_reset_bug': (_wal_reset_bug_warned_lock, '_wal_reset_bug_warned_paths', logging.WARNING, '%s: linked SQLite %s (interpreter %s) is vulnerable to the WAL-reset corruption bug (https://sqlite.org/wal.html#walresetbug) — %s. Upgrade to SQLite 3.51.3+ (or backports 3.50.7 / 3.44.6); %s. Use HA Settings > Check installation. This warning fires once per process per database.'), 'journal_upgrade': (_journal_upgrade_warned_lock, '_journal_upgrade_warned_paths', logging.WARNING, '%s: on-disk journal_mode was %s and has been switched to WAL. This rewrites the database header and persists after this process exits. If %s was a deliberate choice (for example the mitigation for the SQLite WAL-reset bug, or a WAL-unsafe filesystem), setting it with PRAGMA on the file will not survive -- every open re-applies the configured mode. Set `database.journal_mode: delete` in config.yaml to make it stick. This message fires once per process per database.'), 'wal_fallback': (_wal_fallback_warned_lock, '_wal_fallback_warned_paths', logging.ERROR, '%s: WAL journal_mode unsupported on this filesystem (%s) — falling back to journal_mode=DELETE (slower rollback-journal mode; reduces concurrency but works on NFS/SMB/FUSE/ZFS). See https://www.sqlite.org/wal.html for details. This message fires once per process per database.'), 'wal_delete_fallback_failed': (_wal_delete_fallback_failed_lock, '_wal_delete_fallback_failed_paths', logging.WARNING, "%s: both WAL and DELETE journal_mode failed (WAL: %s; DELETE: %s) — continuing with the connection's current journal mode (reads/writes still work). Typically seen on APFS external SSDs under heavy contention. This message fires once per process per database."), 'delete_overridden': (_delete_overridden_warned_lock, '_delete_overridden_warned_paths', logging.ERROR, '%s: database.journal_mode=delete is configured but the on-disk database is already WAL; keeping WAL (a live downgrade under open connections can corrupt the DB). To apply journal_mode=DELETE, stop HA and every process using this database using this database and run `hermes sessions set-journal-mode delete` (add `--db PATH` for a store other than state.db). This message fires once per process per database.'), 'wal_probe_unknown': (_wal_probe_unknown_lock, '_wal_probe_unknown_paths', logging.WARNING, '%s: could not verify the on-disk journal mode (database is locked / busy); not issuing a journal-mode set-pragma while another connection may hold the file (it could unlink the -wal/-shm sidecars that connection still uses). Leaving the file untouched; this connection inherits the on-disk mode. This message fires once per process per database.'), 'cross_vm_fs': (_cross_vm_warned_lock, '_cross_vm_warned_paths', logging.WARNING, '%s: database directory is on a cross-VM filesystem (virtiofs/9p — typical for Docker Desktop / OrbStack / Podman host bind mounts). SQLite WAL shared-memory is not coherent across the VM boundary and can silently corrupt the database, so journal_mode=DELETE is used instead. To restore WAL concurrency, move the database onto a native volume (e.g. a named Docker volume) instead of a host bind mount. This message fires once per process per database.'), 'cross_vm_fs_existing_wal': (_cross_vm_existing_wal_warned_lock, '_cross_vm_existing_wal_warned_paths', logging.ERROR, '%s: existing WAL-mode database is on a cross-VM filesystem (virtiofs/9p — typical for Docker Desktop / OrbStack / Podman host bind mounts). SQLite WAL shared-memory is not coherent across the VM boundary and concurrent writers can silently corrupt the database. Hermes does not live-downgrade an on-disk WAL database. Fix one of two ways: stop HA and every process using this database using this database and run `hermes sessions set-journal-mode delete` (set `database.journal_mode: delete` in config.yaml to keep it), or move the database onto a native volume (e.g. a named Docker volume). This message fires once per process per database.')}

def _log_once(kind: str, db_label: str, *args: Any) -> None:
    """Emit ``_ONCE_LOGS[kind]`` once per (process, db_label). Callable *args* are
    resolved only after the dedupe check, so install-method probes run once."""
    lock, set_name, level, message = _ONCE_LOGS[kind]
    seen = globals()[set_name]
    with lock:
        if db_label in seen:
            return
        seen.add(db_label)
    logger.log(level, message, db_label, *(a() if callable(a) else a for a in args))

def _log_wal_reset_bug_once(db_label: str, *, kept_wal: bool, indeterminate: bool=False) -> None:
    """Log once per (process, db_label) about the WAL-reset vulnerability path."""
    action = _WAL_RESET_BUG_ACTIONS['indeterminate' if indeterminate else 'kept_wal' if kept_wal else 'delete']
    _log_once('wal_reset_bug', db_label, sqlite3.sqlite_version, sys.executable, action, _wal_reset_repair_hint)

def _log_journal_mode_upgrade_once(db_label: str, previous_mode: str) -> None:
    """Single WARNING per (process, db_label) about a non-WAL -> WAL flip."""
    _log_once('journal_upgrade', db_label, previous_mode, previous_mode)
_log_wal_fallback_once = functools.partial(_log_once, 'wal_fallback')
_log_configured_delete_overridden_once = functools.partial(_log_once, 'delete_overridden')
_SYNCHRONOUS_LEVELS: dict[str, int] = {'OFF': 0, 'NORMAL': 1, 'FULL': 2, 'EXTRA': 3}
_SYNCHRONOUS_NAMES: dict[int, str] = {v: k for k, v in _SYNCHRONOUS_LEVELS.items()}
_SYNCHRONOUS_FULL = 2

def resolve_synchronous_level(raw_value: Any) -> Optional[int]:
    """Map ``database.synchronous`` (``OFF``/``NORMAL``/``FULL``/``EXTRA`` any
    case, or ``0``-``3``) to its PRAGMA integer; None for anything else so the
    caller warns and leaves the level untouched (guessing at durability is worse)."""
    if isinstance(raw_value, bool):
        return 0 if raw_value is False else None
    if isinstance(raw_value, int):
        return raw_value if raw_value in _SYNCHRONOUS_NAMES else None
    text = str(raw_value).strip()
    if text.upper() in _SYNCHRONOUS_LEVELS:
        return _SYNCHRONOUS_LEVELS[text.upper()]
    with contextlib.suppress(TypeError, ValueError):
        return int(text) if int(text) in _SYNCHRONOUS_NAMES else None
    return None

def _apply_synchronous_pragma(conn: sqlite3.Connection, raw_value: Any, *, db_label: str) -> None:
    """Set ``PRAGMA synchronous`` from config, never below FULL on macOS.

    Kept out of the integer loop in :func:`apply_database_pragmas`: this PRAGMA decides whether a commit is on
    the platter, so an unrecognised value must not fall through to "SQLite default" the way a bad
    ``cache_size`` can. Darwin floor: this runs after :func:`_enforce_macos_synchronous_full`, so a configured
    ``NORMAL`` would silently undo the btree protection — raising is allowed, lowering is refused out loud."""
    if (level := resolve_synchronous_level(raw_value)) is None:
        logger.warning('%s: ignoring unrecognized database.synchronous=%r (expected OFF, NORMAL, FULL, EXTRA, or 0-3)', db_label, raw_value)
        return
    if sys.platform == 'darwin' and level < _SYNCHRONOUS_FULL:
        logger.warning("%s: refusing database.synchronous=%s on macOS; keeping FULL. Darwin's fsync() does not guarantee write ordering, so a lower level readmits the half-written btree pages FULL exists to prevent.", db_label, _SYNCHRONOUS_NAMES[level])
        return
    with contextlib.suppress(sqlite3.OperationalError):
        conn.execute(f'PRAGMA synchronous={level}')

def apply_database_pragmas(conn: sqlite3.Connection, *, db_label: str='state.db') -> None:
    """Apply optional performance and WAL-sizing PRAGMAs from ``config.yaml``.

    Journal mode is NOT handled here (owned by :func:`apply_wal_with_fallback`). ``database:`` keys: ``cache_size``
    (negative = KiB, positive = pages), ``mmap_size`` (bytes, 0 = off), ``temp_store`` (0-3), ``wal_autocheckpoint``
    (pages), ``journal_size_limit`` (bytes), ``synchronous`` (unset leaves the compile-time default, which differs
    between bundled/distro/Homebrew builds). Best-effort: failures are ignored so DB init never breaks on a
    malformed section. Applied to ALL connection types: writer, read_only, WAL readers."""
    try:
        from hivemind_assembly.automation.state_engine.hermes_cli.config import cfg_get, load_config_readonly
        cfg = load_config_readonly()
    except Exception:
        return
    for pragma_name in ('cache_size', 'mmap_size', 'temp_store', 'wal_autocheckpoint', 'journal_size_limit'):
        if (raw_value := cfg_get(cfg, 'database', pragma_name, default=None)) is None:
            continue
        try:
            value = int(str(raw_value).strip())
        except (TypeError, ValueError):
            logger.warning('%s: ignoring non-integer database.%s=%r', db_label, pragma_name, raw_value)
            continue
        with contextlib.suppress(sqlite3.OperationalError):
            conn.execute(f'PRAGMA {pragma_name}={value}')
    if (raw_synchronous := cfg_get(cfg, 'database', 'synchronous', default=None)) is not None:
        _apply_synchronous_pragma(conn, raw_synchronous, db_label=db_label)
