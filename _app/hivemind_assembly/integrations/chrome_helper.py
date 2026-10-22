"""Chrome companion helper: fills ChatGPT/Claude connector forms and HA's approval page.

Chrome -> native messaging (length-prefixed JSON on stdio) -> this program ->
HA's local dashboard API. The helper only gets connection details and one-time
approval codes. It never receives the dashboard token, project files or tools.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import struct
import sys
from urllib.parse import parse_qs, urlsplit

from hivemind_assembly.core.common import Blocked, ContractError
from hivemind_assembly.paths import APP_ROOT

HOST_NAME = "com.hivemindassembly.connection_helper"
EXTENSION_ID = "lbddbgldcjpoodcoakkgiblhndghpmkj"
EXTENSION_DIR = APP_ROOT / "browser-helper" / "extension"
DESCRIPTION = "Your Hivemind Assembly projects: files, checks and task control."
MAX_MESSAGE = 16 * 1024


def endpoint_origin(endpoint):
    u = urlsplit(endpoint or "")
    if (
        u.scheme != "https" or u.username or u.password or u.port is not None
        or u.path != "/mcp" or u.query or u.fragment
        or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*\.trycloudflare\.com", u.hostname or "")
    ):
        raise Blocked("Start the browser connection in HA (Connections) first.")
    return "https://" + u.hostname


def details(quick, provider):
    from .quick_connect import PROVIDERS

    if provider not in PROVIDERS:
        raise ContractError("Choose ChatGPT or Claude.")
    status = quick.status()
    if status["state"] != "ready":
        raise Blocked("Start the browser connection in HA (Connections) and wait until it is ready.")
    origin = endpoint_origin(status["endpoint"])
    return {
        "name": "Hivemind Assembly",
        "description": DESCRIPTION,
        "provider": provider,
        "endpoint": status["endpoint"],
        "origin": origin,
        "setup_url": PROVIDERS[provider]["url"],
        "acknowledge_risk": True,
    }


def pair(quick, provider, page_url, flow):
    """A code bound to this exact approval page, after checking it really is HA's."""
    from .quick_connect import provider_for_redirect, safe_redirect

    current = details(quick, provider)
    if not isinstance(page_url, str) or len(page_url) > 8192:
        raise ContractError("Invalid approval page.")
    u = urlsplit(page_url)
    if (
        u.scheme != "https" or u.netloc != urlsplit(current["origin"]).netloc
        or u.path != "/authorize" or u.fragment or u.username or u.password
    ):
        raise Blocked("This is not HA's current approval page.")
    if not isinstance(flow, str) or not re.fullmatch(r"[A-Za-z0-9_-]{20,100}", flow):
        raise ContractError("No approval request was found on the page.")
    values = parse_qs(u.query, keep_blank_values=True, max_num_fields=30)
    if any(len(v) != 1 for v in values.values()):
        raise ContractError("Ambiguous approval page.")
    values = {k: v[0] for k, v in values.items()}
    callback = values.get("redirect_uri", "")
    if not safe_redirect(callback) or provider_for_redirect(callback) != provider:
        raise Blocked("The approval page belongs to a different assistant.")
    gateway = quick.gateway
    if gateway is None:
        raise Blocked("The browser connection stopped. Start it again in HA.")
    auth = gateway.auth
    with auth.lock:
        record = auth.get("flow:" + flow)
        if (
            auth.origin != current["origin"] or not record
            or record.get("redirect_uri") != callback
            or record.get("client_id") != values.get("client_id")
        ):
            raise Blocked("This approval page expired. Start the connection again from " + provider + ".")
        code = auth.pairing(flow=flow)
    return {**current, "pairing_code": code["code"], "expires_in": code["expires_in"], "flow": flow}


