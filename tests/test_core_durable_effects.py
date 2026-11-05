"""HA core durable-effect receipts, implementing DeepSeek-style effect safety.

Real HA Store/controller/NativeEventInbox, no browser or model API.
The main interactive chat owns this source/test lane; it does not edit
the scheduled event worker's modules or verifier's existing test files.
"""

import json
import time

import pytest

from hivemind_assembly.automation.event_inbox import NativeEventInbox
from hivemind_assembly.core.common import Blocked, Conflict, ContractError
from hivemind_assembly.core.controller import Controller
from hivemind_assembly.core.durable_effects import DurableEventEffects
from hivemind_assembly.core.store import Store


@pytest.fixture
def owner(tmp_path):
    store = Store(tmp_path)
    task = store.create_project("durable", "Route existing permitted event")
    inbox = NativeEventInbox(store)
    inbox.subscribe(task["id"], "project:" + task["project_id"])
    assert inbox.receive(
        project_id=task["project_id"],
        source="native", source_id="case-1",
        thread="project:" + task["project_id"],
        kind="ci_failed", summary="Source-bound CI failed",
    ) == "stored"
    e = inbox.pending(task["id"])[0]
    controller = Controller(store)
    epoch = controller.acquire(task["id"], "native.chat")
    effects = DurableEventEffects(store)
    try:
        yield store, task, e, epoch, inbox, controller, effects
    finally:
        store.close()


def _valid_receipt(controller, task_id, event_id, name="msg_native_valid"):
    # NativeTeam includes the complete scoped event envelope in its actual
    # browser request. A bare guessed integer is NOT evidence of receipt.
    rows = controller.store.rows(
        """SELECT id,source,source_id,thread,kind,summary,arrived
           FROM ha_event_trigger WHERE id=?""", (event_id,),
    )
    envelope = (
        {
            "event_id": rows[0]["id"], "source": rows[0]["source"],
            "source_id": rows[0]["source_id"], "thread": rows[0]["thread"],
            "kind": rows[0]["kind"], "summary": rows[0]["summary"],
            "arrived": rows[0]["arrived"],
        } if rows else {"event_id": event_id, "kind": "ci_failed"}
    )
    request = {
        "project_id": controller.store.task(task_id)["project_id"],
        "revision": 0,
        "body": {"event_inputs": [envelope]},
    }
    controller.prepare_message(
        task_id, "native.chat", "https://example.invalid/chat",
        request, name,
    )
    controller.message_state(
        name, "validated", '{"request_id":"' + name +
        '","type":"step_intent","intent":{"goal":"Use verified evidence"}}',
    )
    return name


def test_queue_is_deduplicated_and_bound_to_existing_project_delivery(owner):
    store, task, event, epoch, inbox, controller, effects = owner
    assert effects.enqueue(task["id"], "effect-v1", event["event_id"]) == "queued"
    assert effects.enqueue(task["id"], "effect-v1", event["event_id"]) == "duplicate"
    with pytest.raises(Conflict, match="different event"):
        second = inbox.receive(
            project_id=task["project_id"], source="native",
            source_id="case-2", thread="project:" + task["project_id"],
            kind="ci_failed", summary="Second run failed",
        )
        assert second == "stored"
        second_id = inbox.pending(task["id"])[1]["event_id"]
        effects.enqueue(task["id"], "effect-v1", second_id)
    other = store.create_project("unrelated", "No event access")
    with pytest.raises(Blocked, match="unauthorized"):
        effects.enqueue(other["id"], "effect-v1", event["event_id"])


