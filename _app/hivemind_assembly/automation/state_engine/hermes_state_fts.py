# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Sequence
from hivemind_assembly.automation.state_engine.hermes_constants import get_hermes_home
from hivemind_assembly.automation.state_engine.hermes_state_common import FTS_CJK_STALE_KEY, FTS_STALE_KEY, _FTS_CJK_TRIGGERS, _FTS_TRIGGERS, routed_sessions_setting
from hivemind_assembly.automation.state_engine.hermes_state_errors import is_fts_scoped_corruption_error, is_sqlite_lock_error
logger = logging.getLogger('hermes_state')
FTS_CJK_TABLE_SQL = "\nCREATE VIEW IF NOT EXISTS messages_fts_cjk_src AS\n    SELECT id, role, content, tool_name, tool_calls\n    FROM messages\n    WHERE role <> 'tool';\n\nCREATE VIRTUAL TABLE IF NOT EXISTS messages_fts_cjk USING fts5(\n    content,\n    tool_name,\n    tool_calls,\n    content='messages_fts_cjk_src',\n    content_rowid='id',\n    tokenize='cjk_unicode61'\n);\n"
FTS_CJK_TRIGGER_SQL = "\nCREATE TRIGGER IF NOT EXISTS messages_fts_cjk_insert AFTER INSERT ON messages\nWHEN new.role <> 'tool'\n   AND (new.id > COALESCE((SELECT CAST(value AS INTEGER) FROM state_meta\n                           WHERE key = 'fts_cjk_rebuild_high_water'), -1)\n     OR new.id <= COALESCE((SELECT CAST(value AS INTEGER) FROM state_meta\n                            WHERE key = 'fts_cjk_rebuild_progress'), -1))\nBEGIN\n    INSERT INTO messages_fts_cjk(rowid, content, tool_name, tool_calls)\n    VALUES (new.id, new.content, new.tool_name, new.tool_calls);\nEND;\n\nCREATE TRIGGER IF NOT EXISTS messages_fts_cjk_delete AFTER DELETE ON messages\nWHEN old.role <> 'tool'\n   AND (old.id > COALESCE((SELECT CAST(value AS INTEGER) FROM state_meta\n                           WHERE key = 'fts_cjk_rebuild_high_water'), -1)\n     OR old.id <= COALESCE((SELECT CAST(value AS INTEGER) FROM state_meta\n                            WHERE key = 'fts_cjk_rebuild_progress'), -1))\nBEGIN\n    INSERT INTO messages_fts_cjk(messages_fts_cjk, rowid, content, tool_name, tool_calls)\n    VALUES ('delete', old.id, old.content, old.tool_name, old.tool_calls);\nEND;\n\nCREATE TRIGGER IF NOT EXISTS messages_fts_cjk_update\nAFTER UPDATE OF content, tool_name, tool_calls, role ON messages\nWHEN (old.content IS NOT new.content\n    OR old.tool_name IS NOT new.tool_name\n    OR old.tool_calls IS NOT new.tool_calls\n    OR old.role IS NOT new.role)\n   AND (old.id > COALESCE((SELECT CAST(value AS INTEGER) FROM state_meta\n                           WHERE key = 'fts_cjk_rebuild_high_water'), -1)\n     OR old.id <= COALESCE((SELECT CAST(value AS INTEGER) FROM state_meta\n                            WHERE key = 'fts_cjk_rebuild_progress'), -1))\nBEGIN\n    INSERT INTO messages_fts_cjk(messages_fts_cjk, rowid, content, tool_name, tool_calls)\n    SELECT 'delete', old.id, old.content, old.tool_name, old.tool_calls\n    WHERE old.role <> 'tool';\n    INSERT INTO messages_fts_cjk(rowid, content, tool_name, tool_calls)\n    SELECT new.id, new.content, new.tool_name, new.tool_calls\n    WHERE new.role <> 'tool';\nEND;\n"

def fts5_cjk_so_path() -> Path:
    """Location of the cjk_unicode61 loadable extension."""
    env = os.getenv('HERMES_FTS5_CJK_SO')
    return Path(env).expanduser() if env else get_hermes_home() / 'lib' / 'libfts5_cjk.so'

def _cjk_fts_config_enabled() -> bool:
    """config.yaml ``sessions.cjk_fts`` (default on) for the profile being served."""
    value = routed_sessions_setting('cjk_fts', 'HERMES_CJK_FTS')
    return value is None or str(value).strip().lower() not in ('0', 'false', 'off', 'no')

