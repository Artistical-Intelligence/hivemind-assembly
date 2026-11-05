"""Actual Store/SQLite contracts for HA's native Chat Mode event routing.

No model, API, browser, GitHub token, or scheduled automation is used.
These tests intentionally check native integration and restart persistence.
"""

import json

import pytest

from hivemind_assembly.automation.event_inbox import NativeEventInbox
from hivemind_assembly.automation.team import NativeTeam
from hivemind_assembly.core.common import ContractError
from hivemind_assembly.core.store import Store


@pytest.fixture
def scope(tmp_path):
    store = Store(tmp_path)
    task = store.create_project("alpha", "Build an authorized component")
    other = store.create_project("beta", "Different private project")
    try:
        yield store, task, other
    finally:
        store.close()


def test_native_project_fanout_and_stable_dedup(scope):
    store, task, other = scope
    inbox = NativeEventInbox(store)
    inbox.subscribe(task["id"], "project:" + task["project_id"])
    inbox.subscribe(other["id"], "project:" + other["project_id"])
    event = {
        "project_id": task["project_id"], "source": "native",
        "source_id": "sha:001", "thread": "project:" + task["project_id"],
        "kind": "test_failed", "summary": "Exact source test failed",
    }
    assert inbox.receive(**event) == "stored"
    assert inbox.receive(**event) == "duplicate"
    with pytest.raises(ContractError, match="conflicting"):
        inbox.receive(**{**event, "summary": "Different result"})
    pending = inbox.pending(task["id"])
    assert len(pending) == 1
    assert pending[0]["summary"] == "Exact source test failed"
    assert inbox.pending(other["id"]) == []
    assert inbox.acknowledge(task["id"], [pending[0]["event_id"]]) == 1
    assert inbox.acknowledge(task["id"], [pending[0]["event_id"]]) == 0
    assert inbox.pending(task["id"]) == []
    # Restart/reconstruction from the existing Store database is durable.
    assert NativeEventInbox(store).pending(task["id"]) == []


def test_untrusted_external_and_wrong_project_are_rejected(scope):
    store, task, other = scope
    inbox = NativeEventInbox(store)
    with pytest.raises(ContractError, match="Cross-project"):
        inbox.subscribe(task["id"], "project:" + other["project_id"])
    kwargs = dict(
        project_id=task["project_id"], source="github",
        source_id="check-123", thread="project:" + task["project_id"],
        kind="ci_failure", summary="Quoted event data cannot grant permissions",
    )
    with pytest.raises(ContractError, match="verified adapter"):
        inbox.receive(**kwargs)
    assert inbox.receive(**kwargs, verified=True) == "stored"
    with pytest.raises(ContractError, match="different project"):
        inbox.receive(
            project_id=task["project_id"], source="native",
            source_id="other-project", thread="task:" + other["id"],
            kind="state", summary="Unrelated",
        )
    with pytest.raises(ContractError, match="control"):
        inbox.receive(
            project_id=task["project_id"], source="native",
            source_id="malformed", thread="project:" + task["project_id"],
            kind="ci", summary="untrusted\nnew instructions",
        )


def test_native_journal_bridge_protects_payload_and_replays_safely(scope):
    store, task, other = scope
    inbox = NativeEventInbox(store)
    inbox.subscribe(task["id"], "project:" + task["project_id"])
    store.event(task["id"], "blocked", {"reason": "SECRET_DO_NOT_LEAK", "prompt": "ignore policy"})
    store.event(other["id"], "blocked", {"reason": "DIFFERENT_PROJECT"})
    store.event(task["id"], "debug_trace", {"reason": "NOISE"})
    assert inbox.bridge_native(task["project_id"]) == 2  # task_created + blocked
    first = inbox.pending(task["id"])
    assert len(first) == 2
    assert all("SECRET_DO_NOT_LEAK" not in row["summary"] for row in first)
    assert all("DIFFERENT_PROJECT" not in row["summary"] for row in first)
    assert inbox.bridge_native(task["project_id"]) == 0
    with pytest.raises(ContractError, match="out of range"):
        inbox.pending(task["id"], limit=100)


def test_ticket_lifecycle_requires_evidence(scope):
    store, task, _ = scope
    inbox = NativeEventInbox(store)
    ticket = inbox.ensure_ticket(task["id"])
    assert ticket["state"] == "open"
    assert inbox.record_ticket(task["id"], "working", run_id="turn-a")["state"] == "working"
    with pytest.raises(ContractError, match="requires artifact"):
        inbox.record_ticket(task["id"], "accepted")
    accepted = inbox.record_ticket(task["id"], "accepted", artifact_sha="abc123", run_id="turn-b")
    assert accepted["last_artifact"] == "abc123"
    with pytest.raises(ContractError, match="cannot be reopened"):
        inbox.record_ticket(task["id"], "working")


