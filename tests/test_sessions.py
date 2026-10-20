import asyncio
import base64
import json
from pathlib import Path
import pytest
from hivemind_assembly.automation.sessions import Sessions
from hivemind_assembly.automation.native import NativeBrowser
from hivemind_assembly.core.common import Blocked, Retryable
from hivemind_assembly.core.controller import Controller


def test_session_commit_and_crash_recovery_never_repeat_send(
    store, tmp_path, monkeypatch
):
    import hivemind_assembly.automation.sessions as module

    c = Controller(store)
    initial = {
        "provider": "openai",
        "profile": "openai",
        "conversation_url": "https://chatgpt.com/c/old",
        "allowed_hosts": ["chatgpt.com"],
        "model": "GPT-6",
        "mode": "Chat",
        "effort": "Extra High",
        "account_label": "tester@example.com",
        "selectors": {"user_messages": ".user", "download": "a[download]"},
    }
    root = NativeBrowser({"routes": {"worker.extra": initial.copy()}}, tmp_path, c)
    calls = []

    class Page:
        url = "https://chatgpt.com/"

    async def service(profile, url):
        p = Page()
        p.url = url
        return p

    root.service_page = service

    async def discover(page, cfg):
        return {
            "missing": [],
            "selectors": cfg["selectors"],
            "account_label": cfg["account_label"],
        }

    monkeypatch.setattr(module, "discover", discover)

    class Clone(NativeBrowser):
        async def exchange(self, route, message, attachments):
            calls.append(message["id"])
            url = "https://chatgpt.com/c/new-session"
            self.pages[route].url = url
            self.config["routes"][route].update(
                conversation_url=url, draft_session=False
            )
            store.put(
                "message_session",
                message["id"],
                {"route": route, "draft": message["conversation"], "conversation": url},
            )
            result = {
                "type": "session_ready",
                "request_id": message["id"],
                "attachment_base64": base64.b64encode(
                    Path(attachments[0]["path"]).read_bytes()
                ).decode(),
            }
            c.message_state(message["id"], "validated", json.dumps(result))
            return result

        async def observe(self, route):
            return {
                "conversation": self.pages[route].url,
                "account": "tester@example.com",
            }

        async def download(
            self, route, selector, destination, expected_sha256, filename=None
        ):
            Path(destination).write_bytes(
                Path(destination).with_name("ha-session-canary.txt").read_bytes()
            )

    monkeypatch.setattr(module, "NativeBrowser", Clone)
    sessions = Sessions(root, tmp_path / "settings.json")
    original_put = store.put
    crash = {"once": True}

    def put(kind, *args, **kwargs):
        if kind == "session_commit" and crash["once"]:
            crash["once"] = False
            raise ConnectionError("lost before local commit")
        return original_put(kind, *args, **kwargs)

    monkeypatch.setattr(store, "put", put)
    with pytest.raises(ConnectionError):
        asyncio.run(sessions.renew("task", "worker.extra"))
    assert (
        root.config["routes"]["worker.extra"]["conversation_url"]
        == initial["conversation_url"]
    )
    restarted = Sessions(root, tmp_path / "settings.json")
    result = asyncio.run(restarted.renew("task", "worker.extra"))
    assert result["binding"]["conversation_url"] == "https://chatgpt.com/c/new-session"
    assert len(calls) == 1
    assert json.loads((tmp_path / "settings.json").read_text())["routes"][
        "worker.extra"
    ]["conversation_url"].endswith("/new-session")


def test_pending_native_delivery_blocks_renewal(store, tmp_path):
    c = Controller(store)
    b = NativeBrowser(
        {"routes": {"worker.extra": {"conversation_url": "https://chatgpt.com/c/old"}}},
        tmp_path,
        c,
    )
    m = c.prepare_message("task", "worker.extra", "https://chatgpt.com/c/old", {})
    c.message_state(m["id"], "delivery_uncertain")
    with pytest.raises(Retryable, match="unresolved"):
        asyncio.run(
            Sessions(b, tmp_path / "settings.json").renew("task", "worker.extra")
        )
    assert not store.rows("SELECT * FROM records WHERE kind='session_intent'")
