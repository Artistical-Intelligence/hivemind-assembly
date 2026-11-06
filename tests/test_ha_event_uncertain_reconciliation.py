"""Fail-closed SQLite reconciliation of uncertain native Chat event effects.

Authoritative outcome is the persisted source-scoped request, not just the
presence of one matching event ID in a saved validated message. These tests
use synthetic local SQLite evidence only: no provider, API, browser or Actions.
CHECKS PENDING / AWAITING CI: repository source and dependencies are not present
in the permitted local runtime; execute on the exact pinned HA revision.
"""

import json
import time

import pytest

from hivemind_assembly.automation.event_inbox import NativeEventInbox
from hivemind_assembly.core.common import Blocked, Conflict, ContractError
from hivemind_assembly.core.durable_effects import DurableEventEffects
from hivemind_assembly.core.store import Store


@pytest.fixture
def uncertain_delivery(tmp_path):
    store = Store(tmp_path)
    try:
        task = store.create_project("reconcile-owner", "Review one native event")
        foreign = store.create_project("reconcile-foreign", "Unrelated private task")
        inbox = NativeEventInbox(store)
        thread = "project:" + task["project_id"]
        inbox.subscribe(task["id"], thread)
        assert inbox.receive(
            project_id=task["project_id"], source="native",
            source_id="reconcile-source", thread=thread,
            kind="ci_failed", summary="One retained authenticated event",
        ) == "stored"
        with store.tx() as db:
            db.execute(
                """UPDATE tasks SET status='running',owner=?,epoch=1,
                   lease_until=? WHERE id=?""",
                ("worker.chat", time.time() + 3600, task["id"]),
            )
        effects = DurableEventEffects(store)
        pending = inbox.pending(task["id"])
        assert len(pending) == 1
        assert effects.stage_pending(task["id"], limit=1) == [pending[0]["event_id"]]
        claim = effects.claim(task["id"], "worker.chat", 1)
        assert claim is not None
        assert effects.interrupted(
            task["id"], "worker.chat", 1,
            claim["effect_key"], claim["generation"],
            definitely_not_sent=False,
        ) == "uncertain"
        yield store, task, foreign, inbox, effects, claim
    finally:
        store.close()


def _validated_message(store, task, request, receipt_id):
    # A local synthetic message marked validated is a deliberate adversarial
    # fixture, NOT evidence of a real native browser or a permitted model turn.
    with store.tx() as db:
        db.execute(
            """INSERT INTO messages
               (id,task_id,route,conversation,payload_hash,payload,
                state,response,created,updated)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (receipt_id, task["id"], "worker.chat", "reconcile-chat",
             receipt_id + "-hash", json.dumps(request), "validated",
             '{"type":"step_intent"}', time.time() + 1, time.time() + 1),
        )


def _packet(task, claim):
    return {
        "task_id": task["id"],
        "project_id": task["project_id"],
        "native_event_owner": {"owner": "worker.chat", "epoch": 1},
        "body": {"event_inputs": [claim["event_input"]]},
    }


@pytest.mark.parametrize("poison", [
    "foreign_project", "foreign_task", "foreign_owner", "stale_owner_epoch",
    "null_owner_binding", "duplicate_claim", "extra_same_project",
    "extra_foreign_project",
])
def test_uncertain_reconciliation_rejects_mismatched_retained_request(
        uncertain_delivery, poison):
    """A previously uncertain browser send cannot be 'resolved' by a bad packet.

    A positive event-envelope match embedded in unrelated or contradictory
    input does not authorize clearing the effect or consuming its unread event.
    """
    store, task, foreign, inbox, effects, claim = uncertain_delivery
    packet = _packet(task, claim)
    if poison == "foreign_project":
        packet["project_id"] = foreign["project_id"]
    elif poison == "foreign_task":
        packet["task_id"] = foreign["id"]
    elif poison == "foreign_owner":
        packet["native_event_owner"] = {"owner": "worker.other", "epoch": 1}
    elif poison == "stale_owner_epoch":
        packet["native_event_owner"] = {"owner": "worker.chat", "epoch": 2}
    elif poison == "null_owner_binding":
        packet["native_event_owner"] = None
    elif poison == "duplicate_claim":
        packet["body"]["event_inputs"].append(dict(claim["event_input"]))
    elif poison == "extra_same_project":
        assert inbox.receive(
            project_id=task["project_id"], source="native",
            source_id="unclaimed-reconcile-event",
            thread="project:" + task["project_id"],
            kind="ci_failed", summary="Different source event",
        ) == "stored"
        packet["body"]["event_inputs"].append(next(
            item for item in inbox.pending(task["id"])
            if item["event_id"] != claim["event_id"]
        ))
    elif poison == "extra_foreign_project":
        thread = "project:" + foreign["project_id"]
        inbox.subscribe(foreign["id"], thread)
        assert inbox.receive(
            project_id=foreign["project_id"], source="native",
            source_id="private-reconcile-source", thread=thread,
            kind="ci_failed", summary="Private unrelated source",
        ) == "stored"
        packet["body"]["event_inputs"].append(inbox.pending(foreign["id"])[0])
    identifier = "poison_" + poison
    _validated_message(store, task, packet, identifier)

    with pytest.raises((Blocked, Conflict, ContractError)):
        effects.reconcile_uncertain(
            task["id"], "worker.chat", 1, claim["effect_key"]
        )
    assert effects.status(task["id"])[0]["status"] == "uncertain"
    assert claim["event_id"] in {
        item["event_id"] for item in inbox.pending(task["id"])
    }
    if poison == "extra_foreign_project":
        assert len(inbox.pending(foreign["id"])) == 1


def test_uncertain_reconciliation_accepts_one_exact_current_owner_packet(
        uncertain_delivery):
    """Negative checks must not disable real, safely reconciled local receipt."""
    store, task, _, inbox, effects, claim = uncertain_delivery
    _validated_message(store, task, _packet(task, claim), "good_receipt")
    assert effects.reconcile_uncertain(
        task["id"], "worker.chat", 1, claim["effect_key"]
    ) == "delivered"
    assert effects.reconcile_uncertain(
        task["id"], "worker.chat", 1, claim["effect_key"]
    ) == "delivered"
    assert inbox.pending(task["id"]) == []
