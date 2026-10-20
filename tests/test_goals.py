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


def test_goal_runs_protected_native_captures_to_independent_acceptance(store):
    from hivemind_assembly.core.broker import Broker as CoreBroker
    from hivemind_assembly.core.test_acceptance import NativeTestAcceptance
    from test_observations import capture_suite

    class CaptureNative(FixtureNative):
        async def exchange(self, route, message):
            response = await super().exchange(route, message)
            if response["type"] == "tool_request":
                response.update(tool="test_programs", args={})
            return response

    cfg = json.loads(
        (Path(__file__).parents[1] / "_app/config/default.json").read_text()
    )
    for name in cfg["routes"]:
        cfg["routes"][name]["conversation_url"] = "https://example.invalid/" + name
    controller = Controller(store)
    broker = CoreBroker(controller, cfg)
    task = store.create_project(
        "capture goal", "Reconstruct an RGBA frame", continuation=True
    )
    (broker.workspace(task["id"]) / "candidate.py").write_text(
        "from pathlib import Path;Path('capture').write_bytes(bytes([1,0,0,255]))"
    )
    spec = {"scope": "native_tool_tests", "suite": capture_suite()}
    verifier = NativeTestAcceptance(store)
    verifier.allow(task["project_id"], True)
    verifier.authorize_recipe(task["project_id"], spec)
    Acceptance(controller, broker).configure(task["id"], spec)
    native = CaptureNative()
    team = NativeTeam(controller, broker, native, cfg)
    team.host = RecordingHost()
    for name in ("worker.opus", "adviser.extra"):
        team.observations[name] = Availability(
            name, True, True, False, time.time(), [Window("daily", 50)]
        )

    async def run():
        for _ in range(6):
            await team.supervise(task["id"])

    asyncio.run(run())
    assert store.task(task["id"])["status"] == "accepted"
    assert team.goals.status(task["id"])["status"] == "achieved"
    evidence = store.rows(
        "SELECT payload FROM records WHERE kind=?", ("native_test_run:" + task["id"],)
    )
    assert len(evidence) == 2  # Worker test and fresh independent acceptance run.
    result = json.loads(
        broker.artifacts.read(
            json.loads(evidence[-1]["payload"])["observations_artifact"],
            "evaluator",
            task["project_id"],
        )
    )
    assert result["task_id"] == task["id"] and result["passed"]
    assert not result["cases"][0]["comparisons"]["candidate"][0]["files"]["capture"][
        "exact"
    ]


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
    assert "standing_goal" in json.loads(team.host.messages[2][3])


def test_rejected_goal_uses_resumable_reviewer_request(store):
    c = Controller(store)
    broker = Broker(c, {})
    team = NativeTeam(c, broker, None, {"routes": {}, "foundations": {}})
    task = store.create_project("review", "Recover addition")
    root = broker.workspace(task["id"])
    (root / "original.hex").write_text("89f801f0")
    (root / "candidate.hex").write_text("89f829f0")
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
    epoch = c.acquire(task["id"], "worker.opus")
    c.brief(
        task["id"],
        {"revision": 0},
        {"procedure": "Check reconstruction", "acceptance": "Independent equivalence"},
        {"critical_gaps": []},
        [],
    )
    broker.execute(
        {
            "id": "checkpoint",
            "task_id": task["id"],
            "owner": "worker.opus",
            "epoch": epoch,
            "revision": 0,
            "tool": "checkpoint",
            "args": {"reason": "Candidate ready"},
        }
    )
    for i in range(3):
        result = team.acceptance(
            store.task(task["id"]),
            {"result_operations": ["checkpoint"], "summary": str(i)},
        )
        assert not result["passed"]
    flow = team.flow(task["id"])
    assert flow["phase"] == "recovery" and flow["failure"]
    assert store.task(task["id"])["status"] == "running"
    first = team.recovery.request(
        task["id"], flow["failure"], [], request_id="same-turn"
    )
    for _ in range(4):
        assert (
            team.recovery.request(
                task["id"], flow["failure"], [], request_id="same-turn"
            )
            == first
        )
    assert (
        len(
            store.rows(
                "SELECT * FROM records WHERE kind=?", ("recovery:" + task["id"],)
            )
        )
        == 1
    )


def test_explicit_unlimited_goal_retains_usage_without_exhausting(store):
    task = store.create_project("unlimited", "Continue until independently accepted")
    goals = Goals(store)
    goals.command(task["id"], "/goal")
    goals.command(task["id"], "/goal budget unlimited")
    with store.tx() as db:
        db.execute("UPDATE goals SET turns=100000 WHERE task_id=?", (task["id"],))
    goals.reserve(task["id"], "one-more")
    goals.command(task["id"], "/goal pause")
    goals.command(task["id"], "/goal resume")
    status = goals.status(task["id"])
    assert (
        status["unlimited"]
        and status["remaining_turns"] is None
        and status["turns"] == 100001
    )
    goals.command(task["id"], "/goal budget 10")
    with pytest.raises(GoalStopped):
        goals.reserve(task["id"], "bounded-again")