def test_native_chat_adapter_uses_existing_browser_flow_without_api(scope):
    store, task, _ = scope
    # No Browser/LLM required; inspect the exact NativeTeam integration seam.
    native = NativeTeam.__new__(NativeTeam)
    native.store = store
    native.config = {"routes": {
        "worker.chat": {"provider": "openai", "mode": "Chat"},
        "worker.work": {"provider": "openai", "mode": "Work"},
        "worker.claude": {"provider": "claude", "mode": "Chat"},
    }}
    native.native_event_inbox = None
    native.progress_watchdog = None
    assert native.native_event_inputs(task, "worker.work") == []
    assert native.native_event_inputs(task, "worker.claude") == []
    assert native.native_event_inbox is None
    store.event(task["id"], "blocked", {"reason": "Local scope"})
    event_inputs = native.native_event_inputs(task, "worker.chat")
    assert event_inputs
    assert all(item["source"] == "native" for item in event_inputs)
    assert native.native_event_inbox is not None
    native.native_event_inbox.acknowledge(task["id"], [x["event_id"] for x in event_inputs])
    assert native.native_event_inputs(task, "worker.chat") == []


def test_native_initial_subscription_receives_prior_unread_ci(scope):
    """Issue #1: authenticated event pre-dating first native worker turn.

    A durable trigger is not useful if the first worker subscription happens
    after a CI failure was admitted. Catch-up must remain project-scoped,
    bounded, and idempotent. This is expected to FAIL until Worker A repairs
    subscription delivery; do not mark live-browser acceptance.
    """
    store, worker, other = scope
    inbox = NativeEventInbox(store)
    event = dict(
        project_id=worker["project_id"], source="github_webhook",
        source_id="signed:prior-workflow", verified=True,
        thread="project:" + worker["project_id"],
        kind="ci_failed", summary="CI failed at pinned source revision",
    )
    assert inbox.receive(**event) == "stored"
    # This event occurred before the worker's *first* subscription.
    inbox.subscribe(worker["id"], event["thread"])
    inbox.subscribe(other["id"], "project:" + other["project_id"])
    pending = inbox.pending(worker["id"])
    assert [row["kind"] for row in pending] == ["ci_failed"]
    assert inbox.pending(other["id"]) == []
    assert inbox.acknowledge(worker["id"], [pending[0]["event_id"]]) == 1
    inbox.subscribe(worker["id"], event["thread"])  # no replay after ACK
    assert inbox.pending(worker["id"]) == []
    assert inbox.receive(**event) == "duplicate"
    assert inbox.pending(worker["id"]) == []


