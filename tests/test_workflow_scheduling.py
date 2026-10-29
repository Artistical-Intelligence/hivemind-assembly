"""Pending checks gate new native work, while retained work and repairs can finish."""
import asyncio

from test_context_reset import setup_team


def mark(team, task, name="draft.py", content="first"):
    from hivemind_assembly.core.common import file_hash
    root = team.broker.drafts.workspace(task["project_id"])
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    path.write_text(content)
    team.broker.drafts.checks.mark(task["project_id"], name, task["owner"], file_hash(path))


def test_waiting_checks_prevent_new_worker_dispatch_and_retry_next_tick(store, monkeypatch):
    team, task = setup_team(store)
    mark(team, task)
    calls = []

    async def waiting(project):
        calls.append(project)
        return {"waiting": "Checker unavailable", "failed": []}

    monkeypatch.setattr(team.independent, "run", waiting)
    asyncio.run(team.tick(task["id"]))
    asyncio.run(team.tick(task["id"]))
    assert len(calls) == 2
    assert not team.browser.calls
    assert team.store.task(task["id"])["status"] == "waiting_quota"


def test_running_check_yields_without_dispatch(store):
    team, task = setup_team(store)
    mark(team, task)
    team.independent.running.add(task["project_id"])
    assert asyncio.run(team.pending_checks_wait(task)) is True
    assert not team.browser.calls


def test_failed_batch_allows_repairs_and_changed_bytes_trigger_new_check(store, monkeypatch):
    team, task = setup_team(store)
    mark(team, task)
    calls = []

    async def failed(project):
        calls.append(project)
        return {"failed": ["draft.py"], "reports": ["checks/failure.md"]}

    monkeypatch.setattr(team.independent, "run", failed)
    assert asyncio.run(team.pending_checks_wait(task)) is False
    assert team.flow(task["id"])["last_result"]["independent_check"]["failed"] == ["draft.py"]
    assert asyncio.run(team.pending_checks_wait(task)) is False
    assert len(calls) == 1
    mark(team, task, content="repaired")
    assert asyncio.run(team.pending_checks_wait(task)) is False
    assert len(calls) == 2
    packet = team.workflow_packet(task, team.flow(task["id"]))
    assert packet["saver"] == "broker" and packet["repair"]["failed"] == ["draft.py"]


def test_retained_native_response_is_consumed_before_new_checks(store, monkeypatch):
    from hivemind_assembly.core.common import digest
    team, task = setup_team(store)
    mark(team, task)
    flow = team.flow(task["id"])
    key = "msg_" + digest({"task": task["id"], "flow": flow["seq"], "phase": flow["phase"], "route": task["owner"]})[:32]
    team.controller.prepare_message(task["id"], task["owner"], "https://example.invalid/old", {}, key)
    team.controller.message_state(key, "validated", '{"type":"step_intent"}')

    async def forbidden(project):
        raise AssertionError("retained response must be consumed first")

    monkeypatch.setattr(team.independent, "run", forbidden)
    assert asyncio.run(team.pending_checks_wait(task)) is False


def test_startup_and_completion_reconcile_even_without_pending_db_rows(store, monkeypatch):
    team, task = setup_team(store)
    calls = []

    def reconcile(project):
        calls.append(project)
        return {"changed": [], "pending": 0, "deferred": False}

    monkeypatch.setattr(team.broker.drafts, "reconcile", reconcile)
    asyncio.run(team.tick(task["id"]))
    assert calls
    before = len(calls)
    assert asyncio.run(team.completion_waits(store.task(task["id"]))) is False
    assert len(calls) == before + 1


def test_deferred_reconciliation_never_accepts_completion(store, monkeypatch):
    team, task = setup_team(store)
    monkeypatch.setattr(team.broker.drafts, "reconcile", lambda project: {"deferred": True})
    assert asyncio.run(team.completion_waits(task)) is True
    assert asyncio.run(team.pending_checks_wait(task)) is True


def test_unrelated_unresolved_delivery_does_not_allow_new_dispatch(store):
    team, task = setup_team(store)
    team.controller.prepare_message(task["id"], "adviser.extra", "https://example.invalid/other", {}, "other-turn")
    assert asyncio.run(team.pending_checks_wait(task)) is True
    assert not team.browser.calls


def test_retained_tool_batch_drains_before_pending_checks(store, monkeypatch):
    team, task = setup_team(store)
    mark(team, task)
    team.save_flow(task["id"], {**team.flow(task["id"]), "phase": "batch"})

    async def forbidden(project):
        raise AssertionError("retained batch must drain first")

    monkeypatch.setattr(team.independent, "run", forbidden)
    assert asyncio.run(team.pending_checks_wait(task)) is False