def test_complete_requires_validated_browser_request_with_same_event(owner):
    store, task, event, epoch, inbox, controller, effects = owner
    effects.enqueue(task["id"], "send-ci", event["event_id"])
    lease = effects.claim(task["id"], "native.chat", epoch)
    assert lease is not None
    assert effects.claim(task["id"], "native.chat", epoch) is None
    with pytest.raises(Blocked, match="validated"):
        effects.finalize(task["id"], "native.chat", epoch, "send-ci",
                         lease["generation"], "missing-msg")
    controller.prepare_message(task["id"], "native.chat",
                               "https://example.invalid/chat",
                               {"body":{"event_inputs":[{"event_id":event["event_id"]}]}},
                               "pending-msg")
    with pytest.raises(Blocked, match="validated"):
        effects.finalize(task["id"], "native.chat", epoch, "send-ci",
                         lease["generation"], "pending-msg")
    wrong = _valid_receipt(controller, task["id"], event["event_id"]+123,
                           "wrong-msg")
    with pytest.raises(Blocked, match="never received"):
        effects.finalize(task["id"], "native.chat", epoch, "send-ci",
                         lease["generation"], wrong)
    receipt = _valid_receipt(controller, task["id"], event["event_id"])
    assert effects.finalize(task["id"], "native.chat", epoch, "send-ci",
                            lease["generation"], receipt) == "delivered"
    assert effects.finalize(task["id"], "native.chat", epoch, "send-ci",
                            lease["generation"], receipt) == "duplicate"
    assert inbox.pending(task["id"]) == []
    with pytest.raises(Conflict, match="different receipt"):
        effects.finalize(task["id"], "native.chat", epoch, "send-ci",
                         lease["generation"], wrong)


def test_uncertain_delivery_is_not_retried_automatically(owner):
    store, task, event, epoch, inbox, controller, effects = owner
    effects.enqueue(task["id"], "effect", event["event_id"])
    first = effects.claim(task["id"], "native.chat", epoch)
    assert effects.interrupted(task["id"], "native.chat", epoch, "effect",
                               first["generation"],
                               definitely_not_sent=False) == "uncertain"
    assert effects.claim(task["id"], "native.chat", epoch) is None
    assert effects.status(task["id"])[0]["status"] == "uncertain"
    valid = _valid_receipt(controller, task["id"], event["event_id"])
    assert effects.finalize(task["id"], "native.chat", epoch, "effect",
                            first["generation"], valid) == "delivered"
    assert inbox.pending(task["id"]) == []


def test_pre_dispatch_failure_retry_and_stale_epoch_fail_closed(owner):
    store, task, event, epoch, inbox, controller, effects = owner
    effects.enqueue(task["id"], "effect", event["event_id"])
    first = effects.claim(task["id"], "native.chat", epoch)
    assert effects.interrupted(task["id"], "native.chat", epoch, "effect",
                               first["generation"], definitely_not_sent=True,
                               delay_seconds=0) == "queued"
    retry = effects.claim(task["id"], "native.chat", epoch,
                          now=time.time()+0.1)
    assert retry["generation"] == first["generation"]+1
    with pytest.raises(Conflict, match="stale"):
        effects.interrupted(task["id"], "native.chat", epoch, "effect",
                            first["generation"], definitely_not_sent=True)
    with pytest.raises(Conflict, match="live owner lease"):
        effects.finalize(task["id"], "intruder", epoch, "effect",
                         retry["generation"], "message")
    assert DurableEventEffects(store).status(task["id"])[0]["generation"] == 2
    assert effects.status(task["id"])[0]["attempts"] == 2


def test_same_event_cannot_be_reissued_under_another_effect_key(owner):
    store, task, event, epoch, inbox, controller, effects = owner
    eid = event["event_id"]
    assert effects.enqueue(task["id"], "first", eid) == "queued"
    with pytest.raises(Conflict, match="already bound"):
        effects.enqueue(task["id"], "parallel-copy", eid)
    first = effects.claim(task["id"], "native.chat", epoch)
    receipt = _valid_receipt(controller, task["id"], eid, "once-msg")
    assert effects.finalize(task["id"], "native.chat", epoch,
                            "first", first["generation"], receipt) == "delivered"
    assert effects.enqueue(task["id"], "first", eid) == "duplicate"
    with pytest.raises(Blocked, match="already acknowledged"):
        effects.enqueue(task["id"], "after-ack", eid)


