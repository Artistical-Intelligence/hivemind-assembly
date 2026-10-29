"""Resumable native setup through observed controls and verified file transfers."""

import asyncio
import copy
import json
import time
from pathlib import Path
from urllib.parse import urlsplit, urljoin
from hivemind_assembly.core.common import (
    Blocked,
    WaitingForSignIn,
    AllowanceUnavailable,
    Retryable,
    atomic_write,
    canonical,
    uid,
)
from .native import DeliveryPending
from .policy import Availability, Window, validate_config
from .providers import CONTRACTS, discover, conversation_url


PROVIDER_NAMES = {"openai": "ChatGPT", "claude": "Claude"}


class NativeSetup:
    def __init__(self, browser, store, config_path, sessions=None, team=None):
        self.browser, self.store, self.config_path = browser, store, config_path
        self.sessions, self.team = sessions, team
        self.pages = {}
        self.locks = {}
        # Routes sharing a browser profile share one sign-in: only one of them
        # opens a page until that profile is signed in.
        self.signing_in = {}
        self.changed = {}  # route -> when its stage last changed (for "for 3 min")
        self.snapshot_dir = Path(store.root) / "private" / "setup-snapshots"
        self.snapshots = {}  # route -> when the picture of its tab was taken

    def status(self, route):
        rows = self.store.rows(
            "SELECT payload FROM records WHERE kind=? ORDER BY rowid DESC LIMIT 1",
            ("native_setup:" + route,),
        )
        return json.loads(rows[0]["payload"]) if rows else {"stage": "not_started"}

    def save(self, route, **state):
        previous = self.status(route)
        if previous != state:
            self.store.put("native_setup:" + route, uid("setup"), state)
            if previous.get("stage") != state.get("stage"):
                self.changed[route] = time.time()
        return state

    def display_page(self, route):
        for pages in (getattr(self.sessions, "setup_pages", {}), self.pages, getattr(self.browser, "pages", {})):
            page = pages.get(route)
            if page is not None and not page.is_closed():
                return page
        return None

    def progress(self, route):
        """Setup status for the dashboard: stage, message, since when, and a tab picture."""
        page = self.display_page(route)
        return {
            **self.status(route),
            "since": self.changed.get(route),
            "tab_open": bool(page is not None and not page.is_closed()),
            "snapshot": self.snapshots.get(route),
        }

    def snapshot_path(self, route):
        return self.snapshot_dir / (route + ".jpg")

    async def snapshot(self, route, force=False):
        """Keep a picture of the assistant's tab, so the owner can see what HA sees."""
        page = self.display_page(route)
        if page is None or page.is_closed():
            return
        if not force and time.time() - self.snapshots.get(route, 0) < 60:
            return
        try:
            self.snapshot_dir.mkdir(parents=True, exist_ok=True)
            await asyncio.wait_for(
                page.screenshot(path=str(self.snapshot_path(route)), type="jpeg", quality=70),
                15,
            )
            self.snapshots[route] = time.time()
        except Exception:
            pass  # a picture is a convenience; setup goes on without it

    async def show(self, route):
        """Bring the assistant's tab to the front (and its window), if HA has one open."""
        page = self.display_page(route)
        if page is None or page.is_closed():
            page = getattr(self.browser, "pages", {}).get(route)
        if page is None or page.is_closed():
            return False
        await page.bring_to_front()
        return True

    async def allowance(self, route, cfg):
        usage = cfg["usage"]
        scope = usage.get("scope", route)
        observation = self.team.observations.get(route)
        if self.team.usage.claim_poll(scope):
            raw = await self.browser.poll_usage(route)
            record = dict(
                route=route,
                ready=False,
                allowance_known=True,
                no_numeric_limit=raw["no_numeric_limit"],
                observed=raw["observed"],
                windows=raw["windows"],
                blocked="Session acceptance pending",
            )
            observation = Availability(
                **{**record, "windows": [Window(**w) for w in raw["windows"]]}
            )
            self.team.observations[route] = observation
            self.store.put("availability", uid("usage"), record)
        elif observation is None:
            for other, item in self.team.observations.items():
                peer = self.browser.config["routes"][other]
                if (
                    peer.get("usage", {}).get("scope") == scope
                    and peer.get("account_label") == cfg["account_label"]
                ):
                    observation = copy.deepcopy(item)
                    observation.route = route
                    break
        if observation is not None:
            if observation.blocked_kind == "quota":
                return observation
            # The exact identity just observed authorizes only the canary here.
            # Work readiness is published after both transfer directions pass.
            observation = copy.deepcopy(observation)
            observation.ready = True
            observation.blocked = ""
            observation.blocked_kind = ""
        return observation

    async def step(self, route):
        if route not in self.browser.config["routes"]:
            raise Blocked("Unknown native route")
        async with self.locks.setdefault(route, asyncio.Lock()):
            cfg = self.browser.config["routes"][route]
            profile = cfg["profile"]
            page = self.pages.get(route)
            if page is None or page.is_closed():
                owner = self.signing_in.get(profile)
                owner_page = self.pages.get(owner)
                if owner not in (None, route) and owner_page is not None and not owner_page.is_closed():
                    return self.save(
                        route,
                        stage="authentication",
                        instruction="Waiting for sign-in in the window already open for this account.",
                    )
                self.save(
                    route,
                    stage="opening",
                    instruction="Opening " + PROVIDER_NAMES.get(cfg["provider"], cfg["provider"]) + " in a tab.",
                )
                url = (
                    cfg.get("conversation_url") or CONTRACTS[cfg["provider"]]["new_url"]
                )
                self.signing_in[profile] = route
                try:
                    page = await self.browser.service_page(profile, url, cfg["allowed_hosts"])
                except BaseException:
                    if self.signing_in.get(profile) == route:
                        del self.signing_in[profile]
                    raise
                self.pages[route] = page
            if urlsplit(page.url).hostname not in cfg["allowed_hosts"]:
                return self.save(
                    route,
                    stage="authentication",
                    instruction="Waiting for provider sign-in to return to the native service.",
                )
            self.browser.validate_url(route, page.url)
            login = False
            for name in ("Log in", "Sign in"):
                button = page.get_by_role("button", name=name, exact=True)
                login = login or (
                    await button.count() > 0 and await button.first.is_visible()
                )
            if (
                login
                or await page.locator(
                    'input[type="password"], input[autocomplete="one-time-code"]'
                ).count()
                or "/login" in page.url
                or "/auth/" in page.url
            ):
                return self.save(
                    route,
                    stage="authentication",
                    instruction="Complete provider sign-in in the opened browser; setup continues automatically.",
                )
            if self.signing_in.get(profile) == route:
                # Signed in: the account's other routes can open their chats now.
                del self.signing_in[profile]
            # Routes sharing an account take turns: the page keeps model and effort per account.
            lock = getattr(self.browser, "dispatch_lock", None)
            if lock is not None:
                async with lock(route):
                    discovered = await discover(page, cfg)
            else:
                discovered = await discover(page, cfg)
            if discovered["missing"]:
                return self.save(
                    route,
                    stage="binding_required",
                    instruction="Waiting for visible exact controls: "
                    + ", ".join(discovered["missing"]),
                    detail=discovered.get("detail", ""),
                )
            old = copy.deepcopy(cfg)
            cfg.update(
                selectors=discovered["selectors"],
                account_label=discovered["account_label"],
            )
            unresolved = bool(getattr(self.sessions, "pending", lambda r: [])(route))
            # Opening the original chat to recover an unresolved request must not
            # change the previous binding used to identify its retained intent.
            persistent = conversation_url(cfg, page.url) and not unresolved
            evidence = None
            if persistent:
                cfg["conversation_url"] = page.url
                self.browser.pages[route] = page
                try:
                    evidence = await self.browser.observe(route)
                    validate_config(self.browser.config)
                except Exception:
                    cfg.clear()
                    cfg.update(old)
                    raise
            usage = cfg.setdefault("usage", {})
            if not usage.get("url"):
                links = await page.get_by_role("link", name="Usage", exact=True).all()
                if len(links) == 1:
                    url = urljoin(page.url, await links[0].get_attribute("href") or "")
                    self.browser.validate_url(route, url)
                    usage.update(url=url, discover_progressbars=True)
            if not usage.get("url") and CONTRACTS[cfg["provider"]].get("usage_url"):
                # Today's sites keep usage behind menus; their usage pages have fixed addresses.
                url = CONTRACTS[cfg["provider"]]["usage_url"]
                self.browser.validate_url(route, url)
                usage.update(url=url, discover_progressbars=True)
            atomic_write(self.config_path, canonical(self.browser.config))
            if self.sessions is None or self.team is None:
                return self.save(
                    route,
                    stage="bound" if persistent else "ready_for_session",
                    evidence=evidence,
                    instruction="Exact controls observed. Native session acceptance remains pending.",
                )
            if not usage.get("url"):
                return self.save(
                    route,
                    stage="allowance_mapping",
                    instruction="Waiting for an unambiguous provider allowance mapping. No model request has been sent.",
                )
            observation = await self.allowance(route, cfg)
            if observation is None or not observation.eligible():
                return self.save(
                    route,
                    stage="waiting_quota",
                    instruction="Session acceptance waits for sufficient allowance under the 24-hour polling policy.",
                )
            if not (persistent and self.sessions.accepted(route)):
                self.save(route, stage="ready_for_session", instruction="Checking the saved setup conversation; unresolved requests are never resent.")
                await self.sessions.renew("session_setup", route)
                self.pages[route] = self.browser.pages[route]
            # A durable session commit can precede a process crash. Publish
            # readiness from the retained allowance even when no renewal is needed.
            self.team.observations[route] = observation
            from dataclasses import asdict

            self.store.put("availability", uid("usage"), asdict(observation))
            return self.save(
                route,
                stage="verified",
                instruction="Exact native route, persistent conversation and both attachment directions verified.",
            )

    async def run(self, route):
        unconfirmed = 0
        while True:
            try:
                result = await self.step(route)
            except WaitingForSignIn as error:
                result = self.save(
                    route, stage="authentication", instruction=str(error)
                )
            except AllowanceUnavailable as error:
                if self.team is not None:
                    self.team.block_allowance(error.route or route, str(error))
                result = self.save(
                    route, stage="waiting_quota", instruction=str(error)
                )
            except DeliveryPending as error:
                # Each exchange observes the existing send for up to 30 seconds.
                # Bound automatic retries; never recreate or resend the request.
                unconfirmed += 1
                if unconfirmed >= 3:
                    await self.snapshot(route, force=True)
                    return self.save(
                        route, stage="attention",
                        instruction="The existing request could not be confirmed after three checks. "
                        "Its saved state is retained and it has not been resent. Open Show tab to inspect the conversation.",
                    )
                result = self.save(
                    route, stage="waiting_delivery", instruction=str(error)
                )
            except Retryable as error:
                result = self.save(
                    route, stage="waiting_delivery", instruction=str(error)
                )
            except Exception as error:
                # Browser errors carry long call logs; the first line says what happened.
                first = (str(error).strip().splitlines() or [type(error).__name__])[0][:300]
                await self.snapshot(route, force=True)
                return self.save(
                    route, stage="attention", instruction="Setup stopped: " + first + " Select Set up to try again."
                )
            if result["stage"] in ("binding_required", "allowance_mapping", "waiting_delivery"):
                await self.snapshot(route)
            if result["stage"] not in (
                "authentication",
                "binding_required",
                "allowance_mapping",
                "waiting_quota",
                "waiting_delivery",
            ):
                return result
            await asyncio.sleep(5 if result["stage"] == "authentication" else 30)

    async def run_all(self):
        return await asyncio.gather(
            *(self.run(route) for route in self.browser.config["routes"])
        )
