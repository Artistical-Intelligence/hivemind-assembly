"""Recovery-state regressions; browser DOM coverage lives in test_browser_fixture."""

import asyncio
import pytest

from hivemind_assembly.automation import native as module
from hivemind_assembly.automation.native import NativeBrowser, DeliveryPending
from hivemind_assembly.automation.onboarding import NativeSetup
from hivemind_assembly.automation.webmcp import NativeUI
from hivemind_assembly.core.common import Blocked
from hivemind_assembly.core.controller import Controller


@pytest.mark.parametrize("outcome", ["sent", "timeout_after_send", "timeout_before_send", "cancel", "clipped", "duplicate"])
def test_send_outcome_reconciliation(store, tmp_path, monkeypatch, outcome):
    controller = Controller(store)
    task = store.create_project("recovery", "test")
    route = "worker.extra"
    message = controller.prepare_message(task["id"], route, "https://fixture.invalid/c/1", {"test": "full payload"})

    class Page:
        url = "https://fixture.invalid/c/1"
        echoes = []
        envelope = ""
        clicks = 0

        def locator(self, selector):
            return self

        async def fill(self, envelope):
            self.envelope = envelope

        async def click(self):
            self.clicks += 1
            assert store.one("SELECT state FROM messages WHERE id=?", (message["id"],))["state"] == "dispatching"
            if outcome == "cancel":
                raise asyncio.CancelledError()
            if outcome != "timeout_before_send":
                self.echoes = [self.envelope]
            if outcome == "clipped":
                self.echoes = [self.envelope.splitlines()[0]]
            if outcome == "duplicate":
                self.echoes *= 2
            if outcome.startswith("timeout_"):
                raise TimeoutError("click acknowledgement lost")

        async def evaluate(self, script, args):
            assert script == module.REQUEST_ECHO
            return self.echoes

    page = Page()

    class Native(NativeBrowser):
        async def repair(self, route):
            pass

        async def observe(self, route):
            pass

        async def page(self, route):
            return page

        async def await_reply(self, route, message, *args):
            return {"request_id": message["id"], "type": "brief"}

    async def unavailable(*args):
        return False

    wait = module.wait_request_echo

    async def immediate(*args):
        return await wait(*args, timeout=0)

    monkeypatch.setattr(NativeUI, "available", unavailable)
    monkeypatch.setattr(module, "wait_request_echo", immediate)
    native = Native({"routes": {route: {"selectors": {"user_messages": ".user", "composer": "textarea", "send": "button"}}}}, tmp_path, controller)

    async def run():
        if outcome == "cancel":
            with pytest.raises(asyncio.CancelledError):
                await native.exchange(route, message)
        elif outcome in ("timeout_before_send", "clipped", "duplicate"):
            expected = DeliveryPending if outcome == "timeout_before_send" else Blocked
            with pytest.raises(expected):
                await native.exchange(route, message)
        else:
            assert (await native.exchange(route, message))["request_id"] == message["id"]
        current = store.one("SELECT * FROM messages WHERE id=?", (message["id"],))
        assert current["state"] == ("received" if outcome in ("sent", "timeout_after_send") else "delivery_uncertain")
        if outcome in ("timeout_before_send", "timeout_after_send", "sent"):
            # A restart uses durable intent, never another click.
            if outcome == "timeout_before_send":
                with pytest.raises(DeliveryPending):
                    await native.exchange(route, current)
                page.echoes = [page.envelope]  # delayed provider rendering
            await native.exchange(route, current)
        assert page.clicks == 1
        assert not native.dispatch_lock(route).locked()

    asyncio.run(run())


def test_setup_bounds_unconfirmed_delivery_without_resetting_state(store, tmp_path, monkeypatch):
    from hivemind_assembly.automation import onboarding

    setup = NativeSetup(None, store, tmp_path / "config.json")
    attempts = []

    async def step(route):
        attempts.append(route)
        raise DeliveryPending("Observing existing send")

    async def snapshot(*args, **kwargs):
        pass

    async def sleep(*args):
        pass

    monkeypatch.setattr(setup, "step", step)
    monkeypatch.setattr(setup, "snapshot", snapshot)
    monkeypatch.setattr(onboarding.asyncio, "sleep", sleep)
    result = asyncio.run(setup.run("worker.extra"))
    assert len(attempts) == 3
    assert result["stage"] == "attention"
    assert "not been resent" in result["instruction"]
    assert setup.status("worker.extra") == result


def test_request_echo_rejects_separate_messages():
    class Page:
        async def evaluate(self, *args):
            return ["same marker", "same marker"]

    with pytest.raises(Blocked, match="separate messages"):
        asyncio.run(module.request_echo(Page(), ".user", "marker"))


def test_restart_rediscovery_after_duplicate_scan_failure(store, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from hivemind_assembly.automation import sessions as session_module

    route, key = "worker.extra", "recovery_request"
    controller = Controller(store)
    task = store.create_project("restart", "test")
    config = {"routes": {route: {
        "provider": "openai", "profile": "openai", "account_label": "tester",
        "conversation_url": "https://chatgpt.com/c/old", "allowed_hosts": ["chatgpt.com"],
        "model": "GPT-6", "mode": "Chat", "effort": "Extra High",
        "selectors": {"user_messages": ".user"},
    }}}
    root = NativeBrowser(config, tmp_path, controller)
    controller.prepare_message(task["id"], route, "https://chatgpt.com/", {"test": "canary"}, key)
    controller.message_state(key, "delivery_uncertain")

    class Page:
        url = "https://chatgpt.com/c/recovered"
        echoes = ["WORKBENCH_REQUEST:" + key] * 2
        scans = 0

        async def evaluate(self, script, args):
            assert script == module.REQUEST_ECHO
            self.scans += 1
            return self.echoes

    page = Page()
    root.contexts["openai"] = SimpleNamespace(pages=[page])

    class Recovered(Exception):
        pass

    class Clone(NativeBrowser):
        async def exchange(self, route, message, attachments):
            assert self.pages[route] is page
            assert self.config["routes"][route]["conversation_url"] == page.url
            assert message["state"] == "delivery_uncertain"
            raise Recovered()

    async def discover(page, config):
        return {"missing": [], "selectors": config["selectors"], "account_label": config["account_label"]}

    monkeypatch.setattr(session_module, "NativeBrowser", Clone)
    monkeypatch.setattr(session_module, "discover", discover)
    sessions = session_module.Sessions(root, tmp_path / "config.json")

    async def run():
        with pytest.raises(Blocked, match="separate messages"):
            await sessions.renew(task["id"], route, identity=key)
        assert key not in sessions.drafts
        page.echoes = page.echoes[:1]
        with pytest.raises(Recovered):
            await sessions.renew(task["id"], route, identity=key)
        assert page.scans == 2
        assert sessions.drafts[key].pages[route] is page
        assert store.one("SELECT state FROM messages WHERE id=?", (key,))["state"] == "delivery_uncertain"

    asyncio.run(run())