def test_same_task_browser_events_obey_per_conversation_order(owner):
    store, task, first_event, epoch, inbox, controller, effects = owner
    inbox.receive(
        project_id=task["project_id"], source="native", source_id="case-2",
        thread="project:" + task["project_id"], kind="ci_failed",
        summary="A second source-bound check failed",
    )
    second_event = inbox.pending(task["id"])[1]
    assert effects.enqueue(task["id"], "A", first_event["event_id"]) == "queued"
    assert effects.enqueue(task["id"], "B", second_event["event_id"]) == "queued"
    first = effects.claim(task["id"], "native.chat", epoch)
    assert first["effect_key"] == "A"
    assert effects.claim(task["id"], "native.chat", epoch) is None
    msg = _valid_receipt(controller, task["id"], first_event["event_id"], "A-msg")
    assert effects.finalize(task["id"], "native.chat", epoch, "A",
                            first["generation"], msg) == "delivered"
    second = effects.claim(task["id"], "native.chat", epoch)
    assert second is not None and second["effect_key"] == "B"
    assert second["event_id"] == second_event["event_id"]


def test_old_validated_receipt_cannot_complete_new_effect_claim(owner):
    store, task, event, epoch, inbox, controller, effects = owner
    eid = event["event_id"]
    # A previously validated request for this event is not proof that the
    # new effect's dispatch actually reached the browser.
    old = _valid_receipt(controller, task["id"], eid, "pre-claim")
    assert effects.enqueue(task["id"], "new-claim", eid) == "queued"
    lease = effects.claim(task["id"], "native.chat", epoch)
    with pytest.raises(Blocked, match="predates"):
        effects.finalize(task["id"], "native.chat", epoch, "new-claim",
                         lease["generation"], old)
    assert effects.status(task["id"])[0]["status"] == "leased"
    fresh = _valid_receipt(controller, task["id"], eid, "post-claim")
    assert effects.finalize(task["id"], "native.chat", epoch, "new-claim",
                            lease["generation"], fresh) == "delivered"


def test_retry_proof_flag_must_be_explicit_boolean(owner):
    store, task, event, epoch, inbox, controller, effects = owner
    effects.enqueue(task["id"], "flag-test", event["event_id"])
    first = effects.claim(task["id"], "native.chat", epoch)
    with pytest.raises(ContractError, match="explicit boolean"):
        effects.interrupted(
            task["id"], "native.chat", epoch, "flag-test",
            first["generation"], definitely_not_sent=1,
        )
    assert effects.status(task["id"])[0]["status"] == "leased"


def test_revoked_subscription_blocks_late_browser_receipt(owner):
    store, task, event, epoch, inbox, controller, effects = owner
    effects.enqueue(task["id"], "revokable", event["event_id"])
    lease = effects.claim(task["id"], "native.chat", epoch)
    assert inbox.unsubscribe(task["id"], "project:" + task["project_id"]) == 1
    receipt = _valid_receipt(controller, task["id"], event["event_id"],
                             "late-after-revoke")
    with pytest.raises(Conflict, match="revoked"):
        effects.finalize(task["id"], "native.chat", epoch,
                         "revokable", lease["generation"], receipt)
    assert effects.status(task["id"])[0]["status"] == "leased"


