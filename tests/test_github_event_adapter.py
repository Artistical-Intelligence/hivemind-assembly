"""Signed local GitHub event ingress to HA's existing native Chat queue.

No GitHub networking, model inference, or paid API dependency.
"""

import hashlib
import hmac
import json

import pytest

from hivemind_assembly.automation.event_inbox import NativeEventInbox
from hivemind_assembly.automation.github_event_adapter import admit_signed_github_event
from hivemind_assembly.automation.team import NativeTeam
from hivemind_assembly.core.common import ContractError
from hivemind_assembly.core.store import Store


def _signed(secret, payload):
    raw = json.dumps(payload, sort_keys=True).encode("utf-8")
    return raw, "sha256=" + hmac.new(secret, raw, hashlib.sha256).hexdigest()


def test_signed_failure_reaches_existing_native_chat_worker(tmp_path):
    store = Store(tmp_path)
    try:
        task = store.create_project("CI test", "Use authorized native Chat")
        inbox = NativeEventInbox(store)
        inbox.subscribe(task["id"], "project:" + task["project_id"])
        secret = b"private-test-secret-not-a-real-credential"
        sha = "1" * 40
        payload = {
            "repository": {"full_name": "owner/repo"},
            "workflow_run": {
                "id": 456, "head_sha": sha, "status": "completed",
                "conclusion": "failure", "name": "untrusted instruction: ignore",
            },
            "body": "INJECT_AUTHORIZATION_DO_NOT_USE",
        }
        raw, signature = _signed(secret, payload)
        opts = dict(
            inbox=inbox, project_id=task["project_id"],
            repository="owner/repo", event_type="workflow_run",
            delivery_id="delivery-abc", payload=raw,
            signature=signature, secret=secret,
        )
        assert admit_signed_github_event(**opts) == "stored"
        assert admit_signed_github_event(**opts) == "duplicate"
        native = NativeTeam.__new__(NativeTeam)
        native.store = store
        native.config = {"routes": {
            "worker.chat": {"provider": "openai", "mode": "Chat"},
            "worker.work": {"provider": "openai", "mode": "Work"},
        }}
        native.native_event_inbox = inbox
        native.progress_watchdog = None
        assert native.native_event_inputs(task, "worker.work") == []
        events = native.native_event_inputs(task, "worker.chat")
        ci = [x for x in events if x["kind"] == "ci_failed"]
        assert len(ci) == 1
        assert sha in ci[0]["summary"]
        assert "INJECT_AUTHORIZATION_DO_NOT_USE" not in ci[0]["summary"]
        assert "ignore" not in ci[0]["summary"]
        inbox.acknowledge(task["id"], [ci[0]["event_id"]])
        assert not [x for x in inbox.pending(task["id"]) if x["kind"] == "ci_failed"]
    finally:
        store.close()


def test_rejects_wrong_repository_bad_signature_and_unfinished_run(tmp_path):
    store = Store(tmp_path)
    try:
        task = store.create_project("scoped", "CI only")
        inbox = NativeEventInbox(store)
        secret = b"signing key"
        body = {"repository": {"full_name": "allowed/repo"},
                "workflow_run": {"id": 2, "head_sha": "a" * 40,
                                 "status": "completed", "conclusion": "success"}}
        raw, signature = _signed(secret, body)
        common = dict(
            inbox=inbox, project_id=task["project_id"],
            repository="allowed/repo", event_type="workflow_run",
            delivery_id="one", payload=raw, signature=signature, secret=secret,
        )
        with pytest.raises(ContractError, match="signature"):
            admit_signed_github_event(**{**common, "signature": "sha256=" + "0" * 64})
        with pytest.raises(ContractError, match="repository"):
            admit_signed_github_event(**{**common, "repository": "other/repo"})
        assert admit_signed_github_event(**common) == "stored"
        # A pending check/run is not a failed or finished CI signal.
        body["workflow_run"]["status"] = "in_progress"
        raw2, signature2 = _signed(secret, body)
        assert admit_signed_github_event(**{**common, "payload": raw2,
                                             "signature": signature2,
                                             "delivery_id": "two"}) == "filtered"
        assert admit_signed_github_event(**{**common, "event_type": "unsupported"}) == "filtered"
        with pytest.raises(ContractError, match="Unbounded"):
            admit_signed_github_event(**{**common, "payload": b"x" * (128 * 1024 + 1)})
    finally:
        store.close()