def load_fts5_cjk_extension(conn: sqlite3.Connection) -> bool:
    """Best-effort load of the cjk_unicode61 tokenizer; False (never raises) when
    the .so is absent, ``sessions.cjk_fts`` is off, or loading is compiled out."""
    path = fts5_cjk_so_path()
    if not _cjk_fts_config_enabled() or not path.exists():
        return False
    try:
        conn.enable_load_extension(True)
        try:
            conn.load_extension(str(path))
        finally:
            conn.enable_load_extension(False)
        return True
    except Exception:
        logger.warning('fts5_cjk extension load failed (%s)', path, exc_info=True)
        return False
_FTS5_SHADOW_SUFFIXES = ('content', 'data', 'docsize', 'idx', 'config')

def _drop_orphan_fts_shadow_tables(cursor: sqlite3.Cursor, families: Sequence[str]) -> list[str]:
    """Drop, per family, shadow tables whose virtual table row is absent from sqlite_master.

    Matches exact shadow names only (never a prefix LIKE, so the base family cannot reach
    ``messages_fts_trigram_*``) and leaves a family alone whenever its vtable is live. The
    shadows are derived index state; the caller recreates and rebuilds from ``messages``.
    Returns the families that were repaired.
    """
    repaired: list[str] = []
    for family in families:
        vtable_live = cursor.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? AND sql LIKE 'CREATE VIRTUAL TABLE%'", (family,)).fetchone()
        if vtable_live:
            continue
        shadows = [f'{family}_{suffix}' for suffix in _FTS5_SHADOW_SUFFIXES]
        orphans = [row[0] for row in cursor.execute(f"SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ({','.join(('?' for _ in shadows))})", shadows).fetchall()]
        if not orphans:
            continue
        for name in orphans:
            cursor.execute(f'DROP TABLE "{name}"')
        logger.warning('Dropped orphan FTS5 shadow tables of %s (%s); the index is recreated from messages', family, ', '.join(orphans))
        repaired.append(family)
    return repaired

