# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
import contextlib
import errno
import json
import logging
import os
import sys
import time
from typing import Any
from hivemind_assembly.automation.state_engine.hermes_cli.timefmt import EPOCH_MAX, EPOCH_MIN
from hivemind_assembly.automation.state_engine.hermes_state_keys import CRON_PRINCIPAL_ID
from hivemind_assembly.automation.state_engine.hermes_state_pidns import persistent_record_pidns_checkable, pid_namespace_id
from hivemind_assembly.automation.state_engine.agent.skill_commands import AUTO_LOAD_SCAFFOLD_SQL_LIKE, SKILL_EXCERPT_JOINT, SKILL_SCAFFOLD_SQL_LIKE, describe_skill_invocation
from hivemind_assembly.automation.state_engine.agent.context_compressor import LEGACY_SUMMARY_PREFIX, SUMMARY_PREFIX, _MERGED_PRIOR_CONTEXT_HEADER, _MERGED_SUMMARY_DELIMITER, _SUMMARY_END_MARKER
TITLE_SOURCE_DERIVED = 'derived'
TITLE_SOURCE_LLM = 'llm'
TITLE_SOURCE_USER = 'user'
_PREVIEW_HEAD_CHARS = 63
_PREVIEW_SCAFFOLD_WINDOW = 400
_PREVIEW_MAX_CHARS = 60

def routed_sessions_setting(key: str, env_var: str) -> Any:
    """``sessions.<key>`` for the profile whose state.db this process is touching.

    ``gateway/run.py`` bridges the LAUNCH profile's ``sessions.*`` into ``env_var`` (the cross-process
    carrier CLI/cron children read). Under a multiplexer a routed turn runs with a HERMES_HOME override
    and that env slot holds the default profile's value, so a served profile with different
    ``sessions.*`` settings must read its own config.yaml. Unscoped: the env bridge, as before.
    Returns ``None`` when neither source sets the key.
    """
    from hivemind_assembly.automation.state_engine.hermes_constants import get_hermes_home_override
    if get_hermes_home_override():
        try:
            from hivemind_assembly.automation.state_engine.hermes_cli.config import load_config_readonly
            return (load_config_readonly().get('sessions') or {}).get(key)
        except Exception:
            return None
    return os.environ.get(env_var)

def escape_like(text: str) -> str:
    """Escape LIKE wildcards (``%``, ``_``) so derived text matches literally; pair with ``ESCAPE '\\'``.
    ``_`` is common in branch names/titles/paths and a substring match must not silently widen."""
    return text.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
_PREVIEW_CONTENT_SQL = "REPLACE(REPLACE(m.content, X'0A', ' '), X'0D', ' ')"
_PREVIEW_SCAFFOLDED_SQL = f"(m.content LIKE '{SKILL_SCAFFOLD_SQL_LIKE}' OR m.content LIKE '{AUTO_LOAD_SCAFFOLD_SQL_LIKE}')"
_SQL_WHITESPACE = 'CHAR(9) || CHAR(10) || CHAR(13) || CHAR(32)'

def _sql_literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"

def _sql_json_extract(expression: str, path: str) -> str:
    """Build a non-throwing JSON marker lookup for a JSON TEXT column."""
    safe_json = f'(CASE WHEN json_valid({expression}) THEN {expression} ELSE json_object() END)'
    return f'json_extract({safe_json}, {_sql_literal(path)})'

def _sql_ltrim_whitespace(expression: str) -> str:
    return f'LTRIM({expression}, {_SQL_WHITESPACE})'

def _sql_trim_whitespace(expression: str) -> str:
    return f'TRIM({expression}, {_SQL_WHITESPACE})'

def _sql_starts_with(expression: str, prefixes: tuple[str, ...]) -> str:
    trimmed = _sql_ltrim_whitespace(expression)
    return '(' + ' OR '.join((f'SUBSTR({trimmed}, 1, {len(p)}) = {_sql_literal(p)}' for p in prefixes)) + ')'

def _sql_after_marker(marker: str) -> str:
    """``m.content`` after the first occurrence of *marker*."""
    return f'SUBSTR(m.content, INSTR(m.content, {_sql_literal(marker)}) + {len(marker)})'
_PREVIEW_LONG_FORM_PREFIX = SUMMARY_PREFIX.split('Do NOT answer', 1)[0]
_PREVIEW_SUMMARY_PREFIXES = (_PREVIEW_LONG_FORM_PREFIX, LEGACY_SUMMARY_PREFIX)
_PREVIEW_STANDALONE_SUMMARY_SQL = _sql_starts_with('m.content', _PREVIEW_SUMMARY_PREFIXES)
_PREVIEW_MERGED_AFTER_SQL = _sql_after_marker(_MERGED_SUMMARY_DELIMITER)
_PREVIEW_MERGED_SUMMARY_SQL = f'(INSTR(m.content, {_sql_literal(_MERGED_SUMMARY_DELIMITER)}) > 0 AND {_sql_starts_with(_PREVIEW_MERGED_AFTER_SQL, _PREVIEW_SUMMARY_PREFIXES)})'
_PREVIEW_MERGED_PRIOR_SQL = _sql_trim_whitespace(f'SUBSTR(m.content, 1, INSTR(m.content, {_sql_literal(_MERGED_SUMMARY_DELIMITER)}) - 1)')
_PREVIEW_MERGED_PRIOR_LTRIMMED_SQL = _sql_ltrim_whitespace(_PREVIEW_MERGED_PRIOR_SQL)
_PREVIEW_MERGED_PRIOR_UNWRAPPED_SQL = f'CASE WHEN SUBSTR({_PREVIEW_MERGED_PRIOR_LTRIMMED_SQL}, 1, {len(_MERGED_PRIOR_CONTEXT_HEADER)}) = {_sql_literal(_MERGED_PRIOR_CONTEXT_HEADER)} THEN {_sql_ltrim_whitespace(f'SUBSTR({_PREVIEW_MERGED_PRIOR_LTRIMMED_SQL}, {len(_MERGED_PRIOR_CONTEXT_HEADER) + 1})')} ELSE {_PREVIEW_MERGED_PRIOR_SQL} END'
_PREVIEW_FORCE_USER_REMAINDER_SQL = _sql_after_marker(_SUMMARY_END_MARKER)
_PREVIEW_ELIGIBLE_SQL = f"(COALESCE(m.display_kind, '') <> 'hidden' AND ((NOT {_PREVIEW_STANDALONE_SUMMARY_SQL} AND NOT {_PREVIEW_MERGED_SUMMARY_SQL}) OR ({_PREVIEW_STANDALONE_SUMMARY_SQL} AND INSTR(m.content, {_sql_literal(_SUMMARY_END_MARKER)}) > 0 AND LENGTH({_sql_trim_whitespace(_PREVIEW_FORCE_USER_REMAINDER_SQL)}) > 0) OR ({_PREVIEW_MERGED_SUMMARY_SQL} AND LENGTH({_sql_trim_whitespace(_PREVIEW_MERGED_PRIOR_UNWRAPPED_SQL)}) > 0)))"
_PREVIEW_RAW_SELECT = f"CASE WHEN {_PREVIEW_STANDALONE_SUMMARY_SQL} THEN {_PREVIEW_FORCE_USER_REMAINDER_SQL} WHEN {_PREVIEW_MERGED_SUMMARY_SQL} THEN {_PREVIEW_MERGED_PRIOR_UNWRAPPED_SQL} WHEN {_PREVIEW_SCAFFOLDED_SQL} AND LENGTH(m.content) > {_PREVIEW_SCAFFOLD_WINDOW * 2} THEN SUBSTR({_PREVIEW_CONTENT_SQL}, 1, {_PREVIEW_SCAFFOLD_WINDOW}) || '{SKILL_EXCERPT_JOINT}' || SUBSTR({_PREVIEW_CONTENT_SQL}, -{_PREVIEW_SCAFFOLD_WINDOW}) WHEN {_PREVIEW_SCAFFOLDED_SQL} THEN SUBSTR({_PREVIEW_CONTENT_SQL}, 1, {_PREVIEW_SCAFFOLD_WINDOW * 2}) ELSE SUBSTR({_PREVIEW_CONTENT_SQL}, 1, {_PREVIEW_HEAD_CHARS}) END"

