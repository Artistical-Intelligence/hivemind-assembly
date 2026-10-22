"""Browser-chat MCP gateway: OAuth with owner approval, then HA's own tools."""

import base64
import hashlib
import json
import threading
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import pytest

from hivemind_assembly.core.common import Blocked

from hivemind_assembly.integrations.quick_connect import (
    Gateway,
    QuickConnection,
    Rpc,
    provider_for_redirect,
    safe_redirect,
)

ORIGIN = "https://quiet-river-1.trycloudflare.com"
HOST = "quiet-river-1.trycloudflare.com"
CLAUDE = "https://claude.ai/api/mcp/auth_callback"


@pytest.fixture
def gateway():
    calls = []

    def call(tool, args):
        calls.append((tool, args))
        if tool == "ha_task_status":
            raise Blocked("Project is not shared with MCP")
        return {"projects": []}

    g = Gateway(Rpc(call, "1.0"))
    g.auth.activate(ORIGIN)
    threading.Thread(target=g.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    client = httpx.Client(base_url=f"http://127.0.0.1:{g.server_port}", headers={"Host": HOST}, trust_env=False)
    yield g, client, calls
    client.close()
    g.shutdown()
    g.server_close()


def connect(g, client):
    reg = client.post("/register", json={"redirect_uris": [CLAUDE], "token_endpoint_auth_method": "none"})
    assert reg.status_code == 201
    client_id = reg.json()["client_id"]
    verifier = "v" * 64
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    query = urlencode({
        "client_id": client_id, "redirect_uri": CLAUDE, "response_type": "code",
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "s1",
        "scope": "ha.projects offline_access",
    })
    page = client.get("/authorize?" + query)
    assert page.status_code == 200 and "Claude will be able to use" in page.text
    flow = page.text.split('name="flow" value="')[1].split('"')[0]
    form = {"Content-Type": "application/x-www-form-urlencoded"}
    wrong = client.post("/authorize", content=urlencode({"flow": flow, "pairing_code": "nope"}), headers=form)
    assert wrong.status_code == 403 and "No access was granted" in wrong.text
    code = g.auth.pairing()["code"]
    approved = client.post("/authorize", content=urlencode({"flow": flow, "pairing_code": code}), headers=form)
    assert approved.status_code == 303
    target = urlsplit(approved.headers["Location"])
    assert target.netloc == "claude.ai"
    granted = parse_qs(target.query)
    assert granted["state"] == ["s1"] and granted["iss"] == [ORIGIN]
    token = client.post("/token", headers=form, content=urlencode({
        "grant_type": "authorization_code", "code": granted["code"][0], "redirect_uri": CLAUDE,
        "client_id": client_id, "code_verifier": verifier,
    }))
    assert token.status_code == 200
    return token.json()


def rpc(client, token, method, params=None, ident=1):
    return client.post(
        "/mcp",
        headers={"Authorization": "Bearer " + token, "Origin": "https://claude.ai"},
        json={"jsonrpc": "2.0", "id": ident, "method": method, "params": params or {}},
    )


def test_unauthenticated_mcp_requests_are_refused_with_discovery_hint(gateway):
    g, client, calls = gateway
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 401
    assert ORIGIN + "/.well-known/oauth-protected-resource/mcp" in r.headers["WWW-Authenticate"]
    meta = client.get("/.well-known/oauth-authorization-server").json()
    assert meta["registration_endpoint"] == ORIGIN + "/register"
    assert client.get("/", headers={"Host": "evil.example"}).status_code == 403
    assert not calls


def test_approved_client_lists_and_calls_ha_tools(gateway):
    g, client, calls = gateway
    token = connect(g, client)
    assert g.auth.services()["Claude"]["authorized"]
    init = rpc(client, token["access_token"], "initialize", {"protocolVersion": "2025-06-18"}).json()
    assert init["result"]["serverInfo"]["name"] == "Hivemind Assembly"
    tools = rpc(client, token["access_token"], "tools/list").json()["result"]["tools"]
    names = {t["name"] for t in tools}
    assert {"ha_projects", "ha_read_file", "ha_write_file"} <= names
    assert all("inputSchema" in t for t in tools)
    result = rpc(client, token["access_token"], "tools/call", {"name": "ha_projects", "arguments": {}}).json()["result"]
    assert not result.get("isError") and calls == [("ha_projects", {})]
    refused = rpc(client, token["access_token"], "tools/call", {"name": "ha_task_status", "arguments": {"task": "t"}}).json()["result"]
    assert refused["isError"] and "not shared" in json.dumps(refused)
    events = g.auth.services()["Claude"]
    assert {"approved_at", "initialized_at", "tools_listed_at", "last_tool_at"} <= set(events)
    g.auth.revoke()
    assert rpc(client, token["access_token"], "tools/list").status_code == 401


def test_approval_code_is_single_use_and_tied_to_this_address(gateway):
    g, client, _ = gateway
    code = g.auth.pairing()["code"]
    connect(g, client)  # issues and uses its own fresh code, replacing this one
    flow = g.auth.begin({
        "client_id": client.post("/register", json={"redirect_uris": [CLAUDE]}).json()["client_id"],
        "redirect_uri": CLAUDE, "response_type": "code", "code_challenge": "c" * 43,
        "code_challenge_method": "S256",
    })
    with pytest.raises(Exception, match="approval code"):
        g.auth.approve({"flow": flow, "pairing_code": code})
    assert g.auth.services()["Claude"]["authorized"]
    g.auth.activate("https://other-name-2.trycloudflare.com")
    assert not g.auth.services()["Claude"]["authorized"]


def test_only_exact_provider_callbacks_are_accepted():
    assert safe_redirect(CLAUDE) and provider_for_redirect(CLAUDE) == "Claude"
    assert safe_redirect("https://chatgpt.com/connector_platform_oauth_redirect")
    assert not safe_redirect("https://claude.ai/api/mcp/auth_callback?next=x")
    assert not safe_redirect("https://evil.example/api/mcp/auth_callback")
    assert provider_for_redirect("http://chatgpt.com/connector_platform_oauth_redirect") == "Unknown client"


def test_start_requires_mcp_access(tmp_path):
    quick = QuickConnection(tmp_path, lambda t, a: {}, enabled=lambda: False)
    with pytest.raises(Exception, match="MCP access"):
        quick.start()
    assert quick.status()["state"] == "off"


def test_local_apps_are_detected_and_configured_without_losing_settings(store, tmp_path, monkeypatch):
    import tomllib
    from hivemind_assembly.integrations.mcp import Connections

    home = tmp_path / "home"
    monkeypatch.setenv("APPDATA", str(home / "AppData" / "Roaming"))
    (home / ".config" / "Claude").mkdir(parents=True)
    (home / "AppData" / "Roaming" / "Claude").mkdir(parents=True)
    (home / ".codex").mkdir()
    (home / ".codex" / "config.toml").write_text('model = "x"\n[mcp_servers.other]\ncommand = "y"\n')
    connections = Connections(store)
    first = connections.install_local_apps(home)["apps"]
    assert {a["app"] for a in first} == {"Claude Desktop", "Codex"}
    assert all(a["result"].startswith("Added") for a in first)
    again = connections.install_local_apps(home)["apps"]
    assert all(a["result"].startswith("Added") for a in again)
    codex = tomllib.loads((home / ".codex" / "config.toml").read_text())
    assert codex["model"] == "x" and set(codex["mcp_servers"]) == {"other", "hivemind-assembly"}
    claude = next(p for n, p in connections.local_clients(home) if n == "Claude Desktop")
    assert "hivemind-assembly" in json.loads(claude.read_text())["mcpServers"]


def test_connection_lifecycle_with_a_stand_in_tunnel_program(tmp_path):
    """No real tunnel: a stand-in prints the address cloudflared would print."""
    import sys
    import time as clock

    fake = tmp_path / "fake_cloudflared.py"
    fake.write_text(
        "import sys, time\n"
        "print('INF |  https://quiet-river-1.trycloudflare.com  |', flush=True)\n"
        "time.sleep(60)\n"
    )
    launcher = tmp_path / "cloudflared"
    launcher.write_text(f"#!/bin/sh\nexec {sys.executable} {fake}\n")
    launcher.chmod(0o700)

    def installer(folder, progress=None, stop=None):
        if progress:
            progress(5, 10)
        return launcher

    quick = QuickConnection(tmp_path, lambda t, a: {"projects": []}, "1.0", installer=installer)
    quick.start()
    deadline = clock.time() + 20
    while quick.status()["state"] != "ready" and clock.time() < deadline:
        clock.sleep(0.1)
    status = quick.status()
    assert status["state"] == "ready", status
    assert status["endpoint"] == ORIGIN + "/mcp"
    assert set(status["services"]) == {"ChatGPT", "Claude"}
    assert len(quick.pairing()["code"]) >= 10
    quick.stop()
    assert quick.status()["state"] == "off" and quick.status()["endpoint"] == ""