def test_legacy_sqlite_table_adds_claim_timestamp_column_safely(tmp_path):
    store = Store(tmp_path)
    try:
        # Simulate a pre-upgrade HA installation with the first effect schema.
        with store.tx() as db:
            db.execute(
                """CREATE TABLE ha_native_effect (
                task_id TEXT NOT NULL,
                effect_key TEXT NOT NULL,
                project_id TEXT NOT NULL,
                event_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                generation INTEGER NOT NULL DEFAULT 0,
                attempts INTEGER NOT NULL DEFAULT 0,
                due_at REAL NOT NULL,
                lease_until REAL,
                receipt_id TEXT,
                updated REAL NOT NULL,
                PRIMARY KEY(task_id,effect_key))"""
            )
        DurableEventEffects(store)
        columns = store.rows("PRAGMA table_info(ha_native_effect)")
        assert "claimed_at" in {row["name"] for row in columns}
        # Reconstructing a second time must not re-apply the migration.
        DurableEventEffects(store)
        assert len(store.rows("PRAGMA index_list(ha_native_effect)")) >= 2
    finally:
        store.close()



def test_uncertain_recovery_uses_verified_receipt_without_new_browser_send(owner):
    store, task, event, epoch, inbox, controller, effects = owner
    effects.enqueue(task["id"], "recover-me", event["event_id"])
    claim = effects.claim(task["id"], "native.chat", epoch)
    assert effects.interrupted(
        task["id"], "native.chat", epoch, "recover-me",
        claim["generation"], definitely_not_sent=False
    ) == "uncertain"
    assert effects.reconcile_uncertain(
        task["id"], "native.chat", epoch, "recover-me"
    ) == "pending"
    # This is a stored request from the original attempt, not a new model call.
    receipt = _valid_receipt(controller, task["id"], event["event_id"],
                             "recover-validated")
    assert effects.reconcile_uncertain(
        task["id"], "native.chat", epoch, "recover-me"
    ) == "delivered"
    assert effects.reconcile_uncertain(
        task["id"], "native.chat", epoch, "recover-me"
    ) == "delivered"
    assert effects.status(task["id"])[0]["receipt_id"] == receipt
    assert inbox.pending(task["id"]) == []


def test_ambiguous_recovery_refuses_to_choose_between_two_receipts(owner):
    store, task, event, epoch, inbox, controller, effects = owner
    effects.enqueue(task["id"], "ambiguous", event["event_id"])
    claim = effects.claim(task["id"], "native.chat", epoch)
    assert effects.interrupted(
        task["id"], "native.chat", epoch, "ambiguous",
        claim["generation"], definitely_not_sent=False
    ) == "uncertain"
    _valid_receipt(controller, task["id"], event["event_id"], "dupe-msg-1")
    _valid_receipt(controller, task["id"], event["event_id"], "dupe-msg-2")
    with pytest.raises(Blocked, match="Multiple validated"):
        effects.reconcile_uncertain(
            task["id"], "native.chat", epoch, "ambiguous"
        )
    assert effects.status(task["id"])[0]["status"] == "uncertain"
    assert effects.claim(task["id"], "native.chat", epoch) is None


def test_recovery_is_fenced_against_wrong_owner_and_unconfirmed_phase(owner):
    store, task, event, epoch, inbox, controller, effects = owner
    effects.enqueue(task["id"], "fenced", event["event_id"])
    claim = effects.claim(task["id"], "native.chat", epoch)
    with pytest.raises(Conflict, match="Only uncertain"):
        effects.reconcile_uncertain(
            task["id"], "native.chat", epoch, "fenced"
        )
    effects.interrupted(
        task["id"], "native.chat", epoch, "fenced",
        claim["generation"], definitely_not_sent=False
    )
    with pytest.raises(Conflict, match="live owner lease"):
        effects.reconcile_uncertain(
            task["id"], "intruder", epoch, "fenced"
        )
    assert effects.status(task["id"])[0]["status"] == "uncertain"


