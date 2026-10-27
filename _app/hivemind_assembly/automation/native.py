"""Native browser transport only. No hidden model endpoints or API clients."""

from __future__ import annotations
import asyncio, json, re, time, uuid
from pathlib import Path
from urllib.parse import urlsplit
from hivemind_assembly.core.common import (
    Blocked,
    Retryable,
    ContractError,
    canonical,
    file_hash,
    identifier,
    WaitingForSignIn,
    AllowanceUnavailable,
)


def marker_pattern(marker):
    import re

    return re.compile(r"(?:^|\s)" + re.escape(marker) + r"(?:\s|$)")


class NativeBrowser:
    def __init__(self, config, root, controller):
        self.config = config
        self.root = Path(root)
        self.controller = controller
        self.contexts = {}
        self.pages = {}
        self.locks = {}
        self.playwright = None
        self.start_lock = asyncio.Lock()
        self.profile_locks = {}
        self.sign_in_waiting = set()
        self.service_pages = set()
        # "Your Chrome" mode: tabs in the owner's own Chrome via the helper extension.
        self.relay = None
        self.owner_browser = None
        self.owner_lock = asyncio.Lock()
        # Today's pages keep model and effort per account, so routes sharing an account
        # set their route and send one at a time; full checks are reused for a while.
        self.dispatch_locks = {}
        self.deep_checked = {}
        self.light = set()  # routes waiting for a reply: quick checks only, no menus

    def dispatch_lock(self, route):
        profile = identifier(self.config["routes"][route].get("profile") or route)
        return self.dispatch_locks.setdefault(profile, asyncio.Lock())

    def profile_dir(self, profile):
        # Chrome gets its own folders: a profile Edge wrote may not open cleanly in Chrome.
        if self.config.get("browser", {}).get("channel") == "chrome":
            return self.root / "private" / "browser" / "chrome" / profile
        return self.root / "private" / "browser" / profile

    def your_chrome(self):
        return self.config.get("browser", {}).get("mode") == "your_chrome"

    async def owner_context(self):
        """The owner's Chrome, reached through the helper extension; one window of HA tabs."""
        async with self.owner_lock:
            if self.owner_browser is not None and self.owner_browser.is_connected():
                return self.owner_browser.contexts[0]
            if self.relay is None:
                raise Blocked("Your-Chrome mode isn't available in this HA session.")
            await self.start()
            await self.relay.start()
            await self.relay.wait_for_extension(60)
            browser = await self.playwright.chromium.connect_over_cdp(self.relay.cdp_url)
            browser.on("disconnected", lambda _: self.forget_owner(browser))
            self.owner_browser = browser
            return browser.contexts[0]

    def forget_owner(self, browser):
        """Chrome or the extension went away: reconnect (and reopen tabs) on next use."""
        if self.owner_browser is browser:
            self.owner_browser = None
        gone = set(browser.contexts)
        self.contexts = {k: v for k, v in self.contexts.items() if v not in gone}
        self.pages = {k: v for k, v in self.pages.items() if not v.is_closed()}

    async def start(self):
        from playwright.async_api import async_playwright

        async with self.start_lock:
            if self.playwright is None:
                self.playwright = await async_playwright().start()

    async def close(self):
        owned = set(self.owner_browser.contexts) if self.owner_browser else set()
        for ctx in self.contexts.values():
            if ctx not in owned:
                await ctx.close()
        if self.owner_browser is not None:
            await self.owner_browser.close()  # disconnects; the owner's Chrome stays open
            self.owner_browser = None
        if self.playwright:
            await self.playwright.stop()
        self.contexts = {}
        self.pages = {}
        self.playwright = None

    async def page(self, route):
        profile = identifier(self.config["routes"][route]["profile"])
        async with self.profile_locks.setdefault(profile, asyncio.Lock()):
            return await self._page(route)

    async def service_page(self, profile, url, allowed_hosts=None):
        """Dedicated visible profile for owner-requested account setup."""
        profile = identifier(profile)
        parts = urlsplit(url)
        if (
            parts.scheme != "https"
            or parts.username
            or parts.password
            or (allowed_hosts is not None and parts.hostname not in allowed_hosts)
        ):
            # Never open an arbitrary page inside a signed-in provider profile.
            raise Blocked("Setup URL is outside the configured service")
        async with self.profile_locks.setdefault(profile, asyncio.Lock()):
            await self.start()
            if profile not in self.contexts and self.your_chrome():
                self.contexts[profile] = await self.owner_context()
            if profile not in self.contexts:
                opts = {
                    k: v
                    for k, v in self.config.get("browser", {}).items()
                    if k
                    in ("channel", "locale", "timezone_id", "viewport", "color_scheme")
                }
                self.contexts[profile] = (
                    await self.playwright.chromium.launch_persistent_context(
                        str(self.profile_dir(profile)),
                        headless=False,
                        **opts,
                    )
                )
            context = self.contexts[profile]
            # Reuse the empty tab the browser opens at launch instead of adding one.
            self.service_pages = {p for p in self.service_pages if not p.is_closed()}
            claimed = set(self.pages.values()) | self.service_pages
            blank = [p for p in context.pages if p.url == "about:blank" and p not in claimed]
            page = blank[0] if blank else await context.new_page()
            self.service_pages.add(page)
            await page.goto(url, wait_until="domcontentloaded")
            return page

    async def _page(self, route):
        cfg = self.config["routes"][route]
        profile = identifier(cfg["profile"])
        if profile not in self.contexts and self.your_chrome():
            self.contexts[profile] = await self.owner_context()
        if profile not in self.contexts:
            if not self.playwright:
                await self.start()
            opts = self.config.get("browser", {})
            allowed = {
                k: v
                for k, v in opts.items()
                if k
                in (
                    "headless",
                    "channel",
                    "locale",
                    "timezone_id",
                    "viewport",
                    "color_scheme",
                )
            }
            allowed.setdefault("headless", False)
            self.contexts[profile] = (
                await self.playwright.chromium.launch_persistent_context(
                    str(self.profile_dir(profile)),
                    accept_downloads=True,
                    **allowed,
                )
            )
        if route not in self.pages or self.pages[route].is_closed():
            url = cfg.get("conversation_url")
            if not url:
                raise Blocked(f"{route}: native conversation is not bound")
            self.validate_url(route, url)
            context = self.contexts[profile]
            claimed = set(self.pages.values())
            page = (
                next((p for p in context.pages if p.url == url and p not in claimed), None)
                or next((p for p in context.pages if p.url == "about:blank" and p not in claimed), None)
                or await context.new_page()
            )
            if page.url != url:
                await page.goto(url, wait_until="domcontentloaded")
            self.pages[route] = page
        return self.pages[route]

    def validate_url(self, route, url):
        parts = urlsplit(url)
        cfg = self.config["routes"][route]
        allowed = cfg.get("allowed_hosts", [])
        if (
            parts.scheme != "https"
            or parts.hostname not in allowed
            or parts.username
            or parts.password
        ):
            raise Blocked("Conversation URL is outside the configured native service")

    async def visible(self, page, selector):
        return (
            bool(selector)
            and await page.locator(selector).count() > 0
            and await page.locator(selector).first.is_visible()
        )

    async def observe(self, route, deep=True, fresh=False):
        """Check the route's page shows exactly its configured surface, model, effort and
        account. deep opens menus where the page hides a value (reused for 10 minutes on
        the same page unless fresh); while a reply streams, only quick checks run."""
        if route in self.light:
            deep = False
        page = await self.page(route)
        cfg = self.config["routes"][route]
        selectors = cfg["selectors"]
        parts = urlsplit(page.url)
        authentication = await self.visible(page, selectors.get("authentication", ""))
        for name in ("Log in", "Sign in"):
            button = page.get_by_role("button", name=name, exact=True)
            authentication = authentication or (
                await button.count() > 0 and await button.first.is_visible()
            )
        if (
            authentication
            or "/login" in parts.path
            or "/auth/" in parts.path
            or "/logout" in parts.path
            or parts.hostname == "auth.openai.com"
        ):
            self.sign_in_waiting.add(route)
            raise WaitingForSignIn(
                f"{route}: complete native sign-in in the dedicated browser"
            )
        if (
            route in self.sign_in_waiting
            and parts.path in ("/", "/new")
            and not cfg.get("draft_session")
        ):
            self.validate_url(route, page.url)
            await page.goto(cfg["conversation_url"], wait_until="domcontentloaded")
            self.sign_in_waiting.discard(route)
            return await self.observe(route)
        self.validate_url(route, page.url)
        # A redirect to another conversation never inherits authorization.
        if page.url.rstrip("/") != cfg["conversation_url"].rstrip("/"):
            raise Blocked("Conversation binding changed or sign-in required")
        for kind in ("authentication", "quota", "approval"):
            if await self.visible(page, selectors.get(kind, "")):
                if kind == "quota":
                    raise AllowanceUnavailable(
                        f"{route}: quota required or exhausted", route=route
                    )
                raise Blocked(f"{route}: {kind} required or exhausted")
        evidence = {}
        from .surfaces import from_selectors

        surface = from_selectors(selectors)
        if surface is not None:
            evidence.update(await self.observe_surface(route, page, cfg, surface, deep, fresh))
        for field in ("model", "mode", "effort", "account") if surface is None else ():
            if (
                field == "mode"
                and cfg.get("provider") == "claude"
                and cfg.get("mode") == "native"
            ):
                evidence[field] = "native"
                continue
            selector = selectors.get(field)
            if not selector:
                raise Blocked(
                    f"{route}: {field} observation selector is not configured"
                )
            matches = page.locator(selector)
            opened_account = False
            if (
                field == "account"
                and selectors.get("account_trigger")
                and not await self.visible(page, selector)
            ):
                trigger = page.locator(selectors["account_trigger"])
                if await trigger.count() == 1 and await trigger.is_visible():
                    await trigger.click()
                    opened_account = True
            if await matches.count() != 1:
                raise Blocked(f"{route}: ambiguous {field} selector")
            from .providers import label

            try:
                value = await label(matches)
            finally:
                if opened_account:
                    await page.keyboard.press("Escape")
            expected = cfg.get("account_label") if field == "account" else cfg[field]
            if value != expected:
                raise Blocked(f"{route}: observed {field} does not match exact binding")
            evidence[field] = value
        for capability in (
            "composer",
            "send",
            "user_messages",
            "assistant_messages",
            "complete",
        ):
            if not selectors.get(capability):
                raise Blocked(f"{route}: missing {capability} binding")
        evidence.update(
            route=route,
            conversation=page.url,
            observed=time.time(),
            transport="native_browser",
            adapter_revision="1",
        )
        return evidence

    def deep_due(self, route, page):
        recent = self.deep_checked.get(route)
        return not (recent and recent[0] == (id(page), page.url) and time.time() - recent[1] < 600)

    async def repair(self, route):
        """Before sending: put today's pages back on the exact route if they drifted,
        for example after the owner changed the model in HA's tab."""
        from .surfaces import from_selectors

        cfg = self.config["routes"][route]
        surface = from_selectors(cfg.get("selectors", {}))
        if surface is None:
            return
        page = await self.page(route)
        deep = self.deep_due(route, page)
        state = await surface.read(page, deep)
        native = cfg.get("provider") == "claude" and cfg.get("mode") == "native"
        fields = ("model", "effort") if native else ("mode", "model", "effort")
        if any(state.get(f) not in (None, cfg[f]) or (deep and state.get(f) is None) for f in fields):
            await surface.ensure(page, cfg)
            self.deep_checked.pop(route, None)

    async def observe_surface(self, route, page, cfg, surface, deep, fresh):
        key = (id(page), page.url)
        if deep and not fresh and not self.deep_due(route, page):
            deep = False  # fully checked on this very page minutes ago
        state = await surface.read(page, deep)
        native = cfg.get("provider") == "claude" and cfg.get("mode") == "native"
        fields = ("model", "effort") if native else ("mode", "model", "effort")
        evidence = {"mode": "native"} if native else {}
        for field in fields:
            value = state.get(field)
            if value is None and not deep:
                continue  # this page shows it only in its menu; checked on full checks
            if value != cfg[field]:
                raise Blocked(f"{route}: observed {field} does not match exact binding")
            evidence[field] = value
        if deep:
            account = await surface.account(page)
            if not account or account != cfg.get("account_label"):
                raise Blocked(f"{route}: observed account does not match exact binding")
            evidence["account"] = account
            self.deep_checked[route] = (key, time.time())
        return evidence

    async def exchange(self, route, message, attachments=(), timeout=900):
        lock = self.locks.setdefault(route, asyncio.Lock())
        async with lock:
            # One send at a time per account: the page keeps model and effort per account.
            dispatch = self.dispatch_lock(route)
            await dispatch.acquire()
            try:
                await self.repair(route)
                await self.observe(route)
                page = await self.page(route)
                s = self.config["routes"][route]["selectors"]
                marker = "WORKBENCH_REQUEST:" + message["id"]
                payload = json.loads(message["payload"])
                envelope = (
                    marker + "\n" + canonical({"request_id": message["id"], **payload})
                )
                users = page.locator(s["user_messages"])
                # Whole-token match: one request ID may be a prefix of another.
                echoes = users.filter(has_text=marker_pattern(marker))
                exists = await echoes.count()
                state = message["state"]
                if exists > 1:
                    raise Blocked("Duplicate request marker; delivery quarantined")
                if (
                    state in ("dispatching", "delivery_uncertain", "received", "processing")
                    and not exists
                ):
                    raise Blocked(
                        "Prior delivery uncertain; request will not be resent automatically"
                    )
                if not exists:
                    if state != "prepared":
                        raise Blocked("Message has no safe dispatch state")
                    for item in attachments:
                        path = Path(item["path"])
                        if file_hash(path) != item["sha256"]:
                            raise ContractError("Attachment hash mismatch")
                        if not s.get("upload") or not s.get("attachment_ready"):
                            raise Blocked("Attachment round trip is not configured")
                        await page.locator(s["upload"]).set_input_files(str(path))
                        await (
                            page.locator(s["attachment_ready"])
                            .filter(has_text=path.name)
                            .wait_for(state="visible", timeout=120000)
                        )
                    from .webmcp import NativeUI

                    native_ui = NativeUI(page)
                    native_send = (
                        await native_ui.available("submit_conversation_message") is True
                    )
                    if not native_send:
                        composer = page.locator(s["composer"])
                        await composer.fill(envelope)
                    # Intent persisted BEFORE the click. A thrown click is ambiguous, never a safe retry.
                    self.controller.message_state(message["id"], "dispatching")
                    try:
                        if native_send:
                            await native_ui.call(
                                "submit_conversation_message", {"prompt": envelope}
                            )
                        else:
                            await page.locator(s["send"]).click()
                        await echoes.wait_for(state="visible", timeout=30000)
                    except BaseException:
                        self.controller.message_state(message["id"], "delivery_uncertain")
                        raise
                delivered = (await echoes.inner_text()).replace("\r\n", "\n")
                if envelope not in delivered:
                    self.controller.message_state(message["id"], "delivery_uncertain")
                    raise Blocked(
                        "Request marker found, but complete payload delivery is unconfirmed"
                    )
                if self.config["routes"][route].get("draft_session"):
                    from .providers import conversation_url

                    if not conversation_url(self.config["routes"][route], page.url):
                        raise Retryable(
                            "Waiting for the provider to assign a persistent conversation URL"
                        )
                    # The full echoed envelope, not merely navigation, binds a draft.
                    self.controller.store.put(
                        "message_session",
                        message["id"],
                        {
                            "route": route,
                            "draft": message["conversation"],
                            "conversation": page.url,
                        },
                    )
                    self.config["routes"][route]["conversation_url"] = page.url
                    self.config["routes"][route]["draft_session"] = False
                self.controller.message_state(message["id"], "received")
            finally:
                dispatch.release()
            self.light.add(route)
            try:
                return await self.await_reply(route, message, page, s, marker, timeout)
            finally:
                self.light.discard(route)

    async def await_reply(self, route, message, page, s, marker, timeout):
        """Wait for the assistant's complete reply to this request, by DOM turn order."""
        started = time.monotonic()
        stable_text = None
        stable_since = 0
        while time.monotonic() - started < timeout:
            await self.observe(route)
            # Associate by observed DOM order between this user turn and the
            # next user turn, not a model's willingness to echo an ID.
            candidates = await page.evaluate(
                """({users, assistants, marker}) => {
                const u=[...document.querySelectorAll(users)];
                const hit=u.filter(e=>e.innerText.split(/\\s+/).includes(marker));
                if(hit.length!==1) return [];
                const start=hit[0], next=u[u.indexOf(start)+1];
                return [...document.querySelectorAll(assistants)].filter(e=>
                    !!(start.compareDocumentPosition(e)&Node.DOCUMENT_POSITION_FOLLOWING) &&
                    (!next || !!(e.compareDocumentPosition(next)&Node.DOCUMENT_POSITION_FOLLOWING)))
                    .map(e=>e.innerText);
            }""",
                {
                    "users": s["user_messages"],
                    "assistants": s["assistant_messages"],
                    "marker": marker,
                },
            )
            if candidates:
                raw = "\n\n".join(candidates)
                self.controller.traces.append(
                    message["task_id"],
                    message["id"],
                    route,
                    "response_snapshot",
                    {
                        "text": raw,
                        "association": "DOM turn order",
                        "parts": len(candidates),
                    },
                )
            completed_here = await page.evaluate(
                """({users, assistants, complete, marker}) => {
                const us=[...document.querySelectorAll(users)];
                const hit=us.filter(e=>e.innerText.split(/\\s+/).includes(marker));
                if(hit.length!==1)return false;
                const start=hit[0], next=us[us.indexOf(start)+1];
                const after=e=>(start.compareDocumentPosition(e)&Node.DOCUMENT_POSITION_FOLLOWING) &&
                    (!next||(e.compareDocumentPosition(next)&Node.DOCUMENT_POSITION_FOLLOWING));
                return [...document.querySelectorAll(complete)].some(e=>e.getClientRects().length && after(e));
            }""",
                {
                    "users": s["user_messages"],
                    "assistants": s["assistant_messages"],
                    "complete": s["complete"],
                    "marker": marker,
                },
            )
            if (
                candidates
                and completed_here is True
                and not await self.visible(page, s.get("streaming", ""))
            ):
                raw = "\n\n".join(candidates)
                if raw != stable_text:
                    stable_text = raw
                    stable_since = time.monotonic()
                elif time.monotonic() - stable_since >= 1:
                    self.controller.traces.append(
                        message["task_id"],
                        message["id"],
                        route,
                        "response_complete",
                        {"text": raw},
                    )
                    try:
                        response = parse_response(raw, message["id"])
                    except ContractError as error:
                        self.controller.traces.append(
                            message["task_id"],
                            message["id"],
                            route,
                            "response_error",
                            {"error": str(error)},
                        )
                        self.controller.message_state(message["id"], "invalid")
                        raise
                    self.controller.message_state(
                        message["id"], "validated", canonical(response)
                    )
                    return response
            await asyncio.sleep(0.5)
        self.controller.message_state(message["id"], "processing")
        raise Retryable(
            "Native response deadline exceeded; retained for reconciliation"
        )

    async def download(
        self, route, selector, destination, expected_sha256, filename=None
    ):
        await self.observe(route)
        page = await self.page(route)
        link = page.locator(selector)
        if filename is not None:
            link = link.filter(has_text=filename)
        if await link.count() != 1:
            raise Blocked("Returned artifact download is missing or ambiguous")
        async with page.expect_download() as info:
            await link.click()
        download = await info.value
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        stage = destination.with_name(
            destination.name + "." + uuid.uuid4().hex + ".download"
        )
        try:
            # Check the browser's own temporary copy first and delete it when
            # oversized, so a large download is never copied into the workspace.
            temporary = await download.path()
            if temporary is None or Path(temporary).stat().st_size > 32_000_000:
                await download.delete()
                raise Blocked("Returned artifact is missing or exceeds 32 MB")
            await download.save_as(stage)
            if stage.stat().st_size > 32_000_000:
                raise Blocked("Returned artifact exceeds 32 MB")
            if file_hash(stage) != expected_sha256:
                raise ContractError("Returned artifact hash mismatch")
            stage.replace(destination)
            return {"sha256": expected_sha256, "size": destination.stat().st_size}
        finally:
            # Never replace an earlier verified download with partial or invalid bytes.
            stage.unlink(missing_ok=True)

    async def poll_usage(self, route):
        cfg = self.config["routes"][route]
        usage = cfg.get("usage", {})
        if not usage.get("url"):
            raise Blocked("Usage page is not configured")
        self.validate_url(route, usage["url"])
        if cfg.get("conversation_url"):
            context = (await self.page(route)).context
            page = await context.new_page()
        else:
            page = await self.service_page(cfg["profile"], usage["url"], cfg.get("allowed_hosts"))
        try:
            await page.goto(usage["url"], wait_until="domcontentloaded")
            self.validate_url(route, page.url)
            if not same_page(usage["url"], page.url):
                raise Blocked("Usage page redirected; allowance observation rejected")
            windows = []
            no_limit = False
            if usage.get("discover_progressbars"):
                from .providers import read_usage

                reading = await read_usage(page, cfg)
                windows, no_limit = reading["windows"], reading["no_numeric_limit"]
            for window in usage.get("windows", []):
                raw = await page.locator(window["selector"]).inner_text()
                match = re.fullmatch(window["pattern"], raw.strip())
                if not match:
                    raise Blocked("Usage text is ambiguous")
                value = float(match.group("percent"))
                remaining = 100 - value if window["interpretation"] == "used" else value
                if not 0 <= remaining <= 100:
                    raise Blocked("Invalid quota percentage")
                windows.append(
                    {
                        "name": window["name"],
                        "remaining": remaining,
                        **window.get("estimate", {}),
                    }
                )
            no_limit = no_limit or usage.get("no_numeric_limit_confirmed", False)
            if not windows and not no_limit:
                raise Blocked("Allowance mapping unknown")
            return {
                "windows": windows,
                "no_numeric_limit": no_limit,
                "observed": time.time(),
            }
        finally:
            await page.close()


