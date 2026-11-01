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
from contextlib import asynccontextmanager
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
    def __init__(self, folder, browser, details, pair, routes, name=NAME, *, service_status=None):
        """details(provider) and pair(provider, page_url, flow) come from the active connection."""
        self.name = name
        self.settings_path = Path(folder) / "auto_reconnect.json"
        self.browser, self.details, self.pair, self.routes = browser, details, pair, routes
        self.state = {}
        self.locks = {}
        self.service_status = service_status

    @asynccontextmanager
    async def profile_guard(self, provider):
        profile, _ = self.profile(provider)
        # Older adapters may not expose dispatch locking. NativeBrowser does;
        # share its lock with setup and model-picker work on the same profile.
        lock = self.browser.profile_lock(profile) if hasattr(self.browser, "profile_lock") else asyncio.Lock()
        async with lock:
            yield

    def authorized(self, provider):
        return bool(self.service_status and self.service_status(provider).get("authorized"))

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
                async with self.profile_guard(provider):
                    # Read the current endpoint before consulting its authorization
                    # state. A completed setup click is not proof of token exchange.
                    self.details(provider)
                    if self.authorized(provider):
                        self.report(provider, "done", "Already connected: HA confirmed this service's authorization.")
                    else:
                        await self.reconnect(provider)
            except asyncio.CancelledError:
                self.report(provider, "manual", "Connection setup was interrupted. Select Connect to retry.")
                raise
            except Stuck as exc:
                self.report(provider, "manual", str(exc) + " The setup tab stays open. You can also connect " + provider + " by hand (Connection details).")
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
        owned = set()
        def own(candidate):
            if candidate in owned:
                return
            owned.add(candidate)
            if hasattr(candidate, "on"):
                candidate.on("popup", own)
        own(page)
        completed = False
        cancelled = False
        try:
            await page.wait_for_load_state("domcontentloaded")
            if urlsplit(page.url).hostname not in hosts:
                raise Stuck("HA's " + provider + " tab isn't signed in. Sign in there (AI assistants, Set up), then select Connect again.")
            await self.remove_old(provider, page)
            await self.open_form(provider, page)
            self.report(provider, "working", "Filling in the new address.")
            await self.fill_and_submit(provider, page, details)
            self.report(provider, "working", "Approving on HA's page.")
            approval = await self.approval_page(context, origin, pages=owned)
            await self.approve(provider, approval)
            if self.service_status is None:
                raise Stuck("Approval returned, but HA cannot verify this service's token exchange.")
            deadline = time.monotonic() + 30
            while not self.authorized(provider):
                if time.monotonic() >= deadline:
                    raise Stuck("Approval returned, but the service has not completed authorization. Retry Connect after it finishes.")
                await asyncio.sleep(0.5)
            self.report(provider, "done", "Connected. HA verified " + provider + "'s authorization; tool use is checked separately.")
            completed = True
        except asyncio.CancelledError:
            cancelled = True
            raise
        finally:
            for candidate in owned:
                if hasattr(candidate, "remove_listener"):
                    candidate.remove_listener("popup", own)
            if completed or cancelled:
                # A shared Chrome context also contains other agents and owner
                # tabs. Only this setup tab and its own popups belong to us.
                for candidate in owned:
                    if not candidate.is_closed():
                        try:
                            await candidate.close()
                        except Exception:
                            pass  # closing Chrome must not mask the setup result
            elif not page.is_closed():
                try:
                    await page.bring_to_front()
                except Exception:
                    pass

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
        note = "Waiting for the connector settings controls."
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            await page.wait_for_timeout(400)
            try:
                await self.inject(page)
                if not reset:
                    await page.evaluate("globalThis.__haSetupNavigator.reset()")
                    reset = True
                step = await page.evaluate("globalThis.__haSetupNavigator.plan()")
            except Exception as exc:
                if "context" in str(exc).lower() or "navigat" in str(exc).lower():
                    continue  # the page reloaded under us; try again
                raise
            note = step.get("note") or note
            if step["state"] == "click":
                target = page.locator("[data-ha-navigation-target]")
                if await target.count() != 1:
                    raise Stuck("The connector navigation control changed before HA could click it.")
                # React menus may listen to trusted pointerdown rather than element.click().
                await target.click(timeout=5000)
            if step["state"] == "ready":
                return
            if step["state"] == "blocked":
                raise Stuck(step["note"])
        raise Stuck("The Add custom connector form did not open. " + note)

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

    async def approval_page(self, context, origin, seconds=90, *, pages=None):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            for candidate in list(context.pages if pages is None else pages):
                if candidate.is_closed():
                    continue
                u = urlsplit(candidate.url)
                if (u.scheme + "://" + u.netloc == origin and u.path == "/authorize"
                        and not u.username and not u.password and not u.fragment):
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
        hosts = ("chatgpt.com", "chat.openai.com") if provider == "ChatGPT" else ("claude.ai", "claude.com")
        try:
            await page.wait_for_url(lambda url: urlsplit(url).scheme == "https" and urlsplit(url).hostname in hosts, timeout=30000)
        except Exception:
            raise Stuck("The approval didn't return to " + provider + ".") from None
