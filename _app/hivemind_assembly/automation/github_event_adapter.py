"""Verified, no-network GitHub event adapter for HA's native event inbox.

DeepSeek Super-agent's Source -> Trigger -> Thread idea is translated into
a small Python envelope adapter. Grok Bot's event-triggered routine model
informs routing completed CI to an existing project ticket.

NO GitHub API request, model API, webhook listener, or background service
is created here. An existing authenticated host must supply the webhook
bytes and configured secret. Text from the remote payload is never an
instruction, tool permission, or a new task authorization.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re

from hivemind_assembly.core.common import ContractError
from .event_inbox import NativeEventInbox, _bounded


_MAX_PAYLOAD_BYTES = 128 * 1024
_MAX_RUN_ID = (1 << 63) - 1


def _is_sha(value):
    return (isinstance(value, str) and
            re.fullmatch(r"[0-9a-fA-F]{40}", value) is not None)


def _checked_push(data):
    """Require the actual GitHub push identity, not forged partial metadata.

    Newly-created branches legitimately have a zero-valued *before* SHA.
    Deleted branches have a zero-valued *after* SHA and are filtered.
    """
    for flag in ("created", "deleted", "forced"):
        if flag in data and type(data[flag]) is not bool:
            raise ContractError("Malformed GitHub push " + flag + " flag")
    # GitHub represents a newly created ref with a zero before SHA and a
    # deleted ref with a zero after SHA. Reject contradictory signed control
    # flags instead of silently treating a malformed deletion as harmless.
    zero = "0" * 40
    if data.get("created") is True and (
        data.get("deleted") is True or data.get("before") != zero
    ):
        raise ContractError("Contradictory GitHub push creation metadata")
    if data.get("deleted") is True and data.get("after") != zero:
        raise ContractError("Contradictory GitHub push deletion metadata")
    if data.get("deleted") is True or data.get("after") == zero:
        return None
    ref = data.get("ref")
    before, after = data.get("before"), data.get("after")
    if (not isinstance(ref, str) or not 1 <= len(ref) <= 320
            or "\x00" in ref or "\n" in ref or "\r" in ref
            or not (ref.startswith("refs/heads/") and len(ref) > 11
                    or ref.startswith("refs/tags/") and len(ref) > 10)):
        raise ContractError("Malformed GitHub push reference")
    if not _is_sha(before) or not _is_sha(after):
        raise ContractError("Malformed GitHub push revision")
    return ref, before.lower(), after.lower()

_ALLOWED = frozenset({"workflow_run", "check_run", "push"})

_CI_FAILURE_CONCLUSIONS = frozenset({
    "failure", "timed_out", "action_required", "startup_failure",
})


def _ci_kind(conclusion: str) -> str:
    """Never mislabel cancelled/skipped/neutral CI as a test failure.

    An inconclusive check is still relevant evidence, but an HA worker must
    not treat it as failing acceptance or as permission to rerun a workflow.
    """
    if conclusion == "success":
        return "ci_passed"
    if conclusion in _CI_FAILURE_CONCLUSIONS:
        return "ci_failed"
    return "ci_inconclusive"



def _digest_from_payload(event_type: str, data: dict) -> tuple[str, str] | None:
    """Produce bounded metadata-only summaries; discard remote free text."""
    if event_type == "workflow_run":
        run = data.get("workflow_run")
        if not isinstance(run, dict):
            raise ContractError("Missing workflow run object")
        if run.get("status") != "completed":
            return None
        conclusion = run.get("conclusion")
        # An authenticated but malformed JSON payload can contain lists or
        # objects here. Reject deliberately, not via unhashable-type crash.
        if conclusion is not None and not isinstance(conclusion, str):
            raise ContractError("Malformed workflow conclusion")
        if conclusion not in {"success", "failure", "cancelled", "timed_out",
                              "action_required", "skipped", "neutral",
                              "startup_failure"}:
            return None
        sha = run.get("head_sha")
        if not _is_sha(sha):
            raise ContractError("Malformed workflow revision")
        number = run.get("id")
        if type(number) is not int or not 1 <= number <= _MAX_RUN_ID:
            raise ContractError("Malformed workflow run ID")
        kind = _ci_kind(conclusion)
        return kind, f"GitHub workflow run {number} {conclusion} at {sha.lower()}"
    if event_type == "check_run":
        run = data.get("check_run")
        if not isinstance(run, dict):
            raise ContractError("Missing check run object")
        if run.get("status") != "completed":
            return None
        conclusion = run.get("conclusion")
        if not isinstance(conclusion, str) or conclusion not in {
            "success", "failure", "cancelled", "timed_out", "action_required",
            "neutral", "skipped", "stale", "startup_failure",
        }:
            return None
        sha = run.get("head_sha")
        if not _is_sha(sha):
            raise ContractError("Malformed check-run revision")
        number = run.get("id")
        if type(number) is not int or not 1 <= number <= _MAX_RUN_ID:
            raise ContractError("Malformed check-run ID")
        return (_ci_kind(conclusion),
                f"GitHub check run {number} {conclusion} at {sha.lower()}")
    # Validate the full source identity even though only the SHA enters the
    # prompt. Incomplete push envelopes must not manufacture a source change.
    push = _checked_push(data)
    if push is None:
        return None
    return "source_changed", f"GitHub push source revision {push[2]}"


def _semantic_event_key(event_type: str, data: dict, repository: str) -> str:
    """Deduplicate the same signed GitHub fact across transport retries.

    GitHub delivery IDs are unsigned. The body can also be redelivered with
    harmless JSON formatting or unrelated run metadata changed. Independent
    attempts and changed CI conclusions retain distinct receipt identities.
    """
    if event_type in ("workflow_run", "check_run"):
        run = data[event_type]
        attempt = run.get("run_attempt", 1) if event_type == "workflow_run" else 1
        # The run attempt participates in a durable event identity. Keep it
        # within GitHub's bounded integer domain rather than allowing an
        # unbounded signed JSON integer to consume storage/CPU on replay.
        if type(attempt) is not int or not 1 <= attempt <= _MAX_RUN_ID:
            raise ContractError("Malformed GitHub run attempt")
        identity = (repository, event_type, run["id"], attempt,
                    run["head_sha"].lower(), run["conclusion"])
    else:
        ref, before, after = _checked_push(data)
        identity = (repository, event_type, ref, before, after)
    normalized = json.dumps(identity, separators=(",", ":"), ensure_ascii=True)
    return "signed:" + hashlib.sha256(normalized.encode("ascii")).hexdigest()


def admit_signed_github_event(inbox: NativeEventInbox, *, project_id: str,
                              repository: str, event_type: str,
                              delivery_id: str, payload: bytes,
                              signature: str, secret: bytes) -> str:
    """Verify GitHub's HMAC and exact repository before local event intake.

    The caller is responsible for binding a trusted inbound transport
    and retrieving `secret` from approved private configuration. This
    function does not use a network client or expose an HTTP endpoint.
    """
    _bounded(repository, "repository", 200)
    _bounded(event_type, "event type", 60)
    _bounded(delivery_id, "delivery ID", 128)
    if event_type not in _ALLOWED:
        return "filtered"
    if not isinstance(payload, bytes) or len(payload) > _MAX_PAYLOAD_BYTES:
        raise ContractError("Unbounded or non-byte webhook payload")
    if not isinstance(secret, bytes) or not secret:
        raise ContractError("Missing privately configured signing secret")
    # The signature is a transport header, not signed payload data. Check its
    # exact canonical ASCII syntax before compare_digest: non-ASCII header
    # strings otherwise raise TypeError instead of a controlled refusal, and
    # arbitrary-length strings needlessly reach the comparison boundary.
    if not isinstance(signature, str) or not re.fullmatch(
        r"sha256=[0-9a-f]{64}", signature
    ):
        raise ContractError("Missing or malformed signed webhook digest")
    expected = "sha256=" + hmac.new(secret, payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise ContractError("Webhook signature verification failed")
    # GitHub emits strict JSON. Duplicate object names and non-JSON numeric
    # constants would make a signed body's effective repository/run identity
    # depend on parser-specific last-key-wins behavior. Reject ambiguity at
    # admission rather than binding a webhook to an arbitrary interpretation.
    def unique_object(pairs):
        parsed = {}
        for key, value in pairs:
            if key in parsed:
                raise ContractError("Duplicate key in signed webhook JSON")
            parsed[key] = value
        return parsed

    def reject_constant(value):
        raise ContractError("Non-JSON numeric constant in signed webhook")

    try:
        data = json.loads(payload, object_pairs_hook=unique_object,
                          parse_constant=reject_constant)
    except (ValueError, UnicodeDecodeError, RecursionError) as error:
        raise ContractError("Malformed signed webhook JSON") from error
    if not isinstance(data, dict) or not isinstance(data.get("repository"), dict):
        raise ContractError("Missing webhook repository")
    if data["repository"].get("full_name") != repository:
        raise ContractError("Webhook repository does not match granted scope")
    result = _digest_from_payload(event_type, data)
    if result is None:
        return "filtered"
    kind, summary = result
    # The configured project/repository is an authorization from the host;
    # the signed payload's comment/body/commit messages are never forwarded.
    # The trusted host authenticates transport/event-type binding. The
    # validated semantic identity, rather than redelivery headers or JSON
    # byte formatting, gives the inbox a stable replay-protection key.
    stable_id = _semantic_event_key(event_type, data, repository)
    return inbox.receive(
        project_id=project_id, source="github_webhook",
        source_id=stable_id,
        thread="project:" + project_id, kind=kind,
        summary=summary, verified=True,
    )
