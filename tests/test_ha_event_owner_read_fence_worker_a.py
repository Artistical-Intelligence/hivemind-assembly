"""Worker A scoped SQLite owner-epoch read-race regressions.

No provider/browser, paid API, external credentials or RE-Wizard access.
These are local tests only. Verifier should independently review and collect
this module in the focused native-event workflow; tests do not prove live HA.
"""

import json
import time

import pytest

from hivemind_assembly.automation.event_inbox import NativeEventInbox
from hivemind_assembly.automation.progress_watchdog import ProgressWatchdog
from hivemind_assembly.automation.team import NativeTeam
from hivemind_assembly.core.common import ContractError
from hivemind_assembly.core.durable_effects import DurableEventEffects
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


def test_watchdog_admission_fences_current_generation_and_replay(setup):
    store, task, inbox, thread = setup
    _assign(store, task, "worker.first", 1)
    original = (task["id"], "worker.first", 1, "running")
    args = dict(
        project_id=task["project_id"], source="watchdog", verified=True,
        thread=thread, kind="possible_stall", summary="Advisory local review",
        expected_task=original,
    )
    assert inbox.receive(source_id="watchdog-valid", **args) == "stored"
    assert inbox.receive(source_id="watchdog-valid", **args) == "duplicate"
    _assign(store, task, "worker.second", 2)
    assert inbox.receive(source_id="watchdog-stale-owner", **args) == "stale"
    assert store.one(
        "SELECT COUNT(*) AS n FROM ha_event_trigger WHERE source_id=?",
        ("watchdog-stale-owner",),
    )["n"] == 0
    assert inbox.receive(
        source_id="watchdog-successor",
        **{**args, "expected_task": (task["id"], "worker.second", 2, "running")},
    ) == "stored"
    with store.tx() as db:
        db.execute(
            "UPDATE tasks SET status='paused' WHERE id=?", (task["id"],)
        )
    assert inbox.receive(
        source_id="watchdog-stopped",
        **{**args, "expected_task": (task["id"], "worker.second", 2, "running")},
    ) == "stale"
    assert store.one(
        "SELECT COUNT(*) AS n FROM ha_event_trigger WHERE source_id=?",
        ("watchdog-stopped",),
    )["n"] == 0


