"""CHECKS PENDING: browser-open post-await authorization races.

Offline synthetic pages only. These tests do NOT validate a live browser,
a provider login, or acceptance of an external write.
"""
import asyncio

import pytest

from hivemind_assembly.automation.browser_actions import BrowserActions


class _Page:
    def __init__(self, url="https://example.invalid/start", *, close_fails=False):
        self.url = url
        self.close_calls = 0
        self.close_fails = close_fails

    async def close(self):
        self.close_calls += 1
        if self.close_fails:
            raise RuntimeError("simulated browser teardown failure")


class _Browser:
    def __init__(self, race=None, *, close_fails=False):
        self.race = race
        self.config = {"routes": {"fixture_route": {"profile": "fixture"}}}
        self.page = _Page(close_fails=close_fails)
        self.calls = 0

    async def service_page(self, profile, url, allowed_hosts, *, prepare=None):
        assert profile == "fixture"
        assert url == "https://example.invalid/start"
        assert allowed_hosts == {"example.invalid"}
        assert prepare is not None
        self.calls += 1
        # Simulate a change while the real service_page call was awaited.
        if self.race == "revoked":
            self.config["routes"].clear()
        elif self.race == "redirect":
            self.page.url = "https://untrusted.invalid/redirect"
        elif self.race == "insecure":
            self.page.url = "http://example.invalid/start"
        elif self.race == "credential":
            self.page.url = "https://user:password@example.invalid/start"
        return self.page


def _request():
    return {
        "action": "open", "operation_id": "open-postawait-0001",
        "profile": "fixture", "url": "https://example.invalid/start"
    }


@pytest.mark.parametrize("race", ["revoked", "redirect", "insecure", "credential"])
def test_open_fails_closed_after_asynchronous_authority_change(tmp_path, race):
    browser = _Browser(race)
    actions = BrowserActions(browser, tmp_path)
    request = _request()
    response = asyncio.run(actions.run(request))
    assert response["ok"] is False
    assert response["error"]["code"] == "NEED_ATTENTION"
    assert actions.sessions == {}
    assert browser.page.close_calls == 1
    assert actions.receipts[request["operation_id"]]["state"] == "uncertain"

    # A restart cannot accidentally open a second page for the same ID.
    restarted = BrowserActions(browser, tmp_path)
    replay = asyncio.run(restarted.run(request))
    assert replay["ok"] is False
    assert replay["error"]["code"] == "UNCERTAIN"
    assert browser.calls == 1
    assert browser.page.close_calls == 1


def test_open_does_not_grant_session_if_cleanup_itself_fails(tmp_path):
    browser = _Browser("revoked", close_fails=True)
    actions = BrowserActions(browser, tmp_path)
    response = asyncio.run(actions.run(_request()))
    assert response["error"]["code"] == "NEED_ATTENTION"
    assert actions.sessions == {}
    assert browser.page.close_calls == 1
    assert actions.receipts[_request()["operation_id"]]["state"] == "uncertain"


def test_open_maintains_success_for_stable_authorized_profile_and_origin(tmp_path):
    browser = _Browser()
    actions = BrowserActions(browser, tmp_path)
    response = asyncio.run(actions.run(_request()))
    assert response["ok"] is True
    assert response["items"][0]["outcome"] == "opened"
    session_id = response["items"][0]["session"]
    assert actions.sessions[session_id]["page"] is browser.page
    assert browser.page.close_calls == 0
    assert browser.calls == 1
