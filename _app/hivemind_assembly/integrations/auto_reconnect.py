"""Reconnect ChatGPT and Claude to HA by themselves after the connection address changes.

Uses HA's own assistant browser windows (Playwright), which are already signed in
to the same ChatGPT and Claude accounts. For each chosen provider:

1. open its connector settings and remove the old "Hivemind Assembly" connector;
2. open "Add custom connector / MCP server" and fill in the new address;
3. submit it; the provider then opens HA's approval page;
4. HA checks that page is its own current one, fills a code bound to it, and approves.

Every click is limited to recognized controls. If a page doesn't match, it stops
and reports what to do by hand (the Chrome helper still works).
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from urllib.parse import urlsplit

from hivemind_assembly.core.common import Blocked, atomic_write, canonical
from hivemind_assembly.paths import APP_ROOT

NAME = "Hivemind Assembly"
SETUP = {"ChatGPT": "https://chatgpt.com/plugins", "Claude": "https://claude.ai/new#customize/connectors"}
PROVIDER_OF_ROUTE = {"openai": "ChatGPT", "claude": "Claude"}
EXTENSION = APP_ROOT / "browser-helper" / "extension"
SCRIPTS = (EXTENSION / "form.js", EXTENSION / "navigation.js", Path(__file__).with_name("connector_manage.js"))


class Stuck(Exception):
    """The page didn't match what HA can safely operate; the owner finishes by hand."""