def test_stall_scan_transfer_during_admission_emits_no_stale_signal(
    setup, monkeypatch
):
    store, task, inbox, thread = setup
    _assign(store, task, "worker.first", 1)
    watchdog = ProgressWatchdog(store, inbox)
    assert watchdog.scan(task["project_id"], threshold=2, now=100) == []
    baseline = store.one(
        "SELECT updated_at FROM ha_progress_watch WHERE task_id=?", (task["id"],)
    )["updated_at"]
    assert watchdog.scan(task["project_id"], threshold=2, now=110) == []
    # A no-new-evidence poll is not a new progress observation.
    assert store.one(
        "SELECT updated_at FROM ha_progress_watch WHERE task_id=?", (task["id"],)
    )["updated_at"] == baseline
    with store.tx() as db:
        for index in (1, 2):
            db.execute(
                """INSERT INTO messages
                   (id,task_id,route,conversation,payload_hash,payload,state,
                    response,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (f"watch-turn-{index}", task["id"], "worker.first",
                 "local-fixture", f"hash-watch-{index}", "{}",
                 "validated", '{"type":"step_intent"}',
                 float(index), float(index)),
            )
    original_receive = inbox.receive

    def transfer_before_admission(**kwargs):
        _assign(store, task, "worker.second", 2)
        return original_receive(**kwargs)

    monkeypatch.setattr(inbox, "receive", transfer_before_admission)
    assert watchdog.scan(task["project_id"], threshold=2, now=120) == []
    assert store.one(
        "SELECT COUNT(*) AS n FROM ha_event_trigger WHERE source='watchdog'"
    )["n"] == 0
    # Re-observing the successor starts a fresh, non-stalling baseline.
    assert watchdog.scan(task["project_id"], threshold=2, now=130) == []


def test_receipt_health_monitor_rechecks_owner_before_alert(
    setup, monkeypatch
):
    store, task, inbox, thread = setup
    _assign(store, task, "worker.first", 1)
    inbox.subscribe(task["id"], thread, route="worker.first", epoch=1)
    _event(inbox, task, thread, "unresolved-delivery")
    effect = DurableEventEffects(store)
    pending = inbox.pending(task["id"], route="worker.first", epoch=1)
    assert effect.stage_pending(task["id"]) == [pending[0]["event_id"]]
    with store.tx() as db:
        db.execute(
            """UPDATE ha_native_effect SET status='uncertain',
               generation=1,lease_until=? WHERE task_id=?""",
            (time.time() - 30, task["id"]),
        )
    watchdog = ProgressWatchdog(store, inbox)
    original_receive = inbox.receive

    def transfer_before_receipt_alarm(**kwargs):
        _assign(store, task, "worker.second", 2)
        return original_receive(**kwargs)

    monkeypatch.setattr(inbox, "receive", transfer_before_receipt_alarm)
    assert watchdog.scan_delivery_health(
        task["project_id"],
        allowed_owners=frozenset({"worker.first", "worker.second"}),
    ) == []
    assert store.one(
        "SELECT COUNT(*) AS n FROM ha_event_trigger WHERE source='watchdog'"
    )["n"] == 0

    # A later fresh current-owner inspection may warn once; this is an
    # advisory, not permission to resend the uncertain browser exchange.
    monkeypatch.setattr(inbox, "receive", original_receive)
    assert len(watchdog.scan_delivery_health(
        task["project_id"],
        allowed_owners=frozenset({"worker.first", "worker.second"}),
    )) == 1
    assert watchdog.scan_delivery_health(
        task["project_id"],
        allowed_owners=frozenset({"worker.first", "worker.second"}),
    ) == []

def _health_effect_fixture(setup, status):
    """Stage a local receipt intent without launching a native browser turn."""
    store, task, inbox, thread = setup
    _assign(store, task, "worker.chat", 1)
    inbox.subscribe(task["id"], thread, route="worker.chat", epoch=1)
    _event(inbox, task, thread, "effect-state-race")
    effects = DurableEventEffects(store)
    event = inbox.pending(task["id"], route="worker.chat", epoch=1)[0]
    assert effects.stage_pending(task["id"]) == [event["event_id"]]
    with store.tx() as db:
        db.execute(
            """UPDATE ha_native_effect SET status=?,generation=1,
               lease_until=? WHERE task_id=?""",
            (status, time.time() - 20, task["id"]),
        )
    return ProgressWatchdog(store, inbox), event["event_id"]


def test_health_receipt_resolution_during_admission_is_not_reported(
    setup, monkeypatch
):
    store, task, inbox, _ = setup
    watchdog, event_id = _health_effect_fixture(setup, "uncertain")
    original_receive = inbox.receive

    def resolve_before_admission(**kwargs):
        # Simulate the atomic effect/delivery state change, not a browser ACK.
        with store.tx() as db:
            db.execute(
                """UPDATE ha_native_effect SET status='delivered',
                   lease_until=NULL WHERE task_id=?""", (task["id"],)
            )
            db.execute(
                """UPDATE ha_event_delivery SET read_at=?
                   WHERE task_id=? AND event_id=?""",
                (time.time(), task["id"], event_id),
            )
        return original_receive(**kwargs)

    monkeypatch.setattr(inbox, "receive", resolve_before_admission)
    assert watchdog.scan_delivery_health(task["project_id"]) == []
    assert store.one(
        "SELECT COUNT(*) AS n FROM ha_event_trigger WHERE source='watchdog'"
    )["n"] == 0


def test_health_receipt_generation_change_during_admission_is_fenced(
    setup, monkeypatch
):
    store, task, inbox, _ = setup
    watchdog, _ = _health_effect_fixture(setup, "uncertain")
    original_receive = inbox.receive

    def renew_generation_before_admission(**kwargs):
        with store.tx() as db:
            db.execute(
                """UPDATE ha_native_effect SET generation=2
                   WHERE task_id=?""", (task["id"],)
            )
        return original_receive(**kwargs)

    monkeypatch.setattr(inbox, "receive", renew_generation_before_admission)
    assert watchdog.scan_delivery_health(task["project_id"]) == []
    assert store.one(
        "SELECT COUNT(*) AS n FROM ha_event_trigger WHERE source='watchdog'"
    )["n"] == 0
    monkeypatch.setattr(inbox, "receive", original_receive)
    fresh = watchdog.scan_delivery_health(task["project_id"])
    assert len(fresh) == 1
    assert fresh[0]["effect_generation"] == 2


def test_health_effect_lease_renewal_during_admission_is_fenced(
    setup, monkeypatch
):
    store, task, inbox, _ = setup
    watchdog, _ = _health_effect_fixture(setup, "leased")
    original_receive = inbox.receive

    def renew_lease_before_admission(**kwargs):
        with store.tx() as db:
            db.execute(
                """UPDATE ha_native_effect SET lease_until=?
                   WHERE task_id=?""",
                (time.time() + 3600, task["id"]),
            )
        return original_receive(**kwargs)

    monkeypatch.setattr(inbox, "receive", renew_lease_before_admission)
    assert watchdog.scan_delivery_health(task["project_id"]) == []
    assert store.one(
        "SELECT COUNT(*) AS n FROM ha_event_trigger WHERE source='watchdog'"
    )["n"] == 0
    monkeypatch.setattr(inbox, "receive", original_receive)
    assert watchdog.scan_delivery_health(task["project_id"]) == []