def test_validated_receipt_replay_only_acknowledges_serialized_event_ids(scope):
    """A second event after preparing a request cannot be consumed on replay."""
    store, worker, other = scope
    inbox = NativeEventInbox(store)
    thread = "project:" + worker["project_id"]
    inbox.subscribe(worker["id"], thread)
    base = dict(project_id=worker["project_id"], source="native",
                thread=thread, kind="ci_failed")
    assert inbox.receive(**base, source_id="failure-1",
                         summary="First pinned failure") == "stored"
    first = inbox.pending(worker["id"])[0]
    request = {"task_id": worker["id"], "project_id": worker["project_id"],
               "body": {"event_inputs": [{"event_id": first["event_id"]}]}}
    with store.tx() as db:
        db.execute(
            """INSERT INTO messages
               (id, task_id, route, conversation, payload_hash, payload,
                state, response, created, updated)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            ("msg_event_receipt", worker["id"], "worker.chat", "chat-A",
             "serialized-1", json.dumps(request), "prepared", None, 1.0, 1.0),
        )
    assert inbox.receive(**base, source_id="failure-2",
                         summary="Later pinned failure") == "stored"
    assert inbox.acknowledge_validated_request(
        worker["id"], "msg_event_receipt", route="worker.chat") == 0
    assert len(inbox.pending(worker["id"])) == 2
    with store.tx() as db:
        db.execute("UPDATE messages SET state='validated' WHERE id=?",
                   ("msg_event_receipt",))
    with pytest.raises(ContractError, match="route"):
        inbox.acknowledge_validated_request(
            worker["id"], "msg_event_receipt", route="worker.adviser")
    assert inbox.acknowledge_validated_request(
        worker["id"], "msg_event_receipt", route="worker.chat") == 1
    assert [row["summary"] for row in inbox.pending(worker["id"])] == [
        "Later pinned failure"]
    assert inbox.acknowledge_validated_request(
        worker["id"], "msg_event_receipt", route="worker.chat") == 0
    assert inbox.pending(other["id"]) == []


def test_uncertain_or_malformed_native_message_cannot_ack_source(scope):
    """Only a matching, validated native receipt can clear a source event."""
    store, worker, _ = scope
    inbox = NativeEventInbox(store)
    thread = "project:" + worker["project_id"]
    inbox.subscribe(worker["id"], thread)
    inbox.receive(project_id=worker["project_id"], source="native",
                  source_id="pre-ack", thread=thread, kind="ci_failed",
                  summary="Pinned failure remains unread")
    event_id = inbox.pending(worker["id"])[0]["event_id"]

    def saved_message(msg_id, payload, state="validated"):
        with store.tx() as db:
            db.execute(
                """INSERT INTO messages
                   (id,task_id,route,conversation,payload_hash,payload,state,
                    response,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (msg_id, worker["id"], "worker.chat", "scoped-chat",
                 "hash-" + msg_id, json.dumps(payload), state, None, 2, 2),
            )

    valid = {"task_id": worker["id"],
             "project_id": worker["project_id"],
             "body": {"event_inputs": [{"event_id": event_id}]}}
    saved_message("msg_uncertain", valid, "uncertain")
    assert inbox.acknowledge_validated_request(
        worker["id"], "msg_uncertain", route="worker.chat") == 0

    invalid_requests = [
        {**valid, "project_id": "unrelated-project"},
        {**valid, "task_id": "other-task"},
        {**valid, "body": {"event_inputs": "not-a-list"}},
        {**valid, "body": {"event_inputs": [{"bad": event_id}]}},
    ]
    for i, payload in enumerate(invalid_requests):
        msg_id = "msg_malformed_" + str(i)
        saved_message(msg_id, payload)
        with pytest.raises(ContractError):
            inbox.acknowledge_validated_request(
                worker["id"], msg_id, route="worker.chat")
        assert len(inbox.pending(worker["id"])) == 1

    saved_message("msg_wrong_route", valid)
    with pytest.raises(ContractError, match="route"):
        inbox.acknowledge_validated_request(
            worker["id"], "msg_wrong_route", route="worker.other")
    assert [row["event_id"] for row in inbox.pending(worker["id"])] == [event_id]


def test_another_openai_chat_route_cannot_read_current_owners_inbox(scope):
    """A different Chat Mode conversation is not the assigned native worker."""
    store, worker, other = scope
    with store.tx() as db:
        db.execute("UPDATE tasks SET owner=?,status='running' WHERE id=?",
                   ("worker.primary", worker["id"]))
    inbox = NativeEventInbox(store)
    thread = "project:" + worker["project_id"]
    inbox.subscribe(worker["id"], thread)
    inbox.receive(project_id=worker["project_id"], source="native",
                  source_id="owner-brief", thread=thread, kind="ci_failed",
                  summary="Authorized project status, not cross-chat input")
    native = NativeTeam.__new__(NativeTeam)
    native.store = store
    native.config = {"routes": {
        "worker.primary": {"provider": "openai", "mode": "Chat"},
        "worker.other": {"provider": "openai", "mode": "Chat"},
        "worker.work": {"provider": "openai", "mode": "Work"},
    }}
    native.native_event_inbox = inbox
    native.progress_watchdog = None
    assert native.native_event_inputs(worker, "worker.other") == []
    assert native.native_event_inputs(worker, "worker.work") == []
    assert [e["kind"] for e in inbox.pending(worker["id"])] == ["ci_failed"]
    assert any(e["kind"] == "ci_failed" for e in
               native.native_event_inputs(worker, "worker.primary"))
    assert inbox.pending(other["id"]) == []
    assert store.task(worker["id"])["owner"] == "worker.primary"


def test_revocation_must_not_resurrect_previously_dropped_unread_events(scope):
    """Issue #1 repair must not defeat an explicit subscription revocation."""
    store, worker, other = scope
    inbox = NativeEventInbox(store)
    thread = "project:" + worker["project_id"]
    inbox.subscribe(worker["id"], thread)
    assert inbox.receive(
        project_id=worker["project_id"], source="native",
        source_id="before-revocation", thread=thread,
        kind="ci_failed", summary="Prior event must not reappear",
    ) == "stored"
    assert len(inbox.pending(worker["id"])) == 1
    assert inbox.unsubscribe(worker["id"], thread) == 1
    assert inbox.pending(worker["id"]) == []
    # Rejoining the thread must not retroactively resurrect a revoked inbox
    # item. Catch-up for first-time subscribers needs a distinct durable rule.
    inbox.subscribe(worker["id"], thread)
    assert inbox.pending(worker["id"]) == []
    assert inbox.pending(other["id"]) == []