def dashboard_request(data_dir, path, payload, timeout=35):
    """Call the running HA dashboard API with its local token."""
    import httpx

    try:
        endpoint = json.loads((Path(data_dir) / "private" / "endpoint.json").read_text())
        port = endpoint["port"]
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError()
        with httpx.Client(timeout=timeout, trust_env=False, follow_redirects=False) as client:
            r = client.post(
                f"http://127.0.0.1:{port}/api/{path}",
                headers={"X-Workbench-Token": endpoint["token"]},
                json=payload,
            )
    except (OSError, ValueError, KeyError, httpx.HTTPError):
        raise Blocked("HA is not running. Open Hivemind Assembly, then try again.") from None
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code != 200:
        raise Blocked(str(data.get("error") or "HA refused the request.")[:500])
    return data


def native_dispatch(message, requester):
    if not isinstance(message, dict) or not isinstance(message.get("op"), str):
        raise ContractError("Expected a helper request.")
    op = message["op"]
    if op == "status":
        if set(message) != {"op"}:
            raise ContractError("Unexpected field.")
        status = requester("helper/status", {})
        # Explicit projection: never pass on anything beyond connection progress.
        services = status.get("services") or {}
        return {
            "state": status.get("state"),
            "message": status.get("message"),
            "services": {
                p: {k: v for k, v in (services.get(p) or {}).items() if k in (
                    "authorized", "approval_requested_at", "approved_at",
                    "initialized_at", "tools_listed_at", "last_request_at", "last_tool_at")}
                for p in ("ChatGPT", "Claude")
            },
        }
    allowed = {"details": {"op", "provider"}, "pair": {"op", "provider", "page_url", "flow"}}
    if op not in allowed:
        raise ContractError("Only status, connection details and approval codes are supported.")
    if set(message) - allowed[op]:
        raise ContractError("Unexpected field.")
    return requester("helper/" + op, {k: v for k, v in message.items() if k != "op"})


def read_exact(stream, size):
    parts = []
    while size:
        part = stream.read(size)
        if not part:
            raise EOFError()
        parts.append(part)
        size -= len(part)
    return b"".join(parts)


