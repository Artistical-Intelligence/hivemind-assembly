"""Local-only debugging grants, OAuth isolation, UI and actual Chromium controls."""
import asyncio
import base64
import json
import os
import threading
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import pytest
from mcp import Client
import test_app
from hivemind_assembly.core.common import Blocked, Conflict
from hivemind_assembly.integrations.debug_mcp import build_debug_server
from hivemind_assembly.integrations.quick_connect import Gateway, Rpc, digest

app, server = test_app.app, test_app.server
CHROME = os.environ.get("WORKBENCH_TEST_CHROME")
ROUTE = "worker.extra"


@pytest.fixture
def debug(app, monkeypatch):
    d = app.debugging
    monkeypatch.setattr(d.quick, "start", lambda: None)
    d.start([ROUTE])
    return d


def test_grant_default_off_no_project_privilege_and_identity_fence(app, debug):
    assert not app.connections.settings()["enabled"]
    assert debug.call("ha_debug_status", {})["routes"][0]["route"] == ROUTE
    with pytest.raises(Blocked):
        debug.call("ha_debug_tab", {"route": "worker.opus"})
    with pytest.raises(Exception):
        debug.call("ha_projects", {})
    app.config["routes"][ROUTE]["account_label"] = "changed@example.test"
    with pytest.raises(Blocked, match="identity changed"):
        debug.call("ha_debug_status", {})


def test_old_rpc_cannot_acquire_new_grant(debug):
    old = debug.rpc()
    debug.stop()
    with pytest.raises(Blocked):
        debug.call("ha_debug_status", {})
    debug.start([ROUTE])
    stale = old.call("ha_debug_status", {})
    assert stale["isError"]
    assert not debug.rpc().call("ha_debug_status", {}).get("isError")
    project = Rpc(lambda tool, args: {}, "test")
    assert all(not t["name"].startswith("ha_debug") for t in project.tools)
    assert project.call("ha_debug_status", {})["isError"]


def test_sdk_catalog_and_status(debug):
    async def run():
        async with Client(build_debug_server(debug.call)) as client:
            inventory = await client.list_tools()
            assert {t.name for t in inventory.tools} == {"ha_debug_status", "ha_debug_tab", "ha_debug_screenshot", "ha_debug_action"}
            result = await client.call_tool("ha_debug_status", {})
            assert not result.is_error
            assert result.structured_content["routes"][0]["route"] == ROUTE
    asyncio.run(run())


def test_debug_oauth_scope_approval_and_revocation(debug):
    gateway = Gateway(debug.rpc())
    origin = "https://debug-local.trycloudflare.com"
    gateway.auth.activate(origin)
    threading.Thread(target=gateway.serve_forever, kwargs={"poll_interval": .05}, daemon=True).start()
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{gateway.server_port}", headers={"Host": urlsplit(origin).netloc}, trust_env=False) as client:
            metadata = client.get("/.well-known/oauth-authorization-server").json()
            assert metadata["scopes_supported"] == ["ha.debug", "offline_access"]
            redirect = "https://claude.ai/api/mcp/auth_callback"
            registration = client.post("/register", json={"redirect_uris": [redirect], "token_endpoint_auth_method": "none"}).json()
            params = {"client_id": registration["client_id"], "redirect_uri": redirect, "response_type": "code", "code_challenge": digest("v"*64), "code_challenge_method": "S256", "scope": "ha.projects"}
            assert client.get("/authorize?"+urlencode(params)).status_code == 400
            params["scope"] = "ha.debug offline_access"
            approval = client.get("/authorize?"+urlencode(params))
            assert "inspect the HA assistant tabs" in approval.text
            assert "use the projects you shared" not in approval.text
            flow = approval.text.split('name="flow" value="')[1].split('"')[0]
            accepted = client.post("/authorize", data={"flow": flow, "pairing_code": gateway.auth.pairing()["code"]})
            code = parse_qs(urlsplit(accepted.headers["Location"]).query)["code"][0]
            token = client.post("/token", data={"grant_type": "authorization_code", "client_id": registration["client_id"], "redirect_uri": redirect, "code": code, "code_verifier": "v"*64}).json()["access_token"]
            headers = {"Authorization": "Bearer "+token}
            request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
            assert client.post("/mcp", headers=headers, json=request).status_code == 200
            other = Gateway(Rpc(lambda t,a: {}))
            try:
                other.auth.activate("https://project-local.trycloudflare.com")
                with pytest.raises(Exception):
                    other.auth.check("Bearer "+token)
            finally:
                other.server_close()
            gateway.auth.revoke()
            assert client.post("/mcp", headers=headers, json=request).status_code == 401
    finally:
        gateway.shutdown();gateway.server_close()


def test_retry_idempotency_busy_rejection_and_stop_cancels_owned(app, debug, monkeypatch):
    calls = []
    started = threading.Event()
    async def setup(route):
        calls.append(route);started.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(app, "setup_assistant", setup)
    args = {"route": ROUTE, "action": "retry_setup", "request_id": "retry-one"}
    first = debug.call("ha_debug_action", args)
    assert started.wait(2) and first["state"] == "started"
    assert debug.call("ha_debug_action", args) == first
    with pytest.raises(Blocked, match="active"):
        debug.call("ha_debug_action", {**args, "request_id": "retry-two"})
    with pytest.raises(Conflict):
        debug.call("ha_debug_action", {**args, "action": "reload"})
    debug.stop()
    assert app.native_setup_futures[ROUTE].cancelled()
    assert calls == [ROUTE]


