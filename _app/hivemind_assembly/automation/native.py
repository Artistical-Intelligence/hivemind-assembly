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
)


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

    async def start(self):
        from playwright.async_api import async_playwright

        async with self.start_lock:
            if self.playwright is None:
                self.playwright = await async_playwright().start()

    async def close(self):
        for ctx in self.contexts.values():
            await ctx.close()
        if self.playwright:
            await self.playwright.stop()
        self.contexts = {}
        self.pages = {}
        self.playwright = None

    async def page(self, route):
        profile = identifier(self.config["routes"][route]["profile"])
        async with self.profile_locks.setdefault(profile, asyncio.Lock()):
            return await self._page(route)

    async def service_page(self, profile, url):
        """Dedicated visible profile for owner-requested account setup."""
        profile = identifier(profile)
        async with self.profile_locks.setdefault(profile, asyncio.Lock()):
            await self.start()
            if profile not in self.contexts:
                opts = {
                    k: v
                    for k, v in self.config.get("browser", {}).items()
                    if k
                    in ("channel", "locale", "timezone_id", "viewport", "color_scheme")
                }
                self.contexts[profile] = (
                    await self.playwright.chromium.launch_persistent_context(
                        str(self.root / "private" / "browser" / profile),
                        headless=False,
                        **opts,
                    )
                )
            page = await self.contexts[profile].new_page()
            await page.goto(url, wait_until="domcontentloaded")
            return page

    async def _page(self, route):
        cfg = self.config["routes"][route]
        profile = identifier(cfg["profile"])
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
                    str(self.root / "private" / "browser" / profile),
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
            page = (
                next((p for p in context.pages if p.url == url), None)
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

    async def observe(self, route):
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
                raise Blocked(f"{route}: {kind} required or exhausted")
        evidence = {}
        for field in ("model", "mode", "effort", "account"):
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

    async def exchange(self, route, message, attachments=(), timeout=900):
        lock = self.locks.setdefault(route, asyncio.Lock())
        async with lock:
            await self.observe(route)
            page = await self.page(route)
            s = self.config["routes"][route]["selectors"]
            marker = "WORKBENCH_REQUEST:" + message["id"]
            payload = json.loads(message["payload"])
            envelope = (
                marker + "\n" + canonical({"request_id": message["id"], **payload})
            )
            users = page.locator(s["user_messages"])
            echoes = users.filter(has_text=marker)
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
                    const hit=u.filter(e=>e.innerText.includes(marker));
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
                    const hit=us.filter(e=>e.innerText.includes(marker));
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
            page = await self.service_page(cfg["profile"], usage["url"])
        try:
            await page.goto(usage["url"], wait_until="domcontentloaded")
            self.validate_url(route, page.url)
            if page.url.rstrip("/") != usage["url"].rstrip("/"):
                raise Blocked("Usage page redirected; allowance observation rejected")
            windows = []
            if usage.get("discover_progressbars"):
                from .providers import usage_snapshot

                windows = await usage_snapshot(page, cfg)
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
            if not windows and not usage.get("no_numeric_limit_confirmed"):
                raise Blocked("Allowance mapping unknown")
            return {
                "windows": windows,
                "no_numeric_limit": usage.get("no_numeric_limit_confirmed", False),
                "observed": time.time(),
            }
        finally:
            await page.close()


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