class SessionFtsSetupMixin:
    """FTS table/trigger lifecycle shared by schema init, optimize and the write path."""

    @staticmethod
    def _is_fts5_unavailable_error(exc: sqlite3.OperationalError) -> bool:
        """No FTS5 module, or an optional tokenizer missing (same capability-error shape)."""
        err = str(exc).lower()
        return 'no such module' in err and 'fts5' in err or SessionFtsSetupMixin._is_trigram_unavailable_error(exc)

    @staticmethod
    def _is_trigram_unavailable_error(exc: sqlite3.OperationalError) -> bool:
        """Only an optional tokenizer is missing (trigram needs SQLite >= 3.34;
        cjk_unicode61 is loadable): "this one index can't be served", never "disable FTS"."""
        err = str(exc).lower()
        return 'no such tokenizer: trigram' in err or 'no such tokenizer: cjk_unicode61' in err

    @staticmethod
    def _db_has_legacy_inline_fts(cursor: sqlite3.Cursor) -> bool:
        """messages_fts exists in ANY pre-v23 shape: every legacy shape lacks
        tool_name, so "stored CREATE lacks tool_name" catches them all. False when absent.

        v23's messages_fts is external-content over THREE real columns (content, tool_name, tool_calls).
        Every pre-v23 shape lacks the tool_name/tool_calls columns — whether the old inline single-column
        form (v11..v22) or the even older external-content single-column form (v10-era, pre-#16751). We
        therefore detect "needs optimize" as "the stored CREATE lacks the tool_name column", which is the
        precise v23 marker and correctly catches BOTH legacy variants.
        """
        row = cursor.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'messages_fts'").fetchone()
        return row is not None and 'tool_name' not in (row[0] or '')

    @staticmethod
    def _db_has_trigram_tool_calls_projection(cursor: sqlite3.Cursor) -> bool:
        """True when the trigram vtable still includes the tool_calls payload (FTS_STORAGE_VERSION 1)."""
        row = cursor.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'messages_fts_trigram'").fetchone()
        return row is not None and 'tool_calls' in (row[0] or '').lower()

    @classmethod
    def _db_needs_fts_storage_upgrade(cls, cursor: sqlite3.Cursor) -> bool:
        """True when the current FTS storage layout should be treated as stale (optimize-storage has work)."""
        return cls._db_has_legacy_inline_fts(cursor) or cls._db_has_trigram_tool_calls_projection(cursor)

    def _warn_trigram_unavailable(self, exc: sqlite3.OperationalError) -> None:
        """Log once that the trigram tokenizer is missing; base FTS5 stays enabled."""
        if getattr(self, '_trigram_unavailable_warned', False):
            return
        self._trigram_unavailable_warned = True
        logger.info('SQLite trigram tokenizer unavailable for %s (requires SQLite >= 3.34, this build is %s); CJK/substring search will fall back to LIKE: %s', self.db_path, sqlite3.sqlite_version, exc)

    def _warn_fts5_unavailable(self, exc: sqlite3.OperationalError) -> None:
        self._fts_enabled = False
        if self._fts_unavailable_warned:
            return
        self._fts_unavailable_warned = True
        logger.warning('SQLite FTS5 unavailable for %s; full-text session search disabled. Run `hermes update` to rebuild the venv with a current Python (managed uv guarantees FTS5). (underlying error: %s)', self.db_path, exc)

    def _ensure_fts_cjk_schema(self, cursor) -> None:
        """Create / repair / self-heal the CJK-bigram index (see the module comment).
        Sets ``_fts_cjk_available``; never raises. Loaded + absent → create (a
        populated DB gets backfill markers and is NOT served until optimize-storage
        backfills); loaded + present → ensure triggers, honour the stale breadcrumb;
        NOT loaded + live triggers → drop them (INSERTs must not fail at trigger time)."""
        try:
            cjk_present = bool(cursor.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'messages_fts_cjk'").fetchone())
            if not self._fts_cjk_loaded:
                if cjk_present:
                    live = [r[0] for r in cursor.execute(f"SELECT name FROM sqlite_master WHERE type = 'trigger' AND name IN ({','.join(('?' for _ in _FTS_CJK_TRIGGERS))})", _FTS_CJK_TRIGGERS).fetchall()]
                    if live:
                        logger.warning('messages_fts_cjk triggers present but the cjk_unicode61 tokenizer is unavailable (%s) — dropping the cjk triggers so message writes keep working. CJK search falls back to trigram/LIKE; run `hermes sessions optimize-storage` on a host with the extension to rebuild.', fts5_cjk_so_path())
                        cursor.execute("INSERT INTO state_meta (key, value) VALUES (?, '1') ON CONFLICT(key) DO UPDATE SET value = '1'", (FTS_CJK_STALE_KEY,))
                        for trig in live:
                            cursor.execute(f'DROP TRIGGER IF EXISTS {trig}')
                self._fts_cjk_available = False
                return
        except sqlite3.OperationalError:
            logger.warning('messages_fts_cjk presence check failed; CJK search stays on trigram/LIKE', exc_info=True)
            self._fts_cjk_available = False
            return
        try:
            cursor.executescript(FTS_CJK_TABLE_SQL)
            if not cjk_present:
                cursor.execute('DELETE FROM state_meta WHERE key = ?', (FTS_CJK_STALE_KEY,))
                if cursor.execute("SELECT COUNT(*) FROM messages WHERE role <> 'tool'").fetchone()[0] > 0:
                    hw = cursor.execute('SELECT COALESCE(MAX(id), 0) FROM messages').fetchone()[0]
                    for k, v in (('fts_cjk_rebuild_high_water', str(hw)), ('fts_cjk_rebuild_progress', '0')):
                        cursor.execute('INSERT INTO state_meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value', (k, v))
            if cursor.execute('SELECT 1 FROM state_meta WHERE key = ?', (FTS_CJK_STALE_KEY,)).fetchone():
                self._fts_cjk_available = False
                return
            cursor.executescript(FTS_CJK_TRIGGER_SQL)
            backfill_pending = cursor.execute("SELECT 1 FROM state_meta WHERE key = 'fts_cjk_rebuild_high_water' LIMIT 1").fetchone()
            self._fts_cjk_available = not backfill_pending
        except sqlite3.OperationalError:
            logger.warning('messages_fts_cjk ensure failed; CJK search stays on trigram/LIKE', exc_info=True)
            self._fts_cjk_available = False

    @staticmethod
    def _drop_fts_triggers(cursor: sqlite3.Cursor) -> None:
        for trigger in _FTS_TRIGGERS:
            try:
                cursor.execute(f'DROP TRIGGER IF EXISTS {trigger}')
            except sqlite3.OperationalError:
                pass

    def _ensure_fts_schema(self, cursor: sqlite3.Cursor, table_name: str, ddl: str) -> bool:
        status = self._fts_table_probe(cursor, table_name)
        if status is None:
            return False
        try:
            cursor.executescript(ddl)
            return True
        except sqlite3.OperationalError as exc:
            if not self._is_fts5_unavailable_error(exc):
                raise
            if self._is_trigram_unavailable_error(exc):
                self._warn_trigram_unavailable(exc)
            else:
                self._warn_fts5_unavailable(exc)
            return False

    @staticmethod
    def _is_fts_write_corruption_error(exc: sqlite3.DatabaseError) -> bool:
        """Corruption SQLite identifies as FTS-scoped (SQLITE_CORRUPT_VTAB, or an ``fts5:``
        report naming ``messages_fts*`` on builds without result codes); a bare malformed
        image is structural. One rule, shared with ``classify_persistence_error`` and the
        gateway transcript retry: see :func:`hermes_state_errors.is_fts_scoped_corruption_error`."""
        return is_fts_scoped_corruption_error(exc)

    def _enter_fts_fail_open(self, exc: sqlite3.DatabaseError, *, deadline: float | None=None, patience_s: float | None=None) -> bool:
        """Detach corrupt FTS indexes so canonical writes can continue. Breadcrumb +
        trigger drop commit atomically: once triggers are absent the index has a
        gap of unknown extent, so nobody may reinstall them without a full rebuild.

        A busy write lock is waited out on the caller's write budget (default
        ``_WRITE_PATIENCE_S``), like ``_execute_write``: the writer connection's busy
        timeout is only 1 s, and the usual holder is a sibling writer detaching the
        same corrupt index — giving up after 1 s cost that turn's canonical write."""
        if not self._fts_enabled or not self._is_fts_write_corruption_error(exc):
            return False
        if patience_s is None:
            patience_s = self._WRITE_PATIENCE_S
        if deadline is None:
            deadline = time.monotonic() + patience_s
        while True:
            self._raise_if_db_corrupt(storage=True)
            try:
                with self._lock:
                    self._raise_if_db_replaced()
                    if self._conn is None:
                        self._reopen_after_close_locked(context='write')
                    self._conn.execute('BEGIN IMMEDIATE')
                    try:
                        self._conn.execute("INSERT INTO state_meta (key, value) VALUES (?, '1') ON CONFLICT(key) DO UPDATE SET value = excluded.value", (FTS_STALE_KEY,))
                        cjk_triggers_present = self._conn.execute(f"SELECT 1 FROM sqlite_master WHERE type = 'trigger' AND name IN ({','.join(('?' for _ in _FTS_CJK_TRIGGERS))}) LIMIT 1", _FTS_CJK_TRIGGERS).fetchone()
                        if cjk_triggers_present:
                            self._conn.execute("INSERT INTO state_meta (key, value) VALUES (?, '1') ON CONFLICT(key) DO UPDATE SET value = excluded.value", (FTS_CJK_STALE_KEY,))
                        self._drop_all_fts_triggers(self._conn.cursor())
                        self._conn.commit()
                    except BaseException:
                        self._conn.rollback()
                        raise
                break
            except sqlite3.Error as detach_exc:
                if isinstance(detach_exc, sqlite3.OperationalError) and is_sqlite_lock_error(detach_exc) and self._sleep_before_write_retry(deadline, patience_s):
                    continue
                logger.error('Could not detach corrupt FTS indexes; canonical write still cannot proceed: %s', detach_exc)
                return False
        self._fts_stale = True
        self._fts_enabled = False
        self._trigram_available = False
        self._fts_cjk_available = False
        logger.error('state.db FTS indexes remain corrupt (%s); disabled FTS sync and retrying the canonical write. Search temporarily uses LIKE until a later SessionDB open rebuilds the indexes.', exc)
        return True
    _FTS_REBUILD_CHUNK_ROWS = 500
    _FTS_REBUILD_DUTY_FACTOR = 4.0
    _FTS_REBUILD_MIN_PAUSE = 0.2
    _FTS_TRASH_PREFIX = 'fts_v22_trash_'

    def _has_fts_trash(self, conn) -> bool:
        """True when demoted v22 shadow tables are still awaiting teardown.
        Caller must hold ``self._lock`` (or pass a migration-time cursor)."""
        return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name LIKE ? ESCAPE '\\' LIMIT 1", (self._FTS_TRASH_PREFIX.replace('_', '\\_') + '%',)).fetchone())
    _FTS_TABLES = ('messages_fts', 'messages_fts_trigram', 'messages_fts_cjk')
