"""Deterministic watchdog tests: no AI calls, no automatic retasking."""

import pytest

from hivemind_assembly.automation.event_inbox import NativeEventInbox
from hivemind_assembly.automation.progress_watchdog import ProgressWatchdog
from hivemind_assembly.core.store import Store
from hivemind_assembly.core.common import ContractError


def _turn(store, task_id, number):
    with store.tx() as db:
        db.execute(
            """INSERT INTO messages
               (id,task_id,route,conversation,payload_hash,payload,state,
                response,created,updated)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (f"msg_{number}", task_id, "worker.chat", "chat-a",
             f"hash-{number}", "{}", "validated", '{"type":"step_intent"}',
             float(number), float(number)),
        )


def _operation(store, task_id, number):
    with store.tx() as db:
        db.execute(
            """INSERT INTO operations
               (id,task_id,owner,epoch,revision,tool,payload_hash,args,
                state,result,created,updated)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (f"op_{number}", task_id, "worker.chat", 1, 0,
             "test", f"hash-{number}", "{}", "completed", "{}",
             float(number), float(number)),
        )


@pytest.fixture
def env(tmp_path):
    store = Store(tmp_path)
    task = store.create_project("watch", "Use an existing local browser route")
    with store.tx() as db:
        db.execute(
            "UPDATE tasks SET owner='worker.chat',status='running' WHERE id=?",
            (task["id"],),
        )
    inbox = NativeEventInbox(store)
    inbox.subscribe(task["id"], "project:" + task["project_id"])
    try:
        yield store, task, inbox, ProgressWatchdog(store, inbox)
    finally:
        store.close()


def test_watchdog_signals_unproductive_turns_once_and_never_changes_task(env):
    store, task, inbox, watchdog = env
    assert watchdog.scan(task["project_id"], threshold=2, now=100) == []
    _turn(store, task["id"], 1)
    assert watchdog.scan(task["project_id"], threshold=2, now=101) == []
    _turn(store, task["id"], 2)
    alerts = watchdog.scan(task["project_id"], threshold=2, now=102)
    assert len(alerts) == 1
    assert alerts[0]["status"] == "needs_review"
    assert "possible_stall" in [x["kind"] for x in inbox.pending(task["id"])]
    assert watchdog.scan(task["project_id"], threshold=2, now=500) == []
    assert store.task(task["id"])["owner"] == "worker.chat"
    assert store.task(task["id"])["status"] == "running"
    _operation(store, task["id"], 1)
    assert watchdog.scan(task["project_id"], threshold=2, now=600) == []
    _turn(store, task["id"], 3)
    assert watchdog.scan(task["project_id"], threshold=2, now=610) == []


def test_no_turn_is_not_a_fabricated_stall_and_approved_work_is_not_modified(env):
    store, task, inbox, watchdog = env
    assert watchdog.scan(task["project_id"], now=3) == []
    assert watchdog.scan(task["project_id"], now=400) == []
    store.state(task["id"], "paused")
    _turn(store, task["id"], 10)
    _turn(store, task["id"], 11)
    _turn(store, task["id"], 12)
    assert watchdog.scan(task["project_id"], now=450) == []
    assert inbox.pending(task["id"], 20) == []


def test_watchdog_filters_non_chat_routes_and_rejects_bad_thresholds(env):
    store, task, inbox, watchdog = env
    watchdog.scan(task["project_id"], now=1, allowed_owners=frozenset({"worker.work"}))
    _turn(store, task["id"], 20)
    _turn(store, task["id"], 21)
    assert watchdog.scan(
        task["project_id"], threshold=2, now=100,
        allowed_owners=frozenset({"worker.work"})
    ) == []
    with pytest.raises(ContractError):
        watchdog.scan(task["project_id"], threshold=1)
    with pytest.raises(ContractError):
        watchdog.scan(task["project_id"], cooldown_seconds=-5)


def test_watchdog_same_owner_new_lease_epoch_resets_stall_evidence(env):
    """A renewed lease is a new observation epoch, even for the same route.

    Old, validated model turns must not be counted toward a new lease's stall
    threshold; watchdog remains advisory and never mutates the task owner.
    """
    store, task, inbox, watchdog = env
    assert watchdog.scan(task["project_id"], threshold=2, now=100) == []
    _turn(store, task["id"], 301)
    _turn(store, task["id"], 302)
    assert len(watchdog.scan(task["project_id"], threshold=2, now=101)) == 1
    original = store.task(task["id"])
    with store.tx() as db:
        db.execute("UPDATE tasks SET epoch=epoch+1 WHERE id=?", (task["id"],))
    assert watchdog.scan(task["project_id"], threshold=2, now=102) == []
    _turn(store, task["id"], 303)
    assert watchdog.scan(task["project_id"], threshold=2, now=103) == []
    _turn(store, task["id"], 304)
    assert len(watchdog.scan(task["project_id"], threshold=2, now=104)) == 1
    current = store.task(task["id"])
    assert current["epoch"] == original["epoch"] + 1
    assert current["owner"] == original["owner"]
    assert current["status"] == original["status"]
    assert [x["kind"] for x in inbox.pending(task["id"])].count(
        "possible_stall"
    ) == 2
