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


def test_first_subscription_backfill_is_bounded_resumable_and_ordered(scope):
    """A delayed subscriber catches >20 durable events without replay or reordering.

    Synthetic SQLite only. In particular, a newer event arriving while the
    initial historical cursor is still being consumed must remain last.
    """
    store, worker, other = scope
    inbox = NativeEventInbox(store)
    thread = "project:" + worker["project_id"]
    for number in range(37):
        assert inbox.receive(
            project_id=worker["project_id"], source="native",
            source_id=f"before-{number:02d}", thread=thread,
            kind="ci_failed", summary=f"Pinned failure {number:02d}",
        ) == "stored"
    inbox.subscribe(worker["id"], thread)
    inbox.subscribe(other["id"], "project:" + other["project_id"])
    assert inbox.receive(
        project_id=worker["project_id"], source="native",
        source_id="after-37", thread=thread, kind="ci_passed",
        summary="Newer source evidence",
    ) == "stored"
    seen = []
    while True:
        # Reconstructing the inbox after each bounded batch models restart.
        pending = NativeEventInbox(store).pending(worker["id"], limit=6)
        if not pending:
            break
        assert len(pending) <= 6
        seen.extend(item["source_id"] for item in pending)
        assert inbox.acknowledge(
            worker["id"], [item["event_id"] for item in pending]
        ) == len(pending)
        assert len(seen) <= 38
    assert seen == [f"before-{i:02d}" for i in range(37)] + ["after-37"]
    assert inbox.pending(other["id"]) == []
    inbox.subscribe(worker["id"], thread)
    assert inbox.pending(worker["id"]) == []


def test_revoked_subscription_cancels_unloaded_historical_pages(scope):
    """Revocation defeats both already loaded and not-yet-loaded catch-up."""
    store, worker, other = scope
    inbox = NativeEventInbox(store)
    thread = "project:" + worker["project_id"]
    for number in range(45):
        inbox.receive(
            project_id=worker["project_id"], source="native",
            source_id=f"old-{number:02d}", thread=thread,
            kind="ci_failed", summary="Historical event",
        )
    inbox.subscribe(worker["id"], thread)
    assert inbox.pending(worker["id"], limit=6)
    # The first subscription has only filled its first 20 historical rows.
    assert inbox.unsubscribe(worker["id"], thread) > 0
    inbox.receive(
        project_id=worker["project_id"], source="native",
        source_id="during-revocation", thread=thread,
        kind="ci_failed", summary="Should not backfill after rejoin",
    )
    inbox.subscribe(worker["id"], thread)
    assert NativeEventInbox(store).pending(worker["id"], limit=20) == []
    inbox.receive(
        project_id=worker["project_id"], source="native",
        source_id="after-rejoin", thread=thread,
        kind="ci_passed", summary="Only future event",
    )
    assert [row["source_id"] for row in inbox.pending(worker["id"])] == [
        "after-rejoin"
    ]
    assert inbox.pending(other["id"]) == []


