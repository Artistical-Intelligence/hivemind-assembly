"""Private remote HA dashboard with revocable application-level device pairing.

Tailscale is a transport, not an authorization substitute. The browser/debugging
ports are never forwarded. No hosted-T3 compatibility is implied by this route.
"""
from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from hivemind_assembly.core.common import Blocked, ContractError, atomic_write, canonical

HTTPS_PORT = 8443
MAX_UPLOAD = 256 * 1024 * 1024
HOP_HEADERS = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade"}


def tailscale_executable():
    found = shutil.which("tailscale")
    if found:
        return found
    for key in ("ProgramFiles", "LOCALAPPDATA"):
        folder = os.environ.get(key)
        if folder:
            path = Path(folder) / "Tailscale" / "tailscale.exe"
            if path.is_file():
                return str(path)
    return None


def run_tailscale(arguments):
    executable = tailscale_executable()
    if not executable:
        raise Blocked("Private remote access needs Tailscale. Install it and sign in, then choose Check connection in HA.")
    try:
        result = subprocess.run([executable, *arguments], stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=25)
    except subprocess.TimeoutExpired:
        raise Blocked("The private connection did not answer. HA retained its setup state; check the connection before retrying.") from None
    if result.returncode:
        raise Blocked("The private connection could not complete this step. Check Tailscale's sign-in and service permissions, then retry from HA.")
    if len(result.stdout) > 2 * 1024 * 1024:
        raise Blocked("Private connection returned too much status data")
    return result.stdout