def same_page(expected, actual):
    """The usage page HA asked for, allowing what these sites add on load: ChatGPT adds
    ?tab=overview, Claude shows /settings/usage as a dialog at /new#settings/usage."""
    want, got = urlsplit(expected), urlsplit(actual)
    if want.hostname != got.hostname:
        return False
    path = want.path.rstrip("/")
    return got.path.rstrip("/") == path or (bool(path) and got.fragment.rstrip("/") == path.lstrip("/"))


def parse_response(raw, request_id):
    if len(raw) > 2_000_000:
        raise ContractError("Native response too large")
    stripped = raw.strip()
    if stripped.startswith("```json") and stripped.endswith("```"):
        stripped = stripped[7:-3].strip()
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as e:
        raise ContractError("Response must be a single structured JSON envelope") from e
    if not isinstance(data, dict) or data.get("request_id") != request_id:
        raise ContractError("Wrong response identity")
    if data.get("type") not in (
        "knowledge_scope",
        "knowledge_tags",
        "step_intent",
        "task_plan",
        "brief",
        "tool_request",
        "tool_batch",
        "complete",
        "blocker",
        "recovery",
        "learning",
        "learning_cycle",
        "learning_feedback",
        "learning_candidate",
        "artifact_return",
        "session_ready",
        "rollout_result",
    ):
        raise ContractError("Unsupported response type")
    return data
