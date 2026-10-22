"""Browser-chat access to HA's MCP tools through a free Cloudflare Quick Tunnel.

No Cloudflare account. A local gateway, separate from the dashboard server,
exposes only OAuth endpoints and JSON MCP requests. Every connection must be
approved on HA's approval page with a one-time code shown in the dashboard.
A new tunnel address means reconnecting each provider.
"""

from __future__ import annotations

import asyncio
import base64
from collections import deque
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import html
import json
import os
from pathlib import Path
import platform
import re
import secrets
import subprocess
import tarfile
import threading
import time
from urllib.parse import parse_qs, unquote, urlencode, urlsplit
import urllib.request

from hivemind_assembly.core.common import Blocked, atomic_write, canonical

RELEASE = "2026.10.3"
ASSET_BASE = "https://github.com/cloudflare/cloudflared/releases/download/" + RELEASE + "/"
RELEASE_API = "https://api.github.com/repos/cloudflare/cloudflared/releases/tags/" + RELEASE
ORIGIN_RE = re.compile(r"https://[a-z0-9]+(?:-[a-z0-9]+)*\.trycloudflare\.com")
SCOPE = "ha.projects offline_access"
PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
MAX_BODY = 4 * 1024 * 1024
MAX_RESULT = 8 * 1024 * 1024

PROVIDERS = {
    "ChatGPT": {
        "url": "https://chatgpt.com/plugins",
        "steps": [
            "Open Add custom MCP server.",
            "Name: Hivemind Assembly.",
            "Connection: Server URL (not Tunnel). Paste the address below.",
            "Authentication: OAuth. Confirm, then create it.",
            "On HA's approval page, enter the approval code below.",
        ],
    },
    "Claude": {
        "url": "https://claude.ai/new#customize/connectors",
        "steps": [
            "Open Add custom connector.",
            "Name: Hivemind Assembly.",
            "MCP server URL: paste the address below, then Continue.",
            "If asked about authentication, choose Sign in now and Register automatically.",
            "On HA's approval page, enter the approval code below.",
        ],
    },
}


def digest(value: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(value.encode()).digest()).decode().rstrip("=")


def safe_redirect(value):
    """Exact ChatGPT or Claude OAuth callbacks only; no open redirects."""
    if not isinstance(value, str):
        return False
    try:
        u = urlsplit(value)
    except ValueError:
        return False
    if u.scheme != "https" or u.query or u.fragment or u.username or u.password:
        return False
    if u.netloc in ("claude.ai", "claude.com"):
        return u.path == "/api/mcp/auth_callback"
    if u.netloc in ("chatgpt.com", "chat.openai.com"):
        return u.path in (
            "/connector_platform_oauth_redirect",
            "/connector_platform/oauth_redirect",
        ) or bool(re.fullmatch(r"/connector/oauth/[A-Za-z0-9_-]{1,160}", u.path))
    return False


def provider_for_redirect(value):
    if not safe_redirect(value):
        return "Unknown client"
    return "Claude" if urlsplit(value).netloc in ("claude.ai", "claude.com") else "ChatGPT"


def binary_asset(system=None, machine=None):
    system = system or platform.system()
    machine = (machine or platform.machine()).lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "amd64" if machine in ("amd64", "x86_64") else ""
    if not arch:
        raise Blocked("Browser connections need a 64-bit computer.")
    if system == "Windows":
        if arch != "amd64":
            raise Blocked("The tunnel component is not available for Windows on ARM.")
        return "cloudflared-windows-amd64.exe"
    if system == "Linux":
        return "cloudflared-linux-" + arch
    if system == "Darwin":
        return "cloudflared-darwin-" + arch + ".tgz"
    raise Blocked("Unsupported operating system for browser connections.")


def hash_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def installed_binary(folder):
    name = binary_asset()
    target = Path(folder) / ("cloudflared.exe" if os.name == "nt" else "cloudflared")
    try:
        receipt = json.loads((Path(folder) / "installed.json").read_text())
    except (OSError, ValueError):
        return None
    if target.is_file() and receipt.get("release") == RELEASE and receipt.get("asset") == name:
        if hash_file(target) == receipt.get("binary_sha256"):
            return target
    return None