def test_stop_always_stops_tunnel_after_cancellation_timeout(debug, monkeypatch):
    import concurrent.futures
    class Timeout:
        def result(self, **kwargs):
            raise concurrent.futures.TimeoutError()
    def submit(coro):
        coro.close();return Timeout()
    monkeypatch.setattr(debug.app, "submit", submit)
    stopped = []
    monkeypatch.setattr(debug.quick, "stop", lambda: stopped.append(True))
    debug.stop()
    assert stopped and not debug.routes
    monkeypatch.undo()  # application teardown still needs the real event loop


@pytest.mark.skipif(not CHROME, reason="Requires Chromium")
def test_real_tab_control_map_excludes_messages_and_recovers_popup(app, debug):
    from playwright.async_api import async_playwright
    async def run():
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
            context = await browser.new_context()
            body = '''<button>Open menu</button><div data-user-message-bubble="true"><button>PRIVATE MESSAGE</button></div><div role="menu"><div role="menuitem"><span>owner@example.com</span></div></div><button data-testid="user-menu-button">Owner Max</button><input value="PRIVATE INPUT"><div role="dialog"><button onclick="this.parentElement.remove()">Cancel</button></div>'''
            await context.route("**/*", lambda r: r.fulfill(body=body, content_type="text/html"))
            page = await context.new_page();await page.goto("https://chatgpt.com/")
            app.browser.pages[ROUTE] = page
            try:
                result = await debug.execute("ha_debug_tab", {"route": ROUTE}, debug.epoch)
                assert base64.b64decode(result["jpeg"]).startswith(b"\xff\xd8")
                assert len(context.pages) == 1
                text = json.dumps(result["controls"])
                assert "Open menu" in text and "Cancel" in text
                assert all(secret not in text for secret in ("PRIVATE", "owner@", "Owner Max"))
                args = {"route": ROUTE, "action": "dismiss_popup", "request_id": "dismiss"}
                assert (await debug.execute("ha_debug_action", args, debug.epoch))["state"] == "completed"
                assert not await page.locator('[role=dialog]').count()
                await page.set_content('<div role="dialog">You have reached your monthly spend limit<button onclick="window.spent=true">Remove limit</button></div>')
                held = await debug.execute("ha_debug_action", {**args, "request_id": "quota"}, debug.epoch)
                assert held["error"] == "AllowanceUnavailable"
                assert not await page.evaluate("!!window.spent")
                await page.goto("https://chatgpt.com/settings")
                with pytest.raises(Blocked):
                    await debug.execute("ha_debug_tab", {"route": ROUTE}, debug.epoch)
            finally:
                app.browser.pages.pop(ROUTE, None)
                await browser.close()
    app.submit(run()).result(timeout=40)


@pytest.mark.skipif(not CHROME, reason="Requires Chromium")
def test_debug_dashboard_connection_code_and_stop(server, app, monkeypatch):
    from playwright.sync_api import sync_playwright, expect
    d = app.debugging
    def start():
        d.quick.state = "ready";d.quick.origin = "https://debug-local.trycloudflare.com"
    monkeypatch.setattr(d.quick, "start", start)
    monkeypatch.setattr(d.quick, "pairing", lambda: {"code": "LOCAL-CODE", "expires_in": 600})
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        page = browser.new_page();errors=[];page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{server.server_port}/#{app.token}")
        page.locator('[data-tab="settings"]').click()
        expect(page.locator('#debug-routes input')).to_have_count(len(app.config["routes"]))
        page.locator('#debug-card summary').click()
        page.locator('#debug-start').click()
        expect(page.locator('#debug-address')).to_have_value("https://debug-local.trycloudflare.com/mcp")
        page.locator('#debug-code-show').click()
        expect(page.locator('#debug-code')).to_have_text("LOCAL-CODE")
        page.locator('#debug-stop').click()
        expect(page.locator('#debug-status')).to_contain_text("Debugging is off")
        expect(page.locator('#debug-code')).to_be_hidden()
        assert not errors and not app.connections.settings()["enabled"]
        browser.close()


def test_stop_cancels_admitted_operation_and_start_waits(app, debug, monkeypatch):
    entered = threading.Event()
    cancelled = threading.Event()
    async def operation(tool, args, epoch):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    monkeypatch.setattr(debug, "_execute", operation)
    future = app.submit(debug.execute("ha_debug_tab", {"route": ROUTE}, debug.epoch))
    assert entered.wait(2)
    original = debug.quick.stop
    def stop():
        with pytest.raises(Blocked, match="stopping"):
            debug.start([ROUTE])
        return original()
    monkeypatch.setattr(debug.quick, "stop", stop)
    debug.stop()
    assert cancelled.wait(2) and future.cancelled()
