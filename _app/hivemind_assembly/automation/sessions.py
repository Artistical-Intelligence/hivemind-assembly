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
from .native import NativeBrowser
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
        preferences=None
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
        async with self.locks.setdefault(route, asyncio.Lock()):
            cfg = self.browser.config["routes"][route]
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
                clone.playwright = self.browser.playwright
                self.drafts[key] = clone
                if binding:
                    url = json.loads(binding[0]["payload"])["conversation"]
                    clone.config["routes"][route].update(
                        conversation_url=url, draft_session=False
                    )
                    page = await self.browser.service_page(cfg["profile"], url)
                elif message_rows and message_rows[0]["state"] != "prepared":
                    # Search existing visible provider pages for the exact echo.
                    context = self.browser.contexts.get(cfg["profile"])
                    found = []
                    for page in context.pages if context else []:
                        if conversation_url(cfg, page.url):
                            loc = page.locator(
                                cfg["selectors"]["user_messages"]
                            ).filter(has_text="WORKBENCH_REQUEST:" + key)
                            if await loc.count() == 1:
                                found.append(page)
                    if len(found) != 1:
                        self.drafts.pop(key, None)
                        raise Blocked(
                            "New-session delivery uncertain; no duplicate bootstrap will be sent"
                        )
                    page = found[0]
                    # observe() needs the current page; draft remains true until
                    # exchange verifies the complete echoed payload.
                    clone.config["routes"][route]["conversation_url"] = page.url
                else:
                    page = await self.browser.service_page(
                        cfg["profile"], CONTRACTS[cfg["provider"]]["new_url"]
                    )
                clone.pages[route] = page
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
