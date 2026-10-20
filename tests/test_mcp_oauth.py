import asyncio
import base64
import hashlib
import json
import socket
import threading
import time
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx2
import pytest
import uvicorn
import test_mcp_connections
from hivemind_assembly.core.common import Blocked
from hivemind_assembly.integrations.mcp import build_server
from hivemind_assembly.integrations.mcp_oauth import LoopbackCallback, OAuthStorage

app = test_mcp_connections.app


@pytest.fixture
def oauth_server():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    base = "http://127.0.0.1:" + str(sock.getsockname()[1])
    state = {
        "access": "oauth-access-secret-one",
        "refreshes": 0,
        "registrations": 0,
        "tokens": 0,
    }
    sdk = build_server(lambda tool, args: {"echo": state["access"]})
    inner = sdk.streamable_http_app(stateless_http=True, json_response=True)

    async def serve(scope, receive, send):
        if scope["type"] != "http":
            return await inner(scope, receive, send)
        path = scope["path"]
        headers = dict(scope["headers"])
        status, extra = 200, []
        if path == "/.well-known/oauth-protected-resource/mcp":
            result = {
                "resource": base + "/mcp",
                "authorization_servers": [base + "/auth"],
            }
        elif path == "/.well-known/oauth-authorization-server/auth":
            result = {
                "issuer": base + "/auth",
                "authorization_endpoint": base + "/authorize",
                "token_endpoint": base + "/auth/token-v2",
                "registration_endpoint": base + "/register",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "code_challenge_methods_supported": ["S256"],
                "token_endpoint_auth_methods_supported": ["none"],
                "authorization_response_iss_parameter_supported": True,
            }
        elif path in ("/register", "/auth/token-v2"):
            body = b""
            while True:
                chunk = await receive()
                body += chunk.get("body", b"")
                if not chunk.get("more_body"):
                    break
            if path == "/register":
                state["registrations"] += 1
                result = {**json.loads(body), "client_id": "fixture-public-client"}
                status = 201
            else:
                values = parse_qs(body.decode())
                assert values["resource"] == [base + "/mcp"]
                if values["grant_type"] == ["authorization_code"]:
                    state["tokens"] += 1
                    assert values["code"] == ["one-time-code-secret"]
                    challenge = (
                        base64.urlsafe_b64encode(
                            hashlib.sha256(values["code_verifier"][0].encode()).digest()
                        )
                        .decode()
                        .rstrip("=")
                    )
                    assert challenge == state["challenge"]
                else:
                    assert values["refresh_token"] == ["refresh-secret"]
                    state["refreshes"] += 1
                    state["access"] = "oauth-access-secret-refreshed"
                result = {
                    "access_token": state["access"],
                    "token_type": "Bearer",
                    "refresh_token": "refresh-secret",
                    "expires_in": 3600,
                }
        elif path == "/mcp":
            if headers.get(b"authorization") == ("Bearer " + state["access"]).encode():
                return await inner(scope, receive, send)
            status = 401
            extra = [
                (
                    b"www-authenticate",
                    (
                        'Bearer resource_metadata="'
                        + base
                        + '/.well-known/oauth-protected-resource/mcp"'
                    ).encode(),
                )
            ]
            result = {"error": "unauthorized"}
        else:
            status, result = 404, {}
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", b"application/json"), *extra],
            }
        )
        await send({"type": "http.response.body", "body": json.dumps(result).encode()})

    server = uvicorn.Server(uvicorn.Config(serve, log_level="error"))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.01)
    assert server.started
    try:
        yield base, state
    finally:
        server.should_exit = True
        thread.join(10)
        sock.close()


def test_official_oauth_registration_pkce_refresh_and_private_storage(
    app, oauth_server
):
    base, state = oauth_server
    task = app.store.create_project("oauth", "test", paused=True)
    config = app.connections.settings()
    config["servers"]["fixture"] = {
        "transport": "http",
        "url": base + "/mcp",
        "tools": ["ha_projects"],
        "projects": [task["project_id"]],
    }
    app.connections.save(config)
    opens = []

    async def browser(profile, url):
        opens.append(profile)
        values = parse_qs(urlsplit(url).query)
        assert values["code_challenge_method"] == ["S256"]
        assert values["resource"] == [base + "/mcp"]
        state["challenge"] = values["code_challenge"][0]
        async with httpx2.AsyncClient(trust_env=False) as http:
            response = await http.get(
                values["redirect_uri"][0],
                params={
                    "code": "one-time-code-secret",
                    "state": values["state"][0],
                    "iss": base + "/auth",
                },
            )
            assert response.status_code == 200

    app.connections.oauth.open_page = browser
    result = app.action("/api/mcp/authorize", {"server": "fixture"})
    assert result["stage"] == "connecting"
    app.connections.oauth.futures["fixture"].result(timeout=20)
    assert (
        app.connections.oauth.status()[0]["stage"] == "connected"
    ), app.connections.oauth.status()
    assert state["registrations"] == state["tokens"] == len(opens) == 1
    app.action("/api/mcp/authorize", {"server": "fixture"})
    app.connections.oauth.futures["fixture"].result(timeout=20)
    assert app.connections.oauth.status()[0]["stage"] == "connected"
    assert state["registrations"] == state["tokens"] == len(opens) == 1
    assert app.connections.settings()["servers"]["fixture"]["auth"] == "oauth_session"
    app.connections.oauth.credentials["fixture"]["expires_at"] = time.time() - 60

    async def calls():
        return await asyncio.gather(
            *(
                app.connections.external(
                    "fixture", "ha_projects", {}, task["project_id"]
                )
                for _ in range(2)
            )
        )

    outputs = asyncio.run(calls())
    assert state["refreshes"] == 1 and len(opens) == 1
    assert "[redacted]" in json.dumps(
        outputs
    ) and "oauth-access-secret" not in json.dumps(outputs)
    public = json.dumps(app.status()) + app.connections.path.read_text()
    assert "refresh-secret" not in public and "one-time-code-secret" not in public
    for path in app.store.root.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            assert b"refresh-secret" not in data and b"oauth-access-secret" not in data
    storage = OAuthStorage(
        app.connections.oauth,
        "fixture",
        app.connections.settings()["servers"]["fixture"],
    )
    changed = app.connections.settings()
    changed["servers"]["fixture"]["url"] = base + "/different"
    app.connections.save(changed)
    with pytest.raises(Blocked, match="changed"):
        storage.read()
    app.action("/api/mcp/credential", {"server": "fixture", "forget": True})
    assert not app.connections.oauth.credentials