def install_binary(folder, progress=None, stop=None):
    """Pinned official cloudflared release, checked against GitHub's SHA-256 digest.

    No account, token, PATH change or updater. A failed download never replaces
    an existing verified binary.
    """
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    found = installed_binary(folder)
    if found:
        return found
    stop = stop or threading.Event()
    name = binary_asset()
    target = folder / ("cloudflared.exe" if os.name == "nt" else "cloudflared")
    headers = {"User-Agent": "Hivemind-Assembly", "Accept": "application/vnd.github+json"}
    with urllib.request.urlopen(urllib.request.Request(RELEASE_API, headers=headers), timeout=30) as r:
        raw = r.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise Blocked("Unexpectedly large tunnel release information.")
    release = json.loads(raw)
    if release.get("tag_name") != RELEASE or release.get("draft") or release.get("prerelease"):
        raise Blocked("The expected tunnel release could not be verified.")
    asset = next((x for x in release.get("assets", []) if x.get("name") == name), None)
    if not asset:
        raise Blocked("The tunnel release has no download for this computer.")
    expected = asset.get("digest", "")
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", expected):
        raise Blocked("The tunnel release has no checksum; installation stopped.")
    url = asset.get("browser_download_url")
    if url != ASSET_BASE + name or not 0 < asset.get("size", 0) <= 150 * 1024 * 1024:
        raise Blocked("Unexpected tunnel download location or size.")
    download = folder / (name + ".download")
    try:
        h, count = hashlib.sha256(), 0
        request = urllib.request.Request(url, headers={"User-Agent": "Hivemind-Assembly"})
        with urllib.request.urlopen(request, timeout=30) as response, download.open("wb") as f:
            while True:
                if stop.is_set():
                    raise Blocked("Connection setup cancelled.")
                block = response.read(1024 * 1024)
                if not block:
                    break
                count += len(block)
                if count > asset["size"]:
                    raise Blocked("Tunnel download is larger than its release.")
                f.write(block)
                h.update(block)
                if progress:
                    progress(count, asset["size"])
        if count != asset["size"] or h.hexdigest() != expected.split(":")[1]:
            raise Blocked("Tunnel download failed its checksum; it was not installed.")
        if name.endswith(".tgz"):
            with tarfile.open(download, "r:gz") as archive:
                members = [m for m in archive.getmembers() if m.isfile() and Path(m.name).name == "cloudflared"]
                if len(members) != 1 or members[0].size > 150 * 1024 * 1024:
                    raise Blocked("Unexpected tunnel archive contents.")
                data = archive.extractfile(members[0]).read(150 * 1024 * 1024 + 1)
            download.write_bytes(data)
        if os.name != "nt":
            download.chmod(0o700)
        os.replace(download, target)
        atomic_write(
            folder / "installed.json",
            canonical({"release": RELEASE, "asset": name, "binary_sha256": hash_file(target)}),
        )
        return target
    finally:
        download.unlink(missing_ok=True)


