# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
from typing import Any, Optional
from hivemind_assembly.automation.state_engine.hermes_state_common import SCHEMA_SQL, _shape_preview, _sql_preview_raw, _sql_session_last_active

def _rich_select(select_cols: str, where: str, tail: str='', prompt_select: Optional[str]='') -> str:
    """``list_sessions_rich``-shaped SELECT: resolved prompt (``prompt_select`` fragment;
    None omits prompt columns AND the join), preview, last_active. Whitespace matches
    the historical inline queries (SQL text is pinned)."""
    prompt_join = '' if prompt_select is None else 'LEFT JOIN system_prompts sp ON sp.hash = s.system_prompt_hash'
    return f'\n            SELECT {select_cols}{prompt_select or ''},\n                {_sql_preview_raw()},\n                {_sql_session_last_active('s')} AS last_active\n            FROM sessions s\n            {prompt_join}\n            WHERE {where}{tail}\n        '
_PROMPT_RESOLVED_SQL = 'COALESCE(sp.prompt, s.system_prompt) AS _system_prompt_resolved'

class SessionPortabilityMixin:
    """See module docstring — mixin for SessionDB (Port cluster)."""

    @classmethod
    def _compact_session_cols(cls) -> str:
        """``s.``-prefixed SELECT list of every SCHEMA_SQL ``sessions`` column except
        prompt storage internals (the compact_rows projection)."""
        if cls._session_compact_cols_sql is None:
            declared = cls._parse_schema_columns(SCHEMA_SQL)['sessions']
            cls._session_compact_cols_sql = ', '.join((f's.{name}' for name in declared if name not in cls._SESSION_COMPACT_EXCLUDED))
        return cls._session_compact_cols_sql

    @classmethod
    def _rich_row(cls, row) -> dict[str, Any]:
        """Session row dict with ``_preview_raw`` shaped into ``preview``."""
        s = cls._session_row_dict(row)
        s['preview'] = _shape_preview(s.pop('_preview_raw', ''))
        return s

    def _read_rows(self, sql: str, params=()) -> list:
        """Pure-read query via ``_read_ctx()`` (never the writer lock: turn persistence must not convoy)."""
        with self._read_ctx() as conn:
            return conn.execute(sql, params).fetchall()

    def _get_session_rich_row(self, session_id: str, compact_rows: bool=False) -> Optional[dict[str, Any]]:
        """One session with the ``list_sessions_rich`` enriched columns, or None.
        ``compact_rows=True`` omits the ``system_prompt`` blob. Public alias:
        :meth:`get_session_rich_row` (web server hydration)."""
        return self._get_session_rich_rows_batch([session_id], compact_rows=compact_rows).get(session_id)
    get_session_rich_row = _get_session_rich_row

    def _get_session_rich_rows_batch(self, session_ids, compact_rows: bool=False) -> dict[str, dict[str, Any]]:
        """Enriched rows for many sessions in one query, keyed by id; missing ids are absent
        (a page of compression tips resolves in one round trip)."""
        ids = [sid for sid in session_ids if sid]
        if not ids:
            return {}
        _CHUNK = 900
        if len(ids) > _CHUNK:
            result: dict[str, dict[str, Any]] = {}
            for start in range(0, len(ids), _CHUNK):
                result.update(self._get_session_rich_rows_batch(ids[start:start + _CHUNK], compact_rows=compact_rows))
            return result
        self.flush_token_counts()
        query = _rich_select(self._compact_session_cols() if compact_rows else 's.*', f's.id IN ({','.join(('?' for _ in ids))})', prompt_select=None if compact_rows else f', {_PROMPT_RESOLVED_SQL}')
        return {s['id']: s for s in map(self._rich_row, self._read_rows(query, ids))}
    _SQLITE_INT_MIN = -(1 << 63)
    _SQLITE_INT_MAX = (1 << 63) - 1
