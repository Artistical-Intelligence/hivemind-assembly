import asyncio
import json
import time
from pathlib import Path
import pytest
from hivemind_assembly.core.acceptance import Acceptance
from hivemind_assembly.core.controller import Controller
from hivemind_assembly.core.broker import Broker
from hivemind_assembly.core.common import Blocked, Conflict
from hivemind_assembly.domains.reverse_engineering.domain import (
    ReverseEngineeringDomain,
)
from hivemind_assembly.automation.team import NativeTeam
from hivemind_assembly.automation.policy import Availability, Window


def setup(store):
    controller = Controller(store)
    broker = Broker(controller, {}, ReverseEngineeringDomain())
    task = store.create_project("Regions", "Recover equivalent arithmetic", paused=True)
    root = broker.workspace(task["id"])
    (root / "original.hex").write_text("89f801f0")
    contract = {
        "scope": "x86_64_register_regions",
        "checks": [
            {
                "original_path": "original.hex",
                "candidate_path": "candidate.hex",
                "original_format": "hex",
                "candidate_format": "hex",
                "inputs": ["RDI", "RSI"],
                "outputs": ["RAX"],
            }
        ],
    }
    acceptance = Acceptance(controller, broker)
    acceptance.configure(task["id"], contract)
    store.state(task["id"], "queued")
    epoch = controller.acquire(task["id"], "worker.opus")
    controller.brief(
        task["id"],
        {"revision": 0},
        {"procedure": "Check region", "acceptance": "Prove RAX"},
        {"critical_gaps": []},
        [],
    )
    broker.execute(
        {
            "id": "check",
            "task_id": task["id"],
            "owner": "worker.opus",
            "epoch": epoch,
            "revision": 0,
            "tool": "check_equivalence",
            "args": {"original_hex": "89f801f0", "candidate_hex": "8d0437"},
        }
    )
    return acceptance, controller, broker, store.task(task["id"]), contract


@pytest.mark.parametrize(
    "candidate,accepted",
    [("8d0437", True), ("89f829f0", False), ("not hex", False), ("", False)],
)
def test_actual_candidate_decides_acceptance(store, candidate, accepted):
    acceptance, _, broker, task, _ = setup(store)
    (broker.workspace(task["id"]) / "candidate.hex").write_text(candidate)
    result = acceptance.evaluate(
        task, {"result_operations": ["check"], "summary": "Everything passes"}
    )
    assert result["passed"] is accepted
    assert store.task(task["id"])["status"] == ("accepted" if accepted else "running")
    # The cited operation always passed; the independently read file governs.
    assert (
        json.loads(
            store.one("SELECT result FROM operations WHERE id='check'")["result"]
        )["result"]
        == "UNSAT"
    )


def test_original_is_pinned_and_contract_cannot_be_replaced(store):
    acceptance, _, broker, task, contract = setup(store)
    root = broker.workspace(task["id"])
    (root / "original.hex").write_text("89f829f0")
    (root / "candidate.hex").write_text("8d0437")
    with pytest.raises(Blocked):
        acceptance.configure(task["id"], contract)
    assert acceptance.evaluate(task, {"result_operations": ["check"]})["passed"]


@pytest.mark.parametrize("change", ["pause", "revision", "file"])
def test_acceptance_rejects_concurrent_changes(store, monkeypatch, change):
    acceptance, _, broker, task, _ = setup(store)
    candidate = broker.workspace(task["id"]) / "candidate.hex"
    candidate.write_text("8d0437")
    verifier = broker.domain.acceptance
    original = verifier.verify

    def race(*args):
        result = original(*args)
        if change == "pause":
            store.state(task["id"], "paused")
        elif change == "revision":
            with store.tx() as c:
                c.execute("UPDATE projects SET revision=revision+1")
        else:
            candidate.write_text("89f829f0")
        return result

    monkeypatch.setattr(verifier, "verify", race)
    with pytest.raises((Blocked, Conflict)):
        acceptance.evaluate(task, {"result_operations": ["check"]})
    assert store.task(task["id"])["status"] != "accepted"


def test_missing_or_foreign_operation_cannot_complete(store):
    acceptance, _, _, task, _ = setup(store)
    with pytest.raises(Blocked):
        acceptance.evaluate(task, {"result_operations": ["not-this-task"]})


def test_failed_completion_returns_evidence_and_bounds_retries(store):
    _, controller, broker, task, _ = setup(store)
    (broker.workspace(task["id"]) / "candidate.hex").write_text("89f829f0")
    team = NativeTeam(controller, broker, None, {"routes": {}})
    for attempt in range(3):
        result = team.acceptance(
            task, {"request_id": str(attempt), "result_operations": ["check"]}
        )
        assert result["status"] == "rejected"
        assert team.flow(task["id"])["phase"] == "intent"
        assert (
            team.flow(task["id"])["last_result"]["acceptance"]["checks"][0]["proof"][
                "result"
            ]
            == "SAT"
        )
        assert store.task(task["id"])["status"] == (
            "running" if attempt < 2 else "waiting_dependency"
        )


