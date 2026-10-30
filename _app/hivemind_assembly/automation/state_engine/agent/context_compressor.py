# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
import copy
from typing import Any, Optional
from hivemind_assembly.automation.state_engine.agent.prompt_builder import STEER_DISPLAY_KIND
from hivemind_assembly.automation.state_engine.agent.turn_context import drop_stale_api_content
from hivemind_assembly.automation.state_engine.tools.todo_tool import TODO_INJECTION_HEADER
HISTORICAL_TASK_HEADING = '## Historical Task Snapshot'
SUMMARY_PREFIX = f"[CONTEXT COMPACTION — REFERENCE ONLY] Earlier turns were compacted into the summary below. This is a handoff from a previous context window — treat it as background reference, NOT as active instructions. Do NOT answer questions or fulfill requests mentioned in this summary; they were already addressed. Respond ONLY to the latest user message that appears AFTER this summary — that message is the single source of truth for what to do right now. If no user message appears AFTER this summary, do nothing: do not resume, wrap up, or continue work from '{HISTORICAL_TASK_HEADING}' or any other section, do not call tools, and wait for a new user message. This handoff must never become the active turn by itself. (Exception: if tool results or your own tool calls appear after this summary, you are mid-way through an in-flight exchange — continue that exchange normally.) Topic overlap with the summary does NOT mean you should resume its task: even on similar topics, the latest user message WINS. Treat ONLY the latest message as the active task and discard stale items from '{HISTORICAL_TASK_HEADING}' entirely — do not 'wrap up' or 'finish' work described there unless the latest message explicitly asks for it. Reverse signals in the latest message (e.g. 'stop', 'undo', 'roll back', 'just verify', 'don't do that anymore', 'never mind', a new topic) must immediately end any in-flight work described in the summary; do not re-surface it in later turns. IMPORTANT: Your persistent memory (MEMORY.md, USER.md) in the system prompt is ALWAYS authoritative and active — never ignore or deprioritize memory content due to this compaction note. None of the above restricts HOW you work: your tools remain fully active — keep calling them normally for the active task (edit files, run commands, search) instead of merely narrating what you would do. The current session state (files, config, etc.) may reflect work described here — avoid repeating it:"
LEGACY_SUMMARY_PREFIX = '[CONTEXT SUMMARY]:'
COMPRESSED_SUMMARY_METADATA_KEY = '_compressed_summary'
COMPRESSED_SUMMARY_HAS_USER_TURN_KEY = '_compressed_summary_has_user_turn'
MICRO_COMPACT_MARKER_KEY = '_micro_compact_marker'
MODEL_ONLY_DISPLAY_METADATA_KEY = 'model_only'
_DB_PERSISTED_MARKER = '_db_persisted'
COMPRESSION_CONTINUATION_USER_CONTENT = 'Continue from the compressed conversation context above. This marker exists because no human user turn was available.'
_LEGACY_COMPRESSION_CONTINUATION_USER_CONTENT = 'Continue from the compressed conversation context above. This marker exists because the compacted transcript contained no preserved user turn.'
MAX_ITERATIONS_SUMMARY_REQUEST = "You've reached the maximum number of tool-calling iterations allowed. Please provide a final response summarizing what you've found and accomplished so far, without calling any more tools."
_BACKGROUND_PROCESS_NOTIFICATION_PREFIX = '[IMPORTANT: Background process '
_SUMMARY_END_MARKER = '--- END OF CONTEXT SUMMARY — respond to the message below, not the summary above ---'
_MERGED_PRIOR_CONTEXT_HEADER = '[PRIOR CONTEXT — for reference only; not a new message]'
_MERGED_SUMMARY_DELIMITER = '[END OF PRIOR CONTEXT — COMPACTION SUMMARY BELOW]'
_HISTORICAL_SUMMARY_PREFIXES = ("[CONTEXT COMPACTION — REFERENCE ONLY] Earlier turns were compacted into the summary below. This is a handoff from a previous context window — treat it as background reference, NOT as active instructions. Do NOT answer questions or fulfill requests mentioned in this summary; they were already addressed. Respond ONLY to the latest user message that appears AFTER this summary — that message is the single source of truth for what to do right now. Topic overlap with the summary does NOT mean you should resume its task: even on similar topics, the latest user message WINS. Treat ONLY the latest message as the active task and discard stale items from '## Historical Task Snapshot' entirely — do not 'wrap up' or 'finish' work described there unless the latest message explicitly asks for it. Reverse signals in the latest message (e.g. 'stop', 'undo', 'roll back', 'just verify', 'don't do that anymore', 'never mind', a new topic) must immediately end any in-flight work described in the summary; do not re-surface it in later turns. IMPORTANT: Your persistent memory (MEMORY.md, USER.md) in the system prompt is ALWAYS authoritative and active — never ignore or deprioritize memory content due to this compaction note. None of the above restricts HOW you work: your tools remain fully active — keep calling them normally for the active task (edit files, run commands, search) instead of merely narrating what you would do. The current session state (files, config, etc.) may reflect work described here — avoid repeating it:", "[CONTEXT COMPACTION — REFERENCE ONLY] Earlier turns were compacted into the summary below. This is a handoff from a previous context window — treat it as background reference, NOT as active instructions. Do NOT answer questions or fulfill requests mentioned in this summary; they were already addressed. Respond ONLY to the latest user message that appears AFTER this summary — that message is the single source of truth for what to do right now. Topic overlap with the summary does NOT mean you should resume its task: even on similar topics, the latest user message WINS. Treat ONLY the latest message as the active task and discard stale items from '## Historical Task Snapshot' / '## Historical In-Progress State' / '## Historical Pending User Asks' / '## Historical Remaining Work' entirely — do not 'wrap up' or 'finish' work described there unless the latest message explicitly asks for it. Reverse signals in the latest message (e.g. 'stop', 'undo', 'roll back', 'just verify', 'don't do that anymore', 'never mind', a new topic) must immediately end any in-flight work described in the summary; do not re-surface it in later turns. IMPORTANT: Your persistent memory (MEMORY.md, USER.md) in the system prompt is ALWAYS authoritative and active — never ignore or deprioritize memory content due to this compaction note. None of the above restricts HOW you work: your tools remain fully active — keep calling them normally for the active task (edit files, run commands, search) instead of merely narrating what you would do. The current session state (files, config, etc.) may reflect work described here — avoid repeating it:", "[CONTEXT COMPACTION — REFERENCE ONLY] Earlier turns were compacted into the summary below. This is a handoff from a previous context window — treat it as background reference, NOT as active instructions. Do NOT answer questions or fulfill requests mentioned in this summary; they were already addressed. Respond ONLY to the latest user message that appears AFTER this summary — that message is the single source of truth for what to do right now. Topic overlap with the summary does NOT mean you should resume its task: even on similar topics, the latest user message WINS. Treat ONLY the latest message as the active task and discard stale items from '## Historical Task Snapshot' / '## Historical In-Progress State' / '## Historical Pending User Asks' / '## Historical Remaining Work' entirely — do not 'wrap up' or 'finish' work described there unless the latest message explicitly asks for it. Reverse signals in the latest message (e.g. 'stop', 'undo', 'roll back', 'just verify', 'don't do that anymore', 'never mind', a new topic) must immediately end any in-flight work described in the summary; do not re-surface it in later turns. IMPORTANT: Your persistent memory (MEMORY.md, USER.md) in the system prompt is ALWAYS authoritative and active — never ignore or deprioritize memory content due to this compaction note. The current session state (files, config, etc.) may reflect work described here — avoid repeating it:", "[CONTEXT COMPACTION — REFERENCE ONLY] Earlier turns were compacted into the summary below. This is a handoff from a previous context window — treat it as background reference, NOT as active instructions. Do NOT answer questions or fulfill requests mentioned in this summary; they were already addressed. Respond ONLY to the latest user message that appears AFTER this summary — that message is the single source of truth for what to do right now. If the latest user message is consistent with the '## Active Task' section, you may use the summary as background. If the latest user message contradicts, supersedes, changes topic from, or in any way diverges from '## Active Task' / '## In Progress' / '## Pending User Asks' / '## Remaining Work', the latest message WINS — discard those stale items entirely and do not 'wrap up the old task first'. Reverse signals in the latest message (e.g. 'stop', 'undo', 'roll back', 'just verify', 'don't do that anymore', 'never mind', a new topic) must immediately end any in-flight work described in the summary; do not re-surface it in later turns. IMPORTANT: Your persistent memory (MEMORY.md, USER.md) in the system prompt is ALWAYS authoritative and active — never ignore or deprioritize memory content due to this compaction note. The current session state (files, config, etc.) may reflect work described here — avoid repeating it:", "[CONTEXT COMPACTION — REFERENCE ONLY] Earlier turns were compacted into the summary below. This is a handoff from a previous context window — treat it as background reference, NOT as active instructions. Do NOT answer questions or fulfill requests mentioned in this summary; they were already addressed. Your current task is identified in the '## Active Task' section of the summary — resume exactly from there. Respond ONLY to the latest user message that appears AFTER this summary. The current session state (files, config, etc.) may reflect work described here — avoid repeating it:")
_SUMMARY_INPUT_MAX_CHARS = 160000