def _shape_preview(raw: Any) -> str:
    """Turn a ``_preview_raw`` column into the short preview callers show."""
    text = str(raw or '').strip()
    if not text:
        return ''
    text = text.replace('\n', ' ').replace('\r', ' ')
    described = describe_skill_invocation(text)
    text = described if described is not None else text.split(SKILL_EXCERPT_JOINT)[0]
    return text[:_PREVIEW_MAX_CHARS] + '...' if len(text) > _PREVIEW_MAX_CHARS else text

def _sql_preview_raw(session_id_expr: str='s.id') -> str:
    """Correlated ``_preview_raw`` column: the first eligible user message of *session_id_expr*.
    ``INDEXED BY`` walks the session in timestamp order and stops at the first eligible row; with planner
    stats older than idx_messages_session_id, SQLite otherwise reads and sorts the whole session (#119403)."""
    return f"COALESCE((SELECT {_PREVIEW_RAW_SELECT} FROM messages m INDEXED BY idx_messages_session WHERE m.session_id = {session_id_expr} AND m.role = 'user' AND m.content IS NOT NULL AND {_PREVIEW_ELIGIBLE_SQL} ORDER BY m.timestamp, m.id LIMIT 1), '') AS _preview_raw"
_BRANCH_CHILD_SQL = f"{_sql_json_extract('{a}.model_config', '$._branched_from')} IS NOT NULL OR EXISTS (SELECT 1 FROM sessions p            WHERE p.id = {{a}}.parent_session_id            AND p.end_reason = 'branched'            AND {{a}}.started_at >= p.ended_at)"
_COMPRESSION_CHILD_SQL = "EXISTS (SELECT 1 FROM sessions p        WHERE p.id = {a}.parent_session_id        AND p.end_reason = 'compression')"
_RESET_END_REASONS = ('session_reset', 'session_switch', 'idle', 'daily', 'suspended', 'resume_pending_expired')
_RESET_END_REASONS_SQL = ', '.join((f"'{reason}'" for reason in _RESET_END_REASONS))
_RECOVERABLE_END_REASONS = ('agent_close', 'ws_orphan_reap', 'superseded_by_resume', 'startup_orphan_reap')

def _legacy_reset_child_sql(alias: str, reasons_sql: str) -> str:
    """Pre-marker reset-continuation heuristic: child rides its parent's exact non-empty routing key and the
    parent ended at a reset boundary.  Shared by ``_RESET_CHILD_SQL`` and ``reopen_session()`` so the two
    cannot drift; ``reasons_sql`` is a literal or placeholder list."""
    return f"EXISTS (SELECT 1 FROM sessions p            WHERE p.id = {alias}.parent_session_id            AND p.end_reason IN ({reasons_sql})            AND {alias}.session_key IS NOT NULL            AND {alias}.session_key != ''            AND {alias}.session_key = p.session_key)"

def _non_continuation_child_sql(child: str='', parent: str='?') -> str:
    """``  AND ...`` clauses rejecting children that are NOT compression continuations of *parent*
    (branch/delegate/reset forks, tool sessions).  Markers are bound to the parent id: continuations
    inherit ``model_config`` verbatim, so a marker naming another row is inherited, not a fork.
    ``child`` is the column prefix (``""``, ``"c."``); single owner so prune and compression agree."""
    return ''.join((f"  AND COALESCE({_sql_json_extract(f'{child}model_config', f'$.{marker}')}, '') != {parent}\n" for marker in ('_branched_from', '_delegate_from', '_reset_from'))) + f"  AND COALESCE({child}source, '') != 'tool'\n"
_RESET_CHILD_SQL = f'{_sql_json_extract('{a}.model_config', '$._reset_from')} IS NOT NULL OR ' + _legacy_reset_child_sql('{a}', _RESET_END_REASONS_SQL)

def _ephemeral_child_sql(alias: str='s') -> str:
    """Subagent runs, not branch, reset, or compression children."""
    return f'({alias}.parent_session_id IS NOT NULL AND NOT ({_BRANCH_CHILD_SQL.format(a=alias)}) AND NOT ({_COMPRESSION_CHILD_SQL.format(a=alias)}) AND NOT ({_RESET_CHILD_SQL.format(a=alias)}))'
_SQL_IN_WINDOW = f'BETWEEN {EPOCH_MIN!r} AND {EPOCH_MAX!r}'

def _sql_in_window(expr: str) -> str:
    """*expr* when it is inside the ``coerce_epoch`` window, else NULL."""
    return f'(SELECT _win.v FROM (SELECT {expr} AS v) _win WHERE _win.v {_SQL_IN_WINDOW})'

def _sql_freshest_of(activity: str, session_id_expr: str, started: str) -> str:
    """Freshest of *activity* and the latest message timestamp for *session_id_expr*, else *started*.
    Heartbeats are rate-limited (~60s) so ``last_activity_at`` can lag a newer message; never use it alone.
    Cells outside the ``coerce_epoch`` window (garbage doubles salvaged from a damaged page, TEXT) are
    skipped, fallback included, or one bad row pins the session's recency to ``5e+246`` (#91536); a
    session with no trusted cell at all is NULL."""
    msg_max = f'(SELECT MAX(_act_m.timestamp) FROM messages _act_m INDEXED BY idx_messages_session WHERE _act_m.session_id = {session_id_expr} AND _act_m.timestamp {_SQL_IN_WINDOW})'
    return f'COALESCE((SELECT MAX(_act_v.v) FROM (SELECT {activity} AS v UNION ALL SELECT {msg_max}) _act_v WHERE _act_v.v {_SQL_IN_WINDOW}), {_sql_in_window(started)})'

def _sql_session_last_active(alias: str='s') -> str:
    """Session recency expression for a ``sessions {alias}`` row."""
    return _sql_freshest_of(f'{alias}.last_activity_at', f'{alias}.id', f'{alias}.started_at')
SCHEMA_VERSION = 32
FTS_STORAGE_VERSION = 3
FTS_TOOL_CONTENT_PREFIX_CHARS = 8192

def _fts_indexed_content_sql(alias: str) -> str:
    return f"CASE WHEN {alias}.role = 'tool'\n         THEN substr(COALESCE({alias}.content, ''), 1, {FTS_TOOL_CONTENT_PREFIX_CHARS})\n         ELSE {alias}.content END"
_FTS_NEW_INDEXED_CONTENT_SQL = _fts_indexed_content_sql('new')
_FTS_OLD_INDEXED_CONTENT_SQL = _fts_indexed_content_sql('old')