@pytest.mark.parametrize("change_after_worker_check", [False, True])
def test_goal_arm_program_rechecks_actual_files_before_completion(
    store, change_after_worker_check
):
    import os
    import shutil
    from hivemind_assembly.domains.reverse_engineering.program import build

    compiler = os.environ.get("HA_TEST_CLANG") or shutil.which("clang")
    if not compiler:
        pytest.skip("Clang and LLD required")
    cfg = json.loads(
        (Path(__file__).parents[1] / "_app/config/default.json").read_text()
    )
    cfg["foundations"]["c_compiler"] = compiler
    for name in cfg["routes"]:
        cfg["routes"][name]["conversation_url"] = "https://example.invalid/" + name
    controller = Controller(store)
    broker = Broker(controller, cfg)
    task = store.create_project("ARM program goal", "Recover a file transformer")
    root = broker.workspace(task["id"])
    source = """int ha_main(void){unsigned char b[32];long f=ha_open("input",0,0);
    long n=ha_file_read(f,b,32);ha_close(f);for(long i=0;i<n;i++)b[i]^=13;
    f=ha_open("result",577,384);ha_file_write(f,b,n);ha_close(f);return 0;}"""
    (root / "main.c").write_text(source)
    manifest = {"sources": ["main.c"]}
    built = build(root, {**manifest, "architecture": "aarch64"}, broker.jobs, compiler)
    assert built["passed"], built
    (root / "original.elf").write_bytes(bytes.fromhex(built["elf_hex"]))
    (root / "build.json").write_text(json.dumps(manifest))
    cases = [
        {
            "runtime": "qiling_linux",
            "files": {"/input": value.hex()},
            "effect_policy": "observable",
        }
        for value in (b"", bytes(range(32)))
    ]
    Acceptance(controller, broker).configure(
        task["id"],
        {
            "scope": "linux_program",
            "original_path": "original.elf",
            "manifest_path": "build.json",
            "cases": cases,
        },
    )

    class ProgramNative(FixtureNative):
        async def exchange(self, route, message):
            response = await super().exchange(route, message)
            if response["type"] == "tool_request":
                response.update(
                    tool="compare_program",
                    args={
                        "original_path": "original.elf",
                        "manifest_path": "build.json",
                        "cases": cases,
                    },
                )
            elif response["type"] == "complete" and change_after_worker_check:
                (root / "main.c").write_text(source.replace("^=13", "^=12"))
            return response

    team = NativeTeam(controller, broker, ProgramNative(), cfg)
    team.host = RecordingHost()
    for name in ("worker.opus", "adviser.extra"):
        team.observations[name] = Availability(
            name, True, True, False, time.time(), [Window("daily", 50)]
        )
    team.goals.command(task["id"], "/goal")
    team.goals.command(task["id"], "/goal budget unlimited")

    async def run():
        for _ in range(6):
            await team.supervise(task["id"])

    asyncio.run(run())
    operations = store.rows(
        "SELECT result FROM operations WHERE tool='compare_program'"
    )
    assert len(operations) == 1 and json.loads(operations[0]["result"])["passed"]
    assert (
        store.task(task["id"])["status"] == "accepted"
    ) is not change_after_worker_check
    assert (
        team.goals.status(task["id"])["status"] == "achieved"
    ) is not change_after_worker_check


def test_structured_objective_is_text_not_a_command(store):
    from hivemind_assembly.core.common import ContractError

    task = store.create_project("structured", "old", paused=True)
    goals = Goals(store)
    result = goals.control(task["id"], "start", objective="pause", max_turns=0)
    assert result["objective"] == "pause" and result["unlimited"]
    assert result["status"] == "active"
    assert goals.control(task["id"], "start", objective="pause")["id"] == result["id"]
    for invalid in (True, -1, 100001, "unlimited"):
        with pytest.raises(ContractError):
            goals.control(task["id"], "budget", max_turns=invalid)
    with pytest.raises(ContractError):
        goals.control(task["id"], "pause", objective="other")


def test_project_and_automatic_objective_share_one_transaction(store, monkeypatch):
    original = Goals.prepare

    def fail(self, task_id, db):
        original(self, task_id, db)
        raise RuntimeError("crash before project commit")

    monkeypatch.setattr(Goals, "prepare", fail)
    with pytest.raises(RuntimeError):
        store.create_project("interrupted", "build", paused=True, continuation=True)
    assert not store.rows("SELECT * FROM projects")
    assert not store.rows("SELECT * FROM tasks")
    assert not store.rows("SELECT * FROM goals")