def test_partial_modern_validated_event_envelope_must_not_ack(scope):
    """Regression: a partial modern envelope must not masquerade as legacy.

    Legacy messages contain only event_id. Newer messages that add *any*
    immutable source metadata must bind all source fields, not merely a
    conveniently truthful subset. This is an expected failing security
    regression until Worker A tightens the validated-receipt boundary.
    """
    store, worker, _ = scope
    inbox = NativeEventInbox(store)
    thread = "project:" + worker["project_id"]
    inbox.subscribe(worker["id"], thread)
    inbox.receive(
        project_id=worker["project_id"], source="native",
        source_id="scope-proof", thread=thread,
        kind="ci_failed", summary="Authorized immutable event",
    )
    item = inbox.pending(worker["id"])[0]
    forged_partial = {
        "task_id": worker["id"], "project_id": worker["project_id"],
        "body": {"event_inputs": [
            {"event_id": item["event_id"], "summary": item["summary"]}
        ]},
    }
    with store.tx() as db:
        db.execute(
            """INSERT INTO messages
               (id,task_id,route,conversation,payload_hash,payload,state,
                response,created,updated) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            ("partial_modern_envelope", worker["id"], "worker.chat",
             "chat-A", "partial-hash", json.dumps(forged_partial),
             "validated", '{"type":"step_intent"}', 1.0, 1.0),
        )
    with pytest.raises(ContractError, match="envelope|Malformed|source"):
        inbox.acknowledge_validated_request(
            worker["id"], "partial_modern_envelope", route="worker.chat"
        )
    assert [row["event_id"] for row in inbox.pending(worker["id"])] == [
        item["event_id"]
    ]


def test_stale_prior_chat_owner_receipt_cannot_consume_transferred_event(scope):
    """A validated old-chat receipt cannot ACK the new owner's unread work.

    This targets the legacy acknowledgment seam independently of the newer
    durable-effect generation fence. No browser or external API is involved.
    The event remains project-scoped, but ownership of its receipt changed.
    """
    store, worker, _ = scope
    inbox = NativeEventInbox(store)
    with store.tx() as db:
        db.execute(
            "UPDATE tasks SET owner=?,epoch=?,status='running' WHERE id=?",
            ("worker.first", 1, worker["id"]),
        )
    thread = "project:" + worker["project_id"]
    inbox.subscribe(worker["id"], thread)
    assert inbox.receive(
        project_id=worker["project_id"], source="native",
        source_id="owner-epoch-fence", thread=thread,
        kind="ci_failed", summary="Unacknowledged assignment evidence",
    ) == "stored"
    event = inbox.pending(worker["id"])[0]
    packet = {
        "task_id": worker["id"], "project_id": worker["project_id"],
        "body": {"event_inputs": [event]},
    }
    with store.tx() as db:
        db.execute(
            """INSERT INTO messages
               (id,task_id,route,conversation,payload_hash,payload,state,
                response,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            ("late_old_chat_validated", worker["id"], "worker.first",
             "old-conversation", "old-saved-packet", json.dumps(packet),
             "validated", '{"type":"step_intent"}', 1.0, 1.0),
        )
        db.execute(
            "UPDATE tasks SET owner=?,epoch=? WHERE id=?",
            ("worker.second", 2, worker["id"]),
        )
    # The old route cannot consume an event now owned by another native Chat
    # worker, even when its saved message is individually 'validated'.
    with pytest.raises(ContractError):
        inbox.acknowledge_validated_request(
            worker["id"], "late_old_chat_validated", route="worker.first"
        )
    assert [item["event_id"] for item in inbox.pending(worker["id"])] == [
        event["event_id"]
    ]


def test_late_validated_receipt_cannot_consume_event_after_hard_stop(scope):
    """A hard task stop must fence delayed native receipt consumption."""
    store, worker, _ = scope
    inbox = NativeEventInbox(store)
    thread = "project:" + worker["project_id"]
    with store.tx() as db:
        db.execute(
            "UPDATE tasks SET owner=?,epoch=?,status='running' WHERE id=?",
            ("worker.chat", 1, worker["id"]),
        )
    inbox.subscribe(worker["id"], thread)
    inbox.receive(
        project_id=worker["project_id"], source="native",
        source_id="stopped-receipt", thread=thread, kind="ci_failed",
        summary="Pending before cancellation",
    )
    event = inbox.pending(worker["id"])[0]
    with store.tx() as db:
        db.execute(
            """INSERT INTO messages
               (id,task_id,route,conversation,payload_hash,payload,state,
                response,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            ("late_stopped_validated", worker["id"], "worker.chat",
             "chat-before-stop", "stopped-packet",
             json.dumps({
                 "task_id": worker["id"],
                 "project_id": worker["project_id"],
                 "body": {"event_inputs": [event]},
             }), "validated", '{"type":"step_intent"}', 1.0, 1.0),
        )
        db.execute("UPDATE tasks SET status='paused' WHERE id=?", (worker["id"],))
    with pytest.raises(ContractError):
        inbox.acknowledge_validated_request(
            worker["id"], "late_stopped_validated", route="worker.chat"
        )
    assert [item["event_id"] for item in inbox.pending(worker["id"])] == [
        event["event_id"]
    ]


def test_subscription_pruner_retains_never_assigned_and_revokes_orphaned_lease(scope):
    """A new task's catch-up survives scanning; a former owner's does not."""
    store, fresh, orphan = scope
    inbox = NativeEventInbox(store)
    first_thread = "project:" + fresh["project_id"]
    orphan_thread = "project:" + orphan["project_id"]
    inbox.subscribe(fresh["id"], first_thread)
    inbox.subscribe(orphan["id"], orphan_thread)
    inbox.subscribe(orphan["id"], "task:" + orphan["id"])
    for task, thread, source_id in (
        (fresh, first_thread, "new-unassigned"),
        (orphan, orphan_thread, "orphan-project"),
        (orphan, "task:" + orphan["id"], "orphan-task"),
    ):
        inbox.receive(
            project_id=task["project_id"], source="native",
            source_id=source_id, thread=thread, kind="ci_failed",
            summary="Source metadata only, not authority",
        )
    # First assignment has epoch zero. Formerly owned task lost its lease.
    with store.tx() as db:
        db.execute(
            "UPDATE tasks SET owner=NULL,epoch=2,status='running' WHERE id=?",
            (orphan["id"],),
        )
    assert inbox.revoke_ineligible(frozenset({"worker.chat"}), limit=5) == 2
    assert [x["source_id"] for x in inbox.pending(fresh["id"])] == [
        "new-unassigned"
    ]
    assert inbox.pending(orphan["id"]) == []
    # A later re-subscribe never recovers explicitly revoked old events.
    inbox.subscribe(orphan["id"], orphan_thread)
    inbox.subscribe(orphan["id"], "task:" + orphan["id"])
    assert inbox.pending(orphan["id"]) == []


# The dedicated HA adversarial fixture is also collected by the existing
# focused Ubuntu/Windows native-event workflow, which selects this module
# explicitly. This is not a browser/provider acceptance test.
from test_ha_event_receipt_scope import (  # noqa: E402
    claimed_delivery,
    test_validated_native_effect_rejects_mismatched_request_scope,
    test_validated_native_effect_rejects_unrelated_second_event,
    test_validated_native_effect_rejects_bad_modern_owner_binding,
    test_validated_native_effect_rejects_extra_same_project_event,
)


# Preserve no-Actions owner override: this import only makes the new adversarial
# uncertain-recovery cases discoverable by the existing focused test command.
# CHECKS PENDING / AWAITING CI; no runner or provider acceptance is claimed.
from test_ha_event_uncertain_reconciliation import (  # noqa: E402
    uncertain_delivery,
    test_uncertain_reconciliation_rejects_mismatched_retained_request,
    test_uncertain_reconciliation_accepts_one_exact_current_owner_packet,
)
