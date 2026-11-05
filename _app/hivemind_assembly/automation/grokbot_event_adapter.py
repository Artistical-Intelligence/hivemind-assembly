"""Local Grok Bot integration-kit event admission (no webhook/network client).

Grounded in the MIT licensed rodrigo-pasini/grokbot-kit 0.6.0
src/grokbot_kit/payload.py and docs/event.md: terminal completed/error/
timeout events, needs_input as a separate nonterminal event, task-scoped
delivery to the correct delegating routine, and distinct dedupe IDs.

Only already-authorized HA work tickets and authenticated host events may
enter. This adapter does not run the Grokbot CLI, OAuth, Claude Code,
Codex, opencode, a model API, or an external webhook.
"""

from __future__ import annotations

from hivemind_assembly.core.common import ContractError
from .event_inbox import NativeEventInbox, _bounded


_STATUS = {
    "completed": frozenset({"ok", "denied"}),
    "error": frozenset({"failed", "interrupted"}),
    "timeout": frozenset({"timeout"}),
    "needs_input": frozenset({"permission", "question"}),
}


def admit_grokbot_event(
    inbox: NativeEventInbox,
    *,
    task_id: str,
    target: str,
    event: dict,
    delivery_id: str,
    verified: bool = False,
) -> str:
    """Bridge an authenticated event to exactly its delegated HA task.

    A trusted local host must verify the originating route and permissions,
    including the target mapping, BEFORE passing verified=True. Never use
    untrusted `event["target"]` as an authorization. The raw summary,
    resume_hint, paths, models, prompts and plugin result are discarded.
    """
    if not verified:
        raise ContractError("Grok Bot event needs an authenticated adapter")
    _bounded(task_id, "task id", 128)
    _bounded(target, "target", 128)
    _bounded(delivery_id, "delivery id", 128)
    if not isinstance(event, dict) or event.get("schema") != "grokbot-kit.event/v1":
        raise ContractError("Unknown Grok Bot event schema")
    if event.get("target") != target:
        raise ContractError("Grok Bot event target does not match authorized route")
    kind = event.get("event")
    status = event.get("status")
    if kind not in _STATUS or status not in _STATUS[kind]:
        raise ContractError("Unsupported Grok Bot event/status combination")
    external_id = event.get("task_id")
    _bounded(external_id, "external task id", 128)
    task = inbox.store.task(task_id)
    # Trigger is directed to the existing delegated work ticket, not every
    # subscribed project worker. It never creates or reassigns tasks.
    inbox.ensure_ticket(task_id)
    inbox.subscribe(task_id, "task:" + task_id)
    mapped = {
        "completed": ("delegated_completed", "completed " + status),
        "error": ("delegated_failed", "error " + status),
        "timeout": ("delegated_timeout", "timeout"),
        "needs_input": ("delegated_needs_input", "needs input " + status),
    }
    native_kind, outcome = mapped[kind]
    return inbox.receive(
        project_id=task["project_id"],
        source="grokbot_kit",
        source_id=target + ":" + external_id + ":" + delivery_id,
        thread="task:" + task_id,
        kind=native_kind,
        summary="Delegated tool " + outcome + " for " + external_id,
        verified=True,
    )
