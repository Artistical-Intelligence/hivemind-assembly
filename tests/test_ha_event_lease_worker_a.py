"""Worker A-owned positive lease-fence cases for local native Chat inbox.

These use SQLite/Store only: no browser, paid API, provider, or Actions.
CHECKS PENDING / AWAITING CI. Independent verifier cases in
test_ha_event_lease_expiry.py remain separately owned and unchanged.
"""

import json
import time

import pytest

from hivemind_assembly.automation import event_inbox as inbox_module
from hivemind_assembly.automation.event_inbox import NativeEventInbox
from hivemind_assembly.core.common import ContractError
from hivemind_assembly.core.store import Store


@pytest.fixture
def live_task(tmp_path):
    store = Store(tmp_path)
    task = store.create_project("lease-positive", "Verify safe event catch-up")
    inbox = NativeEventInbox(store)
    thread = "project:" + task["project_id"]
    with store.tx() as db:
        db.execute(
            """UPDATE tasks SET owner='worker.chat', epoch=1, status='running',
               lease_until=? WHERE id=?""",
            (time.time() + 3600, task["id"]),
        )
    try:
        yield store, task, inbox, thread
    finally:
        store.close()


def _emit(inbox, task, thread, source_id):
    assert inbox.receive(
        project_id=task["project_id"], source="native",
        source_id=source_id, thread=thread,
        kind="ci_failed", summary="Source evidence, never an instruction",
    ) == "stored"


def test_unexpired_first_subscription_backfills_and_survives_restart(live_task):
    store, task, inbox, thread = live_task
    _emit(inbox, task, thread, "before-first-subscription")
    inbox.subscribe(task["id"], thread, route="worker.chat", epoch=1)
    first = inbox.pending(task["id"], route="worker.chat", epoch=1)
    assert [event["source_id"] for event in first] == [
        "before-first-subscription"
    ]
    assert [event["event_id"] for event in NativeEventInbox(store).pending(
        task["id"], route="worker.chat", epoch=1
    )] == [first[0]["event_id"]]


def test_renewed_lease_allows_exact_same_epoch_subscribe_and_pending(live_task):
    store, task, inbox, thread = live_task
    _emit(inbox, task, thread, "lease-renewed-before-read")
    # The old lease would have expired; the controller has extended it
    # without transferring ownership or changing the epoch.
    with store.tx() as db:
        db.execute(
            "UPDATE tasks SET lease_until=? WHERE id=?",
            (time.time() + 7200, task["id"]),
        )
    inbox.subscribe(task["id"], thread, route="worker.chat", epoch=1)
    assert [item["source_id"] for item in inbox.pending(
        task["id"], route="worker.chat", epoch=1
    )] == ["lease-renewed-before-read"]


def test_subscription_expiration_at_final_fence_rolls_back_backfill(
    live_task, monkeypatch
):
    store, task, inbox, thread = live_task
    _emit(inbox, task, thread, "before-expiring-backfill")
    beginning = time.time() + 10
    expiry = beginning + 1
    with store.tx() as db:
        db.execute(
            "UPDATE tasks SET lease_until=? WHERE id=?",
            (expiry, task["id"]),
        )
    clock = [beginning]
    refill = NativeEventInbox._refill_initial

    def expire_after_refill(db, task_id, thread_name, *, limit=20):
        refill(db, task_id, thread_name, limit=limit)
        clock[0] = expiry + 1

    monkeypatch.setattr(inbox_module.time, "time", lambda: clock[0])
    monkeypatch.setattr(
        NativeEventInbox, "_refill_initial", staticmethod(expire_after_refill)
    )
    with pytest.raises(ContractError, match="lease"):
        inbox.subscribe(task["id"], thread, route="worker.chat", epoch=1)
    assert store.one(
        "SELECT COUNT(*) AS n FROM ha_event_subscription WHERE task_id=?",
        (task["id"],),
    )["n"] == 0
    assert store.one(
        "SELECT COUNT(*) AS n FROM ha_event_delivery WHERE task_id=?",
        (task["id"],),
    )["n"] == 0


def _persist_validated_ack(store, task, inbox, thread, *, message_id, count=2):
    """Save an exact modern receipt in local SQLite, without a browser."""
    inbox.subscribe(task["id"], thread, route="worker.chat", epoch=1)
    for n in range(count):
        _emit(inbox, task, thread, f"{message_id}-event-{n}")
    events = inbox.pending(task["id"], route="worker.chat", epoch=1)
    packet = {
        "task_id": task["id"], "project_id": task["project_id"],
        "native_event_owner": {"owner": "worker.chat", "epoch": 1},
        "body": {"event_inputs": events},
    }
    with store.tx() as db:
        db.execute(
            """INSERT INTO messages
               (id,task_id,route,conversation,payload_hash,payload,
                state,response,created,updated)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (message_id, task["id"], "worker.chat", "fixture-chat",
             message_id + "-hash", json.dumps(packet), "validated",
             '{"type":"step_intent"}', time.time(), time.time()),
        )
    return [item["event_id"] for item in events]


def test_validated_receipt_ack_rolls_back_when_lease_expires_mid_batch(
    live_task, monkeypatch
):
    """An expiring owner cannot partially ACK two deliveries during the TX.

    The clock advances after the initial gate and read_at timestamp but
    before COMMIT. All read markers must be rolled back together.
    """
    store, task, inbox, thread = live_task
    ids = _persist_validated_ack(
        store, task, inbox, thread, message_id="ack_lease_expires", count=2,
    )
    beginning = time.time() + 10
    expiry = beginning + 1
    with store.tx() as db:
        db.execute("UPDATE tasks SET lease_until=? WHERE id=?",
                   (expiry, task["id"]))
    samples = [beginning, beginning, expiry + 1]

    def expiring_clock():
        return samples.pop(0) if samples else expiry + 1

    monkeypatch.setattr(inbox_module.time, "time", expiring_clock)
    with pytest.raises(ContractError, match="lease expired during ACK"):
        inbox.acknowledge_validated_request(
            task["id"], "ack_lease_expires", route="worker.chat",
        )
    assert store.one(
        """SELECT COUNT(*) AS n FROM ha_event_delivery
           WHERE task_id=? AND read_at IS NULL""",
        (task["id"],),
    )["n"] == len(ids)


def test_validated_receipt_ack_succeeds_on_renewed_current_lease(live_task):
    """Renewing the same owner's epoch lease permits a legitimate receipt."""
    store, task, inbox, thread = live_task
    ids = _persist_validated_ack(
        store, task, inbox, thread, message_id="ack_lease_renewed", count=2,
    )
    with store.tx() as db:
        db.execute("UPDATE tasks SET lease_until=? WHERE id=?",
                   (time.time() + 7200, task["id"]))
    assert inbox.acknowledge_validated_request(
        task["id"], "ack_lease_renewed", route="worker.chat",
    ) == len(ids)
    assert inbox.pending(task["id"], route="worker.chat", epoch=1) == []
    # Saved validated-message replay remains idempotent after a restart.
    assert NativeEventInbox(store).acknowledge_validated_request(
        task["id"], "ack_lease_renewed", route="worker.chat",
    ) == 0
