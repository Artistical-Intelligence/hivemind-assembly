"""Adversarial scope checks for the real SQLite native event effect finalizer.

These tests never invoke a browser, model, provider API, or scheduler.
They exercise the persisted *validated* request trust boundary under a
legitimate current task/owner lease, not merely malformed input to an adapter.
"""

import json
import time

import pytest

from hivemind_assembly.automation.event_inbox import NativeEventInbox
from hivemind_assembly.core.common import Blocked, Conflict, ContractError
from hivemind_assembly.core.durable_effects import DurableEventEffects
from hivemind_assembly.core.store import Store


@pytest.fixture
def claimed_delivery(tmp_path):
    store = Store(tmp_path)
    task = store.create_project("receipt-alpha", "Validate scoped Chat event")
    foreign = store.create_project("receipt-beta", "Unrelated private work")
    inbox = NativeEventInbox(store)
    thread = "project:" + task["project_id"]
    inbox.subscribe(task["id"], thread)
    assert inbox.receive(
        project_id=task["project_id"], source="native",
        source_id="scoped-source", thread=thread,
        kind="ci_failed", summary="Pinned source regression",
    ) == "stored"
    # A live owner lease is required by DurableEventEffects._fence.
    with store.tx() as db:
        db.execute(
            "UPDATE tasks SET status='running', owner=?, epoch=1, "
            "lease_until=? WHERE id=?",
            ("worker.chat", time.time() + 3600, task["id"]),
        )
    effects = DurableEventEffects(store)
    event_id = inbox.pending(task["id"])[0]["event_id"]
    assert effects.stage_pending(task["id"], limit=1) == [event_id]
    claim = effects.claim(task["id"], "worker.chat", 1)
    assert claim is not None
    try:
        yield store, task, foreign, inbox, effects, claim
    finally:
        store.close()


def _persist_validated(store, task, claim, body, *, identifier):
    packet = {
        "task_id": task["id"],
        "project_id": task["project_id"],
        "body": body,
    }
    with store.tx() as db:
        db.execute(
            """INSERT INTO messages
               (id,task_id,route,conversation,payload_hash,payload,
                state,response,created,updated)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (identifier, task["id"], "worker.chat", "assigned-chat",
             identifier + "-hash", json.dumps(packet), "validated",
             '{"type":"step_intent"}', time.time() + 1, time.time() + 1),
        )
    return packet


def _finalize(effects, task, claim, identifier):
    return effects.finalize(
        task["id"], "worker.chat", 1,
        claim["effect_key"], claim["generation"], identifier,
    )


@pytest.mark.parametrize("poison", ["project", "task"])
def test_validated_native_effect_rejects_mismatched_request_scope(
    claimed_delivery, poison
):
    """Matching event metadata must not supersede a forged request scope."""
    store, task, foreign, inbox, effects, claim = claimed_delivery
    identifier = "invalid_scope_" + poison
    packet = _persist_validated(
        store, task, claim,
        {"event_inputs": [claim["event_input"]]},
        identifier=identifier,
    )
    if poison == "project":
        packet["project_id"] = foreign["project_id"]
    else:
        packet["task_id"] = foreign["id"]
    with store.tx() as db:
        db.execute(
            "UPDATE messages SET payload=? WHERE id=?",
            (json.dumps(packet), identifier),
        )
    with pytest.raises((Blocked, Conflict, ContractError)):
        _finalize(effects, task, claim, identifier)
    assert effects.status(task["id"])[0]["status"] == "leased"
    assert [item["event_id"] for item in inbox.pending(task["id"])] == [
        claim["event_id"]
    ]


def test_validated_native_effect_rejects_unrelated_second_event(
    claimed_delivery,
):
    """One leased source event cannot authorize an unrelated project packet."""
    store, task, foreign, inbox, effects, claim = claimed_delivery
    other_thread = "project:" + foreign["project_id"]
    inbox.subscribe(foreign["id"], other_thread)
    inbox.receive(
        project_id=foreign["project_id"], source="native",
        source_id="private-source", thread=other_thread,
        kind="ci_failed", summary="Do not cross into the other project",
    )
    unrelated = inbox.pending(foreign["id"])[0]
    identifier = "mixed_project_source"
    _persist_validated(
        store, task, claim,
        {"event_inputs": [claim["event_input"], unrelated]},
        identifier=identifier,
    )
    with pytest.raises((Blocked, Conflict, ContractError)):
        _finalize(effects, task, claim, identifier)
    assert effects.status(task["id"])[0]["status"] == "leased"
    assert [item["event_id"] for item in inbox.pending(task["id"])] == [
        claim["event_id"]
    ]
    assert [item["event_id"] for item in inbox.pending(foreign["id"])] == [
        unrelated["event_id"]
    ]
