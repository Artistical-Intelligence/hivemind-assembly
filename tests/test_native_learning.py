import asyncio
import json
import time
import pytest
from hivemind_assembly.core.controller import Controller
from hivemind_assembly.core.common import AllowanceUnavailable, Blocked
from hivemind_assembly.learning.engine import Learning
from hivemind_assembly.learning.native_rollouts import NativeRollouts
from hivemind_assembly.automation.policy import Availability


def test_native_rollouts_isolate_truth_resume_and_promote(store):
    c = Controller(store)
    learning = Learning(store)
    candidate = learning.propose(
        "multiply",
        "procedure",
        {
            "scope": ["core"],
            "preconditions": ["integers"],
            "exclusions": [],
            "evidence": ["fixture-origin"],
            "content": {"multiplier": 2},
            "external_allowed": True,
        },
    )
    calls, sessions = [], []
    ready = Availability(
        "worker.extra",
        ready=True,
        allowance_known=True,
        no_numeric_limit=True,
        observed=time.time(),
    )
    quota = {"available": True, "interrupt": True}

    class Browser:
        def __init__(self, identity):
            self.config = {
                "routes": {
                    "worker.extra": {
                        "conversation_url": "https://chatgpt.com/c/" + identity
                    }
                }
            }

        async def exchange(self, route, message):
            payload = json.loads(message["payload"])
            assert "expected" not in payload and "split" not in payload
            assert "family" not in payload and "trial" not in payload
            calls.append(message["id"])
            factor = (payload["method"] or {}).get("multiplier", 1)
            response = {
                "type": "rollout_result",
                "request_id": message["id"],
                "output": payload["task"]["value"] * factor,
            }
            c.message_state(message["id"], "validated", json.dumps(response))
            if quota["interrupt"]:
                quota["interrupt"] = False
                quota["available"] = False
            return response

    class Sessions:
        async def isolated_browser(self, task, route, identity):
            sessions.append(identity)
            return Browser(identity)

    engine = NativeRollouts(
        store,
        c,
        Sessions(),
        lambda route: ready if quota["available"] else None,
        lambda actual, truth: actual == truth,
        "test-engine",
    )
    suite = engine.protect(
        [
            {
                "id": "one",
                "family": "positive",
                "project": "first",
                "split": "regression",
                "inputs": {"value": 2},
                "expected": 4,
            },
            {
                "id": "two",
                "family": "negative",
                "project": "second",
                "split": "holdout",
                "inputs": {"value": -7},
                "expected": -14,
            },
        ]
    )
    key = engine.bind(candidate, suite)
    with pytest.raises(AllowanceUnavailable):
        asyncio.run(engine.run(key))
    assert engine.status(key)["stage"] == "waiting_quota" and len(calls) == 1
    quota["available"] = True
    result = asyncio.run(engine.run(key))
    assert result["stage"] == "promoted"
    assert len(calls) == len(set(calls)) == 12
    assert len(sessions) == len(set(sessions)) == 12
    assert (
        store.one("SELECT status FROM lessons WHERE id=?", (candidate,))["status"]
        == "active"
    )
    assert asyncio.run(engine.run(key))["stage"] == "promoted"
    assert len(calls) == 12
    learning.share(candidate, False)
    assert not learning.external_allowed(
        store.one("SELECT * FROM lessons WHERE id=?", (candidate,))
    )


def test_native_trials_require_owner_permission_and_protected_truth(store):
    learning = Learning(store)
    key = learning.propose(
        "asset",
        "knowledge",
        {
            "scope": ["core"],
            "preconditions": [],
            "exclusions": [],
            "evidence": ["source"],
            "content": {},
        },
    )
    engine = NativeRollouts(
        store, Controller(store), None, lambda _: None, None, "test"
    )
    with pytest.raises(Blocked, match="permission"):
        engine.bind(key, "missing")


def test_session_restore_ignores_isolated_trials(store, tmp_path):
    from hivemind_assembly.automation.sessions import Sessions
    from hivemind_assembly.automation.native import NativeBrowser

    original = {"conversation_url": "https://chatgpt.com/c/work"}
    b = NativeBrowser(
        {"routes": {"worker.extra": original.copy()}}, tmp_path, Controller(store)
    )
    store.put(
        "session_commit",
        "private-trial",
        {
            "route": "worker.extra",
            "previous": original["conversation_url"],
            "binding": {"conversation_url": "https://chatgpt.com/c/holdout"},
            "isolated": True,
        },
    )
    Sessions(b, tmp_path / "settings.json").restore_bindings()
    assert b.config["routes"]["worker.extra"] == original


def test_permission_revocation_stops_next_native_trial(store):
    c = Controller(store)
    learning = Learning(store)
    candidate = learning.propose(
        "revocable",
        "procedure",
        {
            "scope": ["core"],
            "preconditions": [],
            "exclusions": [],
            "evidence": ["origin"],
            "content": {},
            "external_allowed": True,
        },
    )
    calls = []

    class Browser:
        config = {
            "routes": {
                "worker.extra": {"conversation_url": "https://chatgpt.com/c/test"}
            }
        }

        async def exchange(self, route, message):
            calls.append(message["id"])
            learning.share(candidate, False)
            return {"request_id": message["id"], "type": "rollout_result", "output": 1}

    class Sessions:
        async def isolated_browser(self, *args):
            return Browser()

    ready = Availability(
        "worker.extra",
        ready=True,
        allowance_known=True,
        no_numeric_limit=True,
        observed=time.time(),
    )
    engine = NativeRollouts(
        store,
        c,
        Sessions(),
        lambda _: ready,
        lambda actual, truth: actual == truth,
        "permission-test",
    )
    suite = engine.protect(
        [
            {
                "id": "a",
                "family": "a",
                "project": "a",
                "split": "regression",
                "inputs": {},
                "expected": 1,
            },
            {
                "id": "b",
                "family": "b",
                "project": "b",
                "split": "holdout",
                "inputs": {},
                "expected": 1,
            },
        ]
    )
    key = engine.bind(candidate, suite)
    with pytest.raises(Blocked, match="revoked"):
        asyncio.run(engine.run(key))
    assert len(calls) == 1
    assert (
        store.one("SELECT status FROM lessons WHERE id=?", (candidate,))["status"]
        == "candidate"
    )
