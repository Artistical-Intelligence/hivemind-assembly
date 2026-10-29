"""Crash-reconcilable conversation creation and renewal over the native UI.

The old binding remains active until exact identity and an attachment canary
have completed in the replacement. Pending deliveries are never abandoned.
"""

import asyncio
import base64
import copy
import json
import secrets
from pathlib import Path
from .native import request_echo, NativeBrowser
from .providers import CONTRACTS, discover, conversation_url, select_preferred_chat
from hivemind_assembly.core.common import (
    Blocked,
    Retryable,
    ContractError,
    atomic_write,
    canonical,
    digest,
    file_hash,
)


class Sessions:
    def __init__(self, browser, config_path):
        self.browser, self.store = browser, browser.controller.store
        self.config_path = Path(config_path)
        self.locks = {}
        self.drafts = {}
        self.setup_pages = {}

    async def recover_page(self, route, key, cfg):
        """Find an existing setup request without creating or sending a replacement."""
        context = self.browser.contexts.get(cfg["profile"])
        if context is None:
            await self.browser.service_page(cfg["profile"], CONTRACTS[cfg["provider"]]["new_url"], cfg.get("allowed_hosts"))
            context = self.browser.contexts.get(cfg["profile"])
        if context is None:
            raise Blocked("Open the original setup conversation in HA's browser, then Retry setup. No request was resent.")
        marker = "WORKBENCH_REQUEST:" + key
        selector = cfg["selectors"]["user_messages"]
        found = {}
        pages = list(context.pages)
        for page in pages:
            if conversation_url(cfg, page.url) and await request_echo(page, selector, marker) is not None:
                found.setdefault(page.url, page)
        if len(found) > 1:
            raise Blocked("The setup request appears in more than one conversation; no request was resent.")
        if found:
            return next(iter(found.values()))
        # A navigation observed during an uncertain send is a recovery hint only.
        # It never establishes delivery or authorizes another send.
        urls = []
        hints = self.store.rows("SELECT payload FROM records WHERE kind='session_candidate' AND id=?", (key,))
        if hints:
            hint = json.loads(hints[0]["payload"])
            if hint.get("route") == route and hint.get("profile") == cfg["profile"] and conversation_url(cfg, hint.get("conversation", "")):
                urls.append(hint["conversation"])
        # Older installs did not retain the URL. Inspect only bounded visible
        # provider history links, and only extract matches for this exact request.
        for page in pages:
            try:
                self.browser.validate_url(route, page.url)
            except Blocked:
                continue
            for url in await page.locator('a[href]').evaluate_all("nodes => nodes.filter(e => e.getClientRects().length).map(e => e.href)"):
                if conversation_url(cfg, url) and url not in urls:
                    urls.append(url)
                if len(urls) >= 24:
                    break
            if len(urls) >= 24:
                break
        opened = []
        keep = None
        try:
            for url in urls[:24]:
                page = await context.new_page()
                opened.append(page)
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                    if not conversation_url(cfg, page.url):
                        continue
                    await page.locator(selector).first.wait_for(state="attached", timeout=5000)
                except Exception:
                    continue
                if await request_echo(page, selector, marker) is not None:
                    found.setdefault(page.url, page)
            if len(found) > 1:
                raise Blocked("The setup request appears in more than one conversation; no request was resent.")
            if not found:
                raise Blocked(
                    "The original setup chat is not among HA's open or recent chats. "
                    "Open that conversation in HA's browser, then Retry setup. No request was resent."
                )
            keep = next(iter(found.values()))
            self.browser.service_pages.add(keep)
            return keep
        finally:
            for page in opened:
                if page is not keep:
                    await page.close()

    def pending(self, route):
        return self.store.rows(
            "SELECT id,state,conversation FROM messages WHERE route=? AND state NOT IN ('validated','invalid','cancelled')",
            (route,),
        )

    def accepted(self, route):
        cfg = self.browser.config["routes"][route]
        for row in self.store.rows(
            "SELECT payload FROM records WHERE kind='session_commit' ORDER BY rowid DESC"
        ):
            value = json.loads(row["payload"])
            if (
                value.get("isolated")
                or value["route"] != route
                or not value.get("download_sha256")
            ):
                continue
            if all(
                value["binding"].get(k) == cfg.get(k)
                for k in (
                    "provider",
                    "profile",
                    "account_label",
                    "model",
                    "mode",
                    "effort",
                    "conversation_url",
                )
            ):
                return True
        return False

    def restore_bindings(self):
        # A crash between durable commit and settings write must not lose a session.
        for row in self.store.rows(
            "SELECT payload FROM records WHERE kind='session_commit' ORDER BY rowid"
        ):
            saved = json.loads(row["payload"])
            if saved.get("isolated"):
                continue
            cfg = self.browser.config["routes"].get(saved["route"])
            if cfg is not None and cfg.get("conversation_url") == saved["previous"]:
                cfg.update(saved["binding"])
        atomic_write(self.config_path, canonical(self.browser.config))

    async def due(self, route):
        cfg = self.browser.config["routes"][route]
        if not cfg.get("conversation_url") or not self.accepted(route):
            return True
        page = await self.browser.page(route)
        selector = cfg.get("selectors", {}).get("context_limit")
        if selector and await self.browser.visible(page, selector):
            return True
        limit = cfg.get("renew_after_turns", 80)
        if type(limit) is not int or not 4 <= limit <= 1000:
            raise ContractError("Session renewal limit must be 4–1000 turns")
        count = self.store.one(
            "SELECT COUNT(*) AS n FROM messages WHERE route=? AND conversation=? AND state='validated'",
            (route, cfg["conversation_url"]),
        )["n"]
        return count >= limit

    async def ensure(self, task, route, allowance, *, context=None):
        cfg = self.browser.config["routes"][route]
        binding_key = digest(
            {"route": route, "conversation": cfg.get("conversation_url")}
        )
        rows = self.store.rows(
            "SELECT payload FROM records WHERE kind='session_knowledge_scope' AND id=?",
            (binding_key,),
        )
        same_context = context is None or (
            rows and json.loads(rows[0]["payload"])["context"] == context
        )
        if same_context and not await self.due(route):
            return
        if allowance is None or not allowance.eligible():
            from hivemind_assembly.core.common import AllowanceUnavailable

            raise AllowanceUnavailable(
                "Session renewal requires verified sufficient allowance"
            )
        await self.renew(task, route)
        if context is not None:
            binding_key = digest(
                {"route": route, "conversation": cfg.get("conversation_url")}
            )
            self.store.put(
                "session_knowledge_scope",
                binding_key,
                {"context": context, "task": task},
            )

    async def renew(
        self,
        task,
        route,
        *,
        isolated=False,
        identity=None,
        target=None,
        preferences=None,
        expected_binding=None,
    ):
        if (target is not None or preferences is not None) and not isolated:
            raise Blocked(
                "Experimental model selection cannot rebind a main work route"
            )
        if target is not None and (
            not isinstance(target, dict)
            or set(target) != {"model", "effort"}
            or any(
                not isinstance(v, str) or not 1 <= len(v) <= 100
                for v in target.values()
            )
        ):
            raise ContractError(
                "Experimental target requires exact model and effort labels"
            )
        if target is not None and preferences is not None:
            raise ContractError("Choose a manual target or automatic preferences")
        selection = {"target": target, "preferences": preferences}
        if expected_binding is not None:
            fields = {"provider", "profile", "account_label", "model", "mode", "effort"}
            if not isinstance(expected_binding, dict) or set(expected_binding) != fields or isolated:
                raise ContractError("Expected native binding requires exact main-route identity fields")
            expected_binding = dict(expected_binding)

        def verify_expected(candidate):
            if expected_binding is not None and any(
                candidate.get(k) != value for k, value in expected_binding.items()
            ):
                raise Blocked("Context renewal no longer matches the configured native identity")

        async with self.locks.setdefault(route, asyncio.Lock()):
            cfg = self.browser.config["routes"][route]
            verify_expected(cfg)
            previous = cfg.get("conversation_url", "")
            key = (
                identity
                or "session_" + digest({"route": route, "previous": previous})[:32]
            )
            committed = self.store.rows(
                "SELECT payload FROM records WHERE kind='session_commit' AND id=?",
                (key,),
            )
            if committed:
                result = json.loads(committed[0]["payload"])
                if not isolated:
                    verify_expected(result["binding"])
                    cfg.update(result["binding"])
                    atomic_write(self.config_path, canonical(self.browser.config))
                return result
            # Never move a work route while another turn is unresolved. This also
            # prevents parallel tasks from losing their last known response.
            pending = [m for m in self.pending(route) if m["id"] != key]
            if pending and not isolated:
                raise Retryable(
                    "Session renewal waits for unresolved native deliveries"
                )
            retained = self.store.rows(
                "SELECT payload FROM records WHERE kind='session_intent' AND id=?",
                (key,),
            )
            if retained:
                intent = json.loads(retained[0]["payload"])
                if (
                    intent.get("selection", {"target": None, "preferences": None})
                    != selection
                ):
                    raise Blocked("Retained session model selection changed")
                if (intent["route"], intent["isolated"]) != (route, isolated) or (
                    not isolated and intent["previous"] != previous
                ):
                    raise Blocked(
                        "Session intent no longer matches its original binding"
                    )
            else:
                intent = {
                    "route": route,
                    "previous": previous,
                    "task": task,
                    "isolated": isolated,
                    "nonce": secrets.token_hex(24),
                    "selection": selection,
                }
                self.store.put("session_intent", key, intent)
            clone = self.drafts.get(key)
            binding = self.store.rows(
                "SELECT payload FROM records WHERE kind='message_session' AND id=?",
                (key,),
            )
            message_rows = self.store.rows("SELECT * FROM messages WHERE id=?", (key,))
            if clone is None:
                config = copy.deepcopy(self.browser.config)
                config["routes"][route].update(
                    conversation_url=CONTRACTS[cfg["provider"]]["new_url"],
                    draft_session=True,
                )
                clone = NativeBrowser(
                    config, self.browser.root, self.browser.controller
                )
                clone.contexts = self.browser.contexts
                clone.profile_locks = self.browser.profile_locks
                clone.dispatch_locks = self.browser.dispatch_locks
                clone.playwright = self.browser.playwright
                if binding:
                    url = json.loads(binding[0]["payload"])["conversation"]
                    clone.config["routes"][route].update(
                        conversation_url=url, draft_session=False
                    )
                    page = await self.browser.service_page(cfg["profile"], url, cfg.get("allowed_hosts"))
                elif message_rows and message_rows[0]["state"] != "prepared":
                    async with self.browser.dispatch_lock(route):
                        page = await self.recover_page(route, key, cfg)
                    # observe() needs the current page; draft remains true until
                    # exchange verifies the complete echoed payload.
                    clone.config["routes"][route]["conversation_url"] = page.url
                else:
                    page = await self.browser.service_page(
                        cfg["profile"], CONTRACTS[cfg["provider"]]["new_url"], cfg.get("allowed_hosts")
                    )
                clone.pages[route] = page
                self.setup_pages[route] = page
                chosen = self.store.rows(
                    "SELECT payload FROM records WHERE kind='session_model_selection' AND id=?",
                    (key,),
                )
                if chosen:
                    clone.config["routes"][route].update(
                        json.loads(chosen[0]["payload"])
                    )
                elif target is not None or preferences is not None:
                    selected = (
                        target
                        if target is not None
                        else await select_preferred_chat(
                            page, clone.config["routes"][route], preferences
                        )
                    )
                    clone.config["routes"][route].update(selected)
                    self.store.put(
                        "session_model_selection",
                        key,
                        {field: selected[field] for field in ("model", "effort")},
                    )
                    if target is not None:
                        # Positional selectors from the old model must be rediscovered.
                        clone.config["routes"][route]["selectors"] = {
                            k: v
                            for k, v in clone.config["routes"][route]
                            .get("selectors", {})
                            .items()
                            if k not in ("model", "effort")
                        }
                async with self.browser.dispatch_lock(route):
                    discovered = await discover(page, clone.config["routes"][route])
                if discovered["missing"]:
                    raise Blocked(
                        "New session identity controls unavailable: "
                        + ", ".join(discovered["missing"])
                    )
                clone.config["routes"][route].update(
                    selectors=discovered["selectors"],
                    account_label=discovered["account_label"],
                )
                if (
                    cfg.get("account_label")
                    and discovered["account_label"] != cfg["account_label"]
                ):
                    raise Blocked("New session changed account")
                # Cache only after recovery and identity discovery succeed. A
                # failed recovery must not leave a half-initialized draft that
                # bypasses those checks on the next setup attempt.
                self.drafts[key] = clone
            target = clone.config["routes"][route]
            canary = canonical(
                {
                    "nonce": intent["nonce"],
                    "purpose": "Hivemind Assembly attachment byte verification",
                }
            ).encode()
            path = (
                self.store.root
                / "private"
                / "transfers"
                / key
                / "ha-session-canary.txt"
            )
            atomic_write(path, canary)
            return_name = "ha-roundtrip-" + key + ".txt"
            request = {
                "instruction": "Establish an isolated Hivemind Assembly session. Perform no project work. Read the attached file and create a native downloadable file containing exactly the same bytes, named "
                + return_name
                + ". Return exactly one JSON object: request_id from the envelope, type session_ready, attachment_base64 containing the exact attached file bytes encoded as base64. Do not infer the contents from the filename. No explanation.",
                "role": route,
                "scope": "session transport acceptance",
            }
            message = (
                message_rows[0]
                if message_rows
                else self.browser.controller.prepare_message(
                    task, route, target["conversation_url"], request, key
                )
            )
            if message["state"] == "validated":
                response = json.loads(message["response"])
            else:
                response = await clone.exchange(
                    route,
                    message,
                    attachments=[{"path": str(path), "sha256": file_hash(path)}],
                )
            if (
                response.get("type") != "session_ready"
                or response.get("attachment_base64")
                != base64.b64encode(canary).decode()
            ):
                raise Blocked(
                    "Native session failed exact attachment byte verification"
                )
            returned = path.with_name(return_name)
            if not returned.exists() or file_hash(returned) != file_hash(path):
                selector = target.get("selectors", {}).get("download")
                if not selector:
                    raise Blocked("Native session has no observed download binding")
                await clone.download(
                    route, selector, returned, file_hash(path), filename=return_name
                )
            evidence = await clone.observe(route)
            if not conversation_url(cfg, evidence["conversation"]):
                raise Blocked("Native session has no persistent conversation identity")
            if any(
                evidence["conversation"] == other.get("conversation_url")
                for name, other in self.browser.config["routes"].items()
                if name != route
            ):
                raise Blocked("New conversation is already assigned to another role")
            value = {
                "route": route,
                "previous": previous,
                "binding": target,
                "evidence": evidence,
                "attachment_sha256": file_hash(path),
                "download_sha256": file_hash(returned),
                "isolated": isolated,
            }
            if expected_binding is not None:
                # The owner can change settings while UI verification awaits.
                # Re-read the current object, including a replaced route dict,
                # before journaling or applying the replacement binding.
                cfg = self.browser.config["routes"][route]
                verify_expected(cfg)
                verify_expected(target)
            self.store.put("session_commit", key, value)
            if not isolated:
                cfg.update(target)
                self.browser.pages[route] = clone.pages[route]
                atomic_write(self.config_path, canonical(self.browser.config))
            return value

    async def isolated_browser(self, task, route, identity, **selection):
        value = await self.renew(
            task, route, isolated=True, identity=identity, **selection
        )
        clone = self.drafts.get(identity)
        if clone is None:
            config = copy.deepcopy(self.browser.config)
            config["routes"][route] = value["binding"]
            clone = NativeBrowser(config, self.browser.root, self.browser.controller)
            clone.contexts, clone.profile_locks = (
                self.browser.contexts,
                self.browser.profile_locks,
            )
            clone.playwright = self.browser.playwright
            clone.dispatch_locks = self.browser.dispatch_locks
            self.drafts[identity] = clone
        return clone

    async def release_isolated(self, identity):
        clone = self.drafts.pop(identity, None)
        if clone is None:
            return
        for page in clone.pages.values():
            if page not in self.browser.pages.values():
                try:
                    await page.close()
                except Exception as error:
                    self.store.event(
                        identity, "trial_tab_cleanup_pending", {"reason": str(error)}
                    )
