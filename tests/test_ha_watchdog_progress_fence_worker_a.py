"""Worker A synthetic Store/SQLite watchdog progress-admission race regressions.

No browser, provider, model API, GitHub Actions or automatic retasking.
Source-pinned tests require execution and qualified independent review.
"""

import time

import pytest

from hivemind_assembly.automation.event_inbox import NativeEventInbox
from hivemind_assembly.automation.progress_watchdog import ProgressWatchdog
from hivemind_assembly.core.common import ContractError
from hivemind_assembly.core.store import Store


OWNER = "worker.chat"


def _scope(tmp_path):
    store = Store(tmp_path)
    task = store.create_project("watchdog-progress-fence", "Check current work")
    with store.tx() as db:
        db.execute(
            """UPDATE tasks SET owner=?,epoch=1,status='running',
               lease_until=? WHERE id=?""",
            (OWNER, time.time() + 3600, task["id"]),
        )
    return store, task, NativeEventInbox(store)


def _turn(store, task, number):
    with store.tx() as db:
        db.execute(
            """INSERT INTO messages
               (id,task_id,route,conversation,payload_hash,payload,state,
                response,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (f"watch_turn_{number}", task["id"], OWNER, "chat-a",
             f"turn-hash-{number}", "{}", "validated",
             '{"type":"step_intent"}', float(number), float(number)),
        )


def _operation(store, task, number):
    with store.tx() as db:
        db.execute(
            """INSERT INTO operations
               (id,task_id,owner,epoch,revision,tool,payload_hash,args,
                state,result,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (f"watch_operation_{number}", task["id"], OWNER, 1, 0,
             "test", f"op-hash-{number}", "{}", "completed", "{}",
             float(number), float(number)),
        )


def _alert(task, source_id, progress):
    return dict(
        project_id=task["project_id"], source="watchdog", verified=True,
        source_id=source_id, thread="project:" + task["project_id"],
        kind="possible_stall", summary="Advisory: inspect retained work evidence",
        expected_task=(task["id"], OWNER, 1, "running"),
        expected_progress=progress,
    )


def _assert_no_trigger(store, task):
    assert store.rows(
        """SELECT id FROM ha_event_trigger WHERE project_id=?
           AND kind='possible_stall'""",
        (task["project_id"],),
    ) == []


def test_fresh_snapshot_admits_one_stall_and_deduplicates_after_restart(tmp_path):
    store, task, inbox = _scope(tmp_path)
    try:
        _turn(store, task, 1)
        _turn(store, task, 2)
        packet = _alert(task, "stall-fresh", (2, 0))
        assert inbox.receive(**packet) == "stored"
        assert NativeEventInbox(store).receive(**packet) == "duplicate"
        assert len(store.rows(
            "SELECT id FROM ha_event_trigger WHERE project_id=?",
            (task["project_id"],),
        )) == 1
    finally:
        store.close()


def test_completed_operation_after_snapshot_rejects_stale_stall(tmp_path):
    store, task, inbox = _scope(tmp_path)
    try:
        _turn(store, task, 1)
        _turn(store, task, 2)
        _operation(store, task, 1)
        assert inbox.receive(**_alert(task, "stale-operation", (2, 0))) == "stale"
        _assert_no_trigger(store, task)
    finally:
        store.close()


def test_validated_turn_after_snapshot_rejects_stale_stall(tmp_path):
    store, task, inbox = _scope(tmp_path)
    try:
        _turn(store, task, 1)
        _turn(store, task, 2)
        _turn(store, task, 3)
        assert inbox.receive(**_alert(task, "stale-new-turn", (2, 0))) == "stale"
        _assert_no_trigger(store, task)
    finally:
        store.close()


@pytest.mark.parametrize(
    "snapshot",
    [(-1, 0), (1, -1), (True, 0), (1, False), (1.0, 0),
     [1, 0], {"turns": 1}, (1,), (1, 0, 0)],
)
def test_malformed_progress_snapshot_is_fail_closed(tmp_path, snapshot):
    store, task, inbox = _scope(tmp_path)
    try:
        with pytest.raises(ContractError, match="progress snapshot"):
            inbox.receive(**_alert(task, "malformed-progress", snapshot))
        _assert_no_trigger(store, task)
    finally:
        store.close()


def test_watchdog_observation_race_does_not_emit_obsolete_alert(tmp_path):
    store, task, inbox = _scope(tmp_path)
    try:
        watchdog = ProgressWatchdog(store, inbox)
        assert watchdog.scan(task["project_id"], threshold=2, now=100) == []
        _turn(store, task, 1)
        _turn(store, task, 2)
        original = inbox.receive

        def work_completes_before_event_admission(**packet):
            if packet["kind"] == "possible_stall":
                _operation(store, task, 1)
            return original(**packet)

        inbox.receive = work_completes_before_event_admission
        assert watchdog.scan(task["project_id"], threshold=2, now=101) == []
        _assert_no_trigger(store, task)
        row = store.one(
            "SELECT last_alert_at FROM ha_progress_watch WHERE task_id=?",
            (task["id"],),
        )
        assert row["last_alert_at"] is None
        inbox.receive = original
        # The next scan sees the new operation and resets stagnation.
        assert watchdog.scan(task["project_id"], threshold=2, now=102) == []
        _turn(store, task, 3)
        _turn(store, task, 4)
        assert len(watchdog.scan(task["project_id"], threshold=2, now=103)) == 1
    finally:
        store.close()


def test_late_operation_does_not_poison_successor_cooldown(tmp_path):
    store, task, inbox = _scope(tmp_path)
    try:
        watchdog = ProgressWatchdog(store, inbox)
        watchdog.scan(task["project_id"], threshold=2, now=100)
        _turn(store, task, 1)
        _turn(store, task, 2)
        original = inbox.receive

        def work_completes_after_event_admission(**packet):
            result = original(**packet)
            if packet["kind"] == "possible_stall" and result == "stored":
                _operation(store, task, 1)
            return result

        inbox.receive = work_completes_after_event_admission
        # The advisory may already be durable, but a newer completion must
        # prevent stamping the old observation as a current cooldown.
        assert watchdog.scan(task["project_id"], threshold=2, now=101) == []
        row = store.one(
            "SELECT last_alert_at FROM ha_progress_watch WHERE task_id=?",
            (task["id"],),
        )
        assert row["last_alert_at"] is None
        assert len(store.rows(
            """SELECT id FROM ha_event_trigger
               WHERE project_id=? AND kind='possible_stall'""",
            (task["project_id"],),
        )) == 1
    finally:
        store.close()
