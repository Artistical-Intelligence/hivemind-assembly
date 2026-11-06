"""Worker A synthetic SQLite regressions for native receipt and ticket fences.

Source-bound offline cases only: no provider, model API, browser or Actions.
Independent verifier execution and review remain CHECKS PENDING.
"""

import json
import time

import pytest

from hivemind_assembly.automation.event_inbox import NativeEventInbox
from hivemind_assembly.core.common import ContractError
from hivemind_assembly.core.store import Store


@pytest.fixture
def env(tmp_path):
    store = Store(tmp_path)
    task = store.create_project("receipt-envelope", "Fenced event receipt")
    inbox = NativeEventInbox(store)
    try:
        yield store, task, inbox
    finally:
        store.close()


def _validated(store, task, message_id, events, *, owner=None):
    request = {
        "task_id": task["id"], "project_id": task["project_id"],
        "body": {"event_inputs": events},
    }
    if owner is not None:
        request["native_event_owner"] = owner
    with store.tx() as db:
        db.execute(
            """INSERT INTO messages
               (id,task_id,route,conversation,payload_hash,payload,state,
                response,created,updated)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (message_id, task["id"], "worker.chat", "chat", message_id,
             json.dumps(request), "validated", None, 1.0, 1.0),
        )


def _one_event(store, task, inbox):
    thread = "project:" + task["project_id"]
    inbox.subscribe(task["id"], thread)
    assert inbox.receive(
        project_id=task["project_id"], source="native",
        source_id="receipt-source", thread=thread,
        kind="ci_failed", summary="Authenticated retained event",
    ) == "stored"
    return inbox.pending(task["id"])[0]


def test_ticket_acceptance_ignores_later_malformed_other_task_record(env):
    store, task, inbox = env
    with store.tx() as db:
        db.execute("UPDATE tasks SET status='accepted' WHERE id=?", (task["id"],))
        db.execute(
            """INSERT INTO artifacts(id,sha256,size,classification,
               project_id,logical_name,created) VALUES(?,?,?,?,?,?,?)""",
            ("accepted-artifact", "a" * 64, 1, "test", task["project_id"],
             "synthetic", 1.0),
        )
        db.execute(
            "INSERT INTO records(kind,id,payload,created) VALUES(?,?,?,?)",
            ("acceptance_result", "correct-acceptance", json.dumps({
                "task_id": task["id"], "status": "accepted",
                "passed": True, "artifact": "accepted-artifact",
            }), 1.0),
        )
        # This later, unrelated, malformed record must not make the entire
        # project acceptance query fail with sqlite3.OperationalError.
        db.execute(
            "INSERT INTO records(kind,id,payload,created) VALUES(?,?,?,?)",
            ("acceptance_result", "malformed-unrelated", "{broken-json", 2.0),
        )
    ticket = inbox.reconcile_ticket(task["id"])
    assert ticket["state"] == "accepted"
    assert ticket["last_artifact"] == "a" * 64
    assert inbox.reconcile_ticket(task["id"])["state"] == "accepted"


def test_ticket_acceptance_without_valid_retained_result_needs_check(env):
    store, task, inbox = env
    with store.tx() as db:
        db.execute("UPDATE tasks SET status='accepted' WHERE id=?", (task["id"],))
        db.execute(
            "INSERT INTO records(kind,id,payload,created) VALUES(?,?,?,?)",
            ("acceptance_result", "invalid-only", "{broken-json", 2.0),
        )
    assert inbox.reconcile_ticket(task["id"])["state"] == "needs_check"


def test_oversized_saved_receipt_fails_before_per_item_inspection(env):
    store, task, inbox = env
    event = _one_event(store, task, inbox)
    _validated(
        store, task, "msg_over_20",
        [{"event_id": event["event_id"]}] * 20 + [{"malformed": True}],
    )
    with pytest.raises(ContractError, match="bounded native event"):
        inbox.acknowledge_validated_request(
            task["id"], "msg_over_20", route="worker.chat"
        )
    assert [x["event_id"] for x in inbox.pending(task["id"])] == [
        event["event_id"]
    ]


@pytest.mark.parametrize("arrival", [
    True, False, "1.0", None, [1.0], {"value": 1.0},
])
def test_forged_non_numeric_arrival_proof_cannot_ack(env, arrival):
    store, task, inbox = env
    event = _one_event(store, task, inbox)
    with store.tx() as db:
        db.execute("UPDATE ha_event_trigger SET arrived=1.0 WHERE id=?",
                   (event["event_id"],))
        db.execute(
            """UPDATE tasks SET owner='worker.chat',epoch=1,status='running',
               lease_until=? WHERE id=?""",
            (time.time() + 3600, task["id"]),
        )
    proof = {**inbox.pending(task["id"])[0], "arrived": arrival}
    _validated(
        store, task, "msg_proof_" + str(type(arrival).__name__),
        [proof], owner={"owner": "worker.chat", "epoch": 1},
    )
    with pytest.raises(ContractError, match="arrival proof"):
        inbox.acknowledge_validated_request(
            task["id"], "msg_proof_" + str(type(arrival).__name__),
            route="worker.chat",
        )
    assert len(inbox.pending(task["id"])) == 1


def test_valid_modern_numeric_proof_ack_and_restart_replay(env):
    store, task, inbox = env
    event = _one_event(store, task, inbox)
    with store.tx() as db:
        db.execute("UPDATE ha_event_trigger SET arrived=1.0 WHERE id=?",
                   (event["event_id"],))
        db.execute(
            """UPDATE tasks SET owner='worker.chat',epoch=1,status='running',
               lease_until=? WHERE id=?""",
            (time.time() + 3600, task["id"]),
        )
    # JSON int 1 remains numerically equivalent to SQLite REAL 1.0.
    proof = {**inbox.pending(task["id"])[0], "arrived": 1}
    _validated(store, task, "msg_numeric", [proof],
               owner={"owner": "worker.chat", "epoch": 1})
    assert inbox.acknowledge_validated_request(
        task["id"], "msg_numeric", route="worker.chat") == 1
    restarted = NativeEventInbox(store)
    assert restarted.acknowledge_validated_request(
        task["id"], "msg_numeric", route="worker.chat") == 0
    assert restarted.pending(task["id"]) == []
