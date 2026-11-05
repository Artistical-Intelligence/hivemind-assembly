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

import re

from hivemind_assembly.core.common import ContractError, digest
from .event_inbox import NativeEventInbox, _bounded


_STATUS = {
    "completed": frozenset({"ok", "denied"}),
    "error": frozenset({"failed", "interrupted"}),
    "timeout": frozenset({"timeout"}),
    "needs_input": frozenset({"permission", "question"}),
}

# Upstream grokbot-kit docs/event.md and terminal.py: each completed or
# failed event carries a reason with narrowly defined status combinations.
# Old local fixtures may omit it, but a provided contradictory reason must
# never silently become a trusted ticket outcome.
_EXIT_REASONS = {
    ("completed", "ok"): frozenset({"success"}),
    ("completed", "denied"): frozenset({"permission_denied"}),
    ("error", "failed"): frozenset({
        "agent_error", "nonzero_exit", "result_invalid",
    }),
    ("error", "interrupted"): frozenset({"interrupted"}),
    ("timeout", "timeout"): frozenset({"timeout"}),
    ("needs_input", "permission"): frozenset({"needs_input"}),
    ("needs_input", "question"): frozenset({"needs_input"}),
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
    if "exit_reason" in event and event["exit_reason"] not in _EXIT_REASONS[(kind, status)]:
        raise ContractError("Grok Bot event has an inconsistent exit reason")
    needs_input = event.get("needs_input")
    if kind == "needs_input" and isinstance(needs_input, dict):
        if "kind" in needs_input and needs_input["kind"] != status:
            raise ContractError("Grok Bot needs-input reason does not match status")
    external_id = event.get("task_id")
    _bounded(external_id, "external task id", 128)
    # The external task ID appears in the native summary. Constrain it to an
    # opaque identifier: unlike an arbitrary signed CLI result, it must never
    # become an instruction-bearing text channel.
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", external_id):
        raise ContractError("Invalid external Grok Bot task identifier")
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
    if kind == "completed" and status == "denied":
        # A terminal permission denial is NOT a successful completion.
        native_kind = "delegated_denied"
    return inbox.receive(
        project_id=task["project_id"],
        source="grokbot_kit",
        # Canonical tuple hashing avoids delimiter collisions across targets
        # and external IDs. Dedupe still requires one exact authenticated
        # event and never creates a worker or changes its permissions.
        source_id=digest({
            "target": target, "external_task_id": external_id,
            "delivery_id": delivery_id,
        }),
        thread="task:" + task_id,
        kind=native_kind,
        summary="Delegated tool " + outcome + " for " + external_id,
        verified=True,
    )
