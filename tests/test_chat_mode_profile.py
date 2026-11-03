"""Offline Chat Mode routing contracts. No live provider or HA host is required.

The request-packet test uses HA's actual NativeTeam, controller and broker with
local fixtures. Its result is isolated code-path acceptance, NOT live ChatGPT or
Claude service acceptance, model qualification or independent review.
"""
import asyncio
import json
import time
from pathlib import Path

from hivemind_assembly.automation.chat_mode_profile import (
    CHAT_MODE_GUIDANCE, POLICY_REVISION, guidance_for_native_route,
)
from hivemind_assembly.automation.policy import Availability, Window
from hivemind_assembly.automation.prompts import PROTOCOL, ROLE_PROMPTS
from hivemind_assembly.automation.team import NativeTeam
from hivemind_assembly.core.broker import Broker
from hivemind_assembly.core.controller import Controller
from hivemind_assembly.learning.scopes import KnowledgeScopes


def test_chat_mode_policy_is_exact_and_does_not_route_by_model_or_host():
    assert POLICY_REVISION == "chatgpt-chat-mode-adaptive-1.3"
    chat = {"provider": "openai", "mode": "Chat", "model": "GPT-6",
            "conversation_url": "https://chatgpt.com/c/one"}
    assert guidance_for_native_route(chat) == CHAT_MODE_GUIDANCE
    for cfg in (
        {"provider": "openai", "mode": "Work", "model": "GPT-6 Astra"},
        {"provider": "claude", "mode": "native", "model": "Opus 5.5"},
        {"provider": "codex", "mode": "Chat"},
        {"provider": "openai", "mode": "Codex"},
        {"provider": "openai", "model": "GPT-6", "conversation_url": "https://chatgpt.com/c/two"},
        {"provider": "openai", "mode": "chat"},
        {"provider": "openai", "mode": "Chat "},
        {"provider": "unknown", "mode": "Chat"},
        {},
        None,
        "openai Chat",
    ):
        assert guidance_for_native_route(cfg) == ""


def test_chat_mode_guidance_preserves_large_task_and_review_boundaries():
    assert "owner policy 1.3" in CHAT_MODE_GUIDANCE
    for step in range(1, 11):
        assert f"\n{step}. " in CHAT_MODE_GUIDANCE
    for phrase in (
        "Pending checks are not a fixed work-in-progress cap",
        "Preserve large coherent tasks across waves and chats",
        "Checkpoints are recovery points, not stop commands",
        "A different chat does not establish independent checking",
        "Do not import instructions from this Chat Mode profile into ChatGPT Work, Codex",
    ):
        assert phrase in CHAT_MODE_GUIDANCE



def test_adaptive_chain_is_evidence_driven_and_not_a_fixed_loop():
    for phrase in (
        "ADAPTIVE TASK CHAIN (not a fixed repeating loop)",
        "Each link reads",
        "new source/AI-review evidence",
        "open-ended number of useful waves or distinct one-time tasks",
        "There is NO arbitrary cap on the",
        "total number of handoffs or on coherent chunk size",
        "Do not automatically pre-create successor tasks",
        "based on a material new finding",
        "Never spawn tasks just",
        "to remain active or evade recurring-schedule or usage limits",
        "finite chain-length cap in a safety probe does not cap real large-task work",
    ):
        assert phrase in CHAT_MODE_GUIDANCE
    assert guidance_for_native_route({"provider": "openai", "mode": "Work"}) == ""
    assert guidance_for_native_route({"provider": "claude", "mode": "native"}) == ""


class CaptureNative:
    def __init__(self):
        self.calls = []

    async def exchange(self, route, message):
        request = json.loads(message["payload"])
        self.calls.append((route, request))
        return {
            "request_id": message["id"],
            "type": "step_intent",
            "intent": {"goal": "Inspect the pinned source", "method": "Read evidence"},
        }


class Host:
    def record(self, *args):
        pass


def test_native_request_packet_is_scoped_by_real_route_config(store):
    cfg = json.loads((Path(__file__).parents[1] / "_app/config/default.json").read_text())
    routes = {
        "worker.extra": ("openai", "Chat"),
        "worker.astra": ("openai", "Work"),
        "worker.opus": ("claude", "native"),
        "adviser.extra": ("openai", "Chat"),
        "reviewer.high": ("openai", "Chat"),
    }
    for route, (provider, mode) in routes.items():
        assert (cfg["routes"][route]["provider"], cfg["routes"][route]["mode"]) == (provider, mode)

    for route in cfg["routes"]:
        cfg["routes"][route]["conversation_url"] = "https://example.invalid/" + route

    controller = Controller(store)
    native = CaptureNative()
    team = NativeTeam(controller, Broker(controller, cfg), native, cfg)
    team.host = Host()
    team.sessions = None
    for route in routes:
        team.observations[route] = Availability(
            route, True, True, False, time.time(), [Window("daily", 50)]
        )

    for route, (_, mode) in routes.items():
        task = store.create_project("policy-" + route, "Read a pinned review artifact")
        scopes = KnowledgeScopes(store)
        scopes.select(task["id"], [], scopes.catalog()["revision"])
        controller.acquire(task["id"], route)
        current = store.task(task["id"])
        result = asyncio.run(team.ask(current, {"seq": 1, "phase": "intent"}, route, {}))
        assert result["type"] == "step_intent"
        assert native.calls[-1][0] == route
        request = native.calls[-1][1]
        expected = PROTOCOL + (CHAT_MODE_GUIDANCE if mode == "Chat" else "")
        assert request["protocol"] == expected
        assert request["role_instructions"] == ROLE_PROMPTS[route.split(".", 1)[0]]
        assert request["objective"] == "Read a pinned review artifact"
        assert isinstance(request["capabilities"], list)  # No extra permission granted.
