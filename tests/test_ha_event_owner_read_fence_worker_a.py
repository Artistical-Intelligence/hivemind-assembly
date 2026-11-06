"""Worker A scoped SQLite owner-epoch read-race regressions.

No provider/browser, paid API, external credentials or RE-Wizard access.
These are local tests only. Verifier should independently review and collect
this module in the focused native-event workflow; tests do not prove live HA.
"""

import json
import time

import pytest

from hivemind_assembly.automation.event_inbox import NativeEventInbox
from hivemind_assembly.automation.team import NativeTeam
from hivemind_assembly.core.common import ContractError
from hivemind_assembly.core.store import Store


@pytest.fixture
def setup(tmp_path):
    store = Store(tmp_path)
    worker = store.create_project("isolated-owner-fence", "Test scoped native owner")
    inbox = NativeEventInbox(store)
    thread = "project:" + worker["project_id"]
    try:
        yield store, worker, inbox, thread
    finally:
        store.close()


def _event(inbox, worker, thread, source):
    assert inbox.receive(
        project_id=worker["project_id"], source="native",
        source_id=source, thread=thread, kind="ci_failed",
        summary="Authenticated local fixture, no prompt authority",
    ) == "stored"


def _assign(store, worker, route, epoch, *, lease_offset=3600):
    with store.tx() as db:
        db.execute(
            """UPDATE tasks SET owner=?,epoch=?,status='running',
               lease_until=? WHERE id=?""",
            (route, epoch, time.time() + lease_offset, worker["id"]),
        )


def test_unassigned_first_read_and_real_assigned_route_are_distinct(setup):
    store, task, inbox, thread = setup
    inbox.subscribe(task["id"], thread, route="worker.chat", epoch=0)
    _event(inbox, task, thread, "catch-up")
    assert [item["source_id"] for item in inbox.pending(
        task["id"], route="worker.chat", epoch=0
    )] == ["catch-up"]
    _assign(store, task, "worker.current", 1)
    with pytest.raises(ContractError, match="epoch|reader"):
        inbox.pending(task["id"], route="worker.chat", epoch=0)
    assert [item["source_id"] for item in inbox.pending(
        task["id"], route="worker.current", epoch=1
    )] == ["catch-up"]


def test_stale_owner_or_epoch_cannot_resubscribe_or_consume_successors_event(setup):
    store, task, inbox, thread = setup
    _assign(store, task, "worker.first", 1)
    inbox.subscribe(task["id"], thread, route="worker.first", epoch=1)
    _event(inbox, task, thread, "before-transfer")
    _assign(store, task, "worker.second", 2)
    for method in (
        lambda: inbox.pending(task["id"], route="worker.first", epoch=1),
        lambda: inbox.subscribe(task["id"], thread,
                                route="worker.first", epoch=1),
        lambda: inbox.pending(task["id"], route="worker.first", epoch=2),
    ):
        with pytest.raises(ContractError):
            method()
    assert [row["source_id"] for row in inbox.pending(
        task["id"], route="worker.second", epoch=2
    )] == ["before-transfer"]


def test_same_route_new_epoch_expired_lease_and_stop_fail_closed(setup):
    store, task, inbox, thread = setup
    _assign(store, task, "worker.chat", 1)
    inbox.subscribe(task["id"], thread, route="worker.chat", epoch=1)
    _event(inbox, task, thread, "lease-generation")
    _assign(store, task, "worker.chat", 2)
    with pytest.raises(ContractError, match="epoch"):
        inbox.pending(task["id"], route="worker.chat", epoch=1)
    assert inbox.pending(task["id"], route="worker.chat", epoch=2)
    _assign(store, task, "worker.chat", 2, lease_offset=-30)
    with pytest.raises(ContractError, match="lease"):
        inbox.pending(task["id"], route="worker.chat", epoch=2)
    _assign(store, task, "worker.chat", 2)
    with store.tx() as db:
        db.execute("UPDATE tasks SET status='paused' WHERE id=?", (task["id"],))
    with pytest.raises(ContractError, match="lease"):
        inbox.pending(task["id"], route="worker.chat", epoch=2)
    # Local inspection retains the evidence even when Chat delivery is denied.
    assert inbox.pending(task["id"])


def test_transfer_between_native_subscribe_and_pending_never_leaks(setup, monkeypatch):
    store, task, inbox, thread = setup
    _assign(store, task, "worker.first", 1)
    _event(inbox, task, thread, "raced-input")
    native = NativeTeam.__new__(NativeTeam)
    native.store = store
    native.config = {"routes": {
        "worker.first": {"provider": "openai", "mode": "Chat"},
        "worker.second": {"provider": "openai", "mode": "Chat"},
    }}
    native.native_event_inbox = inbox
    native.progress_watchdog = None

    def transfer_during_bridge(project_id):
        assert project_id == task["project_id"]
        _assign(store, task, "worker.second", 2)
        return 0

    monkeypatch.setattr(inbox, "bridge_native", transfer_during_bridge)
    with pytest.raises(ContractError, match="epoch|reader"):
        native.native_event_inputs(store.task(task["id"]), "worker.first")
    assert [row["source_id"] for row in inbox.pending(
        task["id"], route="worker.second", epoch=2
    )] == ["raced-input"]


def test_explicit_modern_receipt_cannot_downgrade_to_legacy_source_proof(setup):
    store, task, inbox, thread = setup
    _assign(store, task, "worker.chat", 1)
    inbox.subscribe(task["id"], thread, route="worker.chat", epoch=1)
    _event(inbox, task, thread, "source-proof")
    event = inbox.pending(task["id"])[0]
    base = {"task_id": task["id"], "project_id": task["project_id"],
            "body": {"event_inputs": [event]}}
    packets = [
        {**base, "native_event_owner": None},
        {**base, "native_event_owner": {"owner": "worker.chat", "epoch": 1},
         "body": {"event_inputs": [{"event_id": event["event_id"]}]}},
    ]
    for index, packet in enumerate(packets):
        with store.tx() as db:
            db.execute(
                """INSERT INTO messages
                   (id,task_id,route,conversation,payload_hash,payload,state,
                    response,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (f"modern_downgrade_{index}", task["id"], "worker.chat",
                 "current-chat", f"saved-hash-{index}",
                 json.dumps(packet), "validated", '{"type":"step_intent"}',
                 1.0, 1.0),
            )
        with pytest.raises(ContractError, match="binding|envelope"):
            inbox.acknowledge_validated_request(
                task["id"], f"modern_downgrade_{index}", route="worker.chat"
            )
        assert [row["event_id"] for row in inbox.pending(task["id"])] == [
            event["event_id"]
        ]
