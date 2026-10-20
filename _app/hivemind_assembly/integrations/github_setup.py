"""Resumable owner-initiated OAuth registration through GitHub's visible UI.

No client secret is generated or read. GitHub authentication challenges stay in
its dedicated browser profile. Only non-secret setup state is journalled.
"""

import asyncio
import json
import re
from hashlib import sha256
from urllib.parse import urlsplit

from hivemind_assembly.core.common import (
    Blocked,
    ContractError,
    atomic_write,
    canonical,
)


class GitHubSetup:
    HOME = "https://github.com/Artistical-Intelligence/hivemind-assembly"
    CALLBACK = "http://127.0.0.1/oauth/callback"  # Required registration field; device flow does not use it.
    LIST = "https://github.com/settings/developers"

    def __init__(self, browser, auth, root):
        self.browser, self.auth, self.root = browser, auth, root
        self.path = root / "private" / "github-setup.json"
        self.lock = asyncio.Lock()
        self.device = None
        self.tab = None

    def status(self):
        return (
            json.loads(self.path.read_text())
            if self.path.exists()
            else {"stage": "not_started"}
        )

    def save(self, **values):
        state = {**self.status(), **values}
        atomic_write(self.path, canonical(state))
        return state

    @staticmethod
    def guard(page):
        url = urlsplit(page.url)
        if (
            url.scheme != "https"
            or url.hostname != "github.com"
            or url.username
            or url.password
        ):
            raise Blocked("GitHub setup left github.com; no further action was taken")

    async def page(self):
        if self.tab is None or self.tab.is_closed():
            self.tab = await self.browser.service_page("github-setup", self.LIST)
        self.guard(self.tab)
        return self.tab

    async def challenge(self, page):
        self.guard(page)
        path = urlsplit(page.url).path
        if path.startswith(
            ("/login", "/sessions", "/sudo", "/two-factor")
        ) and not path.startswith("/login/device"):
            return self.save(
                stage="authentication",
                instruction="Complete GitHub sign-in or verification in the opened browser. Setup resumes when you press Continue.",
            )
        if await page.locator(
            'input[type="password"], input[autocomplete="one-time-code"]'
        ).count():
            return self.save(
                stage="authentication",
                instruction="Complete GitHub's authentication challenge in the opened browser, then Continue.",
            )
        return None

    async def step(self):
        async with self.lock:
            self.auth.vault.ready()  # Detect unavailable secure storage before creating an app.
            state = self.status()
            if state.get("stage") == "connected" or self.auth.status().get("connected"):
                if self.auth.vault.read():
                    from .github import GitHubClient

                    identity = await asyncio.to_thread(GitHubClient(self.auth).identity)
                    if (
                        state.get("account")
                        and identity["login"].lower() != state["account"].lower()
                    ):
                        raise Blocked(
                            "GitHub is connected to a different account than this setup"
                        )
                    return self.save(
                        stage="connected", instruction="GitHub connection verified."
                    )
                state = self.save(stage="registered")
            page = await self.page()
            if result := await self.challenge(page):
                return result
            if state.get("client_id"):
                return await self.authorize(page, state["client_id"])
            account = await page.locator('meta[name="user-login"]').get_attribute(
                "content"
            )
            if not account or not re.fullmatch(r"[A-Za-z0-9-]+", account):
                raise Blocked("Cannot verify the signed-in GitHub account")
            if state.get("account") and account != state["account"]:
                raise Blocked(
                    "GitHub account changed during setup; return to the original account"
                )
            app_name = (
                state.get("app_name")
                or "Hivemind Assembly Local "
                + sha256(str(self.root).encode()).hexdigest()[:8]
            )
            state = self.save(account=account, app_name=app_name)
            await page.goto(self.LIST, wait_until="domcontentloaded")
            if result := await self.challenge(page):
                return result
            links = page.get_by_role("link", name=app_name, exact=True)
            count = await links.count()
            if count > 1:
                raise Blocked(
                    "Multiple matching OAuth registrations; setup will not choose one arbitrarily"
                )
            if count == 1:
                href = await links.get_attribute("href")
                if not re.fullmatch(r"/settings/applications/\d+", href or ""):
                    raise Blocked("Unexpected OAuth application link")
                await page.goto(
                    "https://github.com" + href, wait_until="domcontentloaded"
                )
            else:
                if state.get("registration_intent"):
                    return self.save(
                        stage="registration_uncertain",
                        instruction="The registration submission was interrupted and no matching app is visible. Check GitHub's OAuth apps before resetting setup; it will not submit twice.",
                    )
                await page.goto(
                    "https://github.com/settings/applications/new",
                    wait_until="domcontentloaded",
                )
                if result := await self.challenge(page):
                    return result
                await page.get_by_label("Application name", exact=False).fill(app_name)
                await page.get_by_label("Homepage URL", exact=False).fill(self.HOME)
                await page.get_by_label("Authorization callback URL", exact=False).fill(
                    self.CALLBACK
                )
                await page.get_by_label("Enable Device Flow", exact=False).check()
                self.save(stage="registering", registration_intent=True)
                # Persist before clicking. Reconcile by unique app name after any failure.
                await page.get_by_role(
                    "button", name="Register application", exact=True
                ).click()
                await page.wait_for_load_state("domcontentloaded")
            if result := await self.challenge(page):
                return result
            self.guard(page)
            if not re.fullmatch(r"/settings/applications/\d+", urlsplit(page.url).path):
                raise Blocked(
                    "OAuth registration was not confirmed; inspect the browser validation message"
                )
            flow = page.get_by_label("Enable Device Flow", exact=False)
            if not await flow.is_checked():
                await flow.check()
                await page.get_by_role(
                    "button", name="Update application", exact=True
                ).click()
                await page.wait_for_load_state("domcontentloaded")
                self.guard(page)
                if not await flow.is_checked():
                    raise Blocked("GitHub did not confirm Device Flow")
            # Read only the public ID, never the client-secrets region.
            client_id = await page.evaluate(
                """() => {
                const label=[...document.querySelectorAll('dt,label,h3,h4')].find(e=>e.textContent.trim()==='Client ID');
                if(!label) return null;
                const next=label.nextElementSibling;
                const copy=next?.querySelector('clipboard-copy[value]');
                return copy?.getAttribute('value') || next?.textContent.trim() || null;
            }"""
            )
            if not isinstance(client_id, str) or not re.fullmatch(
                r"[A-Za-z0-9_.-]{5,100}", client_id
            ):
                raise Blocked(
                    "GitHub's public Client ID field was not recognized; the registration is retained"
                )
            self.save(stage="registered", client_id=client_id, application_url=page.url)
            return await self.authorize(page, client_id)

    async def authorize(self, page, client_id):
        if not self.auth.pending:
            self.device = await asyncio.to_thread(self.auth.start, client_id)
        if self.device:
            await page.goto(
                self.device["verification_uri"], wait_until="domcontentloaded"
            )
            if result := await self.challenge(page):
                return result
            field = page.get_by_label("Device code", exact=False)
            if await field.count() != 1:
                field = page.locator('input[name="user_code"]')
            if await field.count() == 1:
                await field.fill(self.device["user_code"])
                await page.get_by_role("button", name="Continue", exact=True).click()
                await page.wait_for_load_state("domcontentloaded")
                self.guard(page)
                self.device = None
        # Account sign-in, 2FA or consent can stay open while the rest of HA works.
        # Clicking setup explicitly authorizes this app's repo scope. Never select
        # arbitrary permissions or another app's authorization button.
        app_name = self.status()["app_name"]
        authorize = page.get_by_role(
            "button", name="Authorize " + self.status()["account"], exact=True
        )
        if (
            await page.get_by_text(app_name, exact=True).count()
            and await authorize.count() == 1
        ):
            self.guard(page)
            await authorize.click()
        result = await asyncio.to_thread(self.auth.poll)
        if result.get("status") == "pending":
            return self.save(
                stage="authorizing",
                instruction="Finish any GitHub authentication or consent shown in the browser. Continue checks authorization without restarting setup.",
            )
        if result.get("login", "").lower() != self.status()["account"].lower():
            await asyncio.to_thread(self.auth.disconnect)
            raise Blocked(
                "GitHub authorized a different account; return to the setup account"
            )
        return self.save(stage="connected", instruction="GitHub is connected.")

    async def run(self):
        """Keep progressing while the owner completes authentication in the UI."""
        for _ in range(360):
            try:
                result = await self.step()
            except (Blocked, ContractError) as error:
                return self.save(stage="attention", instruction=str(error))
            except Exception:
                return self.save(
                    stage="attention",
                    instruction="The GitHub page changed or a browser action was interrupted. Continue reconciles the retained registration before another action.",
                )
            if result["stage"] in ("connected", "registration_uncertain"):
                return result
            await asyncio.sleep(5)
        return self.save(
            stage="attention",
            instruction="Setup is retained. Continue when you are ready to finish GitHub authentication.",
        )