def test_callback_rejects_wrong_state_host_duplicates_and_replay():
    async def exercise():
        callback = LoopbackCallback()
        await callback.start()
        callback.expect(
            "https://provider.example/authorize?"
            + urlencode({"state": "expected", "redirect_uri": callback.url})
        )
        try:
            async with httpx2.AsyncClient(trust_env=False) as http:
                assert (
                    await http.get(
                        callback.url, params={"code": "secret", "state": "wrong"}
                    )
                ).status_code == 400
                assert (
                    await http.get(
                        callback.url + "?code=x&state=expected&state=expected"
                    )
                ).status_code == 400
                assert (
                    await http.get(
                        callback.url,
                        params={"code": "secret", "state": "expected"},
                        headers={"Host": "evil.example"},
                    )
                ).status_code == 400
                assert not callback.future.done()
                params = {
                    "code": "secret",
                    "state": "expected",
                    "iss": "https://provider.example",
                }
                assert (await http.get(callback.url, params=params)).status_code == 200
                assert (await callback.result()).iss == params["iss"]
                assert (await http.get(callback.url, params=params)).status_code == 400
            reader, writer = await asyncio.open_connection("127.0.0.1", callback.port)
            await asyncio.sleep(0)
            await callback.close()
            assert await asyncio.wait_for(reader.read(), 2) == b""
            writer.close()
            await writer.wait_closed()
            assert not callback.clients
        finally:
            await callback.close()

    asyncio.run(exercise())


def test_sdk_rejects_wrong_issuer_before_sending_authorization_code(app, oauth_server):
    base, state = oauth_server
    config = app.connections.settings()
    config["servers"]["fixture"] = {"transport": "http", "url": base + "/mcp"}
    app.connections.save(config)

    async def browser(profile, url):
        values = parse_qs(urlsplit(url).query)
        async with httpx2.AsyncClient(trust_env=False) as http:
            await http.get(
                values["redirect_uri"][0],
                params={
                    "code": "one-time-code-secret",
                    "state": values["state"][0],
                    "iss": base + "/wrong-issuer",
                },
            )

    app.connections.oauth.open_page = browser
    app.action("/api/mcp/authorize", {"server": "fixture"})
    app.connections.oauth.futures["fixture"].result(timeout=20)
    assert app.connections.oauth.status()[0]["stage"] == "attention"
    assert state["tokens"] == 0
    assert "one-time-code-secret" not in json.dumps(app.status())


def test_disconnect_cancels_pending_consent_and_closes_listener(app, oauth_server):
    base, state = oauth_server
    config = app.connections.settings()
    config["servers"]["fixture"] = {"transport": "http", "url": base + "/mcp"}
    app.connections.save(config)
    opened = threading.Event()
    callback = []

    async def browser(profile, url):
        callback.append(parse_qs(urlsplit(url).query)["redirect_uri"][0])
        opened.set()

    app.connections.oauth.open_page = browser
    app.action("/api/mcp/authorize", {"server": "fixture"})
    assert opened.wait(10)
    app.action("/api/mcp/credential", {"server": "fixture", "forget": True})
    app.submit(app.connections.oauth.drain()).result(timeout=10)
    assert not app.connections.oauth.credentials
    assert not app.connections.oauth.status()
    port = urlsplit(callback[0]).port
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=1)
    assert state["tokens"] == 0


def test_vault_storage_expiry_and_forget_rejects_late_token_write(app, monkeypatch):
    from mcp.shared.auth import OAuthToken
    from hivemind_assembly.integrations import mcp_oauth

    values = {}

    class Vault:
        def __init__(self, root, service):
            self.service = service

        def read(self):
            return values.get(self.service)

        def write(self, value):
            values[self.service] = value

        def clear(self):
            values.pop(self.service, None)

    monkeypatch.setattr(mcp_oauth, "CredentialVault", Vault)
    config = app.connections.settings()
    spec = {
        "transport": "http",
        "url": "https://mcp.example/service",
        "auth": "oauth_vault",
    }
    config["servers"]["fixture"] = spec
    app.connections.save(config)
    storage = OAuthStorage(app.connections.oauth, "fixture", spec)
    token = OAuthToken(access_token="private-token", token_type="Bearer", expires_in=60)
    asyncio.run(storage.set_tokens(token))
    values["MCP.OAuth.fixture"]["expires_at"] = time.time() - 5
    assert asyncio.run(storage.get_tokens()).expires_in == 0
    assert "private-token" not in app.connections.path.read_text()
    app.connections.oauth.forget("fixture")
    assert not values
    with pytest.raises(Blocked, match="changed"):
        asyncio.run(storage.set_tokens(token))