def stat_db_file_identity(path) -> tuple[int, int] | None:
    """``(st_dev, st_ino)`` for *path*, or None.  st_ino=0 (Windows, some network FS) would false-positive
    every replaced-file check, so it counts as unknown."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_dev, st.st_ino) if st.st_dev and st.st_ino else None
_ENDED_ROW_SQL = 'SELECT ended_at, end_reason FROM sessions WHERE id = ?'
_COMPRESSION_LOCK_ROW_SQL = 'SELECT holder, expires_at FROM compression_locks WHERE session_id = ?'

def _ended_by_compression(row) -> bool:
    return row is not None and row['ended_at'] is not None and (row['end_reason'] == 'compression')

def _placeholders(items) -> str:
    """``?,?,?`` for one bound parameter per element of *items* (a sequence or an int count)."""
    return ','.join(('?' for _ in range(items if isinstance(items, int) else len(items))))
_FTS_TRIGGERS = ('messages_fts_insert', 'messages_fts_delete', 'messages_fts_update', 'messages_fts_trigram_insert', 'messages_fts_trigram_delete', 'messages_fts_trigram_update')
SCHEMA_SQL = "\nCREATE TABLE IF NOT EXISTS schema_version (\n    version INTEGER NOT NULL\n);\n\nCREATE TABLE IF NOT EXISTS system_prompts (\n    hash TEXT PRIMARY KEY,\n    prompt TEXT NOT NULL\n);\n\nCREATE TABLE IF NOT EXISTS sessions (\n    id TEXT PRIMARY KEY,\n    runtime_revision INTEGER NOT NULL DEFAULT 0,\n    runtime_generation INTEGER NOT NULL DEFAULT 0,\n    source TEXT NOT NULL,\n    created_source TEXT,\n    user_id TEXT,\n    session_key TEXT,\n    chat_id TEXT,\n    chat_type TEXT,\n    thread_id TEXT,\n    display_name TEXT,\n    origin_json TEXT,\n    expiry_finalized INTEGER DEFAULT 0,\n    model TEXT,\n    model_config TEXT,\n    system_prompt TEXT,\n    system_prompt_hash TEXT,\n    parent_session_id TEXT,\n    started_at REAL NOT NULL,\n    ended_at REAL,\n    end_reason TEXT,\n    message_count INTEGER DEFAULT 0,\n    tool_call_count INTEGER DEFAULT 0,\n    input_tokens INTEGER DEFAULT 0,\n    output_tokens INTEGER DEFAULT 0,\n    cache_read_tokens INTEGER DEFAULT 0,\n    cache_write_tokens INTEGER DEFAULT 0,\n    reasoning_tokens INTEGER DEFAULT 0,\n    cwd TEXT,\n    git_branch TEXT,\n    git_repo_root TEXT,\n    git_metadata_generation INTEGER NOT NULL DEFAULT 0,\n    billing_provider TEXT,\n    billing_base_url TEXT,\n    billing_mode TEXT,\n    estimated_cost_usd REAL,\n    actual_cost_usd REAL,\n    cost_status TEXT,\n    cost_source TEXT,\n    pricing_version TEXT,\n    title TEXT,\n    title_source TEXT,\n    last_activity_at REAL,\n    last_activity_description TEXT,\n    last_activity_provenance TEXT,\n    api_call_count INTEGER DEFAULT 0,\n    handoff_state TEXT,\n    handoff_platform TEXT,\n    handoff_error TEXT,\n    compression_failure_cooldown_until REAL,\n    compression_failure_error TEXT,\n    compression_fallback_streak INTEGER NOT NULL DEFAULT 0,\n    compression_ineffective_count INTEGER NOT NULL DEFAULT 0,\n    compression_recovery_deadline REAL,\n    compression_overload_streak INTEGER NOT NULL DEFAULT 0,\n    profile_name TEXT,\n    transport_profile TEXT,\n    rewind_count INTEGER NOT NULL DEFAULT 0,\n    archived INTEGER NOT NULL DEFAULT 0,\n    auto_archived INTEGER NOT NULL DEFAULT 0,\n    pinned INTEGER NOT NULL DEFAULT 0,\n    hidden INTEGER NOT NULL DEFAULT 0,\n    last_read_at REAL,\n    tool_names TEXT,\n    transcript_revision INTEGER NOT NULL DEFAULT 0,\n    FOREIGN KEY (parent_session_id) REFERENCES sessions(id),\n    FOREIGN KEY (system_prompt_hash) REFERENCES system_prompts(hash)\n);\n\nCREATE TABLE IF NOT EXISTS messages (\n    id INTEGER PRIMARY KEY AUTOINCREMENT,\n    session_id TEXT NOT NULL REFERENCES sessions(id),\n    role TEXT NOT NULL,\n    content TEXT,\n    tool_call_id TEXT,\n    tool_calls TEXT,\n    tool_name TEXT,\n    effect_disposition TEXT,\n    timestamp REAL NOT NULL,\n    token_count INTEGER,\n    finish_reason TEXT,\n    reasoning TEXT,\n    reasoning_content TEXT,\n    reasoning_details TEXT,\n    codex_reasoning_items TEXT,\n    codex_message_items TEXT,\n    platform_message_id TEXT,\n    observed INTEGER DEFAULT 0,\n    _compressed_summary INTEGER NOT NULL DEFAULT 0,\n    active INTEGER NOT NULL DEFAULT 1,\n    compacted INTEGER NOT NULL DEFAULT 0,\n    api_content TEXT,\n    display_kind TEXT,\n    display_metadata TEXT,\n    display_identity BLOB,\n    display_order INTEGER,\n    message_uid TEXT,\n    absorbed_message_uids TEXT,\n    tool_call_uids TEXT,\n    tool_call_uid TEXT\n);\n\nCREATE TABLE IF NOT EXISTS session_model_usage (\n    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,\n    model TEXT NOT NULL,\n    billing_provider TEXT NOT NULL DEFAULT '',\n    billing_base_url TEXT NOT NULL DEFAULT '',\n    billing_mode TEXT NOT NULL DEFAULT '',\n    task TEXT NOT NULL DEFAULT '',\n    api_call_count INTEGER NOT NULL DEFAULT 0,\n    input_tokens INTEGER NOT NULL DEFAULT 0,\n    output_tokens INTEGER NOT NULL DEFAULT 0,\n    cache_read_tokens INTEGER NOT NULL DEFAULT 0,\n    cache_write_tokens INTEGER NOT NULL DEFAULT 0,\n    reasoning_tokens INTEGER NOT NULL DEFAULT 0,\n    estimated_cost_usd REAL NOT NULL DEFAULT 0,\n    actual_cost_usd REAL NOT NULL DEFAULT 0,\n    cost_status TEXT,\n    cost_source TEXT,\n    first_seen REAL,\n    last_seen REAL,\n    PRIMARY KEY (session_id, model, billing_provider, billing_base_url, billing_mode, task)\n);\n\nCREATE TABLE IF NOT EXISTS runtime_epoch (\n    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),\n    epoch INTEGER NOT NULL CHECK (epoch > 0),\n    instance_id TEXT NOT NULL\n);\nCREATE TABLE IF NOT EXISTS session_admissions (\n    seq INTEGER PRIMARY KEY AUTOINCREMENT,\n    admission_id TEXT NOT NULL UNIQUE,\n    request_id TEXT NOT NULL,\n    principal_id TEXT NOT NULL,\n    target_session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE RESTRICT,\n    lineage_json TEXT NOT NULL,\n    payload_json TEXT NOT NULL,\n    payload_digest TEXT NOT NULL,\n    intent TEXT NOT NULL CHECK (intent IN ('queue','steer','redirect')),\n    status TEXT NOT NULL CHECK (status IN ('queued','started','unknown','terminal')),\n    outcome TEXT,\n    owner_epoch INTEGER,\n    generation INTEGER,\n    UNIQUE (principal_id, target_session_id, request_id),\n    CHECK (status != 'started' OR (owner_epoch IS NOT NULL AND generation IS NOT NULL))\n);\nCREATE INDEX IF NOT EXISTS session_admissions_pending\n    ON session_admissions(target_session_id, status, seq);\n-- Cron run history finds a job's unified-runtime runs by the scheduler principal's request ids\n-- (``cron:<job>:<execution>``); without this a lookup walked\n-- every cron admission of every job. Partial: interactive turns, the bulk of admissions, pay\n-- nothing for it. The constant leading column gives the planner equality + range over a covering\n-- index, so it beats the UNIQUE autoindex's bare principal_id prefix even without ANALYZE stats.\n-- The WHERE is built from CRON_PRINCIPAL_ID, the literal the run queries inline, so they cannot drift.\nCREATE INDEX IF NOT EXISTS idx_session_admissions_cron_request\n    ON session_admissions(principal_id, request_id, target_session_id) WHERE principal_id = '" + CRON_PRINCIPAL_ID + '\';\nCREATE TABLE IF NOT EXISTS worker_executions (\n    execution_id TEXT PRIMARY KEY,\n    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE RESTRICT,\n    kind TEXT NOT NULL CHECK (kind IN (\'cron\',\'child\',\'compute\',\'kanban\')),\n    owner_epoch INTEGER NOT NULL,\n    generation INTEGER NOT NULL,\n    status TEXT NOT NULL CHECK (status IN (\'registered\',\'running\',\'unknown\',\'terminal\')),\n    adoption_digest TEXT NOT NULL,\n    last_sequence INTEGER NOT NULL DEFAULT 0 CHECK (last_sequence >= 0)\n);\n-- Lineage-wide worker exclusion (claim/register/reset) probes every row of a conversation\'s lineage\n-- inside the write transaction; without this each probe scanned the whole (only-growing) table.\nCREATE INDEX IF NOT EXISTS idx_worker_executions_session_status\n    ON worker_executions(session_id, status);\nCREATE TABLE IF NOT EXISTS worker_receipts (\n    execution_id TEXT NOT NULL REFERENCES worker_executions(execution_id) ON DELETE RESTRICT,\n    sequence INTEGER NOT NULL CHECK (sequence > 0),\n    payload_digest TEXT NOT NULL,\n    result_json TEXT NOT NULL,\n    PRIMARY KEY (execution_id, sequence)\n);\n\nCREATE TABLE IF NOT EXISTS state_meta (\n    key TEXT PRIMARY KEY,\n    value TEXT\n);\n\nCREATE TABLE IF NOT EXISTS gateway_routing (\n    scope TEXT NOT NULL DEFAULT \'\',\n    session_key TEXT NOT NULL,\n    entry_json TEXT NOT NULL,\n    updated_at REAL NOT NULL,\n    PRIMARY KEY (scope, session_key)\n);\n\nCREATE TABLE IF NOT EXISTS gateway_hygiene_state (\n    session_key TEXT PRIMARY KEY,\n    failure_streak INTEGER NOT NULL DEFAULT 0\n);\n\n-- Monotonic conversation generation per routing peer (#96811).\n--\n-- A host-declared conversation key (X-Hermes-Session-Key / build_session_key)\n-- is per-CHAT and outlives any single conversation on it, so the prompt-cache\n-- affinity scope derived from it must be qualified by which conversation is\n-- currently live. Deriving that from the session rows themselves\n-- (COUNT/MAX over _RESET_END_REASONS boundaries) cannot prove non-reuse:\n-- delete_session() and bulk pruning remove ended rows, so an aggregate can\n-- return a pair it already emitted and hand a new conversation a retired\n-- affinity identity.\n--\n-- This counter lives outside prunable session history and only ever\n-- increments, once per boundary actually written, so a generation can never\n-- be reused for a peer even if every session row behind it is deleted.\n--\n-- These rows are deliberately NEVER garbage-collected, including when every\n-- session row for the peer is gone. Collecting one resets that peer to "no\n-- generation", so its next boundary writes generation = 1 again and re-issues\n-- a gwk_ scope a retired conversation already used — exactly the ABA this\n-- table exists to close. Do not add it to delete_session()\'s cascade or to any\n-- prune sweep. One (TEXT, TEXT, INTEGER) row per routing peer is the intended,\n-- bounded cost.\nCREATE TABLE IF NOT EXISTS conversation_generations (\n    source TEXT NOT NULL,\n    session_key TEXT NOT NULL,\n    generation INTEGER NOT NULL DEFAULT 0,\n    PRIMARY KEY (source, session_key)\n);\n\n-- Per-backend liveness heartbeat (#94895). Each serve / tui_gateway process\n-- registers a row at startup and refreshes ``last_heartbeat`` periodically.\n-- The startup orphan sweep (sessions.startup_orphan_reap) consults this\n-- table to avoid reaping rows whose owning backend is still alive but\n-- just idle (multi-backend state.db shared by isolated serve processes).\n-- A backend whose ``last_heartbeat`` is older than the heartbeat staleness\n-- window is treated as dead; rows without ANY matching heartbeat fall back\n-- to the original staleness predicate so legacy deployments keep working.\nCREATE TABLE IF NOT EXISTS gateway_heartbeats (\n    backend_id TEXT PRIMARY KEY,\n    pid INTEGER NOT NULL,\n    started_at REAL NOT NULL,\n    last_heartbeat REAL NOT NULL,\n    profile TEXT NOT NULL DEFAULT \'\',\n    host TEXT NOT NULL DEFAULT \'\'\n);\n\nCREATE TABLE IF NOT EXISTS compression_locks (\n    session_id TEXT PRIMARY KEY,\n    holder TEXT NOT NULL,\n    acquired_at REAL NOT NULL,\n    expires_at REAL NOT NULL\n);\n\nCREATE TABLE IF NOT EXISTS session_turn_leases (\n    conversation_id TEXT PRIMARY KEY,\n    holder TEXT NOT NULL,\n    acquired_at REAL NOT NULL,\n    expires_at REAL NOT NULL\n);\n\nCREATE TABLE IF NOT EXISTS async_delegations (\n    delegation_id TEXT PRIMARY KEY,\n    origin_session TEXT NOT NULL,\n    origin_ui_session_id TEXT NOT NULL DEFAULT \'\',\n    parent_session_id TEXT,\n    state TEXT NOT NULL,\n    dispatched_at REAL NOT NULL,\n    completed_at REAL,\n    updated_at REAL NOT NULL,\n    event_json TEXT,\n    result_json TEXT,\n    delivery_state TEXT NOT NULL DEFAULT \'pending\',\n    delivery_attempts INTEGER NOT NULL DEFAULT 0,\n    delivered_at REAL,\n    owner_pid INTEGER,\n    owner_started_at INTEGER,\n    task_json TEXT,\n    -- Owner-side execution fence (unified runtime).\n    owner_execution_id TEXT,\n    delivery_claim TEXT,\n    delivery_claimed_at REAL,\n    -- Mirrors the delegation tool\'s own CREATE TABLE (tools/async_delegation.py\n    -- _initialize_schema). Keeping the canonical fresh-install shape identical\n    -- to the tool\'s avoids a silent schema drift: the tool\'s lazy\n    -- ALTER TABLE ADD COLUMN used to be the only source of this column, so two\n    -- databases at the same schema_version had different\n    -- async_delegations shapes depending on whether the delegation tool had\n    -- ever run, breaking rebuild/replay pipelines that reconstruct state.db\n    -- from the canonical schema (#94691).\n    origin_session_id TEXT NOT NULL DEFAULT \'\'\n);\n\nCREATE INDEX IF NOT EXISTS idx_sessions_source ON sessions(source);\nCREATE INDEX IF NOT EXISTS idx_sessions_source_id ON sessions(source, id);\nCREATE INDEX IF NOT EXISTS idx_sessions_parent ON sessions(parent_session_id);\nCREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at DESC);\nCREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, timestamp);\nCREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id, id);\n-- Partial index for the Insights assistant tool-call scan\n-- (agent/insights.py _get_tool_usage / _get_skill_usage): those queries filter\n-- messages by role=\'assistant\' AND tool_calls IS NOT NULL, a small fraction of\n-- rows on a large state.db. role and tool_calls are base columns, so this can\n-- live in SCHEMA_SQL rather than DEFERRED_INDEX_SQL.\nCREATE INDEX IF NOT EXISTS idx_messages_assistant_calls_by_session\n    ON messages(session_id)\n    WHERE role = \'assistant\' AND tool_calls IS NOT NULL;\nCREATE INDEX IF NOT EXISTS idx_compression_locks_expires ON compression_locks(expires_at);\nCREATE INDEX IF NOT EXISTS idx_session_turn_leases_expires ON session_turn_leases(expires_at);\nCREATE INDEX IF NOT EXISTS idx_session_model_usage_session ON session_model_usage(session_id);\nCREATE INDEX IF NOT EXISTS idx_session_model_usage_model ON session_model_usage(model);\nCREATE INDEX IF NOT EXISTS idx_async_delegations_delivery\n    ON async_delegations(delivery_state, completed_at);\n'
DEFERRED_INDEX_SQL = "\nDROP TRIGGER IF EXISTS sessions_runtime_ledger_delete_guard;\nCREATE TRIGGER IF NOT EXISTS sessions_runtime_ledger_delete_guard\nBEFORE DELETE ON sessions\nWHEN EXISTS (SELECT 1 FROM session_admissions WHERE target_session_id = old.id)\n  OR EXISTS (SELECT 1 FROM worker_executions WHERE session_id = old.id)\nBEGIN\n    SELECT RAISE(ABORT, 'Refused to delete a session that has gateway runtime history: state.db was upgraded by a newer Hermes, and this older Hermes cannot delete such sessions. Downgrading is unsupported. Run hermes update to go back to the newer release, or restore the pre-update snapshot: https://hermes-agent.nousresearch.com/docs/getting-started/updating#rolling-back-to-an-older-release');\nEND;\nDROP TRIGGER IF EXISTS messages_transcript_revision_update;\nCREATE TRIGGER IF NOT EXISTS messages_transcript_revision_update\nAFTER UPDATE OF role, content, api_content, tool_calls, tool_call_id, tool_name, reasoning, reasoning_content,\n    reasoning_details ON messages\nBEGIN\n    -- An in-place rewrite (prompt expansion, multimodal context, a redaction) moves neither the\n    -- active row count nor the highest id; this write-side revision is what a transcript-derived\n    -- cache keys on (conversation_revision). Whoever wrote the row, old builds included.\n    UPDATE sessions SET transcript_revision = transcript_revision + 1 WHERE id = new.session_id;\nEND;\nCREATE INDEX IF NOT EXISTS idx_messages_session_active\n    ON messages(session_id, active, timestamp);\nCREATE INDEX IF NOT EXISTS idx_messages_display_page\n    ON messages(session_id, display_order, active DESC, id DESC)\n    WHERE active = 1 OR compacted = 1;\nCREATE INDEX IF NOT EXISTS idx_messages_display_backfill\n    ON messages(session_id) WHERE (display_order IS NULL OR display_identity IS NULL)\n    AND (active = 1 OR compacted = 1);\nCREATE INDEX IF NOT EXISTS idx_messages_display_identity\n    ON messages(session_id, display_identity, display_order)\n    WHERE display_identity IS NOT NULL AND (active = 1 OR compacted = 1);\nDROP TRIGGER IF EXISTS messages_message_uid_insert;\nCREATE TRIGGER IF NOT EXISTS messages_message_uid_insert\nAFTER INSERT ON messages WHEN new.message_uid IS NULL\nBEGIN\n    -- Every row carries a message_uid, whoever wrote it: a build that predates the column binds NULL, so\n    -- the store mints one on its behalf (the current build always binds a uid; this never fires for it).\n    -- The note lives inside the body: a comment before DROP/CREATE would defeat the settled-trigger skip.\n    UPDATE messages SET message_uid = lower(hex(randomblob(16))) WHERE id = new.id;\nEND;\nDROP TRIGGER IF EXISTS messages_display_order_insert;\nCREATE TRIGGER IF NOT EXISTS messages_display_order_insert\nAFTER INSERT ON messages WHEN new.display_order IS NULL\nBEGIN\n    UPDATE messages SET display_order = COALESCE((\n        SELECT display_order FROM messages\n        WHERE session_id = new.session_id AND id <> new.id\n          AND (active = 1 OR compacted = 1)\n          AND display_identity = new.display_identity AND display_order IS NOT NULL\n        ORDER BY display_order LIMIT 1\n    ), new.id) WHERE id = new.id;\nEND;\nDROP TRIGGER IF EXISTS messages_display_visibility_update;\nCREATE TRIGGER IF NOT EXISTS messages_display_visibility_update\nAFTER UPDATE OF active, compacted ON messages\nWHEN (new.active = 1 OR new.compacted = 1) <> (old.active = 1 OR old.compacted = 1)\nBEGIN\n    UPDATE messages SET display_order = MIN(new.id, COALESCE((\n        SELECT display_order FROM messages\n        WHERE session_id = new.session_id AND id <> new.id\n          AND (active = 1 OR compacted = 1)\n          AND display_identity = new.display_identity AND display_order IS NOT NULL\n        ORDER BY display_order LIMIT 1\n    ), new.id)) WHERE id = new.id\n      AND (new.active = 1 OR new.compacted = 1);\n    UPDATE messages SET display_order = (SELECT display_order FROM messages WHERE id = new.id)\n    WHERE session_id = new.session_id AND id <> new.id AND (active = 1 OR compacted = 1)\n      AND display_identity = new.display_identity\n      AND (new.active = 1 OR new.compacted = 1);\n    UPDATE messages SET display_order = (\n        SELECT MIN(peer.id) FROM messages AS peer\n        WHERE peer.session_id = old.session_id AND (peer.active = 1 OR peer.compacted = 1)\n          AND peer.display_identity = old.display_identity\n    ) WHERE session_id = old.session_id AND (active = 1 OR compacted = 1)\n      AND display_identity = old.display_identity\n      AND NOT (new.active = 1 OR new.compacted = 1);\nEND;\nDROP TRIGGER IF EXISTS messages_display_identity_update;\nCREATE TRIGGER IF NOT EXISTS messages_display_identity_update\nAFTER UPDATE OF role, content, timestamp, tool_call_id, tool_calls, tool_name,\n                display_kind ON messages\nWHEN new.role IS NOT old.role\n  OR new.content IS NOT old.content\n  OR new.timestamp IS NOT old.timestamp\n  OR new.tool_call_id IS NOT old.tool_call_id\n  OR new.tool_calls IS NOT old.tool_calls\n  OR new.tool_name IS NOT old.tool_name\n  OR new.display_kind IS NOT old.display_kind\nBEGIN\n    UPDATE messages SET display_identity = NULL, display_order = NULL\n    WHERE id = new.id OR (\n        session_id = old.session_id AND display_identity = old.display_identity\n        AND (active = 1 OR compacted = 1)\n    );\nEND;\nDROP TRIGGER IF EXISTS messages_display_identity_delete;\nCREATE TRIGGER IF NOT EXISTS messages_display_identity_delete\nAFTER DELETE ON messages WHEN old.active = 1 OR old.compacted = 1\nBEGIN\n    UPDATE messages SET display_order = (\n        SELECT MIN(peer.id) FROM messages AS peer\n        WHERE peer.session_id = old.session_id AND (peer.active = 1 OR peer.compacted = 1)\n          AND peer.display_identity = old.display_identity\n    ) WHERE session_id = old.session_id AND (active = 1 OR compacted = 1)\n      AND display_identity = old.display_identity;\nEND;\nCREATE INDEX IF NOT EXISTS idx_messages_active_null\n    ON messages(active) WHERE active IS NULL;\n-- Logical-identity recovery (agent.transcript_repair._active_logical_message_row) runs inside the write lock.\nCREATE INDEX IF NOT EXISTS idx_messages_session_uid\n    ON messages(session_id, message_uid) WHERE active = 1;\nCREATE INDEX IF NOT EXISTS idx_sessions_session_key\n    ON sessions(session_key, started_at DESC);\nCREATE INDEX IF NOT EXISTS idx_sessions_gateway_peer\n    ON sessions(source, user_id, chat_id, chat_type, thread_id, started_at DESC);\nCREATE INDEX IF NOT EXISTS idx_sessions_handoff_state\n    ON sessions(handoff_state, started_at);\nCREATE INDEX IF NOT EXISTS idx_sessions_system_prompt_hash\n    ON sessions(system_prompt_hash);\nCREATE INDEX IF NOT EXISTS idx_sessions_tool_names\n    ON sessions(tool_names);\n-- Recent-session browsing must never derive recency by scanning messages.\n-- This expression is the durable, indexable approximation used to preselect\n-- a small candidate set before compression-chain and preview hydration.\nCREATE INDEX IF NOT EXISTS idx_sessions_effective_activity\n    ON sessions(COALESCE(last_activity_at, started_at) DESC, started_at DESC);\n-- CLI/TUI listings match gateway rows stored as source='local' by created_source,\n-- before LIMIT. created_source is reconciled onto legacy DBs, so this index lives\n-- here rather than in SCHEMA_SQL. A source-only index would walk every local row\n-- (Desktop and TUI included) to find one surface.\nCREATE INDEX IF NOT EXISTS idx_sessions_local_created_started\n    ON sessions(created_source, started_at DESC)\n    WHERE source = 'local';\n"
FTS_SQL = f"\n-- Stable projection the base word index reads and writes through: the view\n-- computes EXACTLY what the triggers/backfill insert, so 'rebuild' and the\n-- integrity checker always agree with the stored index.\nCREATE VIEW IF NOT EXISTS messages_fts_src AS\n    SELECT id,\n           CASE WHEN role = 'tool'\n                THEN substr(COALESCE(content, ''), 1, {FTS_TOOL_CONTENT_PREFIX_CHARS})\n                ELSE content END AS content,\n           tool_name, tool_calls\n    FROM messages;\n\nCREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(\n    content,\n    tool_name,\n    tool_calls,\n    content='messages_fts_src',\n    content_rowid='id'\n);\n\nCREATE TRIGGER IF NOT EXISTS messages_fts_insert AFTER INSERT ON messages\nWHEN (new.id > COALESCE((SELECT CAST(value AS INTEGER) FROM state_meta\n                         WHERE key = 'fts_rebuild_high_water'), -1)\n   OR new.id <= COALESCE((SELECT CAST(value AS INTEGER) FROM state_meta\n                          WHERE key = 'fts_rebuild_progress'), -1))\nBEGIN\n    INSERT INTO messages_fts(rowid, content, tool_name, tool_calls)\n    VALUES (\n        new.id,\n        {_FTS_NEW_INDEXED_CONTENT_SQL},\n        new.tool_name,\n        new.tool_calls\n    );\nEND;\n\nCREATE TRIGGER IF NOT EXISTS messages_fts_delete AFTER DELETE ON messages\nWHEN (old.id > COALESCE((SELECT CAST(value AS INTEGER) FROM state_meta\n                         WHERE key = 'fts_rebuild_high_water'), -1)\n   OR old.id <= COALESCE((SELECT CAST(value AS INTEGER) FROM state_meta\n                          WHERE key = 'fts_rebuild_progress'), -1))\nBEGIN\n    INSERT INTO messages_fts(messages_fts, rowid, content, tool_name, tool_calls)\n    VALUES (\n        'delete',\n        old.id,\n        {_FTS_OLD_INDEXED_CONTENT_SQL},\n        old.tool_name,\n        old.tool_calls\n    );\nEND;\n\n-- UPDATE OF skips the trigger entirely for non-content column writes\n-- (status/compacted/observed/etc.), which is stronger than the WHEN gate\n-- alone and avoids FTS I/O saturation on large state.db (#68858 / #73639).\nCREATE TRIGGER IF NOT EXISTS messages_fts_update\nAFTER UPDATE OF content, tool_name, tool_calls, role ON messages\nWHEN (old.content IS NOT new.content\n    OR old.tool_name IS NOT new.tool_name\n    OR old.tool_calls IS NOT new.tool_calls\n    OR old.role IS NOT new.role)\n   AND (old.id > COALESCE((SELECT CAST(value AS INTEGER) FROM state_meta\n                           WHERE key = 'fts_rebuild_high_water'), -1)\n     OR old.id <= COALESCE((SELECT CAST(value AS INTEGER) FROM state_meta\n                            WHERE key = 'fts_rebuild_progress'), -1))\nBEGIN\n    INSERT INTO messages_fts(messages_fts, rowid, content, tool_name, tool_calls)\n    VALUES (\n        'delete',\n        old.id,\n        {_FTS_OLD_INDEXED_CONTENT_SQL},\n        old.tool_name,\n        old.tool_calls\n    );\n    INSERT INTO messages_fts(rowid, content, tool_name, tool_calls)\n    VALUES (\n        new.id,\n        {_FTS_NEW_INDEXED_CONTENT_SQL},\n        new.tool_name,\n        new.tool_calls\n    );\nEND;\n"
FTS_TRIGRAM_EXCLUDED_SOURCES = ('cron', 'subagent')

def fts_trigram_session_sql(alias: str='') -> str:
    """Predicate over a ``sessions`` row selecting sessions whose rows belong in
    the trigram index; ``alias`` qualifies every column for joins. Shared by the
    view, the sync triggers, and the deferred-backfill INSERT ... SELECTs so they
    can never disagree about the index boundary."""
    q = f'{alias}.' if alias else ''
    return f'{q}source NOT IN (' + ', '.join((f"'{src}'" for src in FTS_TRIGRAM_EXCLUDED_SOURCES)) + f') AND {_sql_json_extract(q + 'model_config', '$._delegate_from')} IS NULL'
FTS_TRIGRAM_SESSION_SQL = fts_trigram_session_sql()
FTS_TRIGRAM_SQL = f"\nCREATE VIEW IF NOT EXISTS messages_fts_trigram_src AS\n    SELECT m.id, m.role, m.content, m.tool_name\n    FROM messages AS m\n    JOIN sessions AS s ON s.id = m.session_id\n    WHERE m.role <> 'tool' AND {fts_trigram_session_sql('s')};\n\nCREATE VIRTUAL TABLE IF NOT EXISTS messages_fts_trigram USING fts5(\n    content,\n    tool_name,\n    content='messages_fts_trigram_src',\n    content_rowid='id',\n    tokenize='trigram'\n);\n\nCREATE TRIGGER IF NOT EXISTS messages_fts_trigram_insert AFTER INSERT ON messages\nWHEN new.role <> 'tool'\n   AND EXISTS (SELECT 1 FROM sessions\n               WHERE id = new.session_id AND {FTS_TRIGRAM_SESSION_SQL})\n   AND (new.id > COALESCE((SELECT CAST(value AS INTEGER) FROM state_meta\n                           WHERE key = 'fts_rebuild_high_water'), -1)\n     OR new.id <= COALESCE((SELECT CAST(value AS INTEGER) FROM state_meta\n                            WHERE key = 'fts_rebuild_progress'), -1))\nBEGIN\n    INSERT INTO messages_fts_trigram(rowid, content, tool_name)\n    VALUES (new.id, new.content, new.tool_name);\nEND;\n\nCREATE TRIGGER IF NOT EXISTS messages_fts_trigram_delete AFTER DELETE ON messages\nWHEN old.role <> 'tool'\n   AND EXISTS (SELECT 1 FROM sessions\n               WHERE id = old.session_id AND {FTS_TRIGRAM_SESSION_SQL})\n   AND (old.id > COALESCE((SELECT CAST(value AS INTEGER) FROM state_meta\n                           WHERE key = 'fts_rebuild_high_water'), -1)\n     OR old.id <= COALESCE((SELECT CAST(value AS INTEGER) FROM state_meta\n                            WHERE key = 'fts_rebuild_progress'), -1))\nBEGIN\n    INSERT INTO messages_fts_trigram(messages_fts_trigram, rowid, content, tool_name)\n    VALUES ('delete', old.id, old.content, old.tool_name);\nEND;\n\nCREATE TRIGGER IF NOT EXISTS messages_fts_trigram_update\nAFTER UPDATE OF content, tool_name, role ON messages\nWHEN (old.content IS NOT new.content\n    OR old.tool_name IS NOT new.tool_name\n    OR old.role IS NOT new.role)\n   AND (old.id > COALESCE((SELECT CAST(value AS INTEGER) FROM state_meta\n                           WHERE key = 'fts_rebuild_high_water'), -1)\n     OR old.id <= COALESCE((SELECT CAST(value AS INTEGER) FROM state_meta\n                            WHERE key = 'fts_rebuild_progress'), -1))\nBEGIN\n    INSERT INTO messages_fts_trigram(messages_fts_trigram, rowid, content, tool_name)\n    SELECT 'delete', old.id, old.content, old.tool_name\n    WHERE old.role <> 'tool'\n      AND EXISTS (SELECT 1 FROM sessions\n                  WHERE id = old.session_id AND {FTS_TRIGRAM_SESSION_SQL});\n    INSERT INTO messages_fts_trigram(rowid, content, tool_name)\n    SELECT new.id, new.content, new.tool_name\n    WHERE new.role <> 'tool'\n      AND EXISTS (SELECT 1 FROM sessions\n                  WHERE id = new.session_id AND {FTS_TRIGRAM_SESSION_SQL});\nEND;\n"
_FTS_CJK_TRIGGERS = ('messages_fts_cjk_insert', 'messages_fts_cjk_delete', 'messages_fts_cjk_update')
FTS_CJK_STALE_KEY = 'fts_cjk_stale'
FTS_STALE_KEY = 'fts_stale'
FTS_REBUILD_DEFERRAL_KEY = 'fts_rebuild_deferral'
LEGACY_FTS_SQL = f"\nCREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(\n    content\n);\n\nCREATE TRIGGER IF NOT EXISTS messages_fts_insert AFTER INSERT ON messages BEGIN\n    INSERT INTO messages_fts(rowid, content) VALUES (\n        new.id,\n        COALESCE({_FTS_NEW_INDEXED_CONTENT_SQL}, '')\n        || ' ' || COALESCE(new.tool_name, '') || ' ' || COALESCE(new.tool_calls, '')\n    );\nEND;\n\nCREATE TRIGGER IF NOT EXISTS messages_fts_delete AFTER DELETE ON messages BEGIN\n    DELETE FROM messages_fts WHERE rowid = old.id;\nEND;\n\nCREATE TRIGGER IF NOT EXISTS messages_fts_update\nAFTER UPDATE OF content, tool_name, tool_calls, role ON messages BEGIN\n    DELETE FROM messages_fts WHERE rowid = old.id;\n    INSERT INTO messages_fts(rowid, content) VALUES (\n        new.id,\n        COALESCE({_FTS_NEW_INDEXED_CONTENT_SQL}, '')\n        || ' ' || COALESCE(new.tool_name, '') || ' ' || COALESCE(new.tool_calls, '')\n    );\nEND;\n"
LEGACY_FTS_TRIGRAM_SQL = f"\nCREATE VIRTUAL TABLE IF NOT EXISTS messages_fts_trigram USING fts5(\n    content,\n    tokenize='trigram'\n);\n\nCREATE TRIGGER IF NOT EXISTS messages_fts_trigram_insert AFTER INSERT ON messages BEGIN\n    INSERT INTO messages_fts_trigram(rowid, content) VALUES (\n        new.id,\n        COALESCE({_FTS_NEW_INDEXED_CONTENT_SQL}, '')\n        || ' ' || COALESCE(new.tool_name, '') || ' ' || COALESCE(new.tool_calls, '')\n    );\nEND;\n\nCREATE TRIGGER IF NOT EXISTS messages_fts_trigram_delete AFTER DELETE ON messages BEGIN\n    DELETE FROM messages_fts_trigram WHERE rowid = old.id;\nEND;\n\nCREATE TRIGGER IF NOT EXISTS messages_fts_trigram_update\nAFTER UPDATE OF content, tool_name, tool_calls, role ON messages BEGIN\n    DELETE FROM messages_fts_trigram WHERE rowid = old.id;\n    INSERT INTO messages_fts_trigram(rowid, content) VALUES (\n        new.id,\n        COALESCE({_FTS_NEW_INDEXED_CONTENT_SQL}, '')\n        || ' ' || COALESCE(new.tool_name, '') || ' ' || COALESCE(new.tool_calls, '')\n    );\nEND;\n"
logger = logging.getLogger('hermes_state')
_FTS_REBUILD_LOCK_TIMEOUT_SECONDS = 120.0
_FTS_REBUILD_LOCK_POLL_SECONDS = 0.1
_IS_WINDOWS = sys.platform == 'win32'
_LOCK_BREAK_REACQUIRE_SECONDS = 5.0
_LOCK_CONTENTION_ERRNOS = {errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK, errno.EDEADLK}

def is_advisory_lock_contention(exc: BaseException) -> bool:
    """True when *exc* means another process holds the lock; on any other ``OSError`` fail closed at once."""
    return isinstance(exc, BlockingIOError) or (isinstance(exc, OSError) and exc.errno in _LOCK_CONTENTION_ERRNOS)

def _proc_start_ticks(pid: int):
    """Kernel start time of *pid* (field 22 of ``/proc/<pid>/stat``; with the PID it identifies a process
    uniquely).  None off Linux or on any failure — callers must treat None as unknowable and FAIL CLOSED."""
    try:
        with open(f'/proc/{pid}/stat', 'rb') as fh:
            return int(fh.read().rsplit(b')', 1)[1].split()[19])
    except (OSError, ValueError, IndexError):
        return None

def _read_lock_holder_record(handle):
    """Best-effort parse of the holder metadata JSON in a lock file."""
    try:
        handle.seek(0)
        raw = handle.read(4096)
        record = json.loads(raw.decode('utf-8', 'replace')) if raw else None
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    return record if isinstance(record, dict) else None

def _rewrite_lock_file(handle, payload: bytes) -> None:
    """Best-effort truncate-and-write of *payload* at offset 0."""
    with contextlib.suppress(OSError, ValueError):
        handle.seek(0)
        handle.truncate()
        if payload:
            handle.write(payload)
        handle.flush()

def _write_lock_holder_record(handle) -> None:
    """Record this process as holder (best effort) so timed-out contenders can tell an orphaned-fd holder
    from a live wedged one.

    Written under the flock so contenders that time out can tell an orphaned-fd holder (recorded process
    dead, flock inherited by a forked child — issue #100108) from a live wedged holder.  ``pidns``: see
    ``hermes_state_pidns``.
    """
    record = {'pid': os.getpid(), 'pidns': pid_namespace_id(), 'start_ticks': _proc_start_ticks(os.getpid()), 'acquired_at': time.time()}
    _rewrite_lock_file(handle, json.dumps(record, sort_keys=True).encode('utf-8'))

def _clear_lock_holder_record(handle) -> None:
    """Erase holder metadata before a normal release: a surviving record means ABNORMAL exit (break allowed)."""
    _rewrite_lock_file(handle, b'')

def _lock_holder_provably_dead(record) -> bool:
    """True ONLY when the recorded holder is provably dead or PID-recycled.  Anything indeterminate
    (no/malformed record, PID owned by another user, /proc unavailable, foreign PID namespace)
    is False: FAIL CLOSED and defer.  Unstamped records keep probing: see ``hermes_state_pidns``."""
    try:
        pid = int(record['pid'])
    except (KeyError, TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if not persistent_record_pidns_checkable(record.get('pidns')):
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except OSError:
        return False
    recorded_ticks = record.get('start_ticks')
    if recorded_ticks is None:
        return False
    current_ticks = _proc_start_ticks(pid)
    return current_ticks is not None and current_ticks != recorded_ticks

def _acquire_db_flock(lock_path, handle, timeout_seconds, poll_seconds, description):
    """Bounded POSIX flock acquire with orphaned-holder break.  Returns ``(acquired, handle)``; *handle* may
    have been re-opened and the caller closes whichever comes back.  *acquired*: True, False (a holder kept
    the lock past the deadline) or None (non-contention ``OSError``, already logged: treat as not acquired
    without the held-by-another-process warning).  ``flock`` rides the open file DESCRIPTION, which ``fork()``
    duplicates, so a holder that forks then dies leaves the lock held forever; when the acquirer is provably
    dead the file is unlinked and retaken on a fresh inode (the orphan's flock excludes nobody).  Every
    acquire verifies its inode still names *lock_path*, so a racer on a dead inode retries.

    A holder that forks (multiprocessing worker, daemonized helper) and then dies leaves the flock held by a
    child that will never release it — the kernel's holder-death release never triggers, and every contender
    defers forever. Indeterminate liveness always defers (fail closed). See #100108.
    """
    import fcntl
    deadline = time.monotonic() + timeout_seconds
    broke_lock = False
    while True:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError) as exc:
            if not is_advisory_lock_contention(exc):
                logger.warning('Could not acquire %s %s (%s) — deferring rather than waiting out the %.0fs holder timeout on a non-contention error.', description, lock_path, exc, timeout_seconds)
                return (None, handle)
            if time.monotonic() < deadline:
                time.sleep(poll_seconds)
                continue
            if broke_lock:
                return (False, handle)
            record = _read_lock_holder_record(handle)
            if not _lock_holder_provably_dead(record):
                return (False, handle)
            logger.warning('%s %s is held by an orphaned file descriptor (recorded holder pid %s is dead — a forked child inherited the lock fd); breaking the stale lock and retaking it on a fresh file.', description, lock_path, (record or {}).get('pid'))
            try:
                os.unlink(lock_path)
                handle.close()
                handle = open(lock_path, 'a+b')
            except OSError as exc:
                logger.warning('Could not break stale %s %s (%s) — deferring.', description, lock_path, exc)
                return (False, handle)
            broke_lock = True
            deadline = time.monotonic() + _LOCK_BREAK_REACQUIRE_SECONDS
            continue
        try:
            fd_stat, path_stat = (os.fstat(handle.fileno()), os.stat(lock_path))
            same_file = fd_stat.st_dev == path_stat.st_dev and fd_stat.st_ino == path_stat.st_ino
        except OSError:
            same_file = False
        if same_file:
            _write_lock_holder_record(handle)
            return (True, handle)
        try:
            handle.close()
            handle = open(lock_path, 'a+b')
        except OSError:
            return (False, handle)
        if time.monotonic() >= deadline:
            return (False, handle)

def _describe_lock_holder(record) -> str:
    """Human-readable holder identity for deferral warnings."""
    if not isinstance(record, dict) or 'pid' not in record:
        return 'unknown (no holder record; pre-fix writer or non-Hermes)'
    age = ''
    with contextlib.suppress(TypeError, ValueError):
        if record.get('acquired_at') is not None:
            age = f', acquired {time.time() - float(record['acquired_at']):.0f}s ago'
    return f'pid {record.get('pid')}{age}'

def _acquire_msvcrt_lock(lock_path, handle, timeout):
    """Windows counterpart of ``_acquire_db_flock`` (no orphan break); same True / False / None contract."""
    import msvcrt
    deadline = time.monotonic() + timeout
    while True:
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except (BlockingIOError, OSError) as exc:
            if not is_advisory_lock_contention(exc):
                logger.warning('Could not acquire FTS rebuild lock %s (%s) — deferring on a non-contention error.', lock_path, exc)
                return None
            if time.monotonic() >= deadline:
                return False
            time.sleep(_FTS_REBUILD_LOCK_POLL_SECONDS)

@contextlib.contextmanager
def fts_rebuild_admission(db_path, *, timeout_seconds=None):
    """Serialize full structural FTS rebuilds on *db_path* across processes.  Yields True when this process
    holds the authority, False when the bounded acquire timed out or the lock file could not be opened: the
    caller must NOT rebuild (fail closed; the stale breadcrumb guarantees a retry).  ``db_path`` None
    (in-memory) yields True.  In-process retries pass ``timeout_seconds=0`` so a live holder never stalls a
    long-lived writer; the orphan break still applies."""
    if db_path is None:
        yield True
        return
    timeout = _FTS_REBUILD_LOCK_TIMEOUT_SECONDS if timeout_seconds is None else max(float(timeout_seconds), 0.0)
    lock_path = f'{db_path}.fts_rebuild.lock'
    try:
        handle = open(lock_path, 'a+b')
    except OSError as exc:
        logger.warning('Could not open FTS rebuild lock %s (%s) — deferring this rebuild rather than running it without cross-process authority.', lock_path, exc)
        yield False
        return
    acquired = False
    try:
        if _IS_WINDOWS:
            acquired = _acquire_msvcrt_lock(lock_path, handle, timeout)
        else:
            acquired, handle = _acquire_db_flock(lock_path, handle, timeout, _FTS_REBUILD_LOCK_POLL_SECONDS, 'FTS rebuild lock')
        if acquired is None:
            acquired = False
        elif not acquired:
            record = None if _IS_WINDOWS else _read_lock_holder_record(handle)
            if timeout <= 0:
                logger.info('FTS rebuild lock %s is busy — deferring this retry (the stale-FTS breadcrumb keeps it retryable). Recorded holder: %s.', lock_path, _describe_lock_holder(record))
            else:
                logger.warning('FTS rebuild lock %s held by another process for more than %.0fs — deferring this rebuild to avoid racing the holder (the stale-FTS breadcrumb keeps it retryable). Recorded holder: %s.', lock_path, timeout, _describe_lock_holder(record))
        yield acquired
    finally:
        try:
            with contextlib.suppress(OSError):
                if acquired and _IS_WINDOWS:
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                elif acquired:
                    import fcntl
                    _clear_lock_holder_record(handle)
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

def _json_or(raw: Any, fallback: Any, warning: str) -> Any:
    """``json.loads(raw)``; on failure log *warning* and return *fallback*."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning(warning)
        return fallback
