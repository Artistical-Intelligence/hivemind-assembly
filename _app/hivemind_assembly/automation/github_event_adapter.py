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

from hivemind_assembly.core.common import ContractError
from .event_inbox import NativeEventInbox, _bounded


_MAX_PAYLOAD_BYTES = 128 * 1024
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
        if conclusion not in {"success", "failure", "cancelled", "timed_out",
                              "action_required", "skipped", "neutral"}:
            return None
        sha = run.get("head_sha")
        if not isinstance(sha, str) or len(sha) != 40 or not all(
            ch in "0123456789abcdefABCDEF" for ch in sha
        ):
            raise ContractError("Malformed workflow revision")
        number = run.get("id")
        if not isinstance(number, int) or isinstance(number, bool) or number < 1:
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
        if not isinstance(sha, str) or len(sha) != 40 or not all(
            ch in "0123456789abcdefABCDEF" for ch in sha
        ):
            raise ContractError("Malformed check-run revision")
        number = run.get("id")
        if not isinstance(number, int) or isinstance(number, bool) or number < 1:
            raise ContractError("Malformed check-run ID")
        return (_ci_kind(conclusion),
                f"GitHub check run {number} {conclusion} at {sha.lower()}")
    # GitHub uses forty zeroes for a deleted ref; this is not a source SHA
    # and must not be routed to workers as a valid checkout target.
    if data.get("deleted") is True:
        return None
    sha = data.get("after")
    if sha == "0" * 40:
        return None
    if not isinstance(sha, str) or len(sha) != 40 or not all(
        ch in "0123456789abcdefABCDEF" for ch in sha
    ):
        raise ContractError("Malformed pushed source revision")
    return "source_changed", f"GitHub push source revision {sha.lower()}"


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
    if not isinstance(signature, str) or not signature.startswith("sha256="):
        raise ContractError("Missing signed webhook digest")
    expected = "sha256=" + hmac.new(secret, payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise ContractError("Webhook signature verification failed")
    try:
        data = json.loads(payload)
    except (ValueError, UnicodeDecodeError) as error:
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
    # GitHub signs the *body*, not the X-GitHub-Delivery header. A captured
    # authentic body can be replayed with a new delivery-id header by an
    # intermediary that does not know the secret. Never use that changeable
    # header alone as an idempotency key: bind the event key to the verified
    # bytes and event type instead. The bounded delivery ID remains validated
    # above, but is not trusted as event identity.
    stable_id = hashlib.sha256(event_type.encode("ascii") + b"\0" + payload).hexdigest()
    return inbox.receive(
        project_id=project_id, source="github_webhook",
        source_id="signed:" + stable_id,
        thread="project:" + project_id, kind=kind,
        summary=summary, verified=True,
    )
