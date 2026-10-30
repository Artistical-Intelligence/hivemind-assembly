# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
from __future__ import annotations
import json
from typing import Any, Mapping, Optional
from hivemind_assembly.automation.state_engine.agent.message_metadata import ABSORBED_MESSAGE_UIDS, TOOL_CALL_UID, TOOL_CALL_UIDS, uid_list
from hivemind_assembly.automation.state_engine.agent.message_sanitization import coalesce_tool_call_id
from hivemind_assembly.automation.state_engine.hermes_state_common import _json_or

def _live_or_column(msg: Mapping[str, Any], live_key: str, column: str) -> Any:
    """Flushed dicts and batch rows carry the live key; import payloads carry the column name."""
    return msg.get(live_key) if live_key in msg else msg.get(column)

def _uid_list(value: Any) -> list[str]:
    """Normalize a uid list (a live list, or the JSON text an export/import carries) to unique non-empty
    strings in order; anything else is ``[]``."""
    if isinstance(value, str):
        value = _json_or(value, [], 'Failed to deserialize a message uid list, falling back to []')
    return uid_list(value)

def _uid_map(value: Any) -> dict[str, Any]:
    """Normalize a ``{tool call id: uid}`` map (a live dict, or the JSON text an export/import carries): a
    non-empty string uid, or a list of them for a provider id repeated inside one row (one per occurrence,
    see ``merge_tool_call_uids``); anything else is dropped, and a non-map is ``{}``."""
    if isinstance(value, str):
        value = _json_or(value, {}, 'Failed to deserialize a tool-call uid map, falling back to {}')
    if not isinstance(value, dict):
        return {}
    return {k: v for k, v in value.items() if isinstance(k, str) and k and (isinstance(v, str) and v or (isinstance(v, list) and v and all((isinstance(u, str) and u for u in v))))}

def _tool_call_uid_map(msg: Mapping[str, Any]) -> dict[str, Any]:
    return _uid_map(_live_or_column(msg, TOOL_CALL_UIDS, 'tool_call_uids'))

def _absorbed_uids_json(msg: Mapping[str, Any]) -> Optional[str]:
    uids = _uid_list(_live_or_column(msg, ABSORBED_MESSAGE_UIDS, 'absorbed_message_uids'))
    return json.dumps(uids) if uids else None

def _tool_call_uids_json(msg: Mapping[str, Any]) -> Optional[str]:
    uids = _tool_call_uid_map(msg)
    return json.dumps(uids, sort_keys=True) if uids else None

def _tool_call_uid_or_none(msg: Mapping[str, Any]) -> Optional[str]:
    uid = _live_or_column(msg, TOOL_CALL_UID, 'tool_call_uid')
    return uid if isinstance(uid, str) and uid else None

def _stable_tool_key(row: Any) -> Optional[tuple[Any, ...]]:
    """Display-dedupe key of a tool-calling assistant row built from its stable call ids instead of the arguments a
    prune rewrites (#117750: a pruned carried-forward copy must collapse with its durable original). ``None`` for
    every other row and for an incomplete id set, so the caller keeps the full content key: a tool RESULT row keeps
    its payload in the key, because folding the archived full output into its pruned stub would drop the original
    from compacted history and transcript exports, and distinct id-less calls never merge."""
    if row['role'] != 'assistant':
        return None
    calls = _json_or(row['tool_calls'] or '[]', [], 'Failed to deserialize tool_calls, falling back to []')
    call_ids = tuple((coalesce_tool_call_id(tc) for tc in calls or ()))
    if call_ids and all(call_ids):
        return ('assistant', None, row['timestamp'], row['tool_call_id'], call_ids, row['tool_name'])
    return None
