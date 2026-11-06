"""Offline async navigation races at the HA browser trust boundary.

No browser, provider login, network traffic, or model API is used.
"""
import asyncio
from contextlib import asynccontextmanager

from hivemind_assembly.automation.browser_actions import BrowserActions, IDENTITY


class FakeBrowser:
    config = {"routes": {"only": {"profile": "fixture"}}}

    @asynccontextmanager
    async def profile_lock(self, profile):
        assert profile == "fixture"
        yield


class FakeLocator:
    async def evaluate_all(self, script):
        return None

    async def element_handles(self):
        return []


class FakePage:
    def __init__(self):
        self.url = "https://example.invalid/setup"
        self.navigate_on_snapshot = False

    def is_closed(self):
        return False

    def locator(self, selector):
        return FakeLocator()

    async def evaluate(self, script):
        if self.navigate_on_snapshot and script == self.actions.scripts["snapshot"]:
            self.url = "https://other.invalid/private"
            return "private cross-site snapshot must not be returned"
        return "same-origin visible content"


def test_read_discards_snapshot_if_page_navigates_during_await(tmp_path):
    actions = BrowserActions(FakeBrowser(), tmp_path)
    page = FakePage()
    page.actions = actions
    page.navigate_on_snapshot = True
    actions.sessions["session-a"] = {
        "page": page, "profile": "fixture", "origin": "https://example.invalid",
        "snapshot": "stale-authorization", "handles": {},
    }
    request = {"action": "read", "operation_id": "read-navigation-race-001", "session": "session-a"}
    result = asyncio.run(actions.run(request))
    assert result["ok"] is False
    assert "private cross-site snapshot" not in str(result)
    assert actions.sessions["session-a"]["snapshot"] is None
    assert actions.sessions["session-a"]["handles"] == {}
    assert actions.receipts[request["operation_id"]]["state"] == "uncertain"


def test_click_aborts_if_page_navigates_during_element_inspection(tmp_path):
    actions = BrowserActions(FakeBrowser(), tmp_path)
    page = FakePage()
    clicked = []
    identity = {
        "tag": "BUTTON", "type": "", "id": "", "name": "",
        "label": "", "text": "Submit", "connected": True,
    }

    class Element:
        async def evaluate(self, script):
            if script == IDENTITY:
                return dict(identity)
            # Browser navigation raced with async DOM metadata retrieval.
            page.url = "https://other.invalid/redirect"
            return "submit"

        async def is_visible(self):
            return True

        async def is_enabled(self):
            return True

        async def click(self, **kwargs):
            clicked.append(kwargs)

    actions.sessions["session-a"] = {
        "page": page, "profile": "fixture", "origin": "https://example.invalid",
        "snapshot": "original-snapshot", "handles": {"1": (Element(), dict(identity))},
    }
    request = {
        "action": "click", "operation_id": "click-navigation-race-001",
        "session": "session-a", "snapshot": "original-snapshot", "ref": "1",
    }
    result = asyncio.run(actions.run(request))
    assert result["ok"] is False
    assert clicked == []
    assert actions.sessions["session-a"]["snapshot"] is None
    assert actions.sessions["session-a"]["handles"] == {}
    assert actions.receipts[request["operation_id"]]["state"] == "uncertain"

    # Returning to the old origin is not permission to retry the old click.
    page.url = "https://example.invalid/setup"
    retry = asyncio.run(actions.run(request))
    assert retry["ok"] is False
    assert retry["error"]["code"] == "UNCERTAIN"
    assert clicked == []


def test_new_read_disposes_old_handles_before_replacing_snapshot(tmp_path):
    actions = BrowserActions(FakeBrowser(), tmp_path)
    page = FakePage()
    page.actions = actions
    disposed = []

    class OldHandle:
        async def dispose(self):
            disposed.append(True)

    actions.sessions["session-a"] = {
        "page": page, "profile": "fixture", "origin": "https://example.invalid",
        "snapshot": "old-snapshot", "handles": {"1": (OldHandle(), {})},
    }
    request = {"action": "read", "operation_id": "read-dispose-handles-001", "session": "session-a"}
    result = asyncio.run(actions.run(request))
    assert result["ok"] is True
    assert disposed == [True]
    assert actions.sessions["session-a"]["snapshot"] != "old-snapshot"
    assert actions.sessions["session-a"]["handles"] == {}
