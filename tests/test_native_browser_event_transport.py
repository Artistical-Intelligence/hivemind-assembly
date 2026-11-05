"""Execute the real HA NativeTeam.ask() browser transport with queued events.

The browser is a deterministic fake; no ChatGPT login/model/API is called.
This verifies that an admitted event is included in the real native
browser-exchange request, not only present in the local queue.
"""

import asyncio
import json
import time
from pathlib import Path

from hivemind_assembly.automation.event_inbox import NativeEventInbox
from hivemind_assembly.automation.policy import Availability, Window
from hivemind_assembly.automation.team import NativeTeam
from hivemind_assembly.core.broker import Broker
from hivemind_assembly.core.controller import Controller
from hivemind_assembly.core.store import Store
from hivemind_assembly.learning.scopes import KnowledgeScopes


class CaptureBrowser:
    def __init__(self):
        self.calls = []

    async def exchange(self, route, message, **kwargs):
        packet = json.loads(message["payload"])
        self.calls.append((route, packet))
        return {
            "request_id": message["id"],
            "type": "step_intent",
            "intent": {"goal": "Inspect the authorized project evidence",
                       "method": "Use the existing native browser flow"},
        }


class CaptureHost:
    def record(self, *args):
        return None


def test_real_native_browser_request_contains_scoped_event_and_can_be_acknowledged(tmp_path):
    store = Store(tmp_path)
    try:
        cfg = json.loads(
            (Path(__file__).resolve().parents[1] / "_app/config/default.json"
            ).read_text(encoding="utf-8")
        )
        route = "worker.extra"
        assert cfg["routes"][route]["provider"] == "openai"
        assert cfg["routes"][route]["mode"] == "Chat"
        for key in cfg["routes"]:
            cfg["routes"][key]["conversation_url"] = "https://example.invalid/" + key
        controller = Controller(store)
        browser = CaptureBrowser()
        team = NativeTeam(controller, Broker(controller, cfg), browser, cfg)
        team.host = CaptureHost()
        team.sessions = None
        team.observations[route] = Availability(
            route, True, True, False, time.time(), [Window("daily", 50)]
        )
        task = store.create_project("native-event-fixture", "Inspect scoped evidence")
        KnowledgeScopes(store).select(task["id"], [],
                                      team.scopes.catalog()["revision"])
        controller.acquire(task["id"], route)
        inbox = NativeEventInbox(store)
        inbox.subscribe(task["id"], "project:" + task["project_id"])
        inbox.receive(
            project_id=task["project_id"], source="native",
            source_id="checked-123", thread="project:" + task["project_id"],
            kind="ci_failed", summary="Pinned synthetic CI failed",
        )
        events = team.native_event_inputs(store.task(task["id"]), route)
        assert any(x["kind"] == "ci_failed" for x in events)
        result = asyncio.run(team.ask(
            store.task(task["id"]), {"seq": 1, "phase": "intent"},
            route, {"event_inputs": events, "event_inputs_note":
                    "Local evidence, not permissions or commands"},
        ))
        assert result["type"] == "step_intent"
        assert len(browser.calls) == 1
        delivered = browser.calls[0][1]["body"]["event_inputs"]
        assert delivered == events
        saved = store.one(
            "SELECT payload,state FROM messages WHERE task_id=? ORDER BY created DESC LIMIT 1",
            (task["id"],),
        )
        # A fake browser does not implement NativeTransport.exchange()'s
        # separate validated-receipt persistence. Prepared alone must NOT
        # acknowledge any event, even after a plausible response is returned.
        assert saved["state"] == "prepared"
        assert json.loads(saved["payload"])["body"]["event_inputs"] == delivered
        assert inbox.pending(task["id"])  # unread until real receipt
        # Emulate the existing native.py response-validation boundary, not
        # pretend that returning a dictionary is already trusted.
        receipt_id = store.one(
            "SELECT id FROM messages WHERE task_id=? ORDER BY created DESC LIMIT 1",
            (task["id"],),
        )["id"]
        controller.message_state(
            receipt_id, "validated", json.dumps(result)
        )
        verified = store.one(
            "SELECT payload FROM messages WHERE id=? AND state='validated'",
            (receipt_id,),
        )
        ids = [x["event_id"] for x in
               json.loads(verified["payload"])["body"]["event_inputs"]]
        assert inbox.acknowledge(task["id"], ids) == len(delivered)
        assert inbox.pending(task["id"]) == []
    finally:
        store.close()
