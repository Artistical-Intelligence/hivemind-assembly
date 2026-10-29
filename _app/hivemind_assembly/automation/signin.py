"""Observe provider sign-in independently of model selection and session acceptance."""

import asyncio
import time
from urllib.parse import urlsplit

from .providers import CONTRACTS, dismiss_popups
from .surfaces import EMAIL, SURFACES


class NativeSignIn:
    def __init__(self, browser):
        self.browser = browser
        self.pages = {}
        self.profiles = {}
        self.tasks = {}
        self.states = {}
        self.locks = {}

    def status(self, provider):
        return dict(self.states.get(provider, {}))

    def save(self, provider, stage, account="", message=""):
        state = dict(stage=stage, account=account, message=message, checked_at=time.time())
        self.states[provider] = state
        return state

    async def open(self, provider, profile, hosts):
        async with self.locks.setdefault(provider, asyncio.Lock()):
            # A separate tab keeps account-menu clicks away from active conversations.
            page = self.pages.get(provider)
            identity = (profile, tuple(sorted(hosts)))
            if self.profiles.get(provider) != identity:
                task = self.tasks.pop(provider, None)
                if task is not None:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                if page is not None and not page.is_closed():
                    await page.close()
                page = None
                self.pages.pop(provider, None)
                self.states.pop(provider, None)
                self.profiles[provider] = identity
            if page is None or page.is_closed():
                page = await self.browser.service_page(profile, CONTRACTS[provider]["new_url"], hosts)
                self.pages[provider] = page
            await page.bring_to_front()
            task = self.tasks.get(provider)
            if task is None or task.done():
                self.save(provider, "checking", message="Checking the signed-in account…")
                self.tasks[provider] = asyncio.create_task(self.watch(provider, page, hosts))
            return page

    async def observe(self, provider, page, hosts):
        parts = urlsplit(page.url)
        if parts.scheme != "https" or parts.hostname not in hosts or parts.path.startswith(("/login", "/log-in", "/auth/")):
            return self.save(provider, "authentication", message="Complete sign-in in the opened tab.")
        for name in ("Log in", "Sign in"):
            buttons = page.get_by_role("button", name=name, exact=True)
            for button in await buttons.all():
                if await button.is_visible():
                    return self.save(provider, "authentication", message="Complete sign-in in the opened tab.")
        await dismiss_popups(page)
        # Account reading deliberately does not require an available model/effort.
        account = await SURFACES[provider].account(page)
        if account and EMAIL.fullmatch(account):
            return self.save(provider, "signed_in", account, "Signed in. Assistant setup is checked separately.")
        return self.save(provider, "checking", message="Waiting for the account menu to become available…")

    async def watch(self, provider, page, hosts, attempts=120, interval=5):
        # Ten minutes of bounded checks; clicking the service starts another check.
        for _ in range(attempts):
            if page.is_closed():
                return self.save(provider, "attention", message="Sign-in tab closed. Open it to check again.")
            try:
                state = await self.observe(provider, page, hosts)
                if state["stage"] == "signed_in":
                    return state
            except Exception:
                # Loading, redirects and temporary menu failures can resolve after sign-in.
                self.save(provider, "checking", message="Waiting for the account menu. Close any blocking pop-up in the tab.")
            await asyncio.sleep(interval)
        return self.save(provider, "attention", message="Could not confirm the account. Open the service to check again.")

    async def close(self):
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.tasks.clear()
        self.pages.clear()
        self.profiles.clear()
        self.states.clear()
