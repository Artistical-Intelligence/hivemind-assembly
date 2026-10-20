import asyncio
import json
import sys
import threading
from pathlib import Path
import pytest
from mcp import Client, StdioServerParameters
from hivemind_assembly.application.app import Application, make_server
from hivemind_assembly.integrations.mcp import build_server
from hivemind_assembly.core.common import Blocked, Conflict


@pytest.fixture
def app(tmp_path):
    a = Application(tmp_path / "state")
    yield a
    a.close()


def enable(app):
    app.connections.save(
        {"enabled": True, "allow_create": True, "projects": [], "servers": {}}
    )


def test_mcp_project_fencing_and_idempotency(app):
    private = app.store.create_project("private", "unshared", paused=True)
    enable(app)
    api = app.mcp_gateway
    args = {"name": "shared", "objective": "Build a tool", "request_id": "one"}
    task = api.call("ha_create_project", args)
    assert api.call("ha_create_project", args)["id"] == task["id"]
    with pytest.raises(Conflict):
        api.call("ha_create_project", {**args, "name": "different"})
    with pytest.raises(Blocked):
        api.call("ha_read_file", {"task": private["id"], "path": "hidden.txt"})
    assert len(api.call("ha_projects", {})["projects"]) == 1
    written = api.call(
        "ha_write_file", {"task": task["id"], "path": "hello.py", "text": "print(1)"}
    )
    assert (
        api.call("ha_read_file", {"task": task["id"], "path": "hello.py"})["sha256"]
        == written["sha256"]
    )
    with pytest.raises(Exception):
        api.call(
            "ha_write_file", {"task": task["id"], "path": "../escape.py", "text": "bad"}
        )


def test_official_sdk_discovers_and_executes_in_process(app):
    enable(app)

    async def exercise():
        async with Client(build_server(app.mcp_gateway.call)) as client:
            tools = await client.list_tools()
            assert "ha_create_project" in [t.name for t in tools.tools]
            response = await client.call_tool(
                "ha_create_project",
                {"name": "sdk", "objective": "test", "request_id": "sdk"},
            )
            assert not response.is_error
            result = response.structured_content
            assert result["status"] == "paused"
            goal = await client.call_tool(
                "ha_goal", {"task": result["id"], "action": "status"}
            )
            assert goal.structured_content["goal"]["objective"] == "test"
            assert app.store.task(result["id"])["status"] == "paused"
            started = await client.call_tool(
                "ha_goal", {"task": result["id"], "action": "start"}
            )
            assert not started.is_error
            assert app.store.task(result["id"])["status"] == "queued"
            paused = await client.call_tool(
                "ha_goal", {"task": result["id"], "action": "pause"}
            )
            assert paused.structured_content["goal"]["status"] == "paused"
            limited = await client.call_tool(
                "ha_goal", {"task": result["id"], "action": "budget", "max_turns": 0}
            )
            assert limited.structured_content["goal"]["unlimited"]
            assert limited.structured_content["goal"]["status"] == "paused"

    asyncio.run(exercise())


def test_stdio_bridge_to_running_application(app):
    enable(app)
    server = make_server(app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:

        async def exercise():
            launch = Path(__file__).resolve().parents[1] / "_app" / "launch.py"
            params = StdioServerParameters(
                command=sys.executable,
                args=["-u", str(launch), "mcp", "--data-dir", str(app.store.root)],
            )
            async with Client(params) as client:
                result = await client.call_tool("ha_projects", {})
                assert not result.is_error
                assert result.structured_content == {"projects": []}

        asyncio.run(exercise())
    finally:
        server.shutdown()
        server.server_close()


def test_client_config_merge_preserves_other_connections(app, tmp_path):
    p = tmp_path / "client.json"
    p.write_text(
        json.dumps({"mcpServers": {"other": {"command": "example"}}, "keep": True})
    )
    result = app.connections.install_config(p)
    saved = json.loads(p.read_text())
    assert saved["keep"] and saved["mcpServers"]["other"]["command"] == "example"
    assert Path(result["backup"]).exists()
    assert "hivemind-assembly" in saved["mcpServers"]


def test_outbound_stdio_discovery_and_project_tool_allowlist(app, tmp_path):
    fixture = tmp_path / "mcp_fixture.py"
    fixture.write_text(
        'from mcp.server import MCPServer\ns=MCPServer("fixture")\n@s.tool()\ndef add(a:int,b:int)->dict:\n return {"sum":a+b}\ns.run()\n'
    )
    task = app.store.create_project("outbound", "test", paused=True)
    cfg = app.connections.settings()
    cfg["servers"]["fixture"] = {
        "transport": "stdio",
        "command": sys.executable,
        "args": [str(fixture)],
        "tools": ["add"],
        "projects": [task["project_id"]],
    }
    app.connections.save(cfg)
    tools = asyncio.run(app.connections.external("fixture"))
    assert tools[0]["name"] == "add"
    result = asyncio.run(
        app.connections.external("fixture", "add", {"a": 2, "b": 3}, task["project_id"])
    )
    assert json.loads(result["content"][0]["text"]) == {"sum": 5}
    with pytest.raises(Blocked):
        asyncio.run(
            app.connections.external("fixture", "add", {"a": 2, "b": 3}, "unshared")
        )


def test_http_authentication_and_endpoint_bound_session_secret(app):
    import socket
    import time
    import uvicorn

    token = "fixture-bearer-token"
    sdk = build_server(lambda tool, args: {"echo": token})
    inner = sdk.streamable_http_app(stateless_http=True, json_response=True)

    async def authenticated(scope, receive, send):
        if (
            scope["type"] == "http"
            and dict(scope["headers"]).get(b"authorization")
            != ("Bearer " + token).encode()
        ):
            await send({"type": "http.response.start", "status": 401, "headers": []})
            await send({"type": "http.response.body", "body": b"unauthorized"})
            return
        await inner(scope, receive, send)

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(authenticated, log_level="error"))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.01)
        assert server.started
        task = app.store.create_project("HTTP", "test", paused=True)
        cfg = app.connections.settings()
        cfg["servers"]["http"] = {
            "transport": "http",
            "url": f"http://127.0.0.1:{port}/mcp",
            "tools": ["ha_projects"],
            "projects": [task["project_id"]],
        }
        app.connections.save(cfg)
        app.connections.credential("http", token)
        assert token not in app.connections.path.read_text()
        assert token not in json.dumps(app.status())
        catalog = asyncio.run(app.connections.external("http"))
        assert any(t["name"] == "ha_projects" for t in catalog)
        result = asyncio.run(
            app.connections.external("http", "ha_projects", {}, task["project_id"])
        )
        assert result["structuredContent"]["echo"] == "[redacted]"
        cfg = app.connections.settings()
        cfg["servers"]["http"]["url"] += "-changed"
        app.connections.save(cfg)
        with pytest.raises(Blocked, match="different endpoint"):
            asyncio.run(
                app.connections.external("http", "ha_projects", {}, task["project_id"])
            )
        app.connections.credential("http", forget=True)
        assert not app.connections.session_credentials
    finally:
        server.should_exit = True
        thread.join(5)
        sock.close()
