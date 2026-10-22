"""Routes on one account open one sign-in window, not one each."""

import asyncio
from types import SimpleNamespace

from hivemind_assembly.automation.onboarding import NativeSetup


class Locator:
    def __init__(self, n=0):
        self.n = n

    async def count(self):
        return self.n


class Page:
    def __init__(self, url):
        self.url = url
        self.closed = False

    def is_closed(self):
        return self.closed

    def get_by_role(self, *a, **k):
        return Locator()

    def locator(self, *a):
        return Locator()


def routes():
    chatgpt = {"provider": "openai", "profile": "openai", "allowed_hosts": ["chatgpt.com"]}
    return {
        "worker.opus": {"provider": "claude", "profile": "claude", "allowed_hosts": ["claude.ai"]},
        "worker.astra": dict(chatgpt),
        "worker.extra": dict(chatgpt),
        "reviewer.high": dict(chatgpt),
    }


def test_one_signin_page_per_profile_until_signed_in(store, tmp_path):
    opened = []

    async def service_page(profile, url, hosts):
        # Signing in: the provider shows its login page.
        page = Page("https://auth.openai.com/log-in" if profile == "openai" else "https://accounts.google.com/signin")
        opened.append((profile, page))
        return page

    browser = SimpleNamespace(config={"routes": routes()}, service_page=service_page)
    setup = NativeSetup(browser, store, tmp_path / "settings.json")

    async def all_routes():
        return [await setup.step(r) for r in browser.config["routes"]]

    states = asyncio.run(all_routes())
    assert [p for p, _ in opened] == ["claude", "openai"]
    assert all(s["stage"] == "authentication" for s in states)
    assert "already open" in setup.status("worker.extra")["instruction"]

    # The owner closes the sign-in window: the next route takes over, still one at a time.
    opened[1][1].closed = True
    asyncio.run(all_routes())
    assert [p for p, _ in opened] == ["claude", "openai", "openai"]
