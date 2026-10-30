# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
from __future__ import annotations
_LENGTH_CONTINUATION_NETWORK_STUB = '[System: The previous response was cut off by a network error mid-stream — a transport interruption, NOT a change in your capabilities. Your tools are still fully available; call them as normal and ignore any earlier claim that you lack tool access. Continue the task from where you left off. Do not restart or repeat prior text.]'
_LENGTH_CONTINUATION_OUTPUT_LIMIT = '[System: Your previous response was truncated by the output length limit. Continue exactly where you left off. Do not restart or repeat prior text. Finish the answer directly.]'
_LEGACY_LENGTH_CONTINUATION_NETWORK_STUB = '[System: The previous response was cut off by a network error mid-stream. Continue exactly where you left off. Do not restart or repeat prior text. Finish the answer directly.]'
_LENGTH_CONTINUATION_DROPPED_TOOLS_PREFIX = '[System: Your previous tool call '
_CODEX_INCOMPLETE_NUDGE = '[System: Your previous response contained only internal reasoning and never produced a visible answer or tool call. Do not keep thinking. Produce your final answer as plain text now (or make the tool call you were planning).]'
_CODEX_ACK_CONTINUATION_NUDGE = '[System: Continue now. Execute the required tool calls and only send your final answer after completing the task.]'
_DEGENERATE_FINAL_NUDGE = '[System: Your previous message ended the turn with a fragment that is not a usable answer. If the task is unfinished, continue it and then give the complete answer. If that fragment WAS your complete answer, send it again exactly as before.]'
_DROPPED_TOOLCALL_NUDGE_CONTENT = 'Your previous turn indicated a tool call but none was included. Do not narrate a plan or restate intent — issue the actual tool call now to continue the task.'
_EMPTY_TOOL_RESPONSE_NUDGE = 'You just executed tool calls but returned an empty response. Please process the tool results above and continue with the task.'