def _part_text(item: Any) -> Optional[str]:
    """Text of a content part: the string itself, a dict's ``text``, else None."""
    return item if isinstance(item, str) else item.get('text') if isinstance(item, dict) else None

def _with_part_text(item: Any, text: str) -> Any:
    """Copy of a content part carrying ``text`` (string parts become the text itself)."""
    return {**item, 'text': text} if isinstance(item, dict) else text

def _content_text_for_contains(content: Any) -> str:
    """Return a best-effort text view of message content (for substring checks only)."""
    if isinstance(content, list):
        return '\n'.join((t for t in map(_part_text, content) if isinstance(t, str) and t))
    return '' if content is None else content if isinstance(content, str) else str(content)

class ContextCompressor:
    """Default context engine: prune tool results, protect head/tail, summarize the middle
    with an LLM, and iteratively update the previous summary on later compactions."""
    _MIN_CTX_TRIGGER_RATIO = 0.85
    _ANTI_THRASH_RECOVERY_SECONDS = 300.0
    _STRUCTURAL_NO_OP_BACKOFF_SECONDS = 300.0

    @staticmethod
    def _coerce_max_tokens(value: Any) -> int | None:
        """Normalize max_tokens to a positive int, or None for "no reservation"."""
        try:
            ivalue = int(value) if value is not None else 0
        except (TypeError, ValueError):
            return None
        return ivalue if ivalue > 0 else None
    _coerce_threshold_tokens_cap = _coerce_max_tokens
    _CONTENT_MAX = 6000
    _CONTENT_HEAD = 4000
    _CONTENT_TAIL = 1500
    _TOOL_ARGS_MAX = 1500
    _TOOL_ARGS_HEAD = 1200
    _SUMMARY_INPUT_MAX_CHARS = _SUMMARY_INPUT_MAX_CHARS
    _SAMPLED_INPUT_SLICES = 8

    @staticmethod
    def _starts_with_summary_prefix(text: str) -> bool:
        """Return True if *text* begins with any known handoff prefix."""
        return text.startswith((SUMMARY_PREFIX, LEGACY_SUMMARY_PREFIX, *_HISTORICAL_SUMMARY_PREFIXES))

    @classmethod
    def classify_summary_content(cls, content: Any) -> Optional[str]:
        """Classify how *content* relates to a compaction summary.
        Returns ``"standalone"`` (whole message is a handoff), ``"merged"`` (preserved content +
        delimiter + summary body), or None."""
        text = _content_text_for_contains(content).lstrip()
        if _MERGED_SUMMARY_DELIMITER in text:
            after = text.split(_MERGED_SUMMARY_DELIMITER, 1)[1].lstrip()
            return 'merged' if cls._starts_with_summary_prefix(after) else None
        return 'standalone' if cls._starts_with_summary_prefix(text) else None

    @classmethod
    def _is_context_summary_content(cls, content: Any) -> bool:
        return cls.classify_summary_content(content) is not None

    @staticmethod
    def _has_compressed_summary_metadata(message: Any) -> bool:
        """Return True if *message* carries the in-process compressed-summary flag."""
        return isinstance(message, dict) and bool(message.get(COMPRESSED_SUMMARY_METADATA_KEY))

    @classmethod
    def _is_synthetic_compression_user_turn(cls, message: Any) -> bool:
        """Recognize internal user-role rows by content marker (SessionDB drops metadata)."""
        if not isinstance(message, dict) or message.get('role') != 'user':
            return False
        if cls._is_context_summary_message(message):
            return True
        text = _content_text_for_contains(message.get('content')).strip()
        from hivemind_assembly.automation.state_engine.agent.conversation_loop import _CODEX_ACK_CONTINUATION_NUDGE, _CODEX_INCOMPLETE_NUDGE, _DEGENERATE_FINAL_NUDGE, _DROPPED_TOOLCALL_NUDGE_CONTENT, _EMPTY_TOOL_RESPONSE_NUDGE, _LENGTH_CONTINUATION_DROPPED_TOOLS_PREFIX, _LEGACY_LENGTH_CONTINUATION_NETWORK_STUB, _LENGTH_CONTINUATION_NETWORK_STUB, _LENGTH_CONTINUATION_OUTPUT_LIMIT
        return text in {COMPRESSION_CONTINUATION_USER_CONTENT, _LEGACY_COMPRESSION_CONTINUATION_USER_CONTENT, MAX_ITERATIONS_SUMMARY_REQUEST, _CODEX_INCOMPLETE_NUDGE, _CODEX_ACK_CONTINUATION_NUDGE, _DEGENERATE_FINAL_NUDGE, _DROPPED_TOOLCALL_NUDGE_CONTENT, _EMPTY_TOOL_RESPONSE_NUDGE, _LENGTH_CONTINUATION_NETWORK_STUB, _LEGACY_LENGTH_CONTINUATION_NETWORK_STUB, _LENGTH_CONTINUATION_OUTPUT_LIMIT} or text.startswith((_BACKGROUND_PROCESS_NOTIFICATION_PREFIX, TODO_INJECTION_HEADER + '\n', _LENGTH_CONTINUATION_DROPPED_TOOLS_PREFIX))

    @classmethod
    def _is_context_summary_message(cls, message: Any) -> bool:
        """Return True for summary handoff messages by metadata or content."""
        if not isinstance(message, dict):
            return False
        return cls._has_compressed_summary_metadata(message) or cls._is_context_summary_content(message.get('content'))

    @classmethod
    def _is_blank_user_turn(cls, message: Any) -> bool:
        """Return whether *message* is an empty, non-summary user-role echo."""
        if not isinstance(message, dict) or message.get('role') != 'user':
            return False
        if cls._is_context_summary_message(message):
            return False
        content = message.get('content')
        if content is None or (isinstance(content, str) and (not content.strip())):
            return True
        if not isinstance(content, list):
            return False

        def _blank_part(part: Any) -> bool:
            if isinstance(part, str):
                return not part.strip()
            if isinstance(part, dict) and part.get('type') in {'text', 'input_text'}:
                return isinstance(part.get('text'), str) and (not part['text'].strip())
            return False
        return all(map(_blank_part, content))

    @classmethod
    def _is_actionable_user_turn(cls, message: Any) -> bool:
        """Return whether *message* contains user input worth anchoring."""
        if not isinstance(message, dict) or message.get('role') != 'user':
            return False
        display_kind = message.get('display_kind')
        if display_kind and display_kind != STEER_DISPLAY_KIND or cls._is_context_summary_message(message):
            return False
        return not cls._is_blank_user_turn(message)

    @classmethod
    def _strip_context_summary_handoff_message(cls, message: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Drop stale handoff data while preserving merged prior-tail content.
        Returns a copy for non-handoff rows, the unwrapped prior-tail content for merged handoffs
        (delimiter form, or legacy end-marker form), and ``None`` for standalone ones."""
        if not isinstance(message, dict):
            return message
        if not cls._is_context_summary_message(message):
            return message.copy()
        content = message.get('content')

        def _unwrapped(new_content: Any) -> dict[str, Any]:
            unwrapped = {**message, 'content': new_content}
            unwrapped.pop(COMPRESSED_SUMMARY_METADATA_KEY, None)
            return unwrapped
        if isinstance(content, str):
            if _MERGED_SUMMARY_DELIMITER in content:
                prior = content.split(_MERGED_SUMMARY_DELIMITER, 1)[0].strip()
                if prior.startswith(_MERGED_PRIOR_CONTEXT_HEADER):
                    prior = prior[len(_MERGED_PRIOR_CONTEXT_HEADER):].lstrip()
            elif _SUMMARY_END_MARKER in content:
                prior = content.split(_SUMMARY_END_MARKER, 1)[1].lstrip()
            else:
                prior = ''
            return _unwrapped(prior) if prior else None
        if isinstance(content, list):
            prior_blocks: list[Any] = []
            found_delimiter = False
            for item in content:
                text = _part_text(item)
                if isinstance(text, str) and _MERGED_SUMMARY_DELIMITER in text:
                    before = text.split(_MERGED_SUMMARY_DELIMITER, 1)[0]
                    if before.strip():
                        prior_blocks.append(_with_part_text(item, before))
                    found_delimiter = True
                    break
                prior_blocks.append(item.copy() if isinstance(item, dict) else item)
            if not found_delimiter:
                for index, item in enumerate(content):
                    text = _part_text(item)
                    if isinstance(text, str) and _SUMMARY_END_MARKER in text:
                        remainder = text.split(_SUMMARY_END_MARKER, 1)[1].lstrip()
                        legacy_blocks = [_with_part_text(item, remainder)] if remainder else []
                        legacy_blocks += [later.copy() if isinstance(later, dict) else later for later in content[index + 1:]]
                        return _unwrapped(legacy_blocks) if legacy_blocks else None
                return None
            for index, item in enumerate(prior_blocks):
                text = _part_text(item)
                if isinstance(text, str) and text.lstrip().startswith(_MERGED_PRIOR_CONTEXT_HEADER):
                    leading = text.lstrip()[len(_MERGED_PRIOR_CONTEXT_HEADER):].lstrip()
                    if leading:
                        prior_blocks[index] = _with_part_text(item, leading)
                    else:
                        prior_blocks.pop(index)
                    break
            return _unwrapped(prior_blocks) if prior_blocks else None
        return None

    @classmethod
    def _is_real_user_turn(cls, message: dict[str, Any]) -> bool:
        """Actionable user turn that is not synthetic scaffolding — the row test both index scans share.

        Weaker than ``agent.conversation_compression._is_real_user_message``, which also rejects
        metadata-flagged scaffolding this pair cannot see; use that one when the question is
        "is this a genuine inbound user message".
        """
        return cls._is_actionable_user_turn(message) and (not cls._is_synthetic_compression_user_turn(message))
    _COMPRESSION_NOTE = '[Note: Some earlier conversation turns have been compacted into a handoff summary to preserve context space. The current session state may still reflect earlier work, so build on that summary and state rather than re-doing work. Your persistent memory (MEMORY.md, USER.md) remains fully authoritative regardless of compaction.]'

def is_compaction_summary_message(message: Any) -> bool:
    """Return True when *message* is a context-compaction handoff summary.
    Public API. Uses the metadata key, falling back to content heuristics because the key is stripped by
    wire sanitizers and some session-store round-trips."""
    cls = ContextCompressor
    return cls._is_context_summary_message(message) if isinstance(message, dict) else cls._is_context_summary_content(message)
SUMMARY_CARRIER_DURABLE_DISPLAY_METADATA_KEYS = ('reactions',)

def _handoff_only_content(content: Any) -> Any:
    """Project summary-bearing content to the synthetic handoff alone; never keeps live media."""

    def _through_end_marker(text: str) -> str:
        marker_idx = text.find(_SUMMARY_END_MARKER)
        return text[:marker_idx + len(_SUMMARY_END_MARKER)] if marker_idx >= 0 else text
    if isinstance(content, str):
        if _MERGED_SUMMARY_DELIMITER in content:
            content = content.split(_MERGED_SUMMARY_DELIMITER, 1)[1].lstrip()
        return _through_end_marker(content)
    if not isinstance(content, list):
        return content
    for item in content:
        text = _part_text(item)
        if not isinstance(text, str) or _MERGED_SUMMARY_DELIMITER not in text:
            continue
        suffix = _through_end_marker(text.split(_MERGED_SUMMARY_DELIMITER, 1)[1].lstrip())
        return [_with_part_text(item, suffix)] if suffix else []
    projected: list[Any] = []
    for item in content:
        text = _part_text(item)
        if not isinstance(text, str):
            continue
        if _SUMMARY_END_MARKER in text:
            projected.append(_with_part_text(item, text.split(_SUMMARY_END_MARKER, 1)[0] + _SUMMARY_END_MARKER))
            return projected
        projected.append(item.copy() if isinstance(item, dict) else item)
    return projected

def split_user_originated_turn(message: Any) -> tuple[Optional[dict[str, Any]], Optional[dict[str, Any]]]:
    """Split a user row into ``(handoff_only, live_view)``; either may be None; fresh dicts."""
    if not isinstance(message, dict) or message.get('role') != 'user':
        return (None, None)
    is_summary = is_compaction_summary_message(message)
    handoff: Optional[dict[str, Any]] = None
    if is_summary:
        handoff = {'role': 'user', 'content': _handoff_only_content(message.get('content')), COMPRESSED_SUMMARY_METADATA_KEY: True, 'display_kind': 'hidden'}
        if COMPRESSED_SUMMARY_HAS_USER_TURN_KEY in message:
            handoff[COMPRESSED_SUMMARY_HAS_USER_TURN_KEY] = bool(message.get(COMPRESSED_SUMMARY_HAS_USER_TURN_KEY))
        if message.get(MICRO_COMPACT_MARKER_KEY):
            handoff[MICRO_COMPACT_MARKER_KEY] = True
        if message.get('timestamp') is not None:
            handoff['timestamp'] = message['timestamp']
        drop_stale_api_content(handoff)
        display_kind = message.get('display_kind')
        candidate = None if display_kind and display_kind != 'hidden' else ContextCompressor._strip_context_summary_handoff_message(message)
        if candidate is None:
            return (handoff, None)
    elif message.get('display_kind') and message.get('display_kind') != STEER_DISPLAY_KIND:
        return (None, None)
    else:
        candidate = message.copy()
    for key in (COMPRESSED_SUMMARY_METADATA_KEY, COMPRESSED_SUMMARY_HAS_USER_TURN_KEY, MICRO_COMPACT_MARKER_KEY, _DB_PERSISTED_MARKER, *(('_row_id',) if is_summary else ()), 'display_kind', 'display_metadata'):
        candidate.pop(key, None)
    carrier_metadata = message.get('display_metadata')
    if isinstance(carrier_metadata, dict):
        durable_metadata = {key: copy.deepcopy(carrier_metadata[key]) for key in SUMMARY_CARRIER_DURABLE_DISPLAY_METADATA_KEYS if key in carrier_metadata}
        if durable_metadata:
            candidate['display_metadata'] = durable_metadata
    drop_stale_api_content(candidate)
    cls = ContextCompressor
    if not cls._is_real_user_turn(candidate):
        return (handoff, None)
    return (handoff, candidate)
