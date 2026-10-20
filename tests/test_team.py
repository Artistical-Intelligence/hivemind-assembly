import asyncio, json, time
from pathlib import Path
from workbench.controller import Controller
from workbench.broker import Broker
from workbench.team import NativeTeam
from workbench.policy import Availability, Window


class RecordingHost:
    def __init__(self):
        self.messages = []

    def record(self, *args):
        self.messages.append(args)


class FixtureNative:
    def __init__(self):
        self.calls = []

    async def exchange(self, route, m):
        self.calls.append(route)
        p = json.loads(m["payload"])
        body = p["body"]
        x = {"request_id": m["id"]}
        if route == "adviser.extra":
            return {
                **x,
                "type": "brief",
                "brief": {
                    "procedure": "Prove bounded integer output equivalence",
                    "acceptance": "UNSAT under exact register model",
                },
                "obligations": [],
            }
        if "instruction" in body:
            return {
                **x,
                "type": "step_intent",
                "intent": {
                    "goal": "Compare equivalent add implementations",
                    "method": "bitvector proof",
                    "checks": ["UNSAT"],
                },
            }
        if body.get("last_result"):
            return {
                **x,
                "type": "complete",
                "result_operations": [body["last_result"]["operation_id"]],
                "summary": "Region proof only",
            }
        return {
            **x,
            "type": "tool_request",
            "tool": "check_equivalence",
            "args": {"original_hex": "89f801f0", "candidate_hex": "8d0437"},
        }


def test_durable_brief_execute_result_loop(store):
    cfg = json.loads(
        (Path(__file__).parents[1] / "_app/config/default.json").read_text()
    )
    for route in cfg["routes"]:
        cfg["routes"][route]["conversation_url"] = "https://example.invalid/" + route
    c = Controller(store)
    broker = Broker(c, cfg)
    native = FixtureNative()
    team = NativeTeam(c, broker, native, cfg)
    team.host = RecordingHost()
    team.observations["worker.opus"] = Availability(
        "worker.opus", True, True, False, time.time(), [Window("daily", 50)]
    )
    team.observations["adviser.extra"] = Availability(
        "adviser.extra", True, True, False, time.time(), [Window("daily", 50)]
    )
    t = store.create_project("fixture", "Compare the named scalar arithmetic regions")

    async def run():
        for _ in range(6):
            await team.tick(t["id"])

    asyncio.run(run())
    assert store.task(t["id"])["status"] == "awaiting_acceptance"
    assert native.calls[:3] == ["worker.opus", "adviser.extra", "worker.opus"]
    op = store.one("SELECT * FROM operations")
    assert json.loads(op["result"])["status"] == "region_proved"
    assert len(team.host.messages) == 8


def test_promotion_retains_flow_and_rebriefs(store):
    cfg = json.loads(
        (Path(__file__).parents[1] / "_app/config/default.json").read_text()
    )
    for r in cfg["routes"]:
        cfg["routes"][r]["conversation_url"] = "https://example.invalid/" + r
    c = Controller(store)
    b = Broker(c, cfg)
    n = FixtureNative()
    team = NativeTeam(c, b, n, cfg)
    team.host = RecordingHost()
    for route in ("worker.opus", "worker.extra"):
        team.observations[route] = Availability(
            route, True, True, False, time.time(), [Window("daily", 50)]
        )
    t = store.create_project("x", "y")
    old = c.acquire(t["id"], "worker.extra")
    team.save_flow(
        t["id"],
        {
            "seq": 2,
            "phase": "tool",
            "request": {"stale": True},
            "last_result": {"saved": "retained"},
        },
    )
    asyncio.run(team.tick(t["id"]))
    assert store.task(t["id"])["owner"] == "worker.opus"
    assert store.task(t["id"])["epoch"] > old
    assert team.flow(t["id"])["phase"] == "brief"


def test_retained_reply_survives_conversation_renewal_without_new_send(store):
    from hivemind_assembly.core.common import digest

    cfg = json.loads(
        (Path(__file__).parents[1] / "_app/config/default.json").read_text()
    )
    route = "worker.extra"
    cfg["routes"][route]["conversation_url"] = "https://chatgpt.com/c/replacement"
    c = Controller(store)
    task = store.create_project("recovery", "consume the saved result")
    c.acquire(task["id"], route)
    task = store.task(task["id"])
    flow = {"seq": 4, "phase": "tool"}
    key = (
        "msg_"
        + digest({"task": task["id"], "flow": 4, "phase": "tool", "route": route})[:32]
    )
    message = c.prepare_message(
        task["id"], route, "https://chatgpt.com/c/original", {"revision": 0}, key
    )
    response = {
        "request_id": key,
        "type": "complete",
        "summary": "saved before renewal",
    }
    c.message_state(message["id"], "validated", json.dumps(response))

    class Sessions:
        async def ensure(self, *args):
            raise AssertionError("A validated turn must not trigger renewal")

    native = FixtureNative()
    team = NativeTeam(c, Broker(c, cfg), native, cfg)
    team.sessions = Sessions()
    assert asyncio.run(team.ask(task, flow, route, {})) == response
    assert native.calls == []
