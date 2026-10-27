import asyncio
import json
import time
from pathlib import Path

import pytest
from hivemind_assembly.automation.policy import Availability, Window
from hivemind_assembly.core.common import Blocked, ContractError
from hivemind_assembly.learning.policy import ExperimentalLearning, validate


def setup_policy(store):
    config = json.loads(
        (Path(__file__).parents[1] / "_app/config/default.json").read_text()
    )
    observations = {
        route: Availability(route, True, True, True, time.time())
        for route in config["routes"]
    }
    return ExperimentalLearning(store, config, observations.get), config, observations


def test_experiments_are_optional_chat_only_and_have_no_default_ha_cap(store):
    policy, config, observations = setup_policy(store)
    with pytest.raises(Blocked, match="off"):
        policy.choose()
    config["experimental_learning"]["enabled"] = True
    assert policy.choose() == "worker.extra"
    assert policy.settings()["max_turns_per_evaluation"] is None
    for n in range(40):
        policy.reserve("eval", "turn-" + str(n))
    with pytest.raises(Blocked, match="Chat-only"):
        policy.choose("worker.astra")
    config["experimental_learning"]["chat_only"] = False
    assert policy.choose("worker.astra") == "worker.astra"
    config["experimental_learning"].update(
        model_override="GPT-6", effort_override="High"
    )
    assert policy.selection("worker.extra") == {
        "target": {"model": "GPT-6", "effort": "High"}
    }


def test_chat_only_follows_whichever_worker_a_setup_puts_on_chatgpt_chat(store):
    policy, config, observations = setup_policy(store)
    config["experimental_learning"]["enabled"] = True
    routes = config["routes"]
    # A saved setup swaps the places: Claude on worker.extra, ChatGPT Chat on worker.opus.
    routes["worker.extra"].update(provider="claude", mode="native", model="Opus 5.5", effort="High")
    routes["worker.opus"].update(provider="openai", mode="Chat", model="GPT-6", effort="High")
    assert policy.choose() == "worker.opus"
    routes["worker.opus"].update(mode="Work", model="GPT-6 Astra")
    with pytest.raises(Blocked, match="No worker uses ChatGPT Chat"):
        policy.choose()
    config["experimental_learning"]["chat_only"] = False
    assert policy.choose() == "worker.extra"


def test_unknown_allowance_is_optional_but_observed_blocks_are_respected(store):
    policy, config, observations = setup_policy(store)
    config["experimental_learning"]["enabled"] = True
    obs = observations["worker.extra"]
    obs.allowance_known = False
    assert policy.eligible("worker.extra", obs)
    config["experimental_learning"]["allow_unknown_allowance"] = False
    assert not policy.eligible("worker.extra", obs)
    config["experimental_learning"]["allow_unknown_allowance"] = True
    obs.allowance_known = True
    obs.windows = [Window("known pool", 4)]
    assert not policy.eligible("worker.extra", obs)
    assert policy.reservation_observation(obs).windows == obs.windows
    obs.observed -= 86401
    assert policy.eligible("worker.extra", obs)
    assert policy.reservation_observation(obs).windows == []
    assert obs.windows  # The original observation remains available for review.
    obs.windows = []
    obs.blocked = "quota exhausted"
    assert not policy.eligible("worker.extra", obs)


def test_optional_limit_is_durable_and_retries_do_not_spend_twice(store):
    policy, config, observations = setup_policy(store)
    config["experimental_learning"].update(enabled=True, max_turns_per_evaluation=2)
    policy.reserve("evaluation", "one")
    policy.reserve("evaluation", "one")
    ExperimentalLearning(store, config, observations.get).reserve("evaluation", "two")
    with pytest.raises(Blocked, match="limit"):
        policy.reserve("evaluation", "three")
    config["experimental_learning"]["max_turns_per_evaluation"] = None
    policy.reserve("evaluation", "three")
    assert (
        store.one("SELECT COUNT(*) AS n FROM records WHERE kind='experimental_turn'")[
            "n"
        ]
        == 3
    )
    with pytest.raises(ContractError):
        validate({"model_override": "GPT-6"})