class RemoteAccess:
    """One local gateway, one owned Serve mapping, separate revocable device keys."""

    def __init__(self, root, owner_token, runner=None, *, namespace="remote-access", allow_origin=None):
        if namespace not in ("remote-access", "hosted-access"):
            raise ContractError("Invalid remote storage namespace")
        self.allow_origin = allow_origin or (lambda origin: bool(re.fullmatch(r"https://[a-z0-9][a-z0-9.-]*\.ts\.net:8443", origin)))
        self.protocol_request = None
        self.authorize_extra = None
        self.folder = Path(root) / "private" / namespace
        self.path = self.folder / "settings.json"
        self.owner_token = owner_token
        self.runner = runner or run_tailscale
        self.lock = threading.RLock()
        self.server = None
        self.thread = None
        self.upstream = None
        self.state = {"version": 1, "enabled": False, "gateway_port": None,
                      "origin": None, "devices": [], "transport": "unchecked"}
        self.settings_error = False
        if self.path.exists():
            try:
                saved = json.loads(self.path.read_text(encoding="utf-8"))
                if (not isinstance(saved, dict) or saved.get("version") != 1 or
                        type(saved.get("enabled")) is not bool or
                        not isinstance(saved.get("devices"), list) or
                        len(saved["devices"]) > 32 or
                        saved.get("gateway_port") is not None and
                        (type(saved["gateway_port"]) is not int or not 0 < saved["gateway_port"] < 65536)):
                    raise ValueError("Invalid retained remote settings")
                for device in saved["devices"]:
                    if (not isinstance(device, dict) or
                            not re.fullmatch(r"[a-f0-9]{24}", device.get("id", "")) or
                            not re.fullmatch(r"[a-f0-9]{64}", device.get("hash", "")) or
                            not isinstance(device.get("label"), str) or
                            not 1 <= len(device["label"]) <= 80 or
                            not isinstance(device.get("created"), (float, int)) or
                            not isinstance(device.get("expires"), (float, int))):
                        raise ValueError("Invalid retained device")
                origin = saved.get("origin")
                if origin is not None and (not isinstance(origin, str) or not self.allow_origin(origin)):
                    raise ValueError("Invalid retained network identity")
                self.state.update(saved)
                self.state["transport"] = "unchecked"
            except (ValueError, OSError, TypeError, KeyError):
                self.settings_error = True
                self.state["transport"] = "settings_need_recovery"

    def save(self):
        if self.settings_error:
            raise Blocked("Remote settings need recovery; the original file was preserved. Local HA remains available.")
        self.folder.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            self.folder.chmod(0o700)
        atomic_write(self.path, canonical(self.state))
        if os.name != "nt":
            self.path.chmod(0o600)

    def bind(self, port):
        if type(port) is not int or not 0 < port < 65536:
            raise ContractError("Invalid local HA port")
        self.upstream = port
        if self.state["enabled"]:
            try:
                self.start_gateway()
            except OSError:
                self.state["transport"] = "needs_attention"

    def snapshot(self):
        """Passive status: no CLI, browser, network request or daemon startup."""
        with self.lock:
            now = time.time()
            return {"enabled": bool(self.state["enabled"]),
                    "state": self.state["transport"], "origin": self.state["origin"],
                    "gateway_running": self.server is not None,
                    "devices": [{k: item[k] for k in ("id", "label", "created", "expires")}
                                for item in self.state["devices"] if item["expires"] > now],
                    "hosted": {"state": "not_integrated", "name": "T3 Connect"}}

    def cli_json(self, argv):
        try:
            value = json.loads(self.runner(argv))
        except (ValueError, TypeError):
            raise Blocked("Private connection returned invalid status; no settings were replaced") from None
        if not isinstance(value, dict):
            raise Blocked("Private connection status has an unsupported format")
        return value

    def check(self):
        """Explicit, active check; never called by a dashboard poll."""
        if self.settings_error:
            raise Blocked("Remote settings need recovery; no network settings were changed")
        status = self.cli_json(["status", "--json"])
        if status.get("BackendState") != "Running":
            self.state["transport"] = "needs_sign_in"
            self.save()
            return self.snapshot()
        host = str((status.get("Self") or {}).get("DNSName", "")).rstrip(".").lower()
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.ts\.net", host):
            raise Blocked("A private HTTPS hostname is not available for this computer")
        origin = f"https://{host}:{HTTPS_PORT}"
        if self.state["enabled"] and self.state["origin"] not in (None, origin):
            self.state["transport"] = "account_changed"
            self.save()
            raise Blocked("The private network identity changed. HA did not move paired devices to a different account. Disable the previous mapping before pairing again.")
        self.state["origin"] = origin
        self.state["transport"] = "available"
        if self.state["enabled"]:
            config = self.cli_json(["serve", "status", "--json"])
            if self.mapping(config) != self.proxy_url():
                self.state["transport"] = "needs_attention"
            elif self.server:
                self.state["transport"] = "configured"
        self.save()
        return self.snapshot()

    def proxy_url(self):
        port = self.state.get("gateway_port")
        return f"http://127.0.0.1:{port}" if type(port) is int else None

    def mapping(self, config):
        host = urlsplit(self.state.get("origin") or "").netloc
        handlers = (config.get("Web", {}).get(host, {}) or {}).get("Handlers", {})
        proxy = (handlers.get("/") or {}).get("Proxy")
        if set(handlers) - {"/"}:
            return "conflict"
        if handlers and not proxy:
            return "conflict"
        tcp = config.get("TCP", {}).get(str(HTTPS_PORT))
        if tcp and not handlers:
            return "conflict"
        if (config.get("AllowFunnel") or {}).get(host):
            return "conflict"
        return proxy

    def enable(self):
        with self.lock:
            self.check()
            if self.state["transport"] == "needs_sign_in":
                raise Blocked("Sign in to the private network, then choose Enable remote access again. Local HA remains available.")
            config = self.cli_json(["serve", "status", "--json"])
            current = self.mapping(config)
            if current and current != self.proxy_url():
                raise Blocked("Another application owns private port 8443. HA left its configuration unchanged.")
            self.start_gateway()
            self.state["enabled"] = True
            self.state["transport"] = "configuring"
            self.save()
            if current != self.proxy_url():
                self.runner(["serve", "--bg", f"--https={HTTPS_PORT}", self.proxy_url()])
            return self.check()

    def disable(self):
        # Revoke locally before calling a possibly unavailable network service.
        with self.lock:
            self.state["enabled"] = False
            self.state["devices"] = []
            self.state["transport"] = "disabled"
            self.save()
        try:
            config = self.cli_json(["serve", "status", "--json"])
            current = self.mapping(config)
            if current and current != self.proxy_url():
                raise Blocked("The remote mapping no longer belongs to HA. No other application's mapping was removed.")
            if current:
                self.runner(["serve", f"--https={HTTPS_PORT}", "off"])
        except (Blocked, OSError):
            with self.lock:
                self.state["transport"] = "disabled_cleanup_pending"
                self.save()
            return self.snapshot()
        self.close()
        return self.snapshot()

    def pair(self, label, days=30):
        with self.lock:
            if not self.state["enabled"] or not self.server or self.state["transport"] != "configured":
                raise Blocked("Enable and check the private connection before pairing a device")
            if not isinstance(label, str) or not 1 <= len(label.strip()) <= 80:
                raise ContractError("Give the device a name of 1–80 characters")
            if type(days) is not int or not 1 <= days <= 90:
                raise ContractError("Device access must expire within 1–90 days")
            now = time.time()
            active = [d for d in self.state["devices"] if d["expires"] > now]
            if len(active) >= 32:
                raise Blocked("Remove an old paired device before adding another")
            token = secrets.token_urlsafe(32)
            item = {"id": secrets.token_hex(12), "label": label.strip(), "created": now,
                    "expires": now + days * 86400, "hash": hashlib.sha256(token.encode()).hexdigest()}
            self.state["devices"] = [*active, item]
            self.save()
            return {"id": item["id"], "url": self.state["origin"] + "/#" + token, "expires": item["expires"]}

    def revoke(self, device_id):
        with self.lock:
            self.state["devices"] = [d for d in self.state["devices"] if d["id"] != device_id]
            self.save()
        return self.snapshot()

    def authorized(self, token):
        if not isinstance(token, str) or not 20 <= len(token) <= 256:
            return False
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.lock:
            return bool(self.state["enabled"] and any(
                d["expires"] > time.time() and hmac.compare_digest(d["hash"], digest)
                for d in self.state["devices"]))

    def start_gateway(self):
        if self.server:
            return
        if self.upstream is None:
            raise Blocked("HA's local dashboard has not started")
        remote = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def reject(self, status):
                body = b'{"error":"Remote request was not accepted"}'
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)
                self.close_connection = True

            def handle_request(self):
                self.connection.settimeout(40)
                if not remote.state["enabled"]:
                    return self.reject(403)
                origin = remote.state.get("origin")
                allowed_hosts = {urlsplit(origin or "").netloc,
                                 f"127.0.0.1:{self.server.server_port}"}
                protocol_path = urlsplit(self.path).path in ("/api/t3-connect/health", "/api/t3-connect/mint-credential", "/oauth/token")
                allowed_origins = (None, origin, "https://app.t3.codes") if protocol_path and remote.protocol_request else (None, origin)
                if (self.headers.get("Host") not in allowed_hosts or
                        self.headers.get("Origin") not in allowed_origins or
                        self.headers.get("Transfer-Encoding") or
                        len(self.headers.get_all("Content-Length", [])) > 1):
                    return self.reject(403)
                if not self.path.startswith("/") or self.path.startswith("//"):
                    return self.reject(400)
                path = urlsplit(self.path).path
                if protocol_path and remote.protocol_request:
                    try:
                        size = int(self.headers.get("Content-Length", "0"))
                        if not 0 <= size <= 512 * 1024:
                            return self.reject(413)
                        data = self.rfile.read(size)
                        if len(data) != size:
                            return self.reject(400)
                        answer = remote.protocol_request(path, self.command, self.headers, data)
                        if answer is None:
                            return self.reject(404)
                        code, payload = answer
                        body = json.dumps(payload).encode()
                        self.send_response(code)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", str(len(body)))
                        self.send_header("Cache-Control", "no-store")
                        self.send_header("Referrer-Policy", "no-referrer")
                        if self.headers.get("Origin") == "https://app.t3.codes":
                            self.send_header("Access-Control-Allow-Origin", "https://app.t3.codes")
                            self.send_header("Vary", "Origin")
                        self.end_headers(); self.wfile.write(body)
                        return
                    except (OSError, ValueError, TypeError):
                        return self.reject(403)
                if path.startswith("/api/"):
                    authorized = remote.authorized(self.headers.get("X-Workbench-Token"))
                    if not authorized and remote.authorize_extra:
                        authorized = remote.authorize_extra(self.headers, self.command, self.path)
                    if not authorized:
                        return self.reject(403)
                    if path.startswith(("/api/remote/", "/api/connect/")):
                        return self.reject(403)
                elif self.command != "GET":
                    return self.reject(403)
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    return self.reject(400)
                limit = MAX_UPLOAD if path == "/api/workspace/upload" else 2 * 1024 * 1024
                if not 0 <= length <= limit:
                    return self.reject(413)
                connection = http.client.HTTPConnection("127.0.0.1", remote.upstream, timeout=40)
                try:
                    connection.putrequest(self.command, self.path)
                    connection.putheader("X-Workbench-Token", remote.owner_token)
                    connection.putheader("Content-Type", self.headers.get("Content-Type", "application/json"))
                    connection.putheader("Content-Length", str(length))
                    connection.endheaders()
                    remaining = length
                    while remaining:
                        chunk = self.rfile.read(min(65536, remaining))
                        if not chunk:
                            raise OSError("Truncated request")
                        connection.send(chunk)
                        remaining -= len(chunk)
                    response = connection.getresponse()
                    self.send_response(response.status)
                    for key, value in response.getheaders():
                        if key.lower() not in HOP_HEADERS | {"set-cookie", "server", "date", "content-length", "cache-control"}:
                            self.send_header(key, value)
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Referrer-Policy", "no-referrer")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    while chunk := response.read(65536):
                        self.wfile.write(chunk)
                    self.close_connection = True
                except (OSError, http.client.HTTPException):
                    self.close_connection = True
                finally:
                    connection.close()

            do_GET = handle_request
            do_POST = handle_request

        port = self.state.get("gateway_port") or 0
        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.state["gateway_port"] = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True, name="HA-private-access")
        self.thread.start()
        self.save()

    def close(self):
        server, self.server = self.server, None
        if server:
            server.shutdown()
            server.server_close()
        if self.thread:
            self.thread.join(timeout=5)
            self.thread = None
