"""CHECKS PENDING: profile-revocation races in HA browser read transport.

In-memory browser fakes; no live browser, provider, login, network or model API.
The complete HA source and dependencies are required to execute these contracts.
"""
import asyncio
from contextlib import asynccontextmanager

import pytest

from hivemind_assembly.automation.browser_actions import BrowserActions


class FakeBrowser:
    def __init__(self, revoke_at=None):
        self.revoke_at = revoke_at
        self.config = {"routes": {"only": {"profile": "fixture"}}}
        self.operations = []

    def revoke(self, stage):
        if self.revoke_at == stage:
            self.config["routes"].clear()

    @asynccontextmanager
    async def profile_lock(self, profile):
        assert profile == "fixture"
        self.revoke("lock")
        yield


class FakeHandle:
    def __init__(self, browser, old=False):
        self.browser = browser
        self.old = old
        self.disposed = False

    async def dispose(self):
        self.disposed = True
        self.browser.revoke("dispose")

    async def get_attribute(self, key):
        assert key == "data-ha-ref"
        return "1"

    async def evaluate(self, script):
        self.browser.revoke("element")
        return {
            "tag": "BUTTON", "type": "", "id": "", "name": "",
            "label": "Continue", "text": "Continue", "connected": True,
        }


class FakeLocator:
    def __init__(self, browser):
        self.browser = browser

    async def evaluate_all(self, script):
        self.browser.operations.append("clear_refs")
        self.browser.revoke("locator")

    async def element_handles(self):
        self.browser.operations.append("handles")
        self.browser.revoke("handles")
        return [FakeHandle(self.browser)]


class FakePage:
    def __init__(self, browser):
        self.browser = browser
        self.url = "https://example.invalid/start"
        self.actions = None

    def is_closed(self):
        return False

    def locator(self, selector):
        assert selector == "[data-ha-ref]"
        return FakeLocator(self.browser)

    async def evaluate(self, script):
        if script == self.actions.scripts["stable"]:
            self.browser.operations.append("stable")
            self.browser.revoke("stable")
            return None
        assert script == self.actions.scripts["snapshot"]
        self.browser.operations.append("snapshot")
        self.browser.revoke("snapshot")
        return "SENSITIVE PAGE TEXT MUST NOT ESCAPE A REVOKED PROFILE"


def make_case(tmp_path, revoke_at=None):
    browser = FakeBrowser(revoke_at)
    actions = BrowserActions(browser, tmp_path)
    page = FakePage(browser)
    page.actions = actions
    stale = FakeHandle(browser, old=True)
    actions.sessions["sess-a"] = {
        "profile": "fixture", "origin": "https://example.invalid",
        "page": page, "snapshot": "old-snapshot",
        "handles": {"9": (stale, {})},
    }
    request = {
        "action": "read", "operation_id": "read-revocation-0001",
        "session": "sess-a",
    }
    return actions, browser, stale, request


@pytest.mark.parametrize("stage", [
    "lock", "dispose", "locator", "stable", "snapshot", "handles", "element",
])
def test_revoked_profile_never_returns_read_content_or_replays(tmp_path, stage):
    actions, browser, stale, request = make_case(tmp_path, stage)
    first = asyncio.run(actions.run(request))
    assert first["ok"] is False
    assert first["error"]["code"] == "NEED_ATTENTION"
    assert "SENSITIVE PAGE TEXT" not in str(first)
    assert actions.receipts[request["operation_id"]]["state"] == "uncertain"
    assert actions.sessions["sess-a"]["snapshot"] is None
    assert actions.sessions["sess-a"]["handles"] == {}

    # Once a read is indeterminate, restoring the route must not redo it.
    browser.config["routes"]["restored"] = {"profile": "fixture"}
    before = list(browser.operations)
    second = asyncio.run(actions.run(request))
    assert second["ok"] is False
    assert second["error"]["code"] == "UNCERTAIN"
    assert browser.operations == before


def test_early_revocation_stops_later_dom_snapshot_work(tmp_path):
    for stage in ("lock", "dispose", "locator", "stable"):
        actions, browser, stale, request = make_case(tmp_path / stage, stage)
        result = asyncio.run(actions.run(request))
        assert result["ok"] is False
        assert "snapshot" not in browser.operations


def test_unchanged_route_allows_one_read_but_replay_expires_snapshot(tmp_path):
    actions, browser, stale, request = make_case(tmp_path)
    first = asyncio.run(actions.run(request))
    assert first["ok"] is True
    assert first["items"][0]["text"].startswith("SENSITIVE PAGE TEXT")
    assert first["items"][0]["snapshot"] != "old-snapshot"
    assert stale.disposed
    assert actions.receipts[request["operation_id"]]["state"] == "completed"

    before = list(browser.operations)
    second = asyncio.run(actions.run(request))
    assert second["ok"] is True
    assert second["items"][0]["snapshot_expired"] is True
    assert "SENSITIVE PAGE TEXT" not in str(second)
    assert browser.operations == before
