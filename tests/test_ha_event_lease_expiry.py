"""Adversarial time-of-check/expiration fences for native Chat event receipts.

All evidence is synthetic local SQLite and a deterministic mocked wall clock.
No browser, provider, model API, GitHub Actions, or external source is invoked.
CHECKS PENDING / AWAITING CI: no complete HA local test environment available.
"""

import json
import time

import pytest

from hivemind_assembly.automation import event_inbox as inbox_module
from hivemind_assembly.automation.event_inbox import NativeEventInbox
from hivemind_assembly.core import durable_effects as effect_module
from hivemind_assembly.core.common import Blocked, Conflict, ContractError
from hivemind_assembly.core.durable_effects import DurableEventEffects
from hivemind_assembly.core.store import Store


@pytest.fixture
def lease_owner(tmp_path):
    store = Store(tmp_path)
    task = store.create_project("expiring-lease", "Prove native Chat owner fences")
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


def _event(inbox, task, thread, source_id):
    assert inbox.receive(
        project_id=task["project_id"], source="native",
        source_id=source_id, thread=thread, kind="ci_failed",
        summary="Bounded local event data, never agent instructions",
    ) == "stored"


def _arm_lease(store, task, expiry):
    with store.tx() as db:
        db.execute("UPDATE tasks SET lease_until=? WHERE id=?", (expiry, task["id"]))


def test_effect_receipt_rejects_lease_expiring_during_source_proof(
    lease_owner, monkeypatch
):
    """The owner must still hold its lease at the moment read_at is written.

    The current finalizer checks its owner only before inspecting the saved
    message. Advancing a deterministic wall clock *during* source proof must
    not allow an ACK after expiration, even without a concurrent writer.
    """
    store, task, inbox, thread = lease_owner
    inbox.subscribe(task["id"], thread, route="worker.chat", epoch=1)
    _event(inbox, task, thread, "effect-lease")
    effects = DurableEventEffects(store)
    event = inbox.pending(task["id"], route="worker.chat", epoch=1)[0]
    assert effects.stage_pending(task["id"], limit=1) == [event["event_id"]]
    claim = effects.claim(task["id"], "worker.chat", 1)
    receipt_id = "receipt_expiring_during_proof"
    saved_request = {
        "task_id": task["id"], "project_id": task["project_id"],
        "native_event_owner": {"owner": "worker.chat", "epoch": 1},
        "body": {"event_inputs": [claim["event_input"]]},
    }
    with store.tx() as db:
        db.execute(
            """INSERT INTO messages
               (id,task_id,route,conversation,payload_hash,payload,
                state,response,created,updated)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (receipt_id, task["id"], "worker.chat", "fixture-chat",
             receipt_id + "-hash", json.dumps(saved_request), "validated",
             '{"type":"step_intent"}', time.time() + 1, time.time() + 1),
        )

    beginning = time.time() + 10
    expiry = beginning + 1
    _arm_lease(store, task, expiry)
    clock = [beginning]
    real_contains = effect_module._contains_exact_event

    def expire_while_validating(inputs, native_event):
        clock[0] = expiry + 1
        return real_contains(inputs, native_event)

    monkeypatch.setattr(effect_module.time, "time", lambda: clock[0])
    monkeypatch.setattr(effect_module, "_contains_exact_event", expire_while_validating)
    with pytest.raises((Blocked, Conflict, ContractError)):
        effects.finalize(
            task["id"], "worker.chat", 1,
            claim["effect_key"], claim["generation"], receipt_id,
        )
    assert effects.status(task["id"])[0]["status"] == "leased"
    assert event["event_id"] in {
        item["event_id"] for item in inbox.pending(task["id"])
    }


def test_native_pending_refuses_expiry_during_initial_backfill(
    lease_owner, monkeypatch
):
    """A stale reader cannot receive newly hydrated event source summaries."""
    store, task, inbox, thread = lease_owner
    inbox.subscribe(task["id"], thread, route="worker.chat", epoch=1)
    _event(inbox, task, thread, "pending-lease")
    beginning = time.time() + 10
    expiry = beginning + 1
    _arm_lease(store, task, expiry)
    clock = [beginning]
    refill = NativeEventInbox._refill_initial

    def expire_during_backfill(db, task_id, source_thread, *, limit=20):
        refill(db, task_id, source_thread, limit=limit)
        clock[0] = expiry + 1

    monkeypatch.setattr(inbox_module.time, "time", lambda: clock[0])
    monkeypatch.setattr(
        NativeEventInbox, "_refill_initial", staticmethod(expire_during_backfill)
    )
    with pytest.raises(ContractError, match="lease"):
        inbox.pending(task["id"], route="worker.chat", epoch=1)
    assert len(inbox.pending(task["id"])) == 1  # retained, not consumed


def test_native_subscribe_refuses_expiry_during_initial_catchup(
    lease_owner, monkeypatch
):
    """Expiry after initial gate must not persist an unauthorized subscription."""
    store, task, inbox, thread = lease_owner
    _event(inbox, task, thread, "subscribe-lease")
    beginning = time.time() + 10
    expiry = beginning + 1
    _arm_lease(store, task, expiry)
    clock = [beginning]
    refill = NativeEventInbox._refill_initial

    def expire_during_backfill(db, task_id, source_thread, *, limit=20):
        refill(db, task_id, source_thread, limit=limit)
        clock[0] = expiry + 1

    monkeypatch.setattr(inbox_module.time, "time", lambda: clock[0])
    monkeypatch.setattr(
        NativeEventInbox, "_refill_initial", staticmethod(expire_during_backfill)
    )
    with pytest.raises(ContractError, match="lease"):
        inbox.subscribe(task["id"], thread, route="worker.chat", epoch=1)
    assert store.one(
        "SELECT COUNT(*) AS n FROM ha_event_subscription WHERE task_id=?",
        (task["id"],),
    )["n"] == 0
