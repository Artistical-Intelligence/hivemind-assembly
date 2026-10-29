"""Native reset state-machine fixtures; these are not live provider acceptance."""
import asyncio
import json

import pytest

from hivemind_assembly.automation.context_reset import ContextResetYield, reset_context
from hivemind_assembly.automation.native import parse_response
from hivemind_assembly.core.common import Blocked, ContractError, Retryable
from test_coordination import make_team


def setup_team(store):
    class Native:
        calls = []

        async def exchange(self, route, message):
            payload = json.loads(message["payload"])
            self.calls.append((route, payload))
            response = ({"type": "context_reset", "method": "clear", "reason": "Condense this investigation",
                         "handoff": "Inspect the remaining function using the existing contract."}
                        if len(self.calls) == 1 else
                        {"type": "step_intent", "intent": {"goal": "Inspect", "method": "Read"}})
            response["request_id"] = message["id"]
            team.controller.message_state(message["id"], "validated", json.dumps(response))
            return response

    team = make_team(store, Native())
    task = store.create_project("Reset", "Inspect")
    team.scopes.select(task["id"], [], team.scopes.catalog()["revision"])
    team.controller.acquire(task["id"], "worker.opus")
    task = store.task(task["id"])

    class Sessions:
        calls = []
        committed = set()

        async def ensure(self, *args, **kwargs):
            pass

        def pending(self, route):
            return store.rows("SELECT id FROM messages WHERE route=? AND state NOT IN ('validated','invalid','cancelled')", (route,))

        async def renew(self, task, route, identity=None):
            if identity not in self.committed:
                self.calls.append(identity)
                self.committed.add(identity)
            team.config["routes"][route]["conversation_url"] = "https://example.invalid/new/" + identity

    team.sessions = Sessions()
    return team, task


def request():
    return {"request_id": "native-reset-request", "type": "context_reset", "method": "clear",
            "reason": "Long exploratory history", "handoff": "Keep the current contract; inspect only the unresolved call."}


def test_native_reset_resumes_same_phase_with_role_scoped_handoff(store):
    team, task = setup_team(store)
    original = {k: team.config["routes"][task["owner"]].get(k) for k in ("provider", "model", "mode", "effort", "profile")}

    async def run():
        await team.tick(task["id"])
        flow = team.flow(task["id"])
        assert flow["phase"] == "intent" and flow["seq"] == 1
        assert flow["context_reset_resume"]["effective_method"] == "new_chat"
        assert flow["context_reset_resume"]["clear_supported"] is False
        await team.tick(task["id"])

    asyncio.run(run())
    assert team.flow(task["id"])["phase"] == "brief"
    assert "context_reset_resume" not in team.flow(task["id"])
    assert len(team.sessions.calls) == 1
    assert team.browser.calls[0][1]["body"] == team.browser.calls[1][1]["body"]
    assert team.browser.calls[1][1]["context_reset"]["handoff"]["handoff"]
    assert team.browser.calls[1][1]["context_reset"]["allowed"] is False
    assert original == {k: team.config["routes"][task["owner"]].get(k) for k in original}


def test_crash_after_renewal_reuses_identity_and_preserves_adviser_payload(store, monkeypatch):
    team, task = setup_team(store)
    flow = {**team.flow(task["id"]), "phase": "brief_reading", "intent": {"goal": "Inspect"}}
    team.save_flow(task["id"], flow)
    payload = {"required_passages": {"private_source": "Adviser-only evidence"}}
    original = team.save_flow

    def crash(*args, **kwargs):
        raise RuntimeError("crash after native commit")

    monkeypatch.setattr(team, "save_flow", crash)
    with pytest.raises(RuntimeError):
        asyncio.run(reset_context(team, task, flow, "adviser.extra", payload, request()))
    monkeypatch.setattr(team, "save_flow", original)
    with pytest.raises(ContextResetYield):
        asyncio.run(reset_context(team, task, team.flow(task["id"]), "adviser.extra", payload, request()))
    resumed = team.flow(task["id"])
    assert resumed["phase"] == "brief_reading"
    assert resumed["context_reset_resume"]["payload"] == payload
    assert resumed["context_reset_resume"]["route"] == "adviser.extra"
    assert len(team.sessions.calls) == 1


def test_reset_refuses_pending_delivery_and_reset_only_loop(store):
    team, task = setup_team(store)
    flow = team.flow(task["id"])
    team.controller.prepare_message(task["id"], task["owner"], "https://example.invalid/old", {}, "pending-turn")
    with pytest.raises(Retryable, match="unresolved"):
        asyncio.run(reset_context(team, task, flow, task["owner"], {}, request()))
    assert not team.sessions.calls
    team.controller.message_state("pending-turn", "cancelled")
    with pytest.raises(ContextResetYield):
        asyncio.run(reset_context(team, task, flow, task["owner"], {}, request()))
    with pytest.raises(Blocked, match="substantive"):
        asyncio.run(reset_context(team, task, team.flow(task["id"]), task["owner"], {}, request()))
    assert len(team.sessions.calls) == 1


@pytest.mark.parametrize("changes", [{"method": "guess_selector"}, {"handoff": "x" * 4001}, {"reason": ""}])
def test_reset_is_bounded(store, changes):
    team, task = setup_team(store)
    with pytest.raises(ContractError):
        asyncio.run(reset_context(team, task, team.flow(task["id"]), task["owner"], {}, {**request(), **changes}))
    assert not team.sessions.calls


def test_native_parser_accepts_identified_reset():
    assert parse_response(json.dumps(request()), request()["request_id"])["type"] == "context_reset"


def test_adviser_handoff_is_not_exposed_to_worker(store):
    team, task = setup_team(store)
    flow = {**team.flow(task["id"]), "phase": "brief_reading"}
    with pytest.raises(ContextResetYield):
        asyncio.run(reset_context(team, task, flow, "adviser.extra",
                                  {"required_passages": "restricted adviser-only text"}, request()))
    asyncio.run(team._ask(task, team.flow(task["id"]), task["owner"], {"instruction": "worker scope"}))
    envelope = team.browser.calls[0][1]
    assert envelope["context_reset"]["handoff"] is None
    assert "restricted adviser-only text" not in json.dumps(envelope)
    assert envelope["body"] == {"instruction": "worker scope"}


def test_reset_waits_for_uncertain_project_mutation(store):
    team, task = setup_team(store)
    with store.tx() as db:
        db.execute("INSERT INTO operations VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                   ("uncertain-write", task["id"], task["owner"], task["epoch"], 0,
                    "write_file", "hash", "{}", "uncertain", None, 0, 0))
    with pytest.raises(Retryable, match="mutations"):
        asyncio.run(reset_context(team, task, team.flow(task["id"]), task["owner"], {}, request()))
    assert not team.sessions.calls


def test_reset_rejects_native_identity_change(store):
    team, task = setup_team(store)
    renew = team.sessions.renew

    async def changed(*args, **kwargs):
        await renew(*args, **kwargs)
        team.config["routes"][task["owner"]]["effort"] = "different"

    team.sessions.renew = changed
    with pytest.raises(Blocked, match="native identity"):
        asyncio.run(reset_context(team, task, team.flow(task["id"]), task["owner"], {}, request()))
    assert "context_reset_resume" not in team.flow(task["id"])
