# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
from __future__ import annotations
import re
from typing import Any
_SURROGATE_RE = re.compile('[\\ud800-\\udfff]')

def _sanitize_surrogates(text: str) -> str:
    """Replace lone surrogate code points with U+FFFD; no-op when none present."""
    if text.isascii():
        return text
    return _SURROGATE_RE.sub('�', text)

def _tc_field(tc: Any, key: str) -> Any:
    """Read ``key`` from a tool-call entry that may be a dict or an SDK object."""
    return tc.get(key) if isinstance(tc, dict) else getattr(tc, key, None)

def _expand_tool_id_variants(values: tuple[Any, ...]) -> frozenset[str]:
    """Every wire spelling of one tool-call identifier: Responses bridges may expose the pairing
    id and response-item id separately or as ``call_id|response_item_id``; all alias ONE call."""
    variants: set[str] = set()
    for raw in values:
        value = raw.strip() if isinstance(raw, str) else ''
        if value:
            variants.add(value)
            variants.update((p for p in (part.strip() for part in value.split('|')) if p))
    return frozenset(variants)

def tool_call_id_variants(tc: Any) -> frozenset[str]:
    """Return all pairing-id variants carried by a tool-call entry."""
    return _expand_tool_id_variants(tuple((_tc_field(tc, k) for k in ('call_id', 'id', 'response_item_id'))))

def tool_result_id_variants(tool_call_id: Any) -> frozenset[str]:
    """Return all matching variants for a role=tool ``tool_call_id``."""
    return _expand_tool_id_variants((tool_call_id,))

def coalesce_tool_call_id(tc: Any) -> str:
    """Effective call id of a tool_call entry (dict or object); ``""`` when none. Codex Responses
    carry ``call_id`` (authoritative pairing key), Chat Completions ``id`` only, and bridge ids
    may be ``call_id|response_item_id``."""
    for raw in (_tc_field(tc, 'call_id'), _tc_field(tc, 'id')):
        value = raw.strip() if isinstance(raw, str) else ''
        if value:
            return value.split('|', 1)[0].strip() or value
    return ''
