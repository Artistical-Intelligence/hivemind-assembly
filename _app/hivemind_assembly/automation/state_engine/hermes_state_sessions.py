# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
import logging
import re
from pathlib import Path
from typing import Any, Optional
from hivemind_assembly.automation.state_engine.hermes_state_common import _RECOVERABLE_END_REASONS, _non_continuation_child_sql, _sql_json_extract
logger = logging.getLogger('hermes_state')
_SAME_KEY_NAMESPACE_SQL = "p.session_key IS NULL OR sessions.session_key IS NULL OR substr(p.session_key, 1, instr(substr(p.session_key, 7), ':') + 6)  = substr(sessions.session_key, 1, instr(substr(sessions.session_key, 7), ':') + 6)"
_UPSERT_KEEP_EXISTING_SQL = ',\n'.join((f'                       {col} = COALESCE(sessions.{col}, excluded.{col})' for col in ('session_key', 'chat_id', 'chat_type', 'thread_id', 'parent_session_id', 'cwd', 'profile_name', 'transport_profile', 'git_repo_root', 'origin_json', 'display_name', 'created_source')))

def _inherit_col_sql(col: str, extra: str='') -> str:
    """``col = COALESCE(sessions.col, (SELECT p.col FROM parent))`` (whitespace is part of the SQL text)."""
    pad = ' ' * (30 + len(col))
    return f'{col} = COALESCE(sessions.{col},\n{pad}(SELECT p.{col} FROM sessions p\n{pad}  WHERE p.id = sessions.parent_session_id{extra}))'
_INHERIT_SEP = ',\n' + ' ' * 27
_INHERIT_PARENT_META_SQL = 'UPDATE sessions\n                       SET ' + _INHERIT_SEP.join((*(_inherit_col_sql(c) for c in ('cwd', 'git_repo_root', 'git_branch')), _inherit_col_sql('profile_name', '\n' + ' ' * 46 + f'AND ({_SAME_KEY_NAMESPACE_SQL})'))) + '\n                     WHERE id = ? AND parent_session_id IS NOT NULL'
_FORK_EDGE_EXCLUSION_SQL = ''.join((f"\n                       AND COALESCE({_sql_json_extract('model_config', f'$.{marker}')}, '')\n                           != parent_session_id" for marker in ('_delegate_from', '_branched_from')))
_INHERIT_PARENT_ROUTING_SQL = 'UPDATE sessions\n                       SET ' + _INHERIT_SEP.join((_inherit_col_sql(c) for c in ('user_id', 'session_key', 'chat_id', 'chat_type', 'thread_id', 'display_name', 'origin_json', 'transport_profile'))) + "\n                     WHERE id = ? AND parent_session_id IS NOT NULL\n                       AND EXISTS (\n                           SELECT 1 FROM sessions p\n                           WHERE p.id = sessions.parent_session_id\n                             AND p.end_reason = 'compression'\n                       )" + _FORK_EDGE_EXCLUSION_SQL