def test_automatic_model_selection_uses_visible_exact_controls(monkeypatch):
    from hivemind_assembly.automation import providers
    from hivemind_assembly.learning.policy import CHAT_PREFERENCES

    calls = []

    async def control(page, field, value):
        calls.append((field, value))
        return "observed-" + field if value in ("Chat", "GPT-6", "Extra High") else None

    monkeypatch.setattr(providers, "select_exact", control)
    selected = asyncio.run(
        providers.select_preferred_chat(
            object(), {"provider": "openai", "mode": "Chat"}, CHAT_PREFERENCES
        )
    )
    assert selected["model"] == "GPT-6" and selected["effort"] == "Extra High"
    assert ("effort", "Pro") in calls
    with pytest.raises(Blocked, match="Chat surface"):
        asyncio.run(
            providers.select_preferred_chat(
                object(), {"provider": "openai", "mode": "Work"}, CHAT_PREFERENCES
            )
        )


def test_model_is_pinned_across_experiment_and_main_route_is_unchanged(store):
    from hivemind_assembly.learning.engine import Learning
    from hivemind_assembly.learning.native_rollouts import NativeRollouts
    from hivemind_assembly.core.controller import Controller

    policy, config, observations = setup_policy(store)
    config["experimental_learning"]["enabled"] = True
    original = dict(config["routes"]["worker.extra"])
    controller = Controller(store)
    selections = []

    class Browser:
        config = {
            "routes": {
                "worker.extra": {
                    "conversation_url": "isolated",
                    "model": "GPT-6",
                    "effort": "Pro",
                }
            }
        }

        async def exchange(self, route, message):
            payload = json.loads(message["payload"])
            return {
                "request_id": message["id"],
                "type": "rollout_result",
                "output": payload["task"] * (2 if payload["method"] else 1),
            }

    class Sessions:
        async def isolated_browser(self, task, route, identity, **selection):
            selections.append(selection)
            return Browser()

    engine = NativeRollouts(
        store,
        controller,
        Sessions(),
        observations.get,
        lambda actual, expected: actual == expected,
        "fixture",
        policy=policy,
    )
    candidate = Learning(store).propose(
        "twice",
        "procedure",
        {
            "scope": ["core"],
            "preconditions": [],
            "exclusions": [],
            "evidence": ["fixture"],
            "content": "multiply by two",
            "external_allowed": True,
        },
    )
    suite = engine.protect(
        [
            {
                "id": "one",
                "family": "a",
                "project": "one",
                "split": "regression",
                "inputs": 2,
                "expected": 4,
            },
            {
                "id": "two",
                "family": "b",
                "project": "two",
                "split": "holdout",
                "inputs": 3,
                "expected": 6,
            },
        ]
    )
    key = engine.bind(candidate, suite)
    engine.state(key, "attention", reason="Owner limit reached")
    config["experimental_learning"]["enabled"] = False
    with pytest.raises(Blocked, match="off"):
        engine.resume(key)
    config["experimental_learning"]["enabled"] = True
    assert engine.resume(key)["stage"] == "queued"
    result = asyncio.run(engine.run(key))
    assert result["stage"] == "promoted"
    assert "preferences" in selections[0]
    assert all(
        x == {"target": {"model": "GPT-6", "effort": "Pro"}} for x in selections[1:]
    )
    assert config["routes"]["worker.extra"] == original
    with pytest.raises(Blocked, match="Only a paused"):
        engine.resume(key)
    assert (
        store.one("SELECT COUNT(*) AS n FROM records WHERE kind='experimental_turn'")[
            "n"
        ]
        == 24
    )
    config["experimental_learning"]["enabled"] = False
    with pytest.raises(Blocked, match="off"):
        engine.bind(candidate, suite)


def test_disabling_optional_reflection_keeps_primary_work_runnable(store):
    from test_coordination import make_team

    class Native:
        async def exchange(self, *_):
            raise AssertionError("A disabled reflection must not send a model turn")

    team = make_team(store, Native())
    task = store.create_project("primary", "Continue the implementation")
    team.scopes.select(task["id"], [], team.scopes.catalog()["revision"])
    team.controller.acquire(task["id"], "worker.opus")
    team.save_flow(
        task["id"], {"seq": 5, "phase": "learning_reflect", "campaign": "retained"}
    )
    asyncio.run(team.tick(task["id"]))
    assert team.flow(task["id"])["phase"] == "intent"
    assert store.task(task["id"])["status"] == "running"
    team.save_flow(
        task["id"], {"seq": 7, "phase": "learning_curate", "campaign": "retained"}
    )
    team.controller.prepare_message(
        task["id"], "adviser.extra", "fixture", {}, "pending"
    )
    with pytest.raises(Blocked, match="pending learning delivery"):
        asyncio.run(team.tick(task["id"]))
    assert team.flow(task["id"])["phase"] == "learning_curate"