class AutoReconnect:
    def __init__(self, folder, browser, details, pair, routes, name=NAME):
        """details(provider) and pair(provider, page_url, flow) come from the active connection."""
        self.name = name
        self.settings_path = Path(folder) / "auto_reconnect.json"
        self.browser, self.details, self.pair, self.routes = browser, details, pair, routes
        self.state = {}
        self.locks = {}

    # Settings ---------------------------------------------------------------
    def providers(self):
        try:
            value = json.loads(self.settings_path.read_text())["providers"]
        except (OSError, ValueError, KeyError):
            return []
        return [p for p in value if p in SETUP]

    def save(self, providers):
        if not isinstance(providers, list) or any(p not in SETUP for p in providers):
            raise Blocked("Choose ChatGPT and/or Claude.")
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(self.settings_path, canonical({"providers": sorted(set(providers))}))
        return self.status()

    def status(self):
        return {"providers": self.providers(), "progress": dict(self.state)}

    def report(self, provider, stage, message):
        self.state[provider] = {"stage": stage, "message": message, "at": time.time()}

    # Browser work -----------------------------------------------------------
    def profile(self, provider):
        for cfg in self.routes().values():
            if PROVIDER_OF_ROUTE.get(cfg.get("provider")) == provider:
                return cfg["profile"], cfg["allowed_hosts"]
        raise Blocked("No HA assistant uses " + provider + ", so HA has no signed-in " + provider + " window.")

    async def run_all(self):
        return await asyncio.gather(*(self.run(p) for p in self.providers()))

    async def run(self, provider):
        lock = self.locks.setdefault(provider, asyncio.Lock())
        if lock.locked():
            return self.state.get(provider)
        async with lock:
            try:
                await self.reconnect(provider)
            except Stuck as exc:
                self.report(provider, "manual", str(exc) + " You can also connect " + provider + " by hand (Connection details).")
            except Blocked as exc:
                self.report(provider, "manual", str(exc))
            except Exception as exc:  # browser closed, navigation failed, timeouts
                self.report(provider, "manual", "Stopped (" + type(exc).__name__ + "). Select Connect to try again, or connect " + provider + " by hand (Connection details).")
            return self.state.get(provider)

    async def inject(self, page):
        for script in SCRIPTS:
            # evaluate() runs through the browser's debugger, so page security rules don't block it.
            await page.evaluate(script.read_text(encoding="utf-8"))

    async def reconnect(self, provider):
        details = self.details(provider)
        origin = details["origin"]
        profile, hosts = self.profile(provider)
        self.report(provider, "working", "Opening " + provider + " in HA's window.")
        page = await self.browser.service_page(profile, SETUP[provider], hosts)
        context = page.context
        before = set(context.pages)
        try:
            await page.wait_for_load_state("domcontentloaded")
            if urlsplit(page.url).hostname not in hosts:
                raise Stuck("HA's " + provider + " tab isn't signed in. Sign in there (AI assistants, Set up), then select Connect again.")
            await self.remove_old(provider, page)
            await self.open_form(provider, page)
            self.report(provider, "working", "Filling in the new address.")
            await self.fill_and_submit(provider, page, details)
            self.report(provider, "working", "Approving on HA's page.")
            approval = await self.approval_page(context, origin)
            await self.approve(provider, approval)
            self.report(provider, "done", "Reconnected. " + provider + " will confirm on its first use.")
        finally:
            for extra in set(context.pages) - before:
                if not extra.is_closed():
                    await extra.close()
            if not page.is_closed():
                await page.close()

    async def click_marked(self, page):
        target = page.locator("[data-ha-target]")
        if await target.count() != 1:
            raise Stuck("The page changed while HA was working.")
        await target.click(timeout=5000)
        await page.wait_for_timeout(900)

    async def remove_old(self, provider, page):
        self.report(provider, "working", "Removing the old " + self.name + " connector.")
        for _ in range(10):
            await self.inject(page)
            step = await page.evaluate("name => globalThis.__haConnectorManage.removeStep(name)", self.name)
            if step["state"] == "done":
                if not page.url.startswith(SETUP[provider].split("#")[0]):
                    await page.goto(SETUP[provider], wait_until="domcontentloaded")
                return
            if step["state"] == "stuck":
                raise Stuck(step["note"])
            await self.click_marked(page)
        raise Stuck("Removing the old connector took more steps than expected.")

    async def open_form(self, provider, page):
        if page.url != SETUP[provider]:
            await page.goto(SETUP[provider], wait_until="domcontentloaded")
        reset = False
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            await page.wait_for_timeout(400)
            try:
                await self.inject(page)
                if not reset:
                    await page.evaluate("globalThis.__haSetupNavigator.reset()")
                    reset = True
                step = await page.evaluate("globalThis.__haSetupNavigator.step()")
            except Exception as exc:
                if "context" in str(exc).lower() or "navigat" in str(exc).lower():
                    continue  # the page reloaded under us; try again
                raise
            if step["state"] == "ready":
                return
            if step["state"] == "blocked":
                raise Stuck(step["note"])
        raise Stuck("The Add custom connector form didn't open.")

    async def fill_and_submit(self, provider, page, details):
        # Claude can ask for authentication options after Continue; fill and submit up to three times.
        for _ in range(3):
            await self.inject(page)
            probe = await page.evaluate("globalThis.__haFormHelper.probe()")
            if probe["kind"] not in ("connection", "authentication"):
                return  # the form closed after the last submit
            result = await page.evaluate("d => globalThis.__haFormHelper.fill(d, true)", details)
            if not result.get("filled"):
                raise Stuck("HA couldn't fill the connector form.")
            button = await page.evaluate("p => globalThis.__haConnectorManage.submitButton(p)", provider)
            if button["state"] != "click":
                raise Stuck("HA couldn't find the form's Create or Add button.")
            await self.click_marked(page)
            await page.wait_for_timeout(1500)

    async def approval_page(self, context, origin, seconds=90):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            for candidate in context.pages:
                u = urlsplit(candidate.url)
                if candidate.url.startswith(origin + "/") and u.path == "/authorize":
                    await candidate.wait_for_load_state("domcontentloaded")
                    return candidate
            await asyncio.sleep(0.5)
        raise Stuck("HA's approval page never opened.")

    async def approve(self, provider, page):
        flow = await page.locator("form[action='/authorize'] input[name=flow]").input_value()
        # The same checks as the Chrome helper: HA's current address, a live request, the right provider.
        code = self.pair(provider, page.url, flow)
        await page.locator("form[action='/authorize'] input[name=pairing_code]").fill(code["pairing_code"])
        await page.locator("form[action='/authorize'] button").click()
        hosts = ("chatgpt.com", "chat.openai.com", "claude.ai", "claude.com")
        try:
            await page.wait_for_url(lambda url: urlsplit(url).hostname in hosts, timeout=30000)
        except Exception:
            raise Stuck("The approval didn't return to " + provider + ".") from None
        await page.wait_for_timeout(3000)  # let the provider finish exchanging the code
