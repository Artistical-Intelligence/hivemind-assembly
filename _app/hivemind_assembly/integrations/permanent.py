"""Permanent browser connection: a free Cloudflare Worker at a fixed workers.dev address.

The Worker (web_bridge/worker.mjs) handles ChatGPT/Claude sign-in and approval and
keeps approvals across HA restarts. HA connects out to it over one authenticated
WebSocket, so nothing on this computer is opened to the internet and the address
never changes. Setup is a one-time, owner-started deployment to a Workers Free
account; HA refuses accounts with a paid Workers plan so it can't cause charges.
The Cloudflare API token is used once and never saved.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import math
from pathlib import Path
import random
import re
import secrets
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from hivemind_assembly.core.common import Blocked, ContractError, atomic_write, canonical

API = "https://api.cloudflare.com/client/v4"
WORKER = Path(__file__).with_name("web_bridge") / "worker.mjs"
TAG = "ha-permanent-connection"
MAX_MESSAGE = 4 * 1024 * 1024
MAX_RESULT = 6 * 1024 * 1024


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # never forward a credential to another address


class AccountChoiceRequired(Blocked):
    def __init__(self, accounts):
        self.accounts = [{"id": str(a.get("id", "")), "name": str(a.get("name", "Cloudflare account"))}
                         for a in accounts if isinstance(a, dict)]
        super().__init__("This token can reach several Cloudflare accounts. Choose one, then set up again.")


class Cloudflare:
    def __init__(self, token):
        token = (token or "").strip()
        if not token or "\n" in token or "\r" in token:
            raise ContractError("Paste a Cloudflare API token.")
        self.token = token

    def call(self, method, path, payload=None, raw=None, content_type=None, allow_missing=False):
        if not path.startswith("/accounts"):
            raise ContractError("Unsupported Cloudflare request.")
        data = raw if raw is not None else (json.dumps(payload).encode() if payload is not None else None)
        request = urllib.request.Request(API + path, data=data, method=method, headers={
            "Authorization": "Bearer " + self.token,
            "Content-Type": content_type or "application/json",
            "Accept": "application/json",
        })
        try:
            with urllib.request.build_opener(_NoRedirect()).open(request, timeout=40) as r:
                parsed = json.loads(r.read(4 * 1024 * 1024))
        except urllib.error.HTTPError as e:
            if allow_missing and e.code == 404:
                return None
            try:
                codes = [str(x.get("code", "")) for x in json.loads(e.read(65536)).get("errors", [])]
            except Exception:
                codes = []
            raise Blocked(f"Cloudflare refused the request (HTTP {e.code}" + (", code " + ", ".join(codes) if codes else "")
                          + "). Check the token's permissions.") from None
        except urllib.error.URLError:
            raise Blocked("Can't reach Cloudflare. Check this computer's internet connection.") from None
        if not parsed.get("success", False):
            codes = ", ".join(str(x.get("code", "")) for x in parsed.get("errors", []))
            raise Blocked("Cloudflare refused the request" + (" (code " + codes + ")" if codes else "") + ". Nothing paid was turned on.")
        return parsed.get("result")


def assert_free_subscriptions(value):
    """Stop unless every Workers subscription is clearly the free one."""
    if not isinstance(value, list):
        raise Blocked("Couldn't check the account's plan. Setup stopped.")
    for item in value:
        if not isinstance(item, dict):
            raise Blocked("Unrecognized plan information. Setup stopped.")
        rate = item.get("rate_plan") or {}
        desc = " ".join(str(x) for x in (item.get("product"), item.get("name"), rate.get("id"), rate.get("public_name"))).lower()
        if not any(w in desc for w in ("worker", "durable", "bundled", "unbound")):
            continue
        if item.get("state") in ("canceled", "cancelled", "expired"):
            continue
        if "free" not in desc or item.get("price", 0) not in (0, 0.0, "0", "0.00", None):
            raise Blocked("This Cloudflare account has a paid Workers plan. HA only sets up on Workers Free so it can't cause charges.")


def multipart(metadata, script):
    boundary = "ha_" + secrets.token_hex(16)

    def part(name, content, ctype, filename=None):
        disp = f'Content-Disposition: form-data; name="{name}"' + (f'; filename="{filename}"' if filename else "")
        return f"--{boundary}\r\n{disp}\r\nContent-Type: {ctype}\r\n\r\n".encode() + content + b"\r\n"

    data = part("metadata", json.dumps(metadata).encode(), "application/json")
    data += part("worker.mjs", script, "application/javascript+module", "worker.mjs")
    data += f"--{boundary}--\r\n".encode()
    return data, "multipart/form-data; boundary=" + boundary


def validated_origin(value):
    u = urlsplit(value or "")
    if (u.scheme != "https" or not u.hostname or not u.hostname.endswith(".workers.dev")
            or u.username or u.password or u.port not in (None, 443) or u.path not in ("", "/") or u.query or u.fragment):
        raise Blocked("The permanent address is invalid. Set it up again.")
    return "https://" + u.hostname


class Permanent:
    def __init__(self, root, rpc_factory, vault=None, api_factory=Cloudflare):
        from .github import CredentialVault

        self.folder = Path(root) / "private" / "permanent-connection"
        self.settings_path = self.folder / "settings.json"
        self.vault = vault or CredentialVault(Path(root), service="PermanentConnection")
        self.rpc_factory, self.api_factory = rpc_factory, api_factory
        self.lock = threading.RLock()
        self.relay = None
        self.services = {}
        self.services_checked = 0
        self.message = ""

    # Settings -------------------------------------------------------------------
    def settings(self):
        try:
            return json.loads(self.settings_path.read_text())
        except (OSError, ValueError):
            return {}

    def save(self, **values):
        with self.lock:
            data = {**self.settings(), **values}
            self.folder.mkdir(parents=True, exist_ok=True)
            atomic_write(self.settings_path, canonical(data))
            return data

    def enabled(self):
        s = self.settings()
        return bool(s.get("enabled") and s.get("origin"))

    def device_key(self, create=False):
        value = self.vault.read() or {}
        if not value.get("device_key") and create:
            value = {"device_key": secrets.token_urlsafe(32)}
            self.vault.write(value)
        return value.get("device_key")

    # One-time setup ---------------------------------------------------------------
    def deploy(self, token, account_id="", confirmed_free=False, emit=lambda m: None):
        if not confirmed_free:
            raise ContractError("Confirm the Cloudflare account is on Workers Free.")
        cf = self.api_factory(token)
        account_id = (account_id or "").strip() or self.settings().get("account_id", "")
        if not account_id:
            accounts = cf.call("GET", "/accounts?per_page=50")
            if not isinstance(accounts, list) or not accounts:
                raise Blocked("The token can't see any Cloudflare account. Check its permissions.")
            if len(accounts) != 1:
                raise AccountChoiceRequired(accounts)
            account_id = accounts[0]["id"]
        if not re.fullmatch(r"[0-9a-fA-F]{32}", account_id):
            raise ContractError("A Cloudflare account ID has 32 letters and digits (0-9, a-f).")
        prefix = "/accounts/" + account_id
        emit("Checking the account is on Workers Free.")
        assert_free_subscriptions(cf.call("GET", prefix + "/subscriptions"))
        sub = cf.call("GET", prefix + "/workers/subdomain", allow_missing=True)
        subdomain = sub.get("subdomain") if isinstance(sub, dict) else ""
        if not subdomain:
            pending = self.settings().get("subdomain_pending") or ("ha-" + secrets.token_hex(8))
            if not re.fullmatch(r"ha-[0-9a-f]{16}", pending):
                raise Blocked("The saved subdomain request is invalid; nothing was changed.")
            self.save(subdomain_pending=pending)
            emit("Creating the account's free workers.dev address.")
            # Only reached when the account has none; an existing one is never renamed.
            cf.call("PUT", prefix + "/workers/subdomain", {"subdomain": pending})
            sub = cf.call("GET", prefix + "/workers/subdomain")
            subdomain = sub.get("subdomain") if isinstance(sub, dict) else ""
        if not subdomain or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", subdomain):
            raise Blocked("Cloudflare didn't confirm a workers.dev address. Finish the account's setup in the Cloudflare dashboard, then retry.")
        name = self.settings().get("worker_name")
        if not name:
            name = "ha-connection-" + secrets.token_hex(6)
            self.save(worker_name=name)  # saved first, so a retry never creates a second Worker
        if not re.fullmatch(r"ha-connection-[0-9a-f]{12}", name):
            raise Blocked("Unexpected saved Worker name; refusing to overwrite another project.")
        origin = f"https://{name}.{subdomain}.workers.dev"
        saved = self.settings().get("origin")
        if saved and saved != origin:
            raise Blocked("HA is already set up on another Cloudflare account. Use that account, or remove the permanent address first.")
        key = self.device_key(create=True)
        existing = cf.call("GET", prefix + "/workers/scripts/" + name + "/settings", allow_missing=True)
        if existing is not None and TAG not in (existing.get("tags", []) if isinstance(existing, dict) else []):
            raise Blocked("A Worker with this name exists but isn't HA's. Refusing to overwrite it.")
        metadata = {
            "main_module": "worker.mjs",
            "compatibility_date": "2026-10-01",
            "tags": [TAG],
            "bindings": [
                {"name": "BRIDGE", "type": "durable_object_namespace", "class_name": "HaBridge"},
                {"name": "DEVICE_KEY", "type": "secret_text", "text": key},
                {"name": "PUBLIC_ORIGIN", "type": "plain_text", "text": origin},
            ],
        }
        if existing is None:
            metadata["migrations"] = {"new_tag": "v1", "new_sqlite_classes": ["HaBridge"]}
        raw, ctype = multipart(metadata, WORKER.read_bytes())
        emit("Deploying the free Worker.")
        cf.call("PUT", prefix + "/workers/scripts/" + name, raw=raw, content_type=ctype)
        cf.call("POST", prefix + "/workers/scripts/" + name + "/subdomain", {"enabled": True, "previews_enabled": False})
        self.save(origin=origin, enabled=True, account_id=account_id)
        emit("Done. Connecting HA to the permanent address.")
        self.start()
        return {"origin": origin, "endpoint": origin + "/mcp"}

    # Running ------------------------------------------------------------------------
    def start(self):
        with self.lock:
            if not self.enabled():
                raise Blocked("Set up the permanent address first.")
            if self.relay and not self.relay.closed.is_set():
                return self.status()
            self.save(enabled=True)
            self.relay = Relay(self.settings()["origin"], self.device_key(), self.rpc_factory())
            self.relay.start()
            return self.status()

    def stop(self):
        with self.lock:
            if self.relay:
                self.relay.stop()
            self.relay = None
        return self.status()

    close = stop

    def forget(self):
        """Stop using the permanent address. The Worker stays in the Cloudflare account."""
        self.stop()
        self.save(enabled=False)
        return self.status()

    def request(self, path, data=None):
        origin = validated_origin(self.settings().get("origin"))
        if path not in ("/device/pair", "/device/revoke", "/device/status"):
            raise ContractError("Unknown request.")
        raw = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(origin + path, data=raw, headers={
            "Authorization": "Bearer " + self.device_key(), "Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urllib.request.build_opener(_NoRedirect()).open(req, timeout=20) as r:
                return json.loads(r.read(128 * 1024))
        except urllib.error.HTTPError as e:
            try:
                text = json.loads(e.read(65536)).get("error")
            except Exception:
                text = None
            raise Blocked(text or f"The permanent address answered HTTP {e.code}.") from None
        except urllib.error.URLError:
            raise Blocked("Can't reach the permanent address.") from None

    def status(self):
        relay = self.relay.status() if self.relay else {"state": "off", "message": "Stopped."}
        settings = self.settings()
        if relay["state"] == "connected" and time.time() - self.services_checked > 30:
            self.services_checked = time.time()

            def refresh():
                try:
                    self.services = self.request("/device/status").get("services", {})
                except Exception:
                    pass
            threading.Thread(target=refresh, daemon=True).start()
        state = {"connected": "ready", "off": "off", "error": "error"}.get(relay["state"], "connecting")
        return {
            "state": state if settings.get("origin") else "off",
            "message": "Ready. Connect ChatGPT or Claude below. This address never changes." if state == "ready" else relay["message"],
            "endpoint": settings.get("origin", "") + "/mcp" if settings.get("origin") else "",
            "origin": settings.get("origin", ""),
            "enabled": bool(settings.get("enabled")),
            "services": self.services,
        }

    def pairing(self, flow=None, client_id=None, redirect_uri=None):
        code = secrets.token_urlsafe(9)
        payload = {"code": code}
        if flow is not None:
            payload.update(flow=flow, client_id=client_id, redirect_uri=redirect_uri)
        result = self.request("/device/pair", payload)
        if flow is not None and result.get("flow_verified") is not True:
            raise Blocked("This approval page expired. Start the connection again.")
        return {"code": code, "expires_in": int(result.get("expires_in", 600))}

    def revoke(self):
        self.request("/device/revoke", {})
        self.services = {}
        return self.status()


class Relay:
    """One outbound WebSocket to the Worker; requests come in over it, answers go back."""

    def __init__(self, origin, key, rpc):
        self.origin = validated_origin(origin)
        if not key:
            raise Blocked("The permanent address's key is missing. Set it up again.")
        self.key, self.rpc = key, rpc
        self.closed = threading.Event()
        self.ws = None
        self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ha-permanent-call")
        self.slots = threading.BoundedSemaphore(12)
        self.send_lock = threading.Lock()
        self.state, self.message, self.last = "starting", "Connecting.", 0

    def status(self):
        return {"state": self.state, "message": self.message, "last_connected": self.last}

    def start(self):
        threading.Thread(target=self.loop, daemon=True, name="ha-permanent-relay").start()

    def stop(self):
        self.closed.set()
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.state, self.message = "off", "Stopped."

    def loop(self):
        try:
            import websocket
        except ImportError:
            self.state, self.message = "error", "A component is missing; reinstall HA."
            return
        delay = 1
        while not self.closed.is_set():
            self.state, self.message = "connecting", "Connecting to the permanent address."
            connected = False
            try:
                self.ws = websocket.create_connection(
                    self.origin.replace("https:", "wss:", 1) + "/device",
                    header={"Authorization": "Bearer " + self.key}, timeout=30, suppress_origin=True, redirect_limit=0)
                connected = True
                self.state, self.message, self.last = "connected", "Ready.", time.time()
                seen = time.monotonic()
                while not self.closed.is_set():
                    try:
                        message = self.ws.recv()
                        if not message:
                            break
                        seen = time.monotonic()
                        self.received(message)
                    except websocket.WebSocketTimeoutException:
                        if time.monotonic() - seen > 95:
                            raise ConnectionError("No answer from the permanent address; reconnecting.")
                        with self.send_lock:
                            self.ws.send("ping")
            except Exception as exc:
                self.state, self.message = "reconnecting", "Reconnecting (" + type(exc).__name__ + ")."
            finally:
                if self.ws:
                    try:
                        self.ws.close()
                    except Exception:
                        pass
            if self.closed.is_set():
                break
            delay = 1 if connected else min(60, delay * 2)
            self.closed.wait(delay + random.random())

    def received(self, message):
        if message == "pong" or not isinstance(message, str) or len(message.encode()) > MAX_MESSAGE:
            return
        try:
            envelope = json.loads(message)
            ident, payload = envelope["id"], envelope["message"]
            if not isinstance(ident, str) or len(ident) > 128 or not isinstance(payload, dict):
                return
        except (ValueError, KeyError, TypeError):
            return
        if not self.slots.acquire(blocking=False):
            self.send(ident, {"jsonrpc": "2.0", "id": payload.get("id"), "error": {"code": -32000, "message": "HA is busy; retry shortly."}})
            return
        try:
            self.pool.submit(self.process, ident, payload)
        except RuntimeError:
            self.slots.release()

    def process(self, ident, payload):
        try:
            response = self.rpc.handle(payload)
            if response is not None:
                self.send(ident, response)
        except Exception:
            self.send(ident, {"jsonrpc": "2.0", "id": payload.get("id"), "error": {"code": -32603, "message": "HA couldn't process the request."}})
        finally:
            self.slots.release()

    def send(self, ident, response):
        raw = json.dumps(response, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
        if len(raw.encode()) > MAX_RESULT:
            raw = json.dumps({"jsonrpc": "2.0", "id": response.get("id"), "error": {"code": -32000, "message": "Result too large; request less at once."}})
        size = 60000
        total = max(1, math.ceil(len(raw) / size))
        with self.send_lock:
            try:
                for i in range(total):
                    if self.closed.is_set():
                        return
                    self.ws.send(json.dumps({"id": ident, "type": "part", "index": i, "total": total,
                                             "text": raw[i * size:(i + 1) * size]}, separators=(",", ":")))
            except Exception:
                pass  # never replay: the request may already have changed something
