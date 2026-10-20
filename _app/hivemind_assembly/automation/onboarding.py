"""Resumable native setup through observed controls and verified file transfers."""

import asyncio
import copy
import json
from urllib.parse import urlsplit, urljoin
from hivemind_assembly.core.common import (
    Blocked,
    WaitingForSignIn,
    Retryable,
    atomic_write,
    canonical,
    uid,
)
from .policy import Availability, Window, validate_config
from .providers import discover, conversation_url


class NativeSetup:
    def __init__(self, browser, store, config_path, sessions=None, team=None):
        self.browser, self.store, self.config_path = browser, store, config_path
        self.sessions, self.team = sessions, team
        self.pages = {}
        self.locks = {}

    def status(self, route):
        rows = self.store.rows(
            "SELECT payload FROM records WHERE kind=? ORDER BY created DESC LIMIT 1",
            ("native_setup:" + route,),
        )
        return json.loads(rows[0]["payload"]) if rows else {"stage": "not_started"}

    def save(self, route, **state):
        if self.status(route) != state:
            self.store.put("native_setup:" + route, uid("setup"), state)
        return state

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
            # The exact identity just observed authorizes only the canary here.
            # Work readiness is published after both transfer directions pass.
            observation = copy.deepcopy(observation)
            observation.ready = True
            observation.blocked = ""
        return observation

    async def step(self, route):
        if route not in self.browser.config["routes"]:
            raise Blocked("Unknown native route")
        async with self.locks.setdefault(route, asyncio.Lock()):
            cfg = self.browser.config["routes"][route]
            page = self.pages.get(route)
            if page is None or page.is_closed():
                from .providers import CONTRACTS

                url = (
                    cfg.get("conversation_url") or CONTRACTS[cfg["provider"]]["new_url"]
                )
                page = await self.browser.service_page(cfg["profile"], url)
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
            discovered = await discover(page, cfg)
            if discovered["missing"]:
                return self.save(
                    route,
                    stage="binding_required",
                    instruction="Waiting for visible exact controls: "
                    + ", ".join(discovered["missing"]),
                )
            old = copy.deepcopy(cfg)
            cfg.update(
                selectors=discovered["selectors"],
                account_label=discovered["account_label"],
            )
            persistent = conversation_url(cfg, page.url)
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
            atomic_write(self.config_path, canonical(self.browser.config))
            if self.sessions is None or self.team is None:
                return self.save(
                    route,
                    stage="bound" if persistent else "ready_for_session",
                    evidence=evidence,
                    instruction="Exact controls observed. Native session acceptance remains pending.",
                )
            if persistent and self.sessions.accepted(route):
                return self.save(
                    route,
                    stage="verified",
                    evidence=evidence,
                    instruction="Exact native route and both attachment directions verified.",
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
            await self.sessions.renew("session_setup", route)
            self.pages[route] = self.browser.pages[route]
            self.team.observations[route] = observation
            from dataclasses import asdict

            self.store.put("availability", uid("usage"), asdict(observation))
            return self.save(
                route,
                stage="verified",
                instruction="Exact native route, persistent conversation and both attachment directions verified.",
            )

    async def run(self, route):
        while True:
            try:
                result = await self.step(route)
            except WaitingForSignIn as error:
                result = self.save(
                    route, stage="authentication", instruction=str(error)
                )
            except Retryable as error:
                result = self.save(
                    route, stage="waiting_delivery", instruction=str(error)
                )
            except Exception as error:
                return self.save(
                    route, stage="attention", instruction="Setup paused: " + str(error)
                )
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