def test_rejected_completion_is_idempotent(store):
    acceptance, _, broker, task, _ = setup(store)
    (broker.workspace(task["id"]) / "candidate.hex").write_text("89f829f0")
    response = {"result_operations": ["check"]}
    first = acceptance.evaluate(task, response)
    assert acceptance.evaluate(task, response) == first
    assert len(store.rows("SELECT * FROM records WHERE kind='acceptance_result'")) == 1


def test_native_team_file_proof_acceptance_and_learning_loop(store):
    cfg = json.loads(
        (Path(__file__).parents[1] / "_app/config/default.json").read_text()
    )
    for route in cfg["routes"]:
        cfg["routes"][route]["conversation_url"] = "https://example.invalid/" + route
    controller = Controller(store)
    broker = Broker(controller, cfg, ReverseEngineeringDomain())
    task = store.create_project(
        "Full loop", "Recover the bounded addition region", paused=True
    )
    (broker.workspace(task["id"]) / "original.hex").write_text("89f801f0")
    Acceptance(controller, broker).configure(
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
    store.state(task["id"], "queued")

    class Host:
        def record(self, *args):
            pass

    class Native:
        async def exchange(self, route, message):
            response = await self.response(route, message)
            controller.message_state(message["id"], "validated", json.dumps(response))
            return response

        async def response(self, route, message):
            body = json.loads(message["payload"])["body"]
            common = {"request_id": message["id"]}
            if "catalog" in body:
                return {
                    **common,
                    "type": "knowledge_scope",
                    "tags": [],
                    "catalog_revision": body["catalog"]["revision"],
                }
            if route.startswith("adviser"):
                return {
                    **common,
                    "type": "brief",
                    "brief": {
                        "procedure": "Recover bytes",
                        "acceptance": "Pinned original proof",
                    },
                    "obligations": [],
                }
            if body.get("last_result"):
                return {
                    **common,
                    "type": "complete",
                    "result_operations": [body["last_result"]["operation_id"]],
                }
            if body.get("instruction"):
                return {
                    **common,
                    "type": "step_intent",
                    "intent": {"goal": "Write candidate", "method": "Equivalent LEA"},
                }
            return {
                **common,
                "type": "tool_request",
                "tool": "write_file",
                "args": {
                    "path": "candidate.hex",
                    "expected_hash": None,
                    "text": "8d0437",
                },
            }

    checked = []

    class Checker:
        config = cfg

        async def exchange(self, route, message):
            response = await self.response(route, message)
            controller.message_state(message["id"], "validated", json.dumps(response))
            return response

        async def response(self, route, message):
            body = json.loads(message["payload"])
            checked.append((route, [f["path"] for f in body["files"]]))
            return {"request_id": message["id"], "type": "check_report", "summary": "Bytes match the proof.",
                    "results": [{"path": f["path"], "verdict": "pass", "findings": "Equivalent LEA."}
                                for f in body["files"]]}

    class Sessions:
        async def ensure(self, *args, **kwargs):
            pass

        async def isolated_browser(self, key, route, identity):
            return Checker()

        async def release_isolated(self, identity):
            pass

    team = NativeTeam(controller, broker, Native(), cfg)
    team.host = Host()
    team.sessions = Sessions()
    for route in cfg["routes"]:
        team.observations[route] = Availability(
            route, True, True, False, time.time(), [Window("daily", 50)]
        )

    async def run():
        for _ in range(8):
            await team.tick(task["id"])

    asyncio.run(run())
    assert store.task(task["id"])["status"] == "accepted"
    # The written file was checked by another provider before acceptance; its markers are gone.
    writer = store.one("SELECT owner FROM operations WHERE tool='write_file'")["owner"]
    assert checked and checked[0][1] == ["candidate.hex"]
    assert cfg["routes"][checked[0][0]]["provider"] != cfg["routes"][writer]["provider"]
    root = broker.workspace(task["id"])
    assert not (root / "STATUS.md").exists() and "Nothing is waiting" in (root / "CHECKS_STATUS.md").read_text()
    assert [p.name for p in (root / "checks").iterdir()][0].endswith(".md")
    lessons = store.rows("SELECT kind,status FROM lessons")
    assert {r["kind"] for r in lessons} == {"knowledge", "procedure"}
    assert all(r["status"] == "candidate" for r in lessons)
    assert (broker.workspace(task["id"]) / "original.hex").read_text() == "89f801f0"