class HTTPError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class Auth:
    """Single-owner OAuth for one tunnel address; keys stay in process memory."""

    def __init__(self):
        self.lock = threading.RLock()
        self.origin = ""
        self.records = {}
        self.rates = {}
        self.provider_events = {}

    def activate(self, origin):
        if not ORIGIN_RE.fullmatch(origin):
            raise ValueError("Unexpected tunnel address.")
        with self.lock:
            if self.origin != origin:
                self.records.clear()
                self.rates.clear()
                self.provider_events.clear()
            self.origin = origin

    def put(self, key, value, ttl):
        now = time.time()
        self.records = {k: v for k, v in self.records.items() if v[0] > now}
        if len(self.records) >= 2048:
            raise HTTPError("Too many pending connections. Retry later.", 429)
        self.records[key] = (now + ttl, value)

    def get(self, key):
        row = self.records.get(key)
        return row[1] if row and row[0] > time.time() else None

    def limit(self, group, maximum=120, seconds=60):
        now = time.monotonic()
        values = self.rates.setdefault(group, deque())
        while values and values[0] < now - seconds:
            values.popleft()
        if len(values) >= maximum:
            raise HTTPError("Too many requests. Retry later.", 429)
        values.append(now)

    def pairing(self):
        with self.lock:
            if not self.origin:
                raise Blocked("Start the browser connection first.")
            code = secrets.token_urlsafe(9)
            self.put("pair", digest(code), 600)
            return {"code": code, "expires_in": 600}

    def revoke(self):
        with self.lock:
            self.records.clear()
            self.provider_events.clear()

    def record_event(self, provider, event):
        """Observed provider traffic only."""
        if provider in PROVIDERS:
            with self.lock:
                self.provider_events.setdefault(provider, {})[event] = time.time()

    def services(self):
        with self.lock:
            result = {}
            for provider in PROVIDERS:
                active = any(
                    k.startswith(("access:", "refresh:"))
                    and exp > time.time()
                    and isinstance(value, dict)
                    and provider_for_redirect(value.get("redirect_uri", "")) == provider
                    for k, (exp, value) in self.records.items()
                )
                result[provider] = {**self.provider_events.get(provider, {}), "authorized": active}
            return result

    def register(self, p):
        with self.lock:
            self.limit("register", 10, 600)
            urls = p.get("redirect_uris")
            if not isinstance(urls, list) or not 1 <= len(urls) <= 5 or not all(safe_redirect(x) for x in urls):
                raise HTTPError("Only ChatGPT or Claude sign-in callback addresses are accepted.")
            method = p.get("token_endpoint_auth_method", "none")
            if method not in ("none", "client_secret_post", "client_secret_basic"):
                raise HTTPError("Unsupported client authentication.")
            ident = secrets.token_urlsafe(24)
            key = secrets.token_urlsafe(32) if method != "none" else None
            result = {
                "client_id": ident,
                "redirect_uris": urls,
                "token_endpoint_auth_method": method,
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "client_id_issued_at": int(time.time()),
                "client_secret_expires_at": 0,
            }
            self.put("client:" + ident, {**result, "secret_hash": digest(key) if key else None}, 30 * 86400)
            if key:
                result["client_secret"] = key
            return result

    def begin(self, p):
        with self.lock:
            self.limit("authorize", 30, 600)
            client = self.get("client:" + p.get("client_id", ""))
            if not client or p.get("redirect_uri") not in client["redirect_uris"]:
                raise HTTPError("Unregistered client or callback address.")
            if (
                p.get("response_type") != "code"
                or p.get("code_challenge_method") != "S256"
                or not re.fullmatch(r"[A-Za-z0-9_-]{43}", p.get("code_challenge", ""))
            ):
                raise HTTPError("Authorization code with PKCE S256 is required.")
            resource = p.get("resource") or self.origin + "/mcp"
            if resource != self.origin + "/mcp":
                raise HTTPError("Invalid resource.")
            scopes = p.get("scope", SCOPE).split()
            if "ha.projects" not in scopes or set(scopes) - {"ha.projects", "offline_access"}:
                raise HTTPError("Invalid scopes.")
            if len(p.get("state", "")) > 2048:
                raise HTTPError("Invalid state.")
            flow = secrets.token_urlsafe(32)
            self.put(
                "flow:" + flow,
                {
                    "client_id": p["client_id"],
                    "redirect_uri": p["redirect_uri"],
                    "challenge": p["code_challenge"],
                    "state": p.get("state", ""),
                    "resource": resource,
                    "scope": " ".join(scopes),
                    "origin": self.origin,
                },
                600,
            )
            self.record_event(provider_for_redirect(p["redirect_uri"]), "approval_requested_at")
            return flow

    def approve(self, p):
        with self.lock:
            self.limit("approve", 10, 600)
            flow = self.get("flow:" + p.get("flow", ""))
            if not flow or flow["origin"] != self.origin:
                raise HTTPError("This connection request expired. Start it again from ChatGPT or Claude.")
            expected = self.get("pair")
            if not expected or not secrets.compare_digest(expected, digest(p.get("pairing_code", "").strip())):
                raise HTTPError("Wrong or expired approval code. Get a new one in HA.", 403)
            self.records.pop("pair", None)
            self.records.pop("flow:" + p["flow"], None)
            self.record_event(provider_for_redirect(flow["redirect_uri"]), "approved_at")
            code = secrets.token_urlsafe(32)
            self.put("code:" + digest(code), flow, 120)
            query = {"code": code, "iss": self.origin}
            if flow["state"]:
                query["state"] = flow["state"]
            return flow["redirect_uri"] + "?" + urlencode(query)

    def exchange(self, p, authorization=""):
        with self.lock:
            self.limit("token", 120)
            ident, supplied = p.get("client_id", ""), p.get("client_secret", "")
            if authorization.startswith("Basic "):
                try:
                    raw = base64.b64decode(authorization[6:], validate=True).decode()
                    ident, supplied = (unquote(x) for x in raw.split(":", 1))
                except (ValueError, UnicodeError):
                    raise HTTPError("Invalid client authentication.", 401)
            client = self.get("client:" + ident)
            if not client or (
                client["secret_hash"] and not secrets.compare_digest(client["secret_hash"], digest(supplied))
            ):
                raise HTTPError("Invalid client.", 401)
            method = client["token_endpoint_auth_method"]
            if method == "client_secret_basic" and not authorization.startswith("Basic "):
                raise HTTPError("Client authentication method mismatch.", 401)
            if method == "client_secret_post" and authorization.startswith("Basic "):
                raise HTTPError("Client authentication method mismatch.", 401)
            resource = p.get("resource") or self.origin + "/mcp"
            if resource != self.origin + "/mcp":
                raise HTTPError("Invalid resource.")
            if p.get("grant_type") == "authorization_code":
                verifier = p.get("code_verifier", "")
                if not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier):
                    raise HTTPError("Invalid PKCE verifier.")
                key = "code:" + digest(p.get("code", ""))
                grant = self.get(key)
                valid = (
                    grant
                    and grant["redirect_uri"] == p.get("redirect_uri")
                    and secrets.compare_digest(grant["challenge"], digest(verifier))
                )
            elif p.get("grant_type") == "refresh_token":
                key = "refresh:" + digest(p.get("refresh_token", ""))
                grant = self.get(key)
                valid = grant
            else:
                raise HTTPError("Unsupported grant type.")
            if (
                not valid
                or grant["client_id"] != ident
                or grant["resource"] != resource
                or grant["origin"] != self.origin
            ):
                raise HTTPError("Invalid or expired grant.")
            self.records.pop(key, None)
            access = secrets.token_urlsafe(32)
            self.put("access:" + digest(access), grant, 3600)
            result = {"access_token": access, "token_type": "Bearer", "expires_in": 3600, "scope": grant["scope"]}
            if "offline_access" in grant["scope"].split():
                refresh = secrets.token_urlsafe(32)
                self.put("refresh:" + digest(refresh), grant, 30 * 86400)
                result["refresh_token"] = refresh
            return result

    def check(self, authorization):
        with self.lock:
            if not authorization.startswith("Bearer "):
                raise HTTPError("Authorization required.", 401)
            grant = self.get("access:" + digest(authorization[7:]))
            if (
                not grant
                or grant["origin"] != self.origin
                or grant["resource"] != self.origin + "/mcp"
                or "ha.projects" not in grant["scope"].split()
            ):
                raise HTTPError("Authorization required.", 401)
            self.limit("mcp", 240)
            return grant