def test_crashed_leased_effect_becomes_uncertain_without_another_send(owner):
    store, task, event, epoch, inbox, controller, effects = owner
    effects.enqueue(task["id"], "crash", event["event_id"])
    first = effects.claim(task["id"], "native.chat", epoch,
                          lease_seconds=30)
    assert first is not None
    assert effects.recover_expired_lease(
        task["id"], "native.chat", epoch, "crash", first["generation"],
        now=first["lease_until"] - 0.5
    ) == "leased"
    assert effects.status(task["id"])[0]["status"] == "leased"
    assert effects.recover_expired_lease(
        task["id"], "native.chat", epoch, "crash", first["generation"],
        now=first["lease_until"] + 0.5
    ) == "uncertain"
    # Even if the saved lease timed out, do not treat an uncertain browser send
    # as definitely not sent, and never auto-claim for a duplicate exchange.
    assert effects.claim(task["id"], "native.chat", epoch) is None
    assert effects.reconcile_uncertain(
        task["id"], "native.chat", epoch, "crash"
    ) == "pending"
    original = _valid_receipt(controller, task["id"], event["event_id"],
                              "late-valid-after-crash")
    assert effects.reconcile_uncertain(
        task["id"], "native.chat", epoch, "crash"
    ) == "delivered"
    assert effects.status(task["id"])[0]["receipt_id"] == original
    assert inbox.pending(task["id"]) == []


def test_expired_lease_recovery_cannot_use_wrong_owner_or_stale_generation(owner):
    store, task, event, epoch, inbox, controller, effects = owner
    effects.enqueue(task["id"], "fence-expired", event["event_id"])
    first = effects.claim(task["id"], "native.chat", epoch,
                          lease_seconds=30)
    with pytest.raises(Conflict, match="live owner lease"):
        effects.recover_expired_lease(
            task["id"], "unauthorized", epoch, "fence-expired",
            first["generation"], now=first["lease_until"] + 1
        )
    with pytest.raises(Conflict, match="generation"):
        effects.recover_expired_lease(
            task["id"], "native.chat", epoch, "fence-expired",
            first["generation"] + 1, now=first["lease_until"] + 1
        )
    assert effects.status(task["id"])[0]["status"] == "leased"


def test_upgrade_refuses_duplicate_legacy_event_effects_without_deleting_data(tmp_path):
    store = Store(tmp_path)
    try:
        task = store.create_project("legacy", "Preserve disputed send evidence")
        with store.tx() as db:
            db.execute(
                """CREATE TABLE ha_native_effect (
                  task_id TEXT NOT NULL,
                  effect_key TEXT NOT NULL,
                  project_id TEXT NOT NULL,
                  event_id INTEGER NOT NULL,
                  status TEXT NOT NULL,
                  generation INTEGER NOT NULL DEFAULT 0,
                  attempts INTEGER NOT NULL DEFAULT 0,
                  due_at REAL NOT NULL,
                  lease_until REAL,
                  receipt_id TEXT,
                  updated REAL NOT NULL,
                  PRIMARY KEY(task_id,effect_key))"""
            )
            for key in ("first", "duplicate"):
                db.execute(
                    """INSERT INTO ha_native_effect
                       (task_id,effect_key,project_id,event_id,status,
                        generation,attempts,due_at,lease_until,updated)
                       VALUES(?,?,?,7,'uncertain',1,1,0,NULL,0)""",
                    (task["id"], key, task["project_id"]),
                )
        with pytest.raises(Blocked, match="manual reconciliation"):
            DurableEventEffects(store)
        unchanged = store.rows(
            "SELECT effect_key,status FROM ha_native_effect ORDER BY effect_key"
        )
        assert unchanged == [
            {"effect_key": "duplicate", "status": "uncertain"},
            {"effect_key": "first", "status": "uncertain"},
        ]
    finally:
        store.close()


