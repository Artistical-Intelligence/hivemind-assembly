"""Primary MCP tab access stays explicitly granted, revocable and inspectable."""
import asyncio
import base64

import pytest
from mcp import Client
import test_app
from hivemind_assembly.core.common import Blocked, ContractError
from hivemind_assembly.integrations.mcp import build_server
from hivemind_assembly.integrations.quick_connect import Rpc

app = test_app.app
ROUTE = "worker.extra"


def enable(app):
    app.connections.save({"enabled": True, "allow_create": False, "projects": [], "servers": {}})


def test_health_is_available_without_project_or_tab_access(app):
    result = app.mcp_gateway.call("ha_connection_status", {})
    assert result["state"] == "disabled"
    assert not result["project_access_enabled"] and not result["tab_access_enabled"]
    assert "projects" not in result and "routes" not in result
    rpc = Rpc(app.mcp_gateway.call, "test")
    assert not rpc.call("ha_connection_status", {}).get("isError")
    blocked = rpc.call("ha_projects", {})
    assert blocked["isError"] and "Enable MCP" in str(blocked)


def test_separate_debug_grant_does_not_enable_primary_then_opt_in_and_revoke(app, monkeypatch):
    debug = app.debugging
    monkeypatch.setattr(debug.quick, "start", lambda: None)
    enable(app)
    debug.start([ROUTE])
    with pytest.raises(Blocked, match="primary connection"):
        app.mcp_gateway.call("ha_debug_status", {})
    with pytest.raises(Blocked, match="Stop debugging"):
        debug.start([ROUTE], primary_connection=True)
    debug.stop()
    debug.start([ROUTE], primary_connection=True)
    status = app.mcp_gateway.call("ha_debug_status", {})
    assert status["primary_connection_enabled"]
    assert [r["route"] for r in status["routes"]] == [ROUTE]
    assert not status["routes"][0]["tab_open"]
    with pytest.raises(Blocked):
        app.mcp_gateway.call("ha_debug_tab", {"route": "worker.opus"})
    with pytest.raises(Blocked, match="screenshots"):
        app.mcp_gateway.call("ha_debug_screenshot", {"route": ROUTE})
    debug.stop()
    assert not app.mcp_gateway.call("ha_connection_status", {})["tab_access_enabled"]
    with pytest.raises(Blocked):
        app.mcp_gateway.call("ha_debug_status", {})


def test_primary_grant_requires_boolean(app):
    with pytest.raises(ContractError):
        app.debugging.start([ROUTE], primary_connection="true")


@pytest.mark.parametrize("raw", ['{bad json', '{}', '[]', '{"enabled": true, "allow_create": false, "projects": null, "servers": {}}'])
def test_invalid_settings_have_actionable_diagnostic_without_overwrite(app, raw):
    app.connections.path.parent.mkdir(exist_ok=True, parents=True)
    app.connections.path.write_text(raw)
    try:
        status = app.mcp_gateway.call("ha_connection_status", {})
        assert status["state"] == "settings_error" and "Connections" in status["message"]
        result = Rpc(app.mcp_gateway.call).call("ha_projects", {})
        assert result["isError"] and "Connections" in str(result)
        assert app.connections.path.read_text() == raw
    finally:
        app.connections.path.unlink()


def test_main_sdk_transports_real_image_blocks(app, monkeypatch):
    enable(app)
    image = base64.b64encode(b"jpeg-fixture").decode()
    calls = []
    def capture(tool, arguments):
        calls.append((tool, arguments))
        return {"route": ROUTE, "jpeg": image, "image_kind": "real provider viewport"}
    monkeypatch.setattr(app.debugging, "call_primary", capture)
    async def run():
        async with Client(build_server(app.mcp_gateway.call)) as client:
            tools = await client.list_tools()
            assert {"ha_connection_status", "ha_debug_status", "ha_debug_tab", "ha_debug_screenshot", "ha_debug_action"} <= {t.name for t in tools.tools}
            result = await client.call_tool("ha_debug_screenshot", {"route": ROUTE, "ocr": False})
            assert not result.is_error
            pictures = [c for c in result.content if c.type == "image"]
            assert len(pictures) == 1 and pictures[0].data == image
    asyncio.run(run())
    assert calls == [("ha_debug_screenshot", {"route": ROUTE, "ocr": False})]


def test_closed_tab_inventory_and_post_action_observation(app, monkeypatch):
    debug = app.debugging
    monkeypatch.setattr(debug.quick, "start", lambda: None)
    debug.start([ROUTE])
    class Page:
        url = "https://chatgpt.com/"
        closed = True
        shown = 0
        def is_closed(self):
            return self.closed
        async def bring_to_front(self):
            self.shown += 1
    page = Page()
    monkeypatch.setattr(app.native_setup, "display_page", lambda route: page)
    status = debug.call("ha_debug_status", {})
    assert not status["routes"][0]["tab_open"]
    page.closed = False
    args = {"route": ROUTE, "action": "show", "request_id": "observed-show"}
    receipt = debug.call("ha_debug_action", args)
    assert receipt["state"] == "completed" and receipt["observation"]["tab_open"]
    assert receipt["observation"]["observed"] > 0
    assert debug.call("ha_debug_action", args) == receipt
    assert page.shown == 1
