# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
import contextlib
import datetime
import hashlib
import logging
import json
import os
import sqlite3
import tempfile
import time
import uuid
from typing import Optional, Sequence
from hivemind_assembly.automation.state_engine.hermes_constants import get_hermes_home
from hivemind_assembly.automation.state_engine.hermes_startup_watchdog import report_startup_progress
from hivemind_assembly.automation.state_engine.utils import safe_json_loads
from hivemind_assembly.automation.state_engine.hermes_state_common import DEFERRED_INDEX_SQL, FTS_CJK_STALE_KEY, FTS_REBUILD_DEFERRAL_KEY, FTS_STALE_KEY, FTS_SQL, FTS_STORAGE_VERSION, FTS_TRIGRAM_SQL, LEGACY_FTS_SQL, LEGACY_FTS_TRIGRAM_SQL, SCHEMA_SQL, SCHEMA_VERSION, _FTS_CJK_TRIGGERS, _FTS_TRIGGERS, _ephemeral_child_sql, _sql_json_extract, fts_rebuild_admission
from hivemind_assembly.automation.state_engine.hermes_state_fts import _drop_orphan_fts_shadow_tables
from hivemind_assembly.automation.state_engine.hermes_state_holders import _read_proc_argv
from hivemind_assembly.automation.state_engine.hermes_state_search import _delete_meta, _meta_row
from hivemind_assembly.automation.state_engine.hermes_state_errors import is_sqlite_lock_error
from hivemind_assembly.automation.state_engine.hermes_state_titles import next_title_in_lineage
logger = logging.getLogger('hermes_state')
_FTS_HOLDER_ESCALATE_ATTEMPTS = 3
_FTS_HOLDER_ESCALATE_SECONDS = 60.0
_FTS_HOLDER_FUTILE_ATTEMPTS = 10
_FTS_HOLDER_FUTILE_SECONDS = 1800.0
_FTS_STALE_RETRY_SECONDS = 60.0
_MESSAGE_UID_BACKFILL_DONE = 'message_uid_backfill'
_MESSAGE_UID_BACKFILL_CURSOR = 'message_uid_backfill_id'
_MESSAGE_UID_BACKFILL_CHUNK = 2000
_MESSAGE_UID_BACKFILL_BUDGET_S = 1.0

def _holder_cmdline(pid: int) -> str:
    argv = _read_proc_argv(pid)
    return ' '.join(argv)[:120] if argv else '<cmdline unavailable>'
_FTS_TRIGRAM_TRIGGERS = tuple((n for n in _FTS_TRIGGERS if '_trigram_' in n))
_FTS_BASE_TRIGGERS = tuple((n for n in _FTS_TRIGGERS if n not in _FTS_TRIGRAM_TRIGGERS))
_FTS_DDL = {False: (FTS_SQL, FTS_TRIGRAM_SQL), True: (LEGACY_FTS_SQL, LEGACY_FTS_TRIGRAM_SQL)}
_LEGACY_INLINE_CONCAT_SQL = "COALESCE(content, '') || ' ' || COALESCE(tool_name, '') || ' ' || COALESCE(tool_calls, '') "
_SESSION_MODEL_USAGE_INDEX_SQL = ('CREATE INDEX IF NOT EXISTS idx_session_model_usage_session ON session_model_usage(session_id)', 'CREATE INDEX IF NOT EXISTS idx_session_model_usage_model ON session_model_usage(model)')
_SESSION_MODEL_USAGE_HEAL_DDL = "CREATE TABLE session_model_usage (\n    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,\n    model TEXT NOT NULL,\n    billing_provider TEXT NOT NULL DEFAULT '',\n    billing_base_url TEXT NOT NULL DEFAULT '',\n    billing_mode TEXT NOT NULL DEFAULT '',\n    task TEXT NOT NULL DEFAULT '',\n    api_call_count INTEGER NOT NULL DEFAULT 0,\n    input_tokens INTEGER NOT NULL DEFAULT 0,\n    output_tokens INTEGER NOT NULL DEFAULT 0,\n    cache_read_tokens INTEGER NOT NULL DEFAULT 0,\n    cache_write_tokens INTEGER NOT NULL DEFAULT 0,\n    reasoning_tokens INTEGER NOT NULL DEFAULT 0,\n    estimated_cost_usd REAL NOT NULL DEFAULT 0,\n    actual_cost_usd REAL NOT NULL DEFAULT 0,\n    cost_status TEXT,\n    cost_source TEXT,\n    first_seen REAL,\n    last_seen REAL,\n    PRIMARY KEY (session_id, model, billing_provider, billing_base_url, billing_mode, task)\n)"
_SESSION_MODEL_USAGE_V22_DDL = '\n'.join([_SESSION_MODEL_USAGE_HEAL_DDL.splitlines()[0]] + [' ' * 35 + ln.strip() for ln in _SESSION_MODEL_USAGE_HEAL_DDL.splitlines()[1:-1]] + [' ' * 31 + ')'])
_SESSION_MODEL_USAGE_V20_SEED_SQL = "INSERT OR IGNORE INTO session_model_usage (\n                               session_id, model, billing_provider,\n                               billing_base_url, billing_mode,\n                               api_call_count, input_tokens,\n                               output_tokens, cache_read_tokens,\n                               cache_write_tokens, reasoning_tokens,\n                               estimated_cost_usd, actual_cost_usd,\n                               cost_status, cost_source, first_seen, last_seen\n                           )\n                           SELECT id, COALESCE(model, 'unknown'),\n                                  COALESCE(billing_provider, ''),\n                                  COALESCE(billing_base_url, ''),\n                                  COALESCE(billing_mode, ''),\n                                  COALESCE(api_call_count, 0),\n                                  COALESCE(input_tokens, 0),\n                                  COALESCE(output_tokens, 0),\n                                  COALESCE(cache_read_tokens, 0),\n                                  COALESCE(cache_write_tokens, 0),\n                                  COALESCE(reasoning_tokens, 0),\n                                  COALESCE(estimated_cost_usd, 0),\n                                  COALESCE(actual_cost_usd, 0),\n                                  cost_status, cost_source,\n                                  started_at, COALESCE(ended_at, started_at)\n                           FROM sessions\n                           WHERE COALESCE(input_tokens, 0)\n                                 + COALESCE(output_tokens, 0)\n                                 + COALESCE(cache_read_tokens, 0)\n                                 + COALESCE(cache_write_tokens, 0)\n                                 + COALESCE(reasoning_tokens, 0) > 0"
_TITLE_UNIQUE_INDEX_SQL = 'CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_title_unique ON sessions(title) WHERE title IS NOT NULL'
_STALE_KEY_UPSERT_SQL = "INSERT INTO state_meta (key, value) VALUES (?, '1') ON CONFLICT(key) DO UPDATE SET value = excluded.value"
_STATE_META_UPSERT_SQL = 'INSERT INTO state_meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value'
_CLEAR_REBUILD_MARKERS_SQL = "DELETE FROM state_meta WHERE key IN ('fts_rebuild_high_water', 'fts_rebuild_progress')"
_DROP_RETIRED_TOOL_HIGH_WATER_SQL = "DELETE FROM state_meta WHERE key = 'fts_tool_full_content_high_water'"