class SessionSessionsMixin:
    """Session rows: create/inherit, lifecycle flags, model_config, listing, deletion."""

    def _own_profile_name(self) -> Optional[str]:
        """The profile owning THIS store, from ``db_path`` alone (``<root>/state.db`` → default,
        ``<root>/profiles/<name>/state.db`` → name): a gateway serving a NON-launch profile opens that
        profile's store. None outside the profile tree — NULL beats a fabricated owner."""
        try:
            from hivemind_assembly.automation.state_engine.hermes_constants import get_default_hermes_root
            root = get_default_hermes_root().resolve()
            parent = Path(self.db_path).resolve().parent
            if parent == root:
                return 'default'
            is_profile_dir = parent.parent == root / 'profiles'
            if is_profile_dir and re.fullmatch('[a-z0-9][a-z0-9_-]{0,63}', parent.name):
                return parent.name
        except Exception:
            logger.debug('own-profile derivation failed', exc_info=True)
        return None

    @staticmethod
    def _inherit_parent_session_metadata(conn, session_id: str) -> None:
        """NULL-fill a child's cwd/git/profile from its parent (profile_name only within the same
        ``agent:<ns>:`` namespace). Gateway routing columns are inherited ONLY by compression forks
        (a crash before the gateway re-records the peer would strand the child unroutable); delegate
        and branch children must NOT inherit them (peer recovery could repoint traffic into a
        subagent's session), including when their parent row itself ended on compression — a long
        batch outlives its coordinator's rotation, and two live rows holding one routing key is the
        shape reported in #92859."""
        conn.execute(_INHERIT_PARENT_META_SQL, (session_id,))
        conn.execute(_INHERIT_PARENT_ROUTING_SQL, (session_id,))

    def _insert_session_row(self, session_id: str, source: str, model: str | None=None, model_config: dict[str, Any] | None=None, system_prompt: str | None=None, user_id: str | None=None, session_key: Optional[str]=None, chat_id: str | None=None, chat_type: str | None=None, thread_id: str | None=None, parent_session_id: str | None=None, cwd: str | None=None, profile_name: Optional[str]=None, git_repo_root: str | None=None, origin_json: str | None=None, display_name: str | None=None, transport_profile: Optional[str]=None) -> None:
        """Upsert a session row, never overwriting what an earlier writer set (the gateway creates a
        bare row before create_session carries the real model/prompt) — the one exception is the
        token-accounting guard's placeholder ``source='unknown'``, which a later writer's real surface
        replaces (#111999): once minted, that placeholder otherwise labelled a real session anonymous
        for life, because this upsert is the only writer that could correct it. chat_id/thread_id scope gateway
        /resume (IDOR). Children backfill from the parent; a missing profile_name is stamped with THIS
        store's own (NULL reads as unowned).

        When ``parent_session_id`` is set (compression fork, delegate/subagent spawn, branch continuation)
        and this row's own ``cwd``/``git_repo_root``/ ``git_branch``/``profile_name`` are still NULL after
        the insert, they are backfilled from the parent row. Callers of ``create_session`` for a child
        session historically didn't propagate these fields themselves (e.g. the compression-fork path), so a
        lineage could silently lose its working directory and drop out of the project sidebar every time it
        forked (#64709), or lose its owning profile and be aggregated as "default" every time it rotated or
        branched (the cross-profile session-jump bug). This only fills NULLs — an explicit value on the
        child is never overwritten. For compression forks specifically (parent ended with
        ``end_reason='compression'``), the gateway origin columns
        (``user_id``/``session_key``/``chat_id``/``chat_type``/
        ``thread_id``/``display_name``/``origin_json``) are inherited too, so a crash before the gateway
        re-records the peer can't strand the child without a recoverable routing mapping (#59527).
        When the caller passes no ``profile_name`` at all, the row is stamped with THIS store's own profile
        (:meth:`_own_profile_name`) instead of NULL. Every ``state.db`` belongs to exactly one profile — the
        same single-match contract :meth:`backfill_null_session_profiles` relies on — so the stamp is
        derivation, not a guess. Rows minted NULL after that one-shot #94724 backfill ran stayed NULL
        forever, and profile-keyed consumers (desktop sidebar scope matching, ``@session:<profile>/<id>``
        deep links, the fail-closed owner ladder) treat NULL as unowned: the session vanishes from the
        sidebar even though its transcript is intact (#99222). Stores outside the profile tree (explicit
        ``db_path`` in tests, ad-hoc copies) derive nothing and keep NULL — never guess.
        """
        from hivemind_assembly.automation.state_engine.hermes_state_worker_lifecycle import insert_session_row_in_transaction
        params = dict(session_id=session_id, source=source, model=model, model_config=model_config, system_prompt=system_prompt, user_id=user_id, session_key=session_key, chat_id=chat_id, chat_type=chat_type, thread_id=thread_id, parent_session_id=parent_session_id, cwd=cwd, profile_name=profile_name, git_repo_root=git_repo_root, origin_json=origin_json, display_name=display_name, transport_profile=transport_profile)
        self._execute_write(lambda conn: insert_session_row_in_transaction(self, conn, **params), patience_s=self._TRANSCRIPT_WRITE_PATIENCE_S)

    def create_session(self, session_id: str, source: str, **kwargs) -> str:
        """Create (upsert) a session record. Returns the session_id."""
        self._insert_session_row(session_id, source, **kwargs)
        return session_id
    _ORPHAN_ADOPTION_MAX_GAP_S = 900.0
    _NON_CONTINUATION_CHILD_FILTER_SQL = _non_continuation_child_sql('{alias}')

    def get_session(self, session_id: str) -> Optional[dict[str, Any]]:
        """Get a session by ID (drains queued token deltas first so cost readers see exact totals)."""
        self.flush_token_counts()
        row = self._read_one('SELECT s.*, COALESCE(sp.prompt, s.system_prompt) AS _system_prompt_resolved, COALESCE(tp.prompt, s.tool_names) AS _tool_names_resolved FROM sessions s LEFT JOIN system_prompts sp ON sp.hash = s.system_prompt_hash LEFT JOIN system_prompts tp ON tp.hash = s.tool_names WHERE s.id = ?', (session_id,))
        return self._session_row_dict(row) if row else None
    RECOVERABLE_END_REASONS = _RECOVERABLE_END_REASONS
    _SESSION_COMPACT_EXCLUDED = frozenset({'system_prompt', 'system_prompt_hash', 'git_metadata_generation'})
    _session_compact_cols_sql: Optional[str] = None
    _EMPTY_SESSION_WHERE = 'message_count = 0 AND ended_at IS NOT NULL AND archived = 0 AND NOT EXISTS (SELECT 1 FROM messages WHERE messages.session_id = sessions.id)'