class Rpc:
    """JSON MCP over HTTP using the same tool definitions as HA's stdio bridge."""

    def __init__(self, call, version="", instructions=""):
        from .mcp import build_server

        self.server = build_server(call)
        self.version = version
        self.instructions = instructions or self.server.instructions or ""
        self.tools = [
            t.model_dump(by_alias=True, mode="json", exclude_none=True)
            for t in asyncio.run(self.server.list_tools())
        ]

    def call(self, name, arguments):
        try:
            result = asyncio.run(self.server.call_tool(name, arguments))
            return result.model_dump(by_alias=True, mode="json", exclude_none=True)
        except Exception as exc:
            text = str(exc) or type(exc).__name__
            return {"content": [{"type": "text", "text": text}], "isError": True}

    def handle(self, message):
        ident = message.get("id") if isinstance(message, dict) else None

        def error(code, text):
            return {"jsonrpc": "2.0", "id": ident, "error": {"code": code, "message": text}}

        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return error(-32600, "Invalid JSON-RPC request")
        method = message.get("method")
        if method is None:
            return None if ("result" in message or "error" in message) else error(-32600, "Missing method")
        if not isinstance(method, str):
            return error(-32600, "Invalid method")
        if "id" not in message:
            return None
        if not isinstance(ident, (str, int)) or isinstance(ident, bool):
            return error(-32600, "Invalid request ID")
        params = message.get("params", {})
        if not isinstance(params, dict):
            return error(-32602, "params must be an object")
        if method == "initialize":
            version = params.get("protocolVersion")
            result = {
                "protocolVersion": version if version in PROTOCOLS else PROTOCOLS[0],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "Hivemind Assembly", "version": self.version},
                "instructions": self.instructions,
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": self.tools}
        elif method == "tools/call":
            name, arguments = params.get("name"), params.get("arguments") or {}
            if not isinstance(name, str) or not isinstance(arguments, dict):
                return error(-32602, "Invalid tool call")
            result = self.call(name, arguments)
        elif method in ("resources/list", "prompts/list", "resources/templates/list"):
            key = {"resources/list": "resources", "prompts/list": "prompts"}.get(method, "resourceTemplates")
            result = {key: []}
        else:
            return error(-32601, "Method not found")
        return {"jsonrpc": "2.0", "id": ident, "result": result}