def test_uncertain_recovery_finds_receipt_after_large_unrelated_native_history(owner):
    store, task, event, epoch, inbox, controller, effects = owner
    effects.enqueue(task["id"], "history", event["event_id"])
    claim = effects.claim(task["id"], "native.chat", epoch)
    effects.interrupted(task["id"], "native.chat", epoch, "history",
                        claim["generation"], definitely_not_sent=False)
    for number in range(75):
        _valid_receipt(controller, task["id"], event["event_id"] + 1000 + number,
                       f"unrelated-{number:03d}")
    match = _valid_receipt(controller, task["id"], event["event_id"],
                           "matching-later")
    # 65 earlier unrelated validated messages must not indefinitely block
    # safe local receipt reconciliation for the original single event.
    assert effects.reconcile_uncertain(
        task["id"], "native.chat", epoch, "history"
    ) == "delivered"
    assert effects.status(task["id"])[0]["receipt_id"] == match


def test_uncertain_recovery_detects_two_matching_receipts_across_many_pages(owner):
    store, task, event, epoch, inbox, controller, effects = owner
    effects.enqueue(task["id"], "two-matches", event["event_id"])
    claim = effects.claim(task["id"], "native.chat", epoch)
    effects.interrupted(task["id"], "native.chat", epoch, "two-matches",
                        claim["generation"], definitely_not_sent=False)
    _valid_receipt(controller, task["id"], event["event_id"], "early-match")
    for number in range(73):
        _valid_receipt(controller, task["id"], event["event_id"] + 2000 + number,
                       f"noise-{number:03d}")
    _valid_receipt(controller, task["id"], event["event_id"], "late-match")
    with pytest.raises(Blocked, match="Multiple validated"):
        effects.reconcile_uncertain(
            task["id"], "native.chat", epoch, "two-matches"
        )
    assert effects.status(task["id"])[0]["status"] == "uncertain"


def test_validated_request_with_only_guessed_event_id_does_not_prove_delivery(owner):
    store, task, event, epoch, inbox, controller, effects = owner
    effects.enqueue(task["id"], "envelope", event["event_id"])
    lease = effects.claim(task["id"], "native.chat", epoch)
    fake = "guessed-int-only"
    controller.prepare_message(
        task["id"], "native.chat", "https://example.invalid/chat",
        {"body": {"event_inputs": [{"event_id": event["event_id"]}]}},
        fake,
    )
    controller.message_state(fake, "validated", '{"type":"step_intent"}')
    with pytest.raises(Blocked, match="complete event envelope"):
        effects.finalize(
            task["id"], "native.chat", epoch, "envelope",
            lease["generation"], fake
        )
    assert inbox.pending(task["id"])
    verified = _valid_receipt(controller, task["id"], event["event_id"],
                              "complete-event-envelope")
    assert effects.finalize(
        task["id"], "native.chat", epoch, "envelope",
        lease["generation"], verified
    ) == "delivered"


def test_recovery_ignores_forged_event_id_only_not_exact_saved_envelope(owner):
    store, task, event, epoch, inbox, controller, effects = owner
    effects.enqueue(task["id"], "strict-recovery", event["event_id"])
    lease = effects.claim(task["id"], "native.chat", epoch)
    effects.interrupted(
        task["id"], "native.chat", epoch, "strict-recovery",
        lease["generation"], definitely_not_sent=False
    )
    fake = "forged-envelope-on-recovery"
    controller.prepare_message(
        task["id"], "native.chat", "https://example.invalid/chat",
        {"body": {"event_inputs": [
            {"event_id": event["event_id"], "kind": "ci_failed",
             "source": "unknown-mismatch", "summary": "Wrong event"}
        ]}},
        fake,
    )
    controller.message_state(fake, "validated", '{"type":"step_intent"}')
    assert effects.reconcile_uncertain(
        task["id"], "native.chat", epoch, "strict-recovery"
    ) == "pending"
    assert inbox.pending(task["id"])
    valid = _valid_receipt(controller, task["id"], event["event_id"],
                           "verified-envelope-on-recovery")
    assert effects.reconcile_uncertain(
        task["id"], "native.chat", epoch, "strict-recovery"
    ) == "delivered"
    assert effects.status(task["id"])[0]["receipt_id"] == valid
