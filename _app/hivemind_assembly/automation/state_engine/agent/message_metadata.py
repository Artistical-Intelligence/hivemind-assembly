# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
from __future__ import annotations
from uuid import uuid4
from typing import Any, Mapping, MutableMapping, Optional
DB_ROW_SNAPSHOT = '_db_row_snapshot'
MESSAGE_UID = 'message_uid'
ABSORBED_MESSAGE_UIDS = '_absorbed_message_uids'
TOOL_CALL_UIDS = '_tool_call_uids'
TOOL_CALL_UID = '_tool_call_uid'

def mint_uid() -> str:
    """A fresh durable id (message or tool-call occurrence): random, never derived from content."""
    return uuid4().hex

def uid_list(value: Any) -> list[str]:
    """The unique non-empty string uids of a live list, in order; anything else is ``[]``."""
    return list(dict.fromkeys((u for u in (value if isinstance(value, list) else ()) if isinstance(u, str) and u)))

def message_uid_or_none(msg: Mapping[str, Any]) -> Optional[str]:
    """The dict's ``message_uid`` when it is a non-empty string, else ``None`` (never coerced: an int or a
    blank would be a bug upstream of the write, not an identity)."""
    uid = msg.get(MESSAGE_UID)
    return uid if isinstance(uid, str) and uid else None

def stamp_message_uid(msg: MutableMapping[str, Any]) -> str:
    """The dict's ``message_uid``, minting one (``mint_uid``) when it carries none.

    Minted ONCE per logical message, at its first insert, and stamped on the caller's dict so every later
    insert of that dict (compaction generation, rotation handoff, replace) writes the same uid. Never
    derived from content, timestamp or tool-call ids: two distinct messages may share all three.
    """
    uid = message_uid_or_none(msg)
    if uid is None:
        uid = msg[MESSAGE_UID] = mint_uid()
    return uid

def index_tool_call_uids(index: MutableMapping[str, str], assistant: Mapping[str, Any]) -> frozenset:
    """Register an assistant dict's ``_tool_call_uids`` under every pairing-id variant of its tool calls, so a
    later tool-result row can be resolved by any spelling of its ``tool_call_id``. Provider ids repeat, so
    every id this assistant names first shadows an earlier occurrence's entry: a result pairs with the
    NEAREST preceding call, and a call without a uid (a legacy row) pairs its result with nothing. A
    provider id repeated inside one row (two folded turns) maps each call to its own occurrence's uid.
    Returns every pairing-id variant the assistant names."""
    from hivemind_assembly.automation.state_engine.agent.message_sanitization import coalesce_tool_call_id, tool_call_id_variants
    calls = [(tc, tool_call_id_variants(tc)) for tc in assistant.get('tool_calls') or ()]
    named = frozenset((variant for _, variants in calls for variant in variants))
    for variant in named:
        index.pop(variant, None)
    uids = assistant.get(TOOL_CALL_UIDS)
    if not isinstance(uids, dict) or not uids:
        return named
    occurrence: dict = {}
    for tc, variants in calls:
        call_id = coalesce_tool_call_id(tc)
        uid = uids.get(call_id)
        if isinstance(uid, list):
            nth = occurrence[call_id] = occurrence.get(call_id, -1) + 1
            uid = uid[nth] if nth < len(uid) else None
        if isinstance(uid, str) and uid:
            for variant in variants:
                index[variant] = uid
    return named

def resolve_tool_call_uid(index: MutableMapping[str, str], tool_call_id: Any) -> Optional[str]:
    """The uid an indexed assistant dict minted for ``tool_call_id`` (any variant), else ``None``."""
    from hivemind_assembly.automation.state_engine.agent.message_sanitization import tool_result_id_variants
    if not index or not isinstance(tool_call_id, str) or (not tool_call_id):
        return None
    for variant in tool_result_id_variants(tool_call_id):
        uid = index.get(variant)
        if uid:
            return uid
    return None