APPROVAL_PAGE = """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Approve Hivemind Assembly</title>
<style>body{font:16px system-ui;max-width:520px;margin:6vh auto;padding:24px;line-height:1.5;color:#18241f}h1{font-size:24px}input,button{box-sizing:border-box;width:100%;font:inherit;padding:11px;margin:10px 0;border:1px solid #9fb0a8;border-radius:7px}button{background:#1f5e46;color:#fff;cursor:pointer}small{display:block;color:#56645d}</style>
<h1>Connect Hivemind Assembly</h1><p>CLIENT will be able to use the projects you shared in HA's Connections page. Nothing else on this computer is shared.</p>
<form method="post" action="/authorize"><input type="hidden" name="flow" value="FLOW"><label>Approval code<input name="pairing_code" autocomplete="off" maxlength="64" required autofocus></label><small>Select Show approval code in HA (Connections) and enter it here.</small><button>Approve</button></form>
<small>Only approve a connection you started. You can disconnect it in HA at any time.</small></html>"""


class Gateway(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, rpc):
        self.rpc = rpc
        self.auth = Auth()
        self.slots = threading.BoundedSemaphore(12)
        super().__init__(("127.0.0.1", 0), GatewayHandler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


class GatewayHandler(BaseHTTPRequestHandler):
    server_version = "HA"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(60)

    def log_message(self, *args):
        pass  # addresses and tokens do not belong in logs

    def respond(self, status, value=None, headers=None, mime="application/json"):
        if value is None:
            body = b""
        elif mime.startswith("text/"):
            body = value.encode()
        else:
            body = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        base = {
            "Content-Type": mime,
            "Content-Length": str(len(body)),
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
        }
        for k, v in {**base, **(headers or {})}.items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def guard(self):
        origin = self.server.auth.origin
        if not origin:
            raise HTTPError("The browser connection is starting.", 503)
        hosts = {urlsplit(origin).netloc, "127.0.0.1:" + str(self.server.server_port)}
        if self.headers.get("Host", "") not in hosts:
            raise HTTPError("Invalid Host.", 403)
        if urlsplit(self.path).path == "/authorize":
            allowed = (None, origin)
        else:
            allowed = (None, origin, "https://chatgpt.com", "https://chat.openai.com", "https://claude.ai", "https://claude.com")
        if self.headers.get("Origin") not in allowed:
            raise HTTPError("Invalid Origin.", 403)
        if len(self.path) > 8192:
            raise HTTPError("Request address too long.", 414)

    def body(self, form=False):
        if self.headers.get("Transfer-Encoding"):
            raise HTTPError("Transfer-Encoding is not accepted.")
        expected = "application/x-www-form-urlencoded" if form else "application/json"
        if self.headers.get("Content-Type", "").split(";")[0].strip() != expected:
            raise HTTPError("Unexpected content type.", 415)
        try:
            size = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            size = -1
        if not 0 < size <= MAX_BODY:
            raise HTTPError("Invalid body size.", 413)
        data = self.rfile.read(size)
        if len(data) != size:
            raise HTTPError("Incomplete body.")
        if form:
            values = parse_qs(data.decode(), keep_blank_values=True, max_num_fields=30)
            if any(len(v) != 1 for v in values.values()):
                raise HTTPError("Repeated parameters are not accepted.")
            p = {k: v[0] for k, v in values.items()}
        else:
            p = json.loads(data)
        if not isinstance(p, dict):
            raise HTTPError("Expected an object.")
        return p

    def dispatch(self):
        self.guard()
        auth = self.server.auth
        origin = auth.origin
        path = urlsplit(self.path).path
        if self.command in ("GET", "HEAD"):
            if path in ("/.well-known/oauth-protected-resource", "/.well-known/oauth-protected-resource/mcp"):
                return self.respond(200, {
                    "resource": origin + "/mcp",
                    "authorization_servers": [origin],
                    "scopes_supported": SCOPE.split(),
                    "bearer_methods_supported": ["header"],
                })
            if path == "/.well-known/oauth-authorization-server":
                return self.respond(200, {
                    "issuer": origin,
                    "authorization_endpoint": origin + "/authorize",
                    "token_endpoint": origin + "/token",
                    "registration_endpoint": origin + "/register",
                    "response_types_supported": ["code"],
                    "grant_types_supported": ["authorization_code", "refresh_token"],
                    "token_endpoint_auth_methods_supported": ["none", "client_secret_post", "client_secret_basic"],
                    "scopes_supported": SCOPE.split(),
                    "code_challenge_methods_supported": ["S256"],
                    "authorization_response_iss_parameter_supported": True,
                })
            if path in ("/", "/health"):
                return self.respond(200, {"name": "Hivemind Assembly", "authorization": "OAuth with owner approval", "transport": "JSON Streamable HTTP"})
            if path == "/authorize":
                values = parse_qs(urlsplit(self.path).query, keep_blank_values=True, max_num_fields=30)
                if any(len(v) != 1 for v in values.values()):
                    raise HTTPError("Repeated authorization parameters.")
                flow = auth.begin({k: v[0] for k, v in values.items()})
                callback = values["redirect_uri"][0]
                page = APPROVAL_PAGE.replace("CLIENT", html.escape(provider_for_redirect(callback))).replace("FLOW", html.escape(flow))
                return self.respond(200, page, {
                    "Referrer-Policy": "same-origin",
                    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self' " + callback + "; frame-ancestors 'none'; base-uri 'none'",
                }, "text/html; charset=utf-8")
            if path == "/mcp":
                auth.check(self.headers.get("Authorization", ""))
                return self.respond(405, {"error": "Use JSON POST."}, {"Allow": "POST"})
        elif self.command == "POST":
            if path == "/register":
                return self.respond(201, auth.register(self.body()))
            if path == "/authorize":
                return self.respond(303, None, {"Location": auth.approve(self.body(True))})
            if path == "/token":
                return self.respond(200, auth.exchange(self.body(True), self.headers.get("Authorization", "")))
            if path == "/mcp":
                grant = auth.check(self.headers.get("Authorization", ""))
                version = self.headers.get("MCP-Protocol-Version")
                if version and version not in PROTOCOLS:
                    raise HTTPError("Unsupported MCP version.")
                message = self.body()
                result = self.server.rpc.handle(message)
                if result is not None and len(json.dumps(result).encode()) > MAX_RESULT:
                    raise HTTPError("Result too large; request less at once.", 413)
                provider = provider_for_redirect(grant["redirect_uri"])
                auth.record_event(provider, "last_request_at")
                if result is not None and "error" not in result:
                    stage = {"initialize": "initialized_at", "tools/list": "tools_listed_at", "tools/call": "last_tool_at"}.get(message.get("method"))
                    if stage and not result["result"].get("isError"):
                        auth.record_event(provider, stage)
                return self.respond(202 if result is None else 200, result)
        elif self.command == "DELETE" and path == "/mcp":
            auth.check(self.headers.get("Authorization", ""))
            return self.respond(405, {"error": "Stateless transport."}, {"Allow": "POST"})
        raise HTTPError("Not found.", 404)

    def handle_request(self):
        try:
            self.dispatch()
        except HTTPError as exc:
            headers = {}
            if exc.status == 401 and self.server.auth.origin:
                headers["WWW-Authenticate"] = 'Bearer resource_metadata="' + self.server.auth.origin + '/.well-known/oauth-protected-resource/mcp"'
            if exc.status == 429:
                headers["Retry-After"] = "60"
            if self.command == "POST" and urlsplit(self.path).path == "/authorize":
                message = "This page is out of date. Start the connection again from ChatGPT or Claude." if "Origin" in str(exc) else str(exc)
                page = ('<!doctype html><meta charset="utf-8"><title>Not connected</title><main style="font:17px system-ui;max-width:520px;margin:8vh auto;padding:24px">'
                        "<h1>Not connected</h1><p>" + html.escape(message) + "</p><p>No access was granted.</p></main>")
                self.respond(exc.status, page, headers, "text/html; charset=utf-8")
            else:
                self.respond(exc.status, {"error": str(exc)}, headers)
        except (ValueError, TypeError, KeyError, UnicodeError):
            self.respond(400, {"error": "Invalid request."})
        except Exception:
            self.respond(500, {"error": "HA could not process this request."})

    do_GET = do_POST = do_HEAD = do_DELETE = handle_request


class QuickConnection:
    """Owns the gateway and the cloudflared process; local work survives tunnel loss."""

    def __init__(self, root, call, version="", installer=install_binary, enabled=lambda: True):
        self.folder = Path(root) / "private" / "quick-tunnel"
        self.call, self.version, self.installer, self.enabled = call, version, installer, enabled
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.proc = self.gateway = self.thread = None
        self.state, self.message, self.origin = "off", "", ""
        self.download = None
        self.address_changed = False
        try:
            prior = json.loads((self.folder / "session.json").read_text())
        except (OSError, ValueError):
            prior = {}
        self.previous_origin = prior.get("origin", "")

    def update(self, state, message):
        with self.lock:
            self.state, self.message = state, message

    def installed(self):
        try:
            return installed_binary(self.folder / "bin") is not None
        except Blocked:
            return False

    def install(self, progress=None):
        report = progress.download if progress else None
        return self.installer(self.folder / "bin", report)

    def status(self):
        with self.lock:
            services = self.gateway.auth.services() if self.gateway else {}
            return {
                "state": self.state,
                "message": self.message,
                "endpoint": self.origin + "/mcp" if self.origin else "",
                "address_changed": bool(self.origin and self.address_changed),
                "download": self.download,
                "services": services,
                "providers": PROVIDERS,
            }

    def start(self):
        if not self.enabled():
            raise Blocked("Turn on HA MCP access and share a project first.")
        with self.lock:
            if self.thread and self.thread.is_alive():
                return self.status()
            self.stop_event.clear()
            self.update("starting", "Starting the browser connection.")
            self.thread = threading.Thread(target=self.run, daemon=True, name="ha-quick-tunnel")
            self.thread.start()
            return self.status()

    def pairing(self):
        with self.lock:
            if not self.gateway or self.state != "ready":
                raise Blocked("Wait until the connection address is ready.")
            return self.gateway.auth.pairing()

    def revoke(self):
        with self.lock:
            if self.gateway:
                self.gateway.auth.revoke()
        return self.status()

    def run(self):
        gateway = None
        try:
            def downloaded(done, total):
                with self.lock:
                    self.download = {"done_bytes": done, "total_bytes": total}
            self.update("preparing", "Downloading the Cloudflare tunnel component (no account needed).")
            binary = self.installer(self.folder / "bin", downloaded, self.stop_event)
            with self.lock:
                self.download = None
            if self.stop_event.is_set():
                return
            gateway = Gateway(Rpc(self.call, self.version))
            self.gateway = gateway
            threading.Thread(target=gateway.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True).start()
            self.folder.mkdir(parents=True, exist_ok=True)
            config = self.folder / "isolated.yml"
            config.write_text("{}\n", encoding="utf-8")
            environment = {k: v for k, v in os.environ.items() if not k.startswith(("TUNNEL_", "CLOUDFLARE_"))}
            failures = 0
            while not self.stop_event.is_set():
                command = [str(binary), "tunnel", "--config", str(config), "--no-autoupdate",
                           "--url", "http://127.0.0.1:" + str(gateway.server_port)]
                kwargs = ({"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
                          if os.name == "nt" else {"start_new_session": True})
                self.update("connecting", "Opening a temporary web address.")
                with self.lock:
                    if self.stop_event.is_set():
                        break
                    proc = subprocess.Popen(
                        command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, encoding="utf-8", errors="replace", env=environment, cwd=self.folder, **kwargs,
                    )
                    self.proc = proc
                found = threading.Event()

                def reader(process=proc):
                    while True:
                        line = process.stdout.readline(16385)
                        if not line:
                            break
                        match = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com(?=[\s/|]|$)", line)
                        if match and not found.is_set():
                            origin = match.group(0)
                            with self.lock:
                                if self.stop_event.is_set() or self.proc is not process:
                                    return
                                gateway.auth.activate(origin)
                                self.address_changed = bool(self.previous_origin and origin != self.previous_origin)
                                self.previous_origin = origin
                                self.origin = origin
                                atomic_write(self.folder / "session.json", canonical({"origin": origin}))
                                self.update("ready", "Ready. Connect ChatGPT or Claude below.")
                                found.set()

                reader_thread = threading.Thread(target=reader, daemon=True)
                reader_thread.start()
                started = time.monotonic()
                while proc.poll() is None and not self.stop_event.wait(0.25):
                    if not found.is_set() and time.monotonic() - started > 90:
                        proc.terminate()
                        break
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=5)
                reader_thread.join(timeout=2)
                with self.lock:
                    gateway.auth.revoke()
                    self.origin = ""
                    self.proc = None
                if self.stop_event.is_set():
                    break
                failures = failures + 1 if not found.is_set() else 1
                if failures >= 6:
                    raise Blocked("The free tunnel kept disconnecting. Select Start to try again.")
                self.update("reconnecting", "Disconnected; reconnecting. The address will change, so reconnect ChatGPT and Claude afterwards.")
                if self.stop_event.wait(min(60, 2 ** failures)):
                    break
        except Exception as exc:
            if not self.stop_event.is_set():
                self.update("error", str(exc) or type(exc).__name__)
        finally:
            process = self.proc
            if process and process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                except OSError:
                    pass
            if gateway:
                gateway.auth.revoke()
                gateway.shutdown()
                gateway.server_close()
            with self.lock:
                self.gateway = self.proc = None
                self.origin = ""
                self.download = None
                if self.stop_event.is_set():
                    self.update("off", "Stopped.")

    def stop(self):
        self.stop_event.set()
        with self.lock:
            proc = self.proc
            if self.gateway:
                self.gateway.auth.revoke()
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=8)
        self.update("off", "Stopped.")
        return self.status()

    close = stop