def _legacy_inline_reinsert_sql(table: str, indent: int, *, delete_first: bool=False) -> str:
    """Legacy inline (pre-v23) FTS re-population script fragment (whitespace pinned)."""
    pad = ' ' * indent
    body = f'{pad}DELETE FROM {table};\n' if delete_first else ''
    return f"\n{body}{pad}INSERT INTO {table}(rowid, content)\n{pad}SELECT id,\n{pad}       COALESCE(content, '') || ' ' ||\n{pad}       COALESCE(tool_name, '') || ' ' ||\n{pad}       COALESCE(tool_calls, '')\n{pad}FROM messages;\n{pad[:-4]}"

def _q(ident: str) -> str:
    """Double-quote an SQL identifier."""
    return '"' + ident.replace('"', '""') + '"'

class SessionSchemaMixin:
    """See module docstring — mixin for SessionDB (Schema cluster)."""

    def _dedupe_legacy_system_prompts(self, cursor: sqlite3.Cursor) -> None:
        """Move inline prompt snapshots into the shared content-addressed table. Any
        ``OperationalError`` mid-loop returns instead of raising: partial migration is safe
        (the legacy column stays a read fallback; next init resumes), whereas propagating
        left the version below 25 and re-ran this on every open (gateway crash loop)."""
        try:
            rows = cursor.execute('SELECT id, system_prompt FROM sessions WHERE system_prompt IS NOT NULL').fetchall()
        except sqlite3.OperationalError:
            return
        for session_id, prompt in rows:
            try:
                prompt_hash = self._store_system_prompt(cursor, prompt)
                cursor.execute('UPDATE sessions SET system_prompt_hash = ?, system_prompt = NULL WHERE id = ?', (prompt_hash, session_id))
            except sqlite3.OperationalError as exc:
                logger.warning('v25 prompt dedupe paused after contention (%s); unmigrated rows keep the legacy inline prompt and the next schema init resumes the migration.', exc)
                return

    def _sqlite_supports_fts5(self, cursor: sqlite3.Cursor) -> bool:
        try:
            cursor.execute('CREATE VIRTUAL TABLE temp._hermes_fts5_probe USING fts5(x)')
            cursor.execute('DROP TABLE temp._hermes_fts5_probe')
            return True
        except sqlite3.OperationalError as exc:
            if not self._is_fts5_unavailable_error(exc):
                raise
            self._warn_fts5_unavailable(exc)
            return False

    def _drop_all_fts_triggers(self, cursor: sqlite3.Cursor) -> None:
        self._drop_fts_triggers(cursor)
        for trigger in _FTS_CJK_TRIGGERS:
            with contextlib.suppress(sqlite3.OperationalError):
                cursor.execute(f'DROP TRIGGER IF EXISTS {trigger}')

    @staticmethod
    def _fts_triggers_missing(cursor: sqlite3.Cursor, names: Sequence[str]) -> bool:
        """True unless every trigger in *names* (one DDL half) exists."""
        if not names:
            return False
        placeholders = ','.join(('?' for _ in names))
        sql = f"SELECT COUNT(*) FROM sqlite_master WHERE type = 'trigger' AND name IN ({placeholders})"
        return int(cursor.execute(sql, tuple(names)).fetchone()[0]) < len(names)

    @staticmethod
    def _fts_update_trigger_needs_narrowing(sql: Optional[str]) -> bool:
        """True when trigger SQL is a broad AFTER UPDATE (missing ``OF``)."""
        if not sql:
            return False
        compact = ' '.join(sql.split()).upper()
        return 'AFTER UPDATE OF ' not in compact and 'AFTER UPDATE ON ' in compact

    def _migrate_broad_fts_update_triggers(self, cursor: sqlite3.Cursor) -> int:
        """Replace broad AFTER UPDATE FTS triggers with AFTER UPDATE OF variants (``IF NOT EXISTS``
        never replaces an existing broad trigger). No FTS rebuild: correctness was already
        gated by WHEN clauses; OF only skips trigger evaluation. Returns the number dropped."""
        legacy_layout = self._db_has_legacy_inline_fts(cursor)
        update_names = ('messages_fts_update', 'messages_fts_trigram_update') + (() if legacy_layout else ('messages_fts_cjk_update',))
        placeholders = ', '.join(('?' for _ in update_names))
        sql = f"SELECT name, sql FROM sqlite_master WHERE type = 'trigger' AND name IN ({placeholders})"
        rows = cursor.execute(sql, update_names).fetchall()
        to_drop = [name for name, sql in rows if self._fts_update_trigger_needs_narrowing(sql)]
        if not to_drop:
            return 0
        for name in to_drop:
            cursor.execute(f'DROP TRIGGER IF EXISTS {name}')
        base_sql, trigram_sql = _FTS_DDL[legacy_layout]
        self._ensure_fts_schema(cursor, 'messages_fts', base_sql)
        self._ensure_fts_schema(cursor, 'messages_fts_trigram', trigram_sql)
        if 'messages_fts_cjk_update' in to_drop:
            try:
                self._ensure_fts_cjk_schema(cursor)
            except Exception:
                self._quarantine_cjk_after_update_of_migration(cursor)
                logger.exception('CJK FTS re-ensure after UPDATE OF migration failed')
                raise
            row = cursor.execute("SELECT sql FROM sqlite_master WHERE type = 'trigger' AND name = ?", ('messages_fts_cjk_update',)).fetchone()
            if not row or self._fts_update_trigger_needs_narrowing(row[0]):
                self._quarantine_cjk_after_update_of_migration(cursor)
                logger.warning('CJK FTS UPDATE trigger missing or still broad after UPDATE OF migration; marked stale and unavailable')
        logger.info('Migrated %d broad FTS UPDATE trigger(s) to AFTER UPDATE OF (no rebuild required)', len(to_drop))
        return len(to_drop)

    @staticmethod
    def _fts_index_is_misaligned_source(cursor: sqlite3.Cursor) -> bool:
        """True when ``messages_fts`` is still external-content over the raw
        ``messages`` table (FTS_STORAGE_VERSION < 3): its index holds a TRUNCATED
        projection for long tool rows that the checker/'delete' commands re-read
        as FULL content, a mismatch by construction. Such an index cannot be
        repaired in place — it must be 'rebuild'-filled from the aligned
        ``messages_fts_src`` view exactly once."""
        row = cursor.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'messages_fts'").fetchone()
        return row is not None and 'messages_fts_src' not in (row[0] or '')

    @staticmethod
    def _execute_ddl_skipping_settled_triggers(cursor: sqlite3.Cursor, ddl: str) -> None:
        """Run *ddl* statement by statement, skipping each ``DROP TRIGGER IF EXISTS x`` /
        ``CREATE TRIGGER IF NOT EXISTS x …`` pair whose trigger already exists with the same body.

        ``DROP TRIGGER IF EXISTS`` on an existing trigger takes SQLite's write lock (the
        ``CREATE … IF NOT EXISTS`` forms do not), so the unconditional drop+recreate that lets a
        changed trigger body roll out would otherwise block every open of a settled database
        behind a sibling process's transaction. ``sqlite_master.sql`` stores the CREATE text
        verbatim minus ``IF NOT EXISTS`` and the ``;``, so an exact comparison decides.
        """
        stored = dict(cursor.execute("SELECT name, sql FROM sqlite_master WHERE type = 'trigger'").fetchall())
        pending_drop: Optional[str] = None
        statement = ''
        for line in ddl.splitlines():
            statement += line + '\n'
            if not sqlite3.complete_statement(statement):
                continue
            statement, current = ('', statement.strip())
            upper = current.upper()
            if upper.startswith('DROP TRIGGER IF EXISTS '):
                pending_drop = current
                continue
            if upper.startswith('CREATE TRIGGER IF NOT EXISTS '):
                desired = current.replace('IF NOT EXISTS ', '', 1).rstrip(';')
                if stored.get(desired.split(None, 3)[2]) == desired:
                    pending_drop = None
                    continue
            if pending_drop is not None:
                cursor.execute(pending_drop)
                pending_drop = None
            cursor.execute(current)
        if statement.strip():
            raise sqlite3.OperationalError('incomplete DDL statement')

    def _migrate_misaligned_fts_source(self, cursor: sqlite3.Cursor, *, legacy: bool) -> None:
        """Re-point ``messages_fts`` at the stable ``messages_fts_src`` projection view and
        rebuild it ONCE (FTS_STORAGE_VERSION 2 -> 3). A v1/v2 base index carries token streams
        the raw-``messages`` external-content source cannot read back (truncated long tool
        rows, and tool rows whose full content was indexed under an old high-water mark), so
        in-place continuity is not achievable — the ONLY valid transition is a full rebuild
        from the view, under the shared cross-process rebuild admission. Legacy inline DBs
        skip this entirely (their index is self-contained; they still take the DDL on the
        optimize path)."""
        if legacy or not self._sqlite_table_exists(cursor, 'messages_fts'):
            return
        if not self._fts_index_is_misaligned_source(cursor):
            return
        has_messages = cursor.execute('SELECT 1 FROM messages LIMIT 1').fetchone() is not None

        def do_align() -> None:
            for name in _FTS_BASE_TRIGGERS:
                cursor.execute(f'DROP TRIGGER IF EXISTS {name}')
            cursor.execute('DROP TABLE IF EXISTS messages_fts')
            self._ensure_fts_schema(cursor, 'messages_fts', FTS_SQL)
            if has_messages:
                cursor.execute("INSERT INTO messages_fts(messages_fts) VALUES('rebuild')")
            cursor.execute(_CLEAR_REBUILD_MARKERS_SQL)
            cursor.execute(_DROP_RETIRED_TOOL_HIGH_WATER_SQL)
            cursor.execute(_STATE_META_UPSERT_SQL, ('fts_storage_version', str(FTS_STORAGE_VERSION)))
        if not has_messages:
            cursor.execute('SAVEPOINT fts_align_empty')
            try:
                do_align()
                cursor.execute('RELEASE SAVEPOINT fts_align_empty')
            except BaseException:
                cursor.execute('ROLLBACK TO SAVEPOINT fts_align_empty')
                cursor.execute('RELEASE SAVEPOINT fts_align_empty')
                raise
            return
        self._run_admitted_startup_rebuild(cursor, do_align)

    @staticmethod
    def _sqlite_table_exists(cursor: sqlite3.Cursor, name: str) -> bool:
        return cursor.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone() is not None

    def _migrate_trigram_cron_exclusion(self, cursor: sqlite3.Cursor) -> bool:
        """Install the source-filtered trigram view and purge historical rows (v29 cron exclusion,
        v30 subagent exclusion: both only change the view/trigger predicate and rebuild from it).
        Legacy inline indexes stay opt-in (their content is private to the vtable). A v1 external
        layout whose vtable still declares ``tool_calls`` is left to ``optimize-storage``: swapping
        the view underneath would make 'rebuild' read a column the view no longer has. Otherwise
        the inverted index still holds excluded rows until FTS5 rebuilds from the new view, which
        runs under the shared cross-process admission gate. Returns False to hold schema_version back."""
        if self._db_has_legacy_inline_fts(cursor) or self._db_has_trigram_tool_calls_projection(cursor):
            return True
        trigram_exists = self._fts_table_probe(cursor, 'messages_fts_trigram')
        if trigram_exists is not True:
            return trigram_exists is False
        for name in _FTS_TRIGRAM_TRIGGERS:
            cursor.execute(f'DROP TRIGGER IF EXISTS {name}')
        cursor.execute('DROP VIEW IF EXISTS messages_fts_trigram_src')
        if not self._ensure_fts_schema(cursor, 'messages_fts_trigram', FTS_TRIGRAM_SQL):
            return False
        self._run_admitted_startup_rebuild(cursor, lambda: cursor.execute("INSERT INTO messages_fts_trigram(messages_fts_trigram) VALUES('rebuild')"))
        return True

    def _quarantine_cjk_after_update_of_migration(self, cursor: sqlite3.Cursor) -> None:
        """Fail closed after dropping the CJK UPDATE trigger mid-migration: clear availability,
        persist ``fts_cjk_stale``, drop any residual trigger so a later open cannot
        IF-NOT-EXISTS over a gap."""
        self._fts_cjk_available = False
        try:
            self.set_meta(FTS_CJK_STALE_KEY, '1', cursor=cursor)
        except Exception:
            logger.debug('Could not persist CJK FTS stale breadcrumb', exc_info=True)
        try:
            cursor.execute('DROP TRIGGER IF EXISTS messages_fts_cjk_update')
        except Exception:
            logger.debug('Could not drop residual CJK UPDATE trigger after quarantine', exc_info=True)

    @staticmethod
    def _rebuild_fts_indexes(cursor: sqlite3.Cursor, *, legacy: bool=False, include_trigram: bool=True) -> None:
        """v23+ external-content 'rebuild'. It indexes EVERY row, so the deferred-backfill
        markers are cleared or the worker would re-insert covered rows (duplicates).
        ``legacy`` (pre-v23 inline layout) has no external-content 'rebuild' source, so it
        DELETEs + reinserts the concatenated content the legacy triggers produced."""
        tables = ('messages_fts', 'messages_fts_trigram') if include_trigram else ('messages_fts',)
        for tbl in tables:
            if legacy:
                cursor.execute(f'DELETE FROM {tbl}')
                cursor.execute(f'INSERT INTO {tbl}(rowid, content) SELECT id, {_LEGACY_INLINE_CONCAT_SQL}FROM messages')
            else:
                cursor.execute(f"INSERT INTO {tbl}({tbl}) VALUES('rebuild')")
        if not legacy:
            cursor.execute(_CLEAR_REBUILD_MARKERS_SQL)

    def _fts_table_probe(self, cursor: sqlite3.Cursor, table_name: str) -> Optional[bool]:
        """True = queryable, False = absent, None = FTS module/tokenizer missing or content
        undecodable (index degraded, store accessible). Invalid UTF-8 surfaces as a bare
        UnicodeDecodeError on some builds and OperationalError("Could not decode to UTF-8")
        on others; both are caught so the probe never raises into init/recovery flows.
        Anything else (malformed schema, corrupt vtable) re-raises."""
        try:
            cursor.execute(f'SELECT * FROM {table_name} LIMIT 0')
            return True
        except UnicodeDecodeError as exc:
            decode_exc = exc
        except sqlite3.OperationalError as exc:
            if self._is_fts5_unavailable_error(exc):
                if self._is_trigram_unavailable_error(exc):
                    self._warn_trigram_unavailable(exc)
                else:
                    self._warn_fts5_unavailable(exc)
                return None
            if 'no such table' in str(exc).lower():
                return False
            if 'decode to utf-8' not in str(exc).lower():
                raise
            decode_exc = exc
        logger.warning('%s probe encountered invalid UTF-8 in FTS content; search may return incomplete results until FTS is rebuilt: %s', table_name, decode_exc)
        return None

    def _defer_stale_fts_for_holders(self, cursor: sqlite3.Cursor, foreign_holders) -> bool:
        """Record a deferral diagnostic for the foreign processes holding the DB; True = defer
        (holders remain). After ``_FTS_HOLDER_ESCALATE_ATTEMPTS`` deferrals spanning
        ``_FTS_HOLDER_ESCALATE_SECONDS``, provably inactive orphan Desktop backends are
        reaped and the holders re-checked. The orphan reap is the only exit, so a supervised
        peer (never an orphan) blocks forever: once the SAME PID set has blocked
        ``_FTS_HOLDER_FUTILE_ATTEMPTS`` deferrals over ``_FTS_HOLDER_FUTILE_SECONDS`` the
        record is marked ``futile`` and the escalation names the holders and the remedy that
        works from inside a gateway session (stop only the other holder; this process's own
        retry tick admits the rebuild). A changed holder set restarts that window."""
        now = time.time()
        try:
            row = cursor.execute('SELECT value FROM state_meta WHERE key = ? LIMIT 1', (FTS_REBUILD_DEFERRAL_KEY,)).fetchone()
        except sqlite3.Error:
            row = None
        parsed = safe_json_loads(row[0]) if row else None
        record = parsed if isinstance(parsed, dict) else {}
        try:
            first_seen = float(record.get('first_seen', now))
            attempts = int(record.get('attempts', 0)) + 1
            holders_since = float(record.get('holders_since', now))
            holders_attempts = int(record.get('holders_attempts', 0)) + 1
        except (TypeError, ValueError):
            first_seen, attempts, holders_since, holders_attempts = (now, 1, now, 1)
        if first_seen > now or first_seen < 0:
            first_seen = now
        holder_pids = sorted({pid for pid, _path in foreign_holders if pid > 0})
        if holder_pids != record.get('holder_pids'):
            holders_since, holders_attempts = (now, 1)
        if attempts >= _FTS_HOLDER_ESCALATE_ATTEMPTS and now - first_seen >= _FTS_HOLDER_ESCALATE_SECONDS:
            reaped = self._reap_inactive_orphan_desktop_holders(foreign_holders, min_age_seconds=_FTS_HOLDER_ESCALATE_SECONDS)
            if reaped:
                logger.error('Reaped inactive orphan Desktop backend(s) %s after %d state.db FTS rebuild deferrals; checking holders again.', reaped, attempts)
                foreign_holders = self._foreign_state_db_holders()
                holder_pids = sorted({pid for pid, _path in foreign_holders if pid > 0})
        futile = bool(holder_pids) and (holders_attempts >= _FTS_HOLDER_FUTILE_ATTEMPTS and now - holders_since >= _FTS_HOLDER_FUTILE_SECONDS)
        diagnostic = {'first_seen': first_seen, 'last_seen': now, 'attempts': attempts, 'holder_pids': holder_pids, 'holders_since': holders_since, 'holders_attempts': holders_attempts, 'futile': futile}
        cursor.execute('INSERT INTO state_meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value', (FTS_REBUILD_DEFERRAL_KEY, json.dumps(diagnostic, sort_keys=True)))
        if not foreign_holders:
            self._fts_deferred_holder_pids = None
            return False
        self._fts_deferred_holder_pids = holder_pids
        if futile:
            logger.error('state.db FTS repair has been blocked by the same holder(s) for %d deferrals over %.0f min (%s); waiting is futile. Stop ONLY the other holder(s) — this process keeps running and its own retry admits the rebuild within %.0fs of the holder leaving. `hermes doctor` shows this.', holders_attempts, (now - holders_since) / 60.0, ', '.join((f'pid {pid}: {_holder_cmdline(pid)}' for pid in holder_pids)), _FTS_STALE_RETRY_SECONDS)
        elif attempts >= _FTS_HOLDER_ESCALATE_ATTEMPTS and now - first_seen >= _FTS_HOLDER_ESCALATE_SECONDS:
            logger.error("state.db FTS repair remains blocked after %d deferrals by holder(s) %s. Stop the listed processes (this process's own retry then rebuilds), or run `hermes sessions optimize-storage` with every holder stopped. `hermes doctor` reports this degraded state.", attempts, foreign_holders)
        logger.warning('Deferred stale state.db FTS rebuild while foreign processes hold the database or WAL sidecars (%s); canonical writes and LIKE search remain available (deferral %d).', foreign_holders, attempts)
        return True

    def _recover_stale_fts(self, cursor: sqlite3.Cursor, *, legacy: bool, timeout_seconds=None) -> bool:
        """Atomically rebuild stale base/trigram indexes and resume syncing. *timeout_seconds*
        bounds the admission wait (None = full startup budget, ``0`` = non-blocking retry).
        Fails closed: holders or a lost admission race leave the breadcrumb set."""
        foreign_holders = self._foreign_state_db_holders()
        if foreign_holders and self._defer_stale_fts_for_holders(cursor, foreign_holders):
            return False
        with fts_rebuild_admission(self.db_path, timeout_seconds=timeout_seconds) as admitted:
            if not admitted:
                logger.warning('Deferred stale state.db FTS rebuild: another process holds the rebuild authority; canonical writes and LIKE search remain available.')
                return False
            return self._recover_stale_fts_locked(cursor, legacy=legacy)

    def _recover_stale_fts_locked(self, cursor: sqlite3.Cursor, *, legacy: bool) -> bool:
        """Body of :meth:`_recover_stale_fts`; caller holds rebuild authority. One write
        transaction, so no canonical writer slips between rebuild and trigger restoration."""
        try:
            trigram_present = self._fts_table_probe(cursor, 'messages_fts_trigram') is True
        except (sqlite3.DatabaseError, UnicodeDecodeError):
            include_trigram = True
        else:
            include_trigram = trigram_present or (not legacy and self._trigram_tokenizer_available(cursor))
        drop_sql = ''.join((f'DROP TRIGGER IF EXISTS {trigger};' for trigger in _FTS_TRIGGERS))
        if include_trigram:
            drop_sql += 'DROP TABLE IF EXISTS messages_fts_trigram;'
        drop_sql += 'DROP VIEW IF EXISTS messages_fts_trigram_src;DROP TABLE IF EXISTS messages_fts;'
        if legacy:
            rebuild_sql = LEGACY_FTS_SQL + (LEGACY_FTS_TRIGRAM_SQL if include_trigram else '')
            rebuild_sql += _legacy_inline_reinsert_sql('messages_fts', 16)
            if include_trigram:
                rebuild_sql += _legacy_inline_reinsert_sql('messages_fts_trigram', 20, delete_first=True)
        else:
            rebuild_sql = FTS_SQL + (FTS_TRIGRAM_SQL if include_trigram else '')
            rebuild_sql += "INSERT INTO messages_fts(messages_fts) VALUES('rebuild');"
            if include_trigram:
                rebuild_sql += "INSERT INTO messages_fts_trigram(messages_fts_trigram) VALUES('rebuild');"
            rebuild_sql += _CLEAR_REBUILD_MARKERS_SQL + ';' + _DROP_RETIRED_TOOL_HIGH_WATER_SQL + ';'
        recovery_sql = 'BEGIN IMMEDIATE;' + drop_sql + rebuild_sql + f"DELETE FROM state_meta WHERE key IN ('{FTS_STALE_KEY}', '{FTS_REBUILD_DEFERRAL_KEY}');COMMIT;"
        try:
            cursor.executescript(recovery_sql)
        except sqlite3.DatabaseError as exc:
            with contextlib.suppress(sqlite3.Error):
                self._conn.rollback()
            self._drop_all_fts_triggers(cursor)
            self._conn.commit()
            logger.error('Automatic rebuild of stale FTS indexes failed (%s); canonical writes remain enabled with FTS detached.', exc)
            return False
        self._fts_stale = False
        self._fts_enabled = True
        self._trigram_available = include_trigram
        logger.warning('Rebuilt stale state.db FTS indexes from canonical messages and restored sync triggers.')
        return True

    def _trigram_tokenizer_available(self, cursor: sqlite3.Cursor) -> bool:
        """Probe trigram support without publishing a persistent FTS object."""
        probe = 'temp.hermes_fts5_trigram_probe'
        cursor.execute(f'DROP TABLE IF EXISTS {probe}')
        try:
            cursor.execute(f"CREATE VIRTUAL TABLE {probe} USING fts5(content, tokenize='trigram')")
        except sqlite3.OperationalError as exc:
            if not self._is_trigram_unavailable_error(exc):
                raise
            self._warn_trigram_unavailable(exc)
            return False
        finally:
            cursor.execute(f'DROP TABLE IF EXISTS {probe}')
        return True

    @staticmethod
    def _parse_schema_columns(schema_sql: str) -> dict[str, dict[str, str]]:
        """Expected columns per table: execute SCHEMA_SQL in an in-memory database and read
        PRAGMA table_info (no regex). Memoized on disk keyed by a DDL hash (~85ms per
        startup otherwise); only the reference-side parse is cached — diffing the LIVE
        database still runs every startup. A corrupt/stale cache degrades to recomputation."""
        cache_path = None
        schema_hash = hashlib.sha256(schema_sql.encode('utf-8')).hexdigest()
        with contextlib.suppress(Exception):
            from hivemind_assembly.automation.state_engine.hermes_constants import get_hermes_home as _home
            cache_path = _home() / 'cache' / 'schema_columns.json'
            blob = json.loads(cache_path.read_text(encoding='utf-8'))
            tables = blob.get('tables') if isinstance(blob, dict) and blob.get('schema_hash') == schema_hash else None
            if isinstance(tables, dict) and all((isinstance(cols, dict) and all((isinstance(v, str) for v in cols.values())) for cols in tables.values())):
                return tables
        ref = sqlite3.connect(':memory:')
        try:
            ref.executescript(schema_sql)
            table_columns: dict[str, dict[str, str]] = {}
            for tbl, in ref.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
                cols: dict[str, str] = {}
                info = ref.execute(f'PRAGMA table_info("{tbl}")').fetchall()
                for _cid, col_name, col_type, notnull, default, pk in info:
                    parts = [col_type] if col_type else []
                    if notnull and (not pk):
                        parts.append('NOT NULL')
                    if default is not None:
                        parts.append(f'DEFAULT {default}')
                    cols[col_name] = ' '.join(parts)
                table_columns[tbl] = cols
        finally:
            ref.close()
        if cache_path is not None:
            with contextlib.suppress(Exception):
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                fd, tmp = tempfile.mkstemp(dir=str(cache_path.parent), prefix='.schema_columns.')
                with os.fdopen(fd, 'w', encoding='utf-8') as fh:
                    json.dump({'schema_hash': schema_hash, 'tables': table_columns}, fh)
                os.replace(tmp, cache_path)
        return table_columns

    def _reconcile_columns(self, cursor: sqlite3.Cursor) -> None:
        """ADD every SCHEMA_SQL column missing from the live tables (SCHEMA_SQL is the single
        source of truth; column additions need no version-gated migration)."""
        expected = self._parse_schema_columns(SCHEMA_SQL)
        for table_name, declared_cols in expected.items():
            try:
                rows = cursor.execute(f'PRAGMA table_info("{table_name}")').fetchall()
            except sqlite3.OperationalError:
                continue
            if not rows:
                continue
            live_cols = {row[1] for row in rows}
            for col_name, col_type in declared_cols.items():
                if col_name in live_cols:
                    continue
                try:
                    cursor.execute(f'ALTER TABLE "{table_name}" ADD COLUMN {_q(col_name)} {col_type}')
                except sqlite3.OperationalError as exc:
                    message = str(exc).lower()
                    if 'duplicate column' in message:
                        logger.debug('reconcile %s.%s: %s', table_name, col_name, exc)
                        continue
                    if is_sqlite_lock_error(exc):
                        raise
                    logger.warning('reconcile %s.%s failed; store remains behind SCHEMA_SQL: %s', table_name, col_name, exc)

    @staticmethod
    def _live_pk_columns(cursor: sqlite3.Cursor, table: str) -> Optional[list[str]]:
        """PRIMARY KEY column names of *table* in key order; None when the table is
        missing or has no columns (SCHEMA_SQL creates it correctly)."""
        try:
            rows = cursor.execute(f'PRAGMA table_info("{table}")').fetchall()
        except sqlite3.OperationalError:
            rows = None
        if not rows:
            return None
        return [r[1] for r in sorted((r for r in rows if r[5]), key=lambda r: r[5])]

    @staticmethod
    def _rebuild_table(cursor: sqlite3.Cursor, table: str, legacy_name: str, ddl: str, copy_sql: str, indexes=()) -> None:
        """RENAME *table* to *legacy_name*, CREATE it fresh from *ddl*, copy rows back with
        *copy_sql*, DROP the legacy copy, recreate *indexes* — as ONE write transaction.

        The writer connection is autocommit (``isolation_level=None``), so without an explicit
        BEGIN each statement commits on its own and a sibling process opening the same state.db
        between RENAME and CREATE runs SCHEMA_SQL's ``CREATE TABLE IF NOT EXISTS`` first: our
        CREATE then fails with "table already exists", every row is stranded in *legacy_name*
        and the live table is empty. BEGIN IMMEDIATE holds the write lock for the whole rebuild
        so the sibling blocks (and retries under its lock patience) instead of interleaving;
        any failure rolls the RENAME back."""
        conn = cursor.connection
        if conn.in_transaction:
            SessionSchemaMixin._rebuild_table_statements(cursor, table, legacy_name, ddl, copy_sql, indexes)
            return
        cursor.execute('BEGIN IMMEDIATE')
        try:
            SessionSchemaMixin._rebuild_table_statements(cursor, table, legacy_name, ddl, copy_sql, indexes)
        except BaseException:
            cursor.execute('ROLLBACK')
            raise
        cursor.execute('COMMIT')

    def _heal_gateway_routing_pk(self, cursor: sqlite3.Cursor) -> None:
        """Rebuild ``gateway_routing`` when its PRIMARY KEY predates scoping (``session_key TEXT
        PRIMARY KEY``): the reconciler ADDs ``scope`` but SQLite cannot ALTER a PK, so every
        routing write fails (ON CONFLICT mismatch / cross-scope UNIQUE violation). Newest
        row wins a cross-scope session_key collision (INSERT OR REPLACE in updated_at order).

        Early builds of the routing-index migration (#59203) created the table with ``session_key TEXT
        PRIMARY KEY`` and no ``scope`` column. ``_reconcile_columns()`` ADDs the missing ``scope`` column on
        those databases, but SQLite cannot ALTER a primary key, so the shipped composite ``PRIMARY KEY
        (scope, session_key)`` never lands. On such tables every write path is broken:
        """
        pk_cols = self._live_pk_columns(cursor, 'gateway_routing')
        if pk_cols is None or pk_cols == ['scope', 'session_key']:
            return
        logger.info('gateway_routing has legacy primary key %r; rebuilding with composite (scope, session_key) key', pk_cols)
        self._rebuild_table(cursor, 'gateway_routing', 'gateway_routing_legacy_pk', "CREATE TABLE gateway_routing (\n    scope TEXT NOT NULL DEFAULT '',\n    session_key TEXT NOT NULL,\n    entry_json TEXT NOT NULL,\n    updated_at REAL NOT NULL,\n    PRIMARY KEY (scope, session_key)\n)", "INSERT OR REPLACE INTO gateway_routing (scope, session_key, entry_json, updated_at) SELECT COALESCE(scope, ''), session_key, entry_json, updated_at FROM gateway_routing_legacy_pk ORDER BY updated_at ASC")

    def _heal_session_model_usage_pk(self, cursor: sqlite3.Cursor) -> None:
        """Rebuild ``session_model_usage`` when its PRIMARY KEY lacks ``task``: installs already at
        v22+ when ``task`` landed carry the 5-column PK, the reconciler ADDs ``task`` but
        SQLite cannot ALTER a PK, and the v22 rebuild is unreachable — every upsert then
        fails (ON CONFLICT mismatch), silently zeroing accounting. Idempotent. FK-off
        window: INSERT OR IGNORE does NOT suppress FK violations, so an orphaned usage row
        would abort the rebuild (PRAGMA foreign_keys is a no-op inside a transaction; none
        is open here). OR IGNORE: COALESCE(task, '') on legacy NULL rows can collide with a
        genuine ''-task row — keep the first.

        Installs whose ``state.db`` reached ``schema_version >= 22`` before the ``task`` dimension was added
        carry a 5-column PRIMARY KEY ``(session_id, model, billing_provider, billing_base_url,
        billing_mode)``. See #73823.
        """
        pk_cols = self._live_pk_columns(cursor, 'session_model_usage')
        if pk_cols is None or 'task' in pk_cols:
            return
        logger.info('session_model_usage has legacy primary key %r (missing task); rebuilding with composite 6-column key', sorted(pk_cols))
        cursor.execute('PRAGMA foreign_keys=OFF')
        try:
            self._rebuild_table(cursor, 'session_model_usage', 'session_model_usage_legacy_pk', _SESSION_MODEL_USAGE_HEAL_DDL, "INSERT OR IGNORE INTO session_model_usage (\n                       session_id, model, billing_provider, billing_base_url,\n                       billing_mode, task, api_call_count, input_tokens,\n                       output_tokens, cache_read_tokens, cache_write_tokens,\n                       reasoning_tokens, estimated_cost_usd, actual_cost_usd,\n                       cost_status, cost_source, first_seen, last_seen\n                   )\n                   SELECT session_id, model,\n                          COALESCE(billing_provider, ''),\n                          COALESCE(billing_base_url, ''),\n                          COALESCE(billing_mode, ''),\n                          COALESCE(task, ''),\n                          api_call_count, input_tokens,\n                          output_tokens, cache_read_tokens, cache_write_tokens,\n                          reasoning_tokens, estimated_cost_usd, actual_cost_usd,\n                          cost_status, cost_source, first_seen, last_seen\n                   FROM session_model_usage_legacy_pk", _SESSION_MODEL_USAGE_INDEX_SQL)
        except sqlite3.OperationalError as exc:
            logger.debug('session_model_usage PK heal skipped: %s', exc)
        finally:
            cursor.execute('PRAGMA foreign_keys=ON')

    def _init_schema(self):
        """Create tables and FTS if missing, reconcile columns, run data migrations. Column
        additions are declarative via _reconcile_columns(), so reordered migrations can
        never skip a column; schema_version remains for data migrations only."""
        report_startup_progress(600.0, phase='state_db_init_schema')
        cursor = self._conn.cursor()
        cursor.executescript(SCHEMA_SQL)
        self._reconcile_columns(cursor)
        self._heal_gateway_routing_pk(cursor)
        self._heal_session_model_usage_pk(cursor)
        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_messages_platform_msg_id ON messages(session_id, platform_message_id) WHERE platform_message_id IS NOT NULL')
        except sqlite3.OperationalError as exc:
            logger.debug('idx_messages_platform_msg_id create skipped: %s', exc)
        self._execute_ddl_skipping_settled_triggers(cursor, DEFERRED_INDEX_SQL)
        with contextlib.suppress(sqlite3.OperationalError):
            if cursor.execute('SELECT 1 FROM messages WHERE active IS NULL LIMIT 1').fetchone() is not None:
                cursor.execute('UPDATE messages SET active = 1 WHERE active IS NULL')
        fts5_available = self._sqlite_supports_fts5(cursor)
        stale_row = cursor.execute('SELECT 1 FROM state_meta WHERE key = ? LIMIT 1', (FTS_STALE_KEY,)).fetchone()
        self._fts_stale = stale_row is not None
        if self._fts_stale:
            self._drop_all_fts_triggers(cursor)
        if not fts5_available:
            self._drop_fts_triggers(cursor)
        row = cursor.execute('SELECT version FROM schema_version LIMIT 1').fetchone()
        if row is None:
            cursor.execute('INSERT INTO schema_version (version) VALUES (?)', (SCHEMA_VERSION,))
            now_iso = datetime.datetime.now(datetime.UTC).isoformat()
            cursor.executemany('INSERT OR IGNORE INTO state_meta (key, value) VALUES (?, ?)', [('store_instance_id', str(uuid.uuid4())), ('store_created_at_utc', now_iso), (_MESSAGE_UID_BACKFILL_DONE, '1')])
        else:
            self._run_data_migrations(cursor, row[0], fts5_available)
        self._ensure_unique_title_index(cursor)
        if fts5_available:
            self._init_fts(cursor)
        self._conn.commit()

    def _run_data_migrations(self, cursor: sqlite3.Cursor, current_version: int, fts5_available: bool) -> None:
        """Version-gated chain for DATA migrations only (row backfills); column additions never
        belong here. Advances schema_version at the end unless FTS5 is unavailable."""
        report_startup_progress(600.0, phase='state_db_data_migrations')
        if current_version < 16:
            with contextlib.suppress(sqlite3.OperationalError):
                cursor.execute(f"UPDATE sessions SET model_config = json_set(COALESCE(model_config, '{{}}'), '$._delegate_from', parent_session_id) WHERE parent_session_id IS NOT NULL AND {_sql_json_extract('model_config', '$._delegate_from')} IS NULL AND {_ephemeral_child_sql('sessions')}")
                cursor.execute(f"UPDATE sessions SET model_config = json_set(COALESCE(model_config, '{{}}'), '$._delegate_from', '__orphaned__') WHERE parent_session_id IS NULL AND {_sql_json_extract('model_config', '$._delegate_from')} IS NULL AND {_sql_json_extract('model_config', '$._branched_from')} IS NULL AND title IS NULL AND message_count <= 25 AND EXISTS (SELECT 1 FROM messages m             WHERE m.session_id = sessions.id AND m.role = 'tool') AND NOT EXISTS (SELECT 1 FROM sessions ch                 WHERE ch.parent_session_id = sessions.id)")
        if current_version < 18:
            try:
                self._backfill_gateway_metadata_from_sessions_json(cursor)
            except Exception as exc:
                logger.debug('v18 gateway metadata backfill skipped: %s', exc)
        if current_version < 20:
            with contextlib.suppress(sqlite3.OperationalError):
                cursor.execute(_SESSION_MODEL_USAGE_V20_SEED_SQL)
        if current_version < 22:
            self._migrate_v22_session_model_usage(cursor)
        if current_version < 23 and fts5_available and self._db_needs_fts_storage_upgrade(cursor):
            self.set_meta('fts_optimize_available', '1', cursor=cursor)
        if current_version < 25:
            self._dedupe_legacy_system_prompts(cursor)
        self._advance_message_uid_backfill(cursor)
        fts_migrations_complete = True
        if current_version < 30 and fts5_available:
            fts_migrations_complete = self._migrate_trigram_cron_exclusion(cursor)
        if fts5_available and (not self._db_needs_fts_storage_upgrade(cursor)) and (cursor.execute("SELECT 1 FROM state_meta WHERE key = 'fts_rebuild_high_water' LIMIT 1").fetchone() is None) and (not self._has_fts_trash(cursor)) and (not self._fts_external_index_empty_with_messages(cursor)):
            if cursor.execute("SELECT 1 FROM state_meta WHERE key = 'fts_storage_version' AND value = ? LIMIT 1", (str(FTS_STORAGE_VERSION),)).fetchone() is None:
                self.set_meta('fts_storage_version', str(FTS_STORAGE_VERSION), cursor=cursor)
        if current_version < SCHEMA_VERSION and fts_migrations_complete and fts5_available:
            cursor.execute('UPDATE schema_version SET version = ?', (SCHEMA_VERSION,))

    def _advance_message_uid_backfill(self, cursor: sqlite3.Cursor) -> None:
        """Mint ``message_uid`` onto rows written before the column existed, one bounded slice per open.

        A single full-table UPDATE held the write lock for 261 s on an 835k-row / 4.8 GB store, so every
        sibling process timed out with "database is locked". Id-range chunks commit one at a time (the
        writer connection is autocommit) and an open spends at most ``_MESSAGE_UID_BACKFILL_BUDGET_S``
        after its first chunk, so a large store converges over later opens. Until then a legacy row
        simply has no uid, which every reader already treats as "no identity yet"."""
        if _meta_row(cursor, _MESSAGE_UID_BACKFILL_DONE) is not None:
            return
        row = _meta_row(cursor, _MESSAGE_UID_BACKFILL_CURSOR)
        done_through = int(row[0]) if row else 0
        high = cursor.execute('SELECT MAX(id) FROM messages').fetchone()[0] or 0
        deadline = time.monotonic() + _MESSAGE_UID_BACKFILL_BUDGET_S
        while done_through < high:
            upper = done_through + _MESSAGE_UID_BACKFILL_CHUNK
            cursor.execute('UPDATE messages SET message_uid = lower(hex(randomblob(16))) WHERE id > ? AND id <= ? AND message_uid IS NULL', (done_through, upper))
            done_through = upper
            if done_through < high and time.monotonic() >= deadline:
                self.set_meta(_MESSAGE_UID_BACKFILL_CURSOR, str(done_through), cursor=cursor)
                return
        self.set_meta(_MESSAGE_UID_BACKFILL_DONE, '1', cursor=cursor)
        _delete_meta(cursor, _MESSAGE_UID_BACKFILL_CURSOR)

    def _migrate_v22_session_model_usage(self, cursor: sqlite3.Cursor) -> None:
        """v22: ``task`` joins the session_model_usage PRIMARY KEY ('' = main loop; aux calls
        named). SQLite cannot ALTER a PK, so rebuild; existing rows → task=''."""
        try:
            legacy_pk = cursor.execute("SELECT COUNT(*) FROM pragma_table_info('session_model_usage') WHERE name = 'task' AND pk > 0").fetchone()[0]
            if legacy_pk:
                return
            self._rebuild_table(cursor, 'session_model_usage', 'session_model_usage_v21', _SESSION_MODEL_USAGE_V22_DDL, "INSERT INTO session_model_usage (\n                                   session_id, model, billing_provider, billing_base_url,\n                                   billing_mode, task, api_call_count, input_tokens,\n                                   output_tokens, cache_read_tokens, cache_write_tokens,\n                                   reasoning_tokens, estimated_cost_usd, actual_cost_usd,\n                                   cost_status, cost_source, first_seen, last_seen\n                               )\n                               SELECT session_id, model, billing_provider, billing_base_url,\n                                      billing_mode, '', api_call_count, input_tokens,\n                                      output_tokens, cache_read_tokens, cache_write_tokens,\n                                      reasoning_tokens, estimated_cost_usd, actual_cost_usd,\n                                      cost_status, cost_source, first_seen, last_seen\n                               FROM session_model_usage_v21", _SESSION_MODEL_USAGE_INDEX_SQL)
        except sqlite3.OperationalError as exc:
            logger.debug('v22 session_model_usage rebuild skipped: %s', exc)

    def _ensure_unique_title_index(self, cursor: sqlite3.Cursor) -> None:
        """Unique title index. Older DBs may hold duplicate titles from before the constraint.
        Per title a user-owned (user/NULL) row beats llm > derived (``_title_rank``). User rows are
        never dropped: the oldest keeps the title and newer ones become ``Title #k`` in started_at
        order, so the "#N"-preferring lookup still opens the newest (#126764). Among auto titles
        only, the newest highest-ranked keeps it; lower-ranked auto titles are cleared. Each change
        is logged. Must never abort opening the DB, so the repair is guarded."""
        try:
            cursor.execute(_TITLE_UNIQUE_INDEX_SQL)
        except sqlite3.IntegrityError:
            cursor.execute('SAVEPOINT title_repair')
            try:
                rows = cursor.execute('SELECT rowid, title, title_source, started_at FROM sessions WHERE title IN (SELECT title FROM sessions WHERE title IS NOT NULL GROUP BY title HAVING COUNT(*) > 1)').fetchall()
                groups: dict[str, list] = {}
                for row in sorted(rows, key=lambda r: (self._title_rank(r[2]), r[3], r[0]), reverse=True):
                    groups.setdefault(row[1], []).append(row)
                user_rank = self._TITLE_SOURCE_RANK[self.TITLE_SOURCE_USER]
                for title, group in groups.items():
                    users = [r for r in reversed(group) if self._title_rank(r[2]) == user_rank]
                    keep = users[0] if users else group[0]
                    for rowid, *_ in users[1:]:
                        renamed = next_title_in_lineage(cursor.connection, title)
                        cursor.execute('UPDATE sessions SET title = ? WHERE rowid = ?', (renamed, rowid))
                        logger.warning('Renamed duplicate user session title %r to %r', title, renamed)
                    for rowid, _title, source, _started in group:
                        if rowid != keep[0] and self._title_rank(source) != user_rank:
                            cursor.execute('UPDATE sessions SET title = NULL WHERE rowid = ?', (rowid,))
                            logger.warning('Cleared duplicate %s session title %r', source, title)
                cursor.execute(_TITLE_UNIQUE_INDEX_SQL)
                cursor.execute('RELEASE title_repair')
            except sqlite3.Error:
                cursor.execute('ROLLBACK TO title_repair')
                cursor.execute('RELEASE title_repair')
                logger.exception('Could not repair duplicate session titles; unique title index not created')
        except sqlite3.OperationalError:
            pass

    def _init_fts(self, cursor: sqlite3.Cursor) -> None:
        """Create/repair the FTS objects on an FTS5-capable runtime. The DDL runs even when the
        vtable exists so CREATE TRIGGER IF NOT EXISTS repairs trigger-only degradation.
        OPT-IN v23 boundary: a legacy v22 inline install keeps its inline schema + triggers
        (the v23 DDL would create the trigram source VIEW and leave a mixed state)."""
        legacy_fts = self._db_has_legacy_inline_fts(cursor)
        orphan_repaired = _drop_orphan_fts_shadow_tables(cursor, ('messages_fts', 'messages_fts_trigram', 'messages_fts_cjk'))
        if not self._fts_stale:
            self._migrate_misaligned_fts_source(cursor, legacy=legacy_fts)
        if self._fts_stale:
            if self._recover_stale_fts(cursor, legacy=legacy_fts):
                self._ensure_fts_cjk_schema(cursor)
            else:
                self._fts_enabled = self._trigram_available = self._fts_cjk_available = False
        else:
            base_sql, trigram_sql = _FTS_DDL[legacy_fts]
            base_triggers_missing = self._fts_triggers_missing(cursor, _FTS_BASE_TRIGGERS) or 'messages_fts' in orphan_repaired
            trigram_triggers_missing = self._fts_triggers_missing(cursor, _FTS_TRIGRAM_TRIGGERS) or 'messages_fts_trigram' in orphan_repaired

            def ensure_and_rebuild() -> None:
                self._fts_enabled = self._ensure_fts_schema(cursor, 'messages_fts', base_sql)
                if not self._fts_enabled:
                    return
                self._trigram_available = self._ensure_fts_schema(cursor, 'messages_fts_trigram', trigram_sql)
                self._rebuild_fts_indexes(cursor, legacy=legacy_fts, include_trigram=self._trigram_available)
                if not legacy_fts:
                    self._ensure_fts_cjk_schema(cursor)
            if base_triggers_missing:
                self._run_admitted_startup_rebuild(cursor, ensure_and_rebuild)
            else:
                self._fts_enabled = self._ensure_fts_schema(cursor, 'messages_fts', base_sql)
                if self._fts_enabled:
                    trigram_enabled = self._ensure_fts_schema(cursor, 'messages_fts_trigram', trigram_sql)
                    self._trigram_available = trigram_enabled
                    if trigram_enabled and trigram_triggers_missing:
                        self._run_admitted_startup_rebuild(cursor, lambda: self._rebuild_fts_indexes(cursor, legacy=legacy_fts, include_trigram=trigram_enabled))
            if self._fts_enabled and (not legacy_fts) and (not base_triggers_missing):
                self._ensure_fts_cjk_schema(cursor)
        if self._fts_enabled:
            self._migrate_broad_fts_update_triggers(cursor)

    def _run_admitted_startup_rebuild(self, cursor, rebuild_fn) -> None:
        """Run FTS bootstrap or trigger-repair rebuild under cross-process admission.

        The fresh/base-missing path includes DDL in ``rebuild_fn`` so no process can publish
        triggers before it owns the rebuild. Other repair paths may already have recreated an
        optional trigger; deferral therefore still drops every trigger and persists the stale
        breadcrumb. A later recovery path restores the complete family.

        See #93200.
        See #105790.
        """
        with fts_rebuild_admission(self.db_path) as admitted:
            if admitted:
                rebuild_fn()
                return
        logger.warning('Deferred startup FTS rebuild: another process holds the rebuild authority for this state.db; detaching FTS sync until the stale-index recovery path rebuilds it.')
        cursor.execute(_STALE_KEY_UPSERT_SQL, (FTS_STALE_KEY,))
        self._drop_all_fts_triggers(cursor)
        self._fts_stale = True
        self._fts_enabled = self._trigram_available = self._fts_cjk_available = False

    def _backfill_gateway_metadata_from_sessions_json(self, cursor: sqlite3.Cursor) -> None:
        """One-time v18 backfill of gateway metadata from sessions.json. Only fills NULL
        columns — never overwrites data written by newer code."""
        sessions_file = get_hermes_home() / 'sessions' / 'sessions.json'
        if not sessions_file.exists():
            return
        with open(sessions_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return
        for key, entry in data.items():
            if str(key).startswith('_') or not isinstance(entry, dict):
                continue
            session_id = entry.get('session_id')
            if not session_id:
                continue
            origin = entry.get('origin')
            origin_dict = origin if isinstance(origin, dict) else None
            cursor.execute('UPDATE sessions\n                   SET session_key = COALESCE(session_key, ?),\n                       chat_id = COALESCE(chat_id, ?),\n                       chat_type = COALESCE(chat_type, ?),\n                       thread_id = COALESCE(thread_id, ?),\n                       display_name = COALESCE(display_name, ?),\n                       origin_json = COALESCE(origin_json, ?),\n                       expiry_finalized = CASE\n                           WHEN COALESCE(expiry_finalized, 0) = 0 AND ? = 1 THEN 1\n                           ELSE expiry_finalized\n                       END\n                   WHERE id = ?', (entry.get('session_key') or key, origin_dict.get('chat_id') if origin_dict is not None else None, entry.get('chat_type'), origin_dict.get('thread_id') if origin_dict is not None else None, entry.get('display_name'), json.dumps(origin) if origin_dict is not None else None, 1 if entry.get('expiry_finalized') or entry.get('memory_flushed') else 0, str(session_id)))
