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
        kind = "ci_failed" if conclusion != "success" else "ci_passed"
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
        return ("ci_passed" if conclusion == "success" else "ci_failed",
                f"GitHub check run {number} {conclusion} at {sha.lower()}")
    sha = data.get("after")
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
    return inbox.receive(
        project_id=project_id, source="github_webhook",
        source_id=event_type + ":" + delivery_id,
        thread="project:" + project_id, kind=kind,
        summary=summary, verified=True,
    )