def native_main(argv=None, stdin=None, stdout=None, requester=None):
    argv = sys.argv[1:] if argv is None else argv
    if "--data-dir" not in argv:
        return 2
    data_dir = argv[argv.index("--data-dir") + 1]
    # Chrome passes the calling extension's origin; refuse any other extension.
    if "chrome-extension://" + EXTENSION_ID + "/" not in argv:
        return 2
    if os.name == "nt" and stdin is None:
        import msvcrt

        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    stdin = stdin or sys.stdin.buffer
    stdout = stdout or sys.stdout.buffer
    requester = requester or (lambda path, payload: dashboard_request(data_dir, path, payload))
    while True:
        head = stdin.read(4)
        if not head:
            return 0
        try:
            head += read_exact(stdin, 4 - len(head)) if len(head) < 4 else b""
            size = struct.unpack("=I", head)[0]
            if not 0 < size <= MAX_MESSAGE:
                return 2
            raw = read_exact(stdin, size)
        except EOFError:
            return 2
        try:
            reply = {"ok": True, "value": native_dispatch(json.loads(raw.decode("utf-8")), requester)}
        except (Blocked, ContractError, ValueError) as exc:
            reply = {"ok": False, "error": str(exc)[:1000] or "The request was refused."}
        except Exception:
            reply = {"ok": False, "error": "HA could not answer. Keep HA open and try again."}
        encoded = json.dumps(reply, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(encoded) > 32 * 1024:
            return 2
        stdout.write(struct.pack("=I", len(encoded)) + encoded)
        stdout.flush()


def extension_id(folder=EXTENSION_DIR):
    manifest = json.loads((Path(folder) / "manifest.json").read_text())
    der = base64.b64decode(manifest["key"], validate=True)
    calculated = "".join(chr(ord("a") + int(x, 16)) for x in hashlib.sha256(der).hexdigest()[:32])
    if calculated != EXTENSION_ID:
        raise Blocked("The Chrome helper files are incomplete. Reinstall HA.")
    return calculated


def _write_if_changed(path, text, executable=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        temp = path.with_suffix(path.suffix + ".new")
        temp.write_text(text, encoding="utf-8", newline="")
        temp.replace(path)
    if os.name != "nt":
        path.chmod(0o700 if executable else 0o600)


def register_native_host(data_dir, home=None):
    """Register for the current user only. Chrome still needs the extension loaded once."""
    ident = extension_id()
    data_dir = Path(data_dir).resolve()
    directory = data_dir / "private" / "chrome-helper"
    # Not resolve(): a virtual environment's python is a symlink to a base interpreter without HA's packages.
    executable = Path(sys.executable).absolute()
    launch_py = (APP_ROOT / "launch.py").resolve()
    if os.name == "nt":
        def quoted(p):
            s = str(p)
            if any(x in s for x in ('"', "\r", "\n")):
                raise Blocked("Unsupported installation folder name.")
            return '"' + s.replace("%", "%%") + '"'

        launcher = directory / "ha-chrome-helper.cmd"
        text = ("@echo off\r\nsetlocal DisableDelayedExpansion\r\n" + quoted(executable) + " -u "
                + quoted(launch_py) + " chrome-helper --data-dir " + quoted(data_dir) + " %*\r\n")
    else:
        launcher = directory / "ha-chrome-helper"
        text = ("#!/bin/sh\nexec " + shlex.quote(str(executable)) + " -u " + shlex.quote(str(launch_py))
                + " chrome-helper --data-dir " + shlex.quote(str(data_dir)) + ' "$@"\n')
    _write_if_changed(launcher, text, True)
    manifest = {
        "name": HOST_NAME,
        "description": "Hivemind Assembly connection setup only",
        "path": str(launcher),
        "type": "stdio",
        "allowed_origins": ["chrome-extension://" + ident + "/"],
    }
    body = json.dumps(manifest, indent=2) + "\n"
    manifest_path = directory / (HOST_NAME + ".json")
    _write_if_changed(manifest_path, body)
    registered = []
    if os.name == "nt":
        import winreg

        for browser, key in [
            ("Chrome", "Software\\Google\\Chrome\\NativeMessagingHosts\\"),
            ("Edge", "Software\\Microsoft\\Edge\\NativeMessagingHosts\\"),
        ]:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key + HOST_NAME, 0, winreg.KEY_WRITE) as handle:
                winreg.SetValueEx(handle, "", 0, winreg.REG_SZ, str(manifest_path))
            registered.append(browser)
    else:
        home = Path(home or Path.home())
        if sys.platform == "darwin":
            paths = {"Chrome": home / "Library/Application Support/Google/Chrome/NativeMessagingHosts",
                     "Edge": home / "Library/Application Support/Microsoft Edge/NativeMessagingHosts"}
        else:
            paths = {"Chrome": home / ".config/google-chrome/NativeMessagingHosts",
                     "Chromium": home / ".config/chromium/NativeMessagingHosts"}
        for browser, path in paths.items():
            _write_if_changed(path / manifest_path.name, body)
            registered.append(browser)
    return {"registered": registered, "extension_id": ident, "folder": str(EXTENSION_DIR)}


def open_extensions_page():
    """Open Chrome's own Extensions page; Chrome lets a program open it, not a web page."""
    import shutil
    import subprocess

    url = "chrome://extensions"
    if os.name == "nt":
        roots = [os.environ.get(k) for k in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        found = [Path(r) / "Google/Chrome/Application/chrome.exe" for r in roots if r]
        exe = next((str(p) for p in found if p.is_file()), None)
    elif sys.platform == "darwin":
        exe = None
        if shutil.which("open"):
            subprocess.Popen(["open", "-a", "Google Chrome", url])
            return True
    else:
        exe = next((shutil.which(x) for x in ("google-chrome", "google-chrome-stable", "chromium") if shutil.which(x)), None)
    if not exe:
        return False
    subprocess.Popen(
        [exe, url], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        **({"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if os.name == "nt" else {}),
    )
    return True
