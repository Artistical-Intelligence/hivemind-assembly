import asyncio
import json
import time
from pathlib import Path

import pytest
from hivemind_assembly.core.goals import Goals, GoalStopped
from hivemind_assembly.core.common import Blocked, Conflict
from hivemind_assembly.core.store import Store
from hivemind_assembly.core.controller import Controller
from hivemind_assembly.core.acceptance import Acceptance
from workbench.broker import Broker
from hivemind_assembly.automation.team import NativeTeam
from hivemind_assembly.automation.policy import Availability, Window
from test_team import RecordingHost, FixtureNative


def test_goal_restart_budget_idempotency_and_shared_children(store):
    task = store.create_project("goal", "Recover the program")
    goals = Goals(store)
    goals.command(task["id"], "/goal")
    goals.command(task["id"], "/goal budget 2")
    goals.reserve(task["id"], "request1")
    reopened = Store(store.root)
    try:
        resumed = Goals(reopened)
        resumed.reserve(task["id"], "request1")
        assert resumed.status(task["id"])["turns"] == 1
        with store.tx() as db:
            db.execute(
                "INSERT INTO tasks(id,project_id,objective,updated) VALUES('child',?,'child',?)",
                (task["project_id"], time.time()),
            )
        resumed.reserve("child", "request2")
        with pytest.raises(GoalStopped, match="exhausted"):
            resumed.reserve("child", "request3")
        assert goals.status(task["id"])["status"] == "exhausted"
        with pytest.raises(Blocked):
            goals.command(task["id"], "/goal resume")
        goals.command(task["id"], "/goal budget 3")
        goals.command(task["id"], "/goal resume")
        goals.reserve("child", "request3")
        assert goals.status(task["id"])["turns"] == 3
        with pytest.raises(Conflict):
            goals.command("child", "/goal pause")
    finally:
        reopened.close()


def test_goal_pause_clear_and_immutable_objective(store):
    t = store.create_project("goal", "Old objective")
    g = Goals(store)
    assert g.command(t["id"], "/goal New objective")["objective"] == "New objective"
    assert store.task(t["id"])["objective"] == "New objective"
    for command in ("pause", "clear"):
        g.command(t["id"], "/goal " + command)
        assert not g.runnable(t["id"])
        with pytest.raises(GoalStopped):
            g.reserve(t["id"], "request")
        g.command(t["id"], "/goal resume")
    with pytest.raises(Conflict):
        g.command(t["id"], "/goal Silently replace scope")


def test_native_goal_continues_to_actual_acceptance(store):
    cfg = json.loads(
        (Path(__file__).parents[1] / "_app/config/default.json").read_text()
    )
    for name in cfg["routes"]:
        cfg["routes"][name]["conversation_url"] = "https://example.invalid/" + name
    c = Controller(store)
    broker = Broker(c, cfg)
    native = FixtureNative()
    team = NativeTeam(c, broker, native, cfg)
    team.host = RecordingHost()
    for route in ("worker.opus", "adviser.extra"):
        team.observations[route] = Availability(
            route, True, True, False, time.time(), [Window("daily", 50)]
        )
    task = store.create_project("goal", "Compare equivalent regions")
    root = broker.workspace(task["id"])
    (root / "original.hex").write_text("89f801f0")
    (root / "candidate.hex").write_text("8d0437")
    Acceptance(c, broker).configure(
        task["id"],
        {
            "scope": "x86_64_register_regions",
            "checks": [
                {
                    "original_path": "original.hex",
                    "candidate_path": "candidate.hex",
                    "original_format": "hex",
                    "candidate_format": "hex",
                }
            ],
        },
    )
    team.goals.command(task["id"], "/goal")
    team.goals.command(task["id"], "/goal budget 1")

    async def run():
        await team.supervise(task["id"])
        await team.supervise(task["id"])
        assert len(native.calls) == 1
        assert team.goals.status(task["id"])["status"] == "exhausted"
        team.goals.command(task["id"], "/goal budget 20")
        team.goals.command(task["id"], "/goal resume")
        for _ in range(6):
            await team.supervise(task["id"])

    asyncio.run(run())
    assert store.task(task["id"])["status"] == "accepted"
    assert team.goals.status(task["id"])["status"] == "achieved"
    assert "standing_goal" in json.loads(team.host.messages[0][3])
