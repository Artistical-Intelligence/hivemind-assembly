# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
import logging
import sqlite3
from typing import Any, Optional
from hivemind_assembly.automation.state_engine.hermes_state_common import FTS_TOOL_CONTENT_PREFIX_CHARS, fts_trigram_session_sql
logger = logging.getLogger('hermes_state')

def _meta_row(conn, key: str) -> Optional[sqlite3.Row]:
    """Point-read one ``state_meta`` row (``None`` when absent)."""
    return conn.execute('SELECT value FROM state_meta WHERE key = ?', (key,)).fetchone()

def _delete_meta(conn, *keys: str) -> None:
    conn.execute(f'DELETE FROM state_meta WHERE key IN ({','.join(('?' for _ in keys))})', keys)

def _positive_int(name: str, value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f'{name} must be an integer')
    if value <= 0:
        raise ValueError(f'{name} must be greater than zero')

class SessionSearchMixin:
    """See module docstring — mixin for SessionDB (Search cluster)."""
    _SEARCH_MESSAGE_RESULT_FIELDS = ('id', 'session_id', 'role', 'snippet', 'timestamp', 'tool_name', 'source', 'model', 'session_started', 'context')

    def _try_incremental_merge_fts(self) -> None:
        """One bounded FTS5 merge pass that never fails the already-committed write (a caller
        must never replay an ambiguous, possibly-durable write — even on the bare
        SystemError CPython's sqlite3 layer can raise under cross-thread errmsg scrambling)."""
        if not self._fts_enabled:
            return
        try:
            self._merge_fts_incrementally(max_pages=self._FTS_MERGE_MAX_PAGES_PER_INDEX)
        except Exception as exc:
            logger.warning('FTS incremental merge failed after commit: %s', exc)
    _BOUNDARY_SWEEP_SQL = 'INSERT INTO {table}(rowid, content, tool_name, tool_calls) SELECT m.id, m.content, m.tool_name, m.tool_calls FROM messages m WHERE m.id > ? AND m.id <= ? {extra}AND NOT EXISTS (SELECT 1 FROM {table}_docsize d WHERE d.id = m.id)'
    _BASE_BOUNDARY_SWEEP_SQL = "INSERT INTO messages_fts(rowid, content, tool_name, tool_calls) SELECT m.id, CASE WHEN m.role = 'tool' THEN substr(COALESCE(m.content, ''), 1, ?) ELSE m.content END, m.tool_name, m.tool_calls FROM messages m WHERE m.id > ? AND m.id <= ? AND NOT EXISTS (SELECT 1 FROM messages_fts_docsize d WHERE d.id = m.id)"
    _TRIGRAM_BOUNDARY_SWEEP_SQL = f"INSERT INTO messages_fts_trigram(rowid, content, tool_name) SELECT m.id, m.content, m.tool_name FROM messages m JOIN sessions s ON s.id = m.session_id WHERE m.id > ? AND m.id <= ? AND m.role <> 'tool' AND {fts_trigram_session_sql('s')} AND NOT EXISTS (SELECT 1 FROM messages_fts_trigram_docsize d WHERE d.id = m.id)"
    _CHUNK_INSERT_SQL = f"INSERT INTO {{table}}(rowid, content, tool_name, tool_calls) SELECT id, CASE WHEN role = 'tool' THEN substr(COALESCE(content, ''), 1, {FTS_TOOL_CONTENT_PREFIX_CHARS}) ELSE content END, tool_name, tool_calls FROM messages WHERE id > ? AND id <= ?{{extra}}"
    _TRIGRAM_CHUNK_INSERT_SQL = f"INSERT INTO messages_fts_trigram(rowid, content, tool_name) SELECT m.id, m.content, m.tool_name FROM messages m JOIN sessions s ON s.id = m.session_id WHERE m.id > ? AND m.id <= ? AND m.role <> 'tool' AND {fts_trigram_session_sql('s')}"

    def _fts_external_index_empty_with_messages(self, conn) -> bool:
        """True when the base FTS table indexes nothing while ``messages`` has rows (post-demote
        empty-index shape). Caller holds ``self._lock``. docsize is the authoritative "is this
        rowid indexed" surface; EXISTS not COUNT(*) because this runs on every writable open."""
        try:
            if not conn.execute('SELECT EXISTS(SELECT 1 FROM messages)').fetchone()[0]:
                return False
            return not conn.execute('SELECT EXISTS(SELECT 1 FROM messages_fts_docsize)').fetchone()[0]
        except sqlite3.OperationalError:
            return False

    def _fts_table_exists(self, name: str) -> bool:
        """True if an FTS5 virtual table is queryable ("no such table" and "vtable
        constructor failed" — missing tokenizer / mid-teardown — both count as not)."""
        try:
            self._conn.execute(f'SELECT 1 FROM {name} LIMIT 0')
            return True
        except sqlite3.DatabaseError:
            return False

    def _present_fts_tables(self) -> list[str]:
        """Queryable FTS tables (caller holds ``self._lock``)."""
        return [tbl for tbl in self._FTS_TABLES if self._fts_table_exists(tbl)]

    def _merge_fts_incrementally(self, *, max_pages: int, max_commands: Optional[int]=None) -> int:
        """Run bounded FTS5 ``'merge'`` commands against each present index. A positive merge rank
        stops after ~that many output pages, so each command holds the write lock for
        milliseconds regardless of index size (``'optimize'`` takes 9-18 s per index on a
        10 GB DB). ``usermerge`` is lowered to its minimum of 2 (persisted in ``%_config``,
        once per instance) so a merge acts on ANY level with >= 2 segments; at the default
        4 a fragmented index cannot converge. Up to *max_commands* per index, stopping on
        the no-progress signal ``total_changes`` delta < 2 (the INSERT itself is 1). Each
        command is its own implicit transaction, so processes interleave mid-pass. Missing
        tables are skipped (optimize_fts_storage drops + backfills them live); other SQLite
        errors propagate. Returns commands executed."""
        _positive_int('max_pages', max_pages)
        if max_commands is None:
            max_commands = self._FTS_MERGE_COMMANDS_PER_PASS
        _positive_int('max_commands', max_commands)
        executed = 0
        with self._lock:
            for tbl in self._present_fts_tables():
                if not self._fts_usermerge_floor_applied:
                    self._conn.execute(f"INSERT INTO {tbl}({tbl}, rank) VALUES('usermerge', 2)")
                for _ in range(max_commands):
                    before = self._conn.total_changes
                    self._conn.execute(f"INSERT INTO {tbl}({tbl}, rank) VALUES('merge', ?)", (max_pages,))
                    executed += 1
                    if self._conn.total_changes - before < 2:
                        break
            self._fts_usermerge_floor_applied = True
        return executed
