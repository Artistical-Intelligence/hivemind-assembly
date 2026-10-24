"""Run HA's AI assistant tabs in the owner's own Chrome, using the sign-ins already there.

Chrome (since version 136) doesn't let programs drive the everyday profile directly,
so the HA helper extension does it with chrome.debugger. This relay sits between:

    Playwright  --CDP-->  relay (this file)  --JSON-->  extension  --chrome.debugger-->  tabs

To Playwright it looks like a browser holding only HA's tabs. The extension opens
those tabs in one Chrome window of their own. Tabs, history and sign-ins outside
that window are never touched: the relay only forwards commands for tabs it created.

Downloads: Chrome saves them through its own download manager. The extension
reports them; the relay copies a finished file to where Playwright expects it and
emits the matching download events, so page.expect_download() keeps working.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import secrets
import shutil
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from hivemind_assembly.core.common import Blocked

CONTEXT_ID = "ha-your-chrome"


class ChromeRelay:
    def __init__(self):
        self.token = secrets.token_urlsafe(24)
        self.server = None
        self.port = None
        self.extension = None  # the extension's WebSocket
        self.extension_ready = asyncio.Event()
        self.clients = set()  # Playwright CDP connections
        self.tabs = {}  # tabId -> {"targetId", "session", "url", "title"}
        self.children = {}  # child CDP session -> tabId
        self.pending = {}  # request id -> Future
        self.ids = itertools.count(1)
        self.download_path = None
        self.downloads = {}  # Chrome download id -> {"guid", "tabId"}
        self.last_click = (None, 0.0)  # (tabId, time) of the latest HA click

    # Lifecycle ---------------------------------------------------------------------
    async def start(self):
        if self.server is not None:
            return self
        from websockets.asyncio.server import serve

        self.server = await serve(self.connection, "127.0.0.1", 0, max_size=64 * 1024 * 1024)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def close(self):
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
            self.server = None

    @property
    def extension_url(self):
        return f"ws://127.0.0.1:{self.port}/extension?token={self.token}" if self.port else None

    @property
    def cdp_url(self):
        return f"ws://127.0.0.1:{self.port}/cdp?token={self.token}"

    def connected(self):
        return self.extension is not None

    async def wait_for_extension(self, seconds=60):
        try:
            await asyncio.wait_for(self.extension_ready.wait(), seconds)
        except asyncio.TimeoutError:
            raise Blocked(
                "Open Chrome with the HA helper extension installed (Connections > Chrome helper). "
                "HA uses your Chrome's ChatGPT and Claude sign-ins through it."
            ) from None

    async def connection(self, ws):
        parts = urlsplit(ws.request.path)
        token = parse_qs(parts.query).get("token", [""])[0]
        if not secrets.compare_digest(token, self.token):
            await ws.close(4001, "Wrong token")
            return
        if parts.path == "/extension":
            await self.serve_extension(ws)
        elif parts.path == "/cdp":
            await self.serve_client(ws)
        else:
            await ws.close(4004, "Unknown path")

    # Extension side -----------------------------------------------------------------
    async def serve_extension(self, ws):
        if self.extension is not None:
            await self.extension.close(4000, "Replaced by a newer connection")
        self.extension = ws
        self.extension_ready.set()
        try:
            async for raw in ws:
                await self.from_extension(json.loads(raw))
        finally:
            if self.extension is ws:
                self.extension = None
                self.extension_ready.clear()
                for future in self.pending.values():
                    if not future.done():
                        future.set_exception(Blocked("Chrome or the HA helper extension disconnected."))
                self.pending.clear()
                self.tabs.clear()
                self.children.clear()
                # Playwright sees the browser go away and reconnects on next use.
                for client in list(self.clients):
                    await client.close(1001, "Chrome disconnected")

    async def call(self, message, seconds=60):
        if self.extension is None:
            raise Blocked("Chrome or the HA helper extension isn't connected.")
        ident = next(self.ids)
        future = asyncio.get_running_loop().create_future()
        self.pending[ident] = future
        await self.extension.send(json.dumps({"id": ident, **message}))
        try:
            return await asyncio.wait_for(future, seconds)
        finally:
            self.pending.pop(ident, None)

    async def from_extension(self, message):
        if "id" in message:
            future = self.pending.get(message["id"])
            if future and not future.done():
                if "error" in message:
                    future.set_exception(RelayError(message["error"]))
                else:
                    future.set_result(message.get("result"))
            return
        event = message.get("event")
        if event == "cdp":
            tab = self.tabs.get(message.get("tabId"))
            if tab is None:
                return
            params = message.get("params") or {}
            child = message.get("sessionId")
            if message["method"] == "Target.attachedToTarget" and params.get("sessionId"):
                self.children[params["sessionId"]] = message["tabId"]
            if message["method"] == "Target.detachedFromTarget" and params.get("sessionId"):
                self.children.pop(params["sessionId"], None)
            await self.broadcast({"method": message["method"], "params": params, "sessionId": child or tab["session"]})
        elif event == "detached":
            tab = self.tabs.pop(message.get("tabId"), None)
            if tab:
                for child, owner in list(self.children.items()):
                    if owner == message["tabId"]:
                        del self.children[child]
                await self.broadcast({"method": "Target.detachedFromTarget",
                                      "params": {"sessionId": tab["session"], "targetId": tab["targetId"]}})
        elif event == "download":
            await self.on_download(message)
        elif event == "ping":
            await self.extension.send(json.dumps({"event": "pong"}))

    async def on_download(self, message):
        kind = message.get("kind")
        if kind == "begin":
            tab_id, at = self.last_click
            # Only downloads that follow an HA click in an HA tab are HA's.
            if tab_id not in self.tabs or time.time() - at > 15 or self.download_path is None:
                return
            guid = secrets.token_hex(16)
            self.downloads[message["downloadId"]] = {"guid": guid, "tabId": tab_id}
            await self.broadcast({"method": "Browser.downloadWillBegin", "params": {
                "frameId": self.tabs[tab_id]["targetId"], "guid": guid,
                "url": message.get("url", ""), "suggestedFilename": message.get("suggested") or "download"}})
            return
        record = self.downloads.pop(message.get("downloadId"), None)
        if record is None:
            return
        state = "canceled"
        size = 0
        if kind == "done" and message.get("filename"):
            source = Path(message["filename"])
            target = Path(self.download_path) / record["guid"]
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                size = target.stat().st_size
                state = "completed"
            except OSError:
                state = "canceled"
            # The copy is HA's; don't leave AI artifacts in the owner's Downloads folder.
            try:
                await self.call({"op": "removeDownload", "downloadId": message["downloadId"]}, 15)
            except Exception:
                pass
        await self.broadcast({"method": "Browser.downloadProgress", "params": {
            "guid": record["guid"], "totalBytes": size, "receivedBytes": size, "state": state}})

    # Playwright side ------------------------------------------------------------------
    async def serve_client(self, ws):
        self.clients.add(ws)
        try:
            async for raw in ws:
                message = json.loads(raw)
                asyncio.ensure_future(self.from_client(ws, message))
        finally:
            self.clients.discard(ws)

    async def broadcast(self, message):
        text = json.dumps(message)
        for client in list(self.clients):
            try:
                await client.send(text)
            except Exception:
                self.clients.discard(client)

    async def from_client(self, ws, message):
        ident, method = message.get("id"), message.get("method")
        session = message.get("sessionId")
        params = message.get("params") or {}
        try:
            if session:
                result = await self.session_command(session, method, params)
            else:
                result = await self.browser_command(ws, method, params)
            reply = {"id": ident, "result": result or {}}
        except RelayError as exc:
            reply = {"id": ident, "error": {"code": -32000, "message": str(exc)}}
        except Blocked as exc:
            reply = {"id": ident, "error": {"code": -32000, "message": str(exc)}}
        if session:
            reply["sessionId"] = session
        try:
            await ws.send(json.dumps(reply))
            if method == "Browser.close" and not session:
                # Disconnect Playwright only; the owner's Chrome stays open.
                await ws.close()
        except Exception:
            pass

    def target_info(self, tab_id):
        tab = self.tabs[tab_id]
        return {"targetId": tab["targetId"], "type": "page", "title": tab.get("title", ""),
                "url": tab.get("url", "about:blank"), "attached": True, "canAccessOpener": False,
                "browserContextId": CONTEXT_ID}

    async def announce(self, tab_id):
        tab = self.tabs[tab_id]
        await self.broadcast({"method": "Target.attachedToTarget", "params": {
            "sessionId": tab["session"], "targetInfo": self.target_info(tab_id), "waitingForDebugger": False}})

    async def browser_command(self, ws, method, params):
        if method == "Browser.getVersion":
            return {"protocolVersion": "1.3", "product": "Chrome/HA-helper", "revision": "",
                    "userAgent": "", "jsVersion": ""}
        if method == "Browser.setDownloadBehavior":
            self.download_path = params.get("downloadPath")
            return {}
        if method == "Target.setAutoAttach":
            for tab_id in list(self.tabs):
                await self.announce(tab_id)
            return {}
        if method == "Target.getBrowserContexts":
            return {"browserContextIds": []}
        if method == "Target.getTargets":
            return {"targetInfos": [self.target_info(t) for t in self.tabs]}
        if method == "Target.createTarget":
            created = await self.call({"op": "createTab", "url": params.get("url") or "about:blank"})
            tab_id = created["tabId"]
            self.tabs[tab_id] = {"targetId": created["targetId"], "session": "ha-tab-" + str(tab_id),
                                 "url": created.get("url", ""), "title": created.get("title", "")}
            await self.announce(tab_id)
            return {"targetId": created["targetId"]}
        if method == "Target.closeTarget":
            tab_id = self.tab_for_target(params.get("targetId"))
            if tab_id is not None:
                await self.call({"op": "closeTab", "tabId": tab_id})
                await self.from_extension({"event": "detached", "tabId": tab_id})
            return {"success": tab_id is not None}
        if method == "Target.activateTarget":
            tab_id = self.tab_for_target(params.get("targetId"))
            if tab_id is not None:
                await self.call({"op": "activateTab", "tabId": tab_id})
            return {}
        # Browser-wide settings (permissions, window bounds, closing the browser) stay
        # with the owner's Chrome; Playwright treats an empty answer as done.
        return {}

    def tab_for_target(self, target_id):
        return next((t for t, v in self.tabs.items() if v["targetId"] == target_id), None)

    async def session_command(self, session, method, params):
        tab_id = next((t for t, v in self.tabs.items() if v["session"] == session), None)
        child = None
        if tab_id is None:
            tab_id, child = self.children.get(session), session
        if tab_id is None:
            raise RelayError("Unknown session")
        if method == "Input.dispatchMouseEvent" and params.get("type") == "mousePressed":
            self.last_click = (tab_id, time.time())
        if method == "Runtime.runIfWaitingForDebugger":
            return {}
        if method == "Page.bringToFront" and not child:
            # Also raise the window, so "Show tab" works when Chrome is behind other windows.
            await self.call({"op": "activateTab", "tabId": tab_id})
            return {}
        message = {"op": "cdp", "tabId": tab_id, "method": method, "params": params}
        if child:
            message["sessionId"] = child
        return await self.call(message, 120)


class RelayError(Exception):
    pass
