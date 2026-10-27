"""Create a GitHub repository through github.com's own New repository page.

This is the fallback when HA's GitHub connection cannot create the repository
(not connected yet, or GitHub refused the request). It is a fixed sequence of
browser steps, not an AI: open github.com/new in HA's GitHub browser profile, fill
in the name, description and visibility, press Create repository and confirm
that GitHub opened the new repository's page. Nothing else is clicked.

It never signs in for the owner. If GitHub shows a sign-in or verification page,
the step stops and asks the owner to finish it in the opened window. A repository
that already exists is never adopted silently; the caller decides.
"""

import asyncio
import re
from urllib.parse import urlsplit

from hivemind_assembly.core.common import Blocked, Conflict, ContractError

NAME = re.compile(r"[A-Za-z0-9_.-]{1,100}")
OWNER = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}")
PROFILE = "github-setup"  # The same profile as Connect GitHub, so one sign-in covers both.


def guard(page):
    url = urlsplit(page.url)
    if url.scheme != "https" or url.hostname != "github.com" or url.username or url.password:
        raise Blocked("The GitHub page left github.com; nothing more was done.")


class GitHubWeb:
    NEW = "https://github.com/new"

    def __init__(self, browser, timeout=60):
        self.browser, self.timeout = browser, timeout

    async def page(self, url):
        page = await self.browser.service_page(PROFILE, url, {"github.com"})
        guard(page)
        return page

    @staticmethod
    async def signed_in(page):
        path = urlsplit(page.url).path
        if path.startswith(("/login", "/session", "/sessions", "/sudo", "/two-factor")):
            return None
        if await page.locator('input[type="password"], input[autocomplete="one-time-code"]').count():
            return None
        login = await page.locator('meta[name="user-login"]').get_attribute("content")
        return login if login and OWNER.fullmatch(login) else None

    async def exists(self, owner, name):
        """True when the signed-in account can open github.com/owner/name."""
        page = await self.page(self.NEW)
        try:
            if not await self.signed_in(page):
                page = None  # Leave the window open for the owner to sign in.
                raise Blocked(
                    "Sign in to GitHub in the window HA opened, then try again."
                )
            response = await page.goto(
                f"https://github.com/{owner}/{name}", wait_until="domcontentloaded"
            )
            guard(page)
            return bool(response and response.status == 200) and self._at_repository(
                page, owner, name
            )
        finally:
            await self._close(page)

    @staticmethod
    def _at_repository(page, owner, name):
        path = urlsplit(page.url).path.strip("/").lower()
        return path == f"{owner}/{name}".lower()

    async def create(self, owner, name, description="", visibility="private"):
        """Fill in and submit github.com/new; return the created repository."""
        if not NAME.fullmatch(name or "") or name in (".", ".."):
            raise ContractError("Repository name must contain 1–100 letters, numbers, dots, underscores or hyphens.")
        if owner and not OWNER.fullmatch(owner):
            raise ContractError("Invalid GitHub account or organization name.")
        if visibility not in ("private", "public"):
            raise ContractError("Repository visibility must be private or public.")
        page = await self.page(self.NEW)
        try:
            login = await self.signed_in(page)
            if not login:
                page = None  # Leave the window open for the owner to sign in.
                raise Blocked(
                    "Sign in to GitHub in the window HA opened, then try again."
                )
            owner = owner or login
            if owner.lower() != login.lower():
                await self._choose_owner(page, owner)
            field = page.locator("#repository-name-input")
            if await field.count() != 1:
                field = page.get_by_label("Repository name", exact=False)
            await field.fill(name)
            if await self._name_taken(page, name):
                raise Conflict(
                    f"{owner}/{name} already exists on GitHub. Choose another name or use the existing repository."
                )
            if description:
                await page.get_by_label("Description", exact=True).fill(description)
            await self._choose_visibility(page, visibility)
            guard(page)
            await page.get_by_role("button", name="Create repository", exact=True).click()
            await page.wait_for_url(
                re.compile(rf"^https://github\.com/{re.escape(owner)}/{re.escape(name)}/?(\?.*)?$", re.I),
                timeout=self.timeout * 1000,
            )
            guard(page)
            return {
                "owner": owner,
                "name": name,
                "url": f"https://github.com/{owner}/{name}",
                "visibility": visibility,
                "created_with": "browser",
            }
        finally:
            await self._close(page)

    async def _choose_owner(self, page, owner):
        await page.locator("#owner-dropdown-header-button").click()
        for role in ("menuitemradio", "option", "menuitem"):
            item = page.get_by_role(role, name=owner, exact=True)
            if await item.count() == 1:
                await item.click()
                break
        else:
            raise Blocked(
                f"GitHub's New repository page does not offer {owner} as an owner for this account."
            )
        label = await page.locator("#owner-dropdown-header-button").get_attribute("aria-label") or ""
        if not label.lower().startswith(owner.lower() + ","):
            raise Blocked(f"GitHub did not switch the owner to {owner}.")

    async def _name_taken(self, page, name):
        # GitHub checks the name as it is typed; wait for its verdict.
        for _ in range(20):
            if await page.get_by_text(f"{name} is available.", exact=False).count():
                return False
            if await page.get_by_text("already exists", exact=False).count():
                return True
            await asyncio.sleep(0.25)
        raise Blocked("GitHub did not confirm that the repository name is available.")

    async def _choose_visibility(self, page, visibility):
        wanted = "Private" if visibility == "private" else "Public"
        button = page.locator("#visibility-anchor-button")
        if await button.count() != 1:
            button = page.get_by_role("button", name=re.compile(r"^Choose visibility", re.I))
        label = await button.get_attribute("aria-label") or ""
        if not label.endswith(": " + wanted):
            await button.click()
            await page.get_by_role("menuitemradio", name=re.compile("^" + wanted)).click()
            label = await button.get_attribute("aria-label") or ""
        if not label.endswith(": " + wanted):
            raise Blocked(f"GitHub did not confirm {wanted} visibility; nothing was created.")

    @staticmethod
    async def _close(page):
        if page is None:
            return
        try:
            await page.close()
        except Exception:
            pass
