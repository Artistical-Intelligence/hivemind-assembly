"""Worker A-owned positive lease-fence cases for local native Chat inbox.

These use SQLite/Store only: no browser, paid API, provider, or Actions.
CHECKS PENDING / AWAITING CI. Independent verifier cases in
test_ha_event_lease_expiry.py remain separately owned and unchanged.
"""

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
