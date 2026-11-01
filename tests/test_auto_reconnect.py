"""Automatic reconnect against a stand-in ChatGPT connector page and HA's real gateway.

The stand-in imitates the parts HA relies on (a listed old connector with a menu,
Add custom MCP server, the form, provider registration, the OAuth redirect and the
token exchange). Real ChatGPT and Claude pages can differ; HA then stops and reports.
"""

import asyncio
import base64
import hashlib
import json
import os
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from hivemind_assembly.integrations import chrome_helper
from hivemind_assembly.integrations.auto_reconnect import AutoReconnect
from hivemind_assembly.integrations.quick_connect import Gateway, Rpc

ORIGIN = "https://quiet-river-1.trycloudflare.com"
VERIFIER = "v" * 64
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).decode().rstrip("=")

PLUGINS = """<!doctype html><html><body><h1>Plugins</h1>
<div id="old" class="row"><span>Hivemind Assembly</span><button aria-label="More options" aria-haspopup="menu" onclick="menu()">…</button></div>
<div class="row"><span>Other plugin</span><button aria-label="More options" aria-haspopup="menu">…</button></div>
<button onclick="openForm()">Add custom MCP server</button>
<script>
function menu(){document.body.insertAdjacentHTML('beforeend','<div role="menu" id="m"><button role="menuitem" onclick="ask()">Delete</button></div>')}
function ask(){document.getElementById('m').remove();document.body.insertAdjacentHTML('beforeend','<div role="dialog" id="d"><p>Delete Hivemind Assembly?</p><button onclick="gone()">Delete</button><button>Cancel</button></div>')}
function gone(){document.getElementById('d').remove();document.getElementById('old').remove();window.deleted=true}
function openForm(){document.body.insertAdjacentHTML('beforeend',`<div role="dialog" id="f"><h2>Add custom MCP server</h2>
<label>Name<input id="n"></label><label>Description<input id="ds"></label><label>Server URL<input id="u"></label>
<label>Authentication<select id="a"><option>None</option><option>OAuth</option></select></label>
<label><input type="checkbox" id="c">I understand and want to continue</label><button onclick="create()">Create</button></div>`)}
async function create(){
  const url=document.getElementById('u').value, origin=new URL(url).origin;
  if(document.getElementById('a').value!=='OAuth'||!document.getElementById('c').checked||document.getElementById('n').value!=='Hivemind Assembly')throw new Error('form');
  const reg=await (await fetch(origin+'/register',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({redirect_uris:['https://chatgpt.com/connector_platform_oauth_redirect']})})).json();
  sessionStorage.setItem('client', reg.client_id); sessionStorage.setItem('origin', origin);
  location = origin+'/authorize?'+new URLSearchParams({client_id:reg.client_id,response_type:'code',
    redirect_uri:'https://chatgpt.com/connector_platform_oauth_redirect',code_challenge:'CHALLENGE',
    code_challenge_method:'S256',state:'s1',scope:'ha.projects offline_access'});
}
</script></body></html>""".replace("CHALLENGE", CHALLENGE)

CALLBACK = """<!doctype html><script>
(async()=>{const q=new URLSearchParams(location.search), origin=sessionStorage.getItem('origin');
 const r=await fetch(origin+'/token',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},
  body:new URLSearchParams({grant_type:'authorization_code',code:q.get('code'),client_id:sessionStorage.getItem('client'),
  redirect_uri:'https://chatgpt.com/connector_platform_oauth_redirect',code_verifier:'VERIFIER'})});
 document.title=r.ok?'connected':'failed'})()</script>""".replace("VERIFIER", VERIFIER)


@pytest.mark.skipif(not os.environ.get("WORKBENCH_TEST_CHROME"), reason="needs Chromium")
@pytest.mark.parametrize("name,scope", [("Hivemind Assembly", "ha.projects"), ("HA Debugging", "ha.debug")])
def test_reconnect_replaces_the_old_connector_and_approves_on_has_page(tmp_path, name, scope):
    from playwright.async_api import async_playwright

    from hivemind_assembly.integrations.debug_mcp import build_debug_server
    gateway = Gateway(Rpc(lambda t, a: {}, "1.0", scope=scope, server_factory=build_debug_server if scope == "ha.debug" else None))
    gateway.auth.activate(ORIGIN)
    threading.Thread(target=gateway.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    quick = SimpleNamespace(gateway=gateway, status=lambda: {"state": "ready", "endpoint": ORIGIN + "/mcp"})
    local = httpx.Client(base_url=f"http://127.0.0.1:{gateway.server_port}", trust_env=False)

    async def scenario():
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(executable_path=os.environ["WORKBENCH_TEST_CHROME"], args=["--no-sandbox"])
            context = await browser.new_context()

            async def provider(route):
                path = route.request.url.split("chatgpt.com", 1)[1]
                body = PLUGINS.replace("Hivemind Assembly", name).replace("ha.projects", scope) if path.startswith("/plugins") else CALLBACK
                await route.fulfill(status=200, content_type="text/html", body=body)

            async def ha(route):
                req = route.request
                headers = {k: v for k, v in req.headers.items() if k.lower() in ("content-type", "origin", "authorization")}
                headers["Host"] = ORIGIN.removeprefix("https://")
                r = await asyncio.to_thread(local.request, req.method, req.url.removeprefix(ORIGIN), headers=headers,
                                            content=req.post_data_buffer)
                if r.status_code == 303:
                    # Playwright doesn't route a fulfilled redirect's next hop; follow it in the page
                    # so the test never reaches the real chatgpt.com.
                    target = json.dumps(r.headers["location"])
                    await route.fulfill(status=200, content_type="text/html",
                                        body=f"<script>location.replace({target})</script>")
                    return
                await route.fulfill(status=r.status_code, headers={k: v for k, v in r.headers.items()
                                    if k.lower() in ("content-type", "location", "content-security-policy")} |
                                    {"Access-Control-Allow-Origin": "https://chatgpt.com"}, body=r.content)

            await context.route("https://chatgpt.com/**", provider)
            await context.route(ORIGIN + "/**", ha)

            async def service_page(profile, url, hosts):
                page = await context.new_page()
                await page.goto(url)
                return page

            auto = AutoReconnect(
                tmp_path, SimpleNamespace(service_page=service_page),
                lambda p: {**chrome_helper.details(quick, p), "name": name},
                lambda p, url, flow: chrome_helper.pair(quick, p, url, flow),
                lambda: {"worker.astra": {"provider": "openai", "profile": "openai", "allowed_hosts": ["chatgpt.com"]}},
                name=name,
                service_status=lambda p: gateway.auth.services()[p],
            )
            auto.save(["ChatGPT"])
            results = await auto.run_all()
            await browser.close()
            return results

    try:
        [result] = asyncio.run(scenario())
    finally:
        local.close()
        gateway.shutdown()
        gateway.server_close()
    assert result["stage"] == "done", result
    services = gateway.auth.services()["ChatGPT"]
    assert services.get("approved_at"), services
    assert services["authorized"], services


def test_settings_accept_only_known_providers(tmp_path):
    auto = AutoReconnect(tmp_path, None, None, None, lambda: {})
    assert auto.providers() == []
    assert auto.save(["Claude", "Claude"])["providers"] == ["Claude"]
    with pytest.raises(Exception):
        auto.save(["Gemini"])


def test_missing_signed_in_window_is_reported_not_raised(tmp_path):
    auto = AutoReconnect(tmp_path, None, lambda p: {"origin": ORIGIN}, None, lambda: {})
    result = asyncio.run(auto.run("Claude"))
    assert result["stage"] == "manual" and "No HA assistant uses Claude" in result["message"]


class SetupPage:
    def __init__(self, url="https://chatgpt.com/plugins"):
        self.url = url
        self.events = {}
        self.closed = False
        self.wait_for_load_state = AsyncMock()
        self.bring_to_front = AsyncMock()

    def on(self, event, callback):
        self.events[event] = callback

    def remove_listener(self, event, callback):
        if self.events.get(event) is callback:
            del self.events[event]

    def is_closed(self):
        return self.closed

    async def close(self):
        self.closed = True


def setup_fixture(tmp_path):
    page = SetupPage()
    page.context = SimpleNamespace(pages=[page])
    locks = {}
    browser = SimpleNamespace(
        service_page=AsyncMock(return_value=page),
        profile_lock=lambda profile: locks.setdefault(profile, asyncio.Lock()),
    )
    state = {"authorized": False}
    auto = AutoReconnect(
        tmp_path, browser, lambda p: {"origin": ORIGIN}, None,
        lambda: {"worker": {"provider": "openai", "profile": "openai", "allowed_hosts": ["chatgpt.com"]}},
        service_status=lambda p: state,
    )
    auto.remove_old = AsyncMock()
    auto.open_form = AsyncMock()
    auto.fill_and_submit = AsyncMock()
    auto.approval_page = AsyncMock(return_value=page)
    async def approve(provider, target):
        state["authorized"] = True
    auto.approve = approve
    return auto, page, state


@pytest.mark.parametrize("cancelled", [False, True])
def test_cleanup_closes_only_owned_setup_and_popups(tmp_path, cancelled):
    auto, page, _ = setup_fixture(tmp_path)
    unrelated, popup, nested_popup = SetupPage(), SetupPage(), SetupPage()

    async def submit(*args):
        # An agent tab opens while connector setup runs in the same Chrome.
        page.context.pages.extend([unrelated, popup, nested_popup])
        page.events["popup"](popup)
        popup.events["popup"](nested_popup)
        if cancelled:
            raise asyncio.CancelledError()
    auto.fill_and_submit = submit

    async def run():
        if cancelled:
            with pytest.raises(asyncio.CancelledError):
                await auto.run("ChatGPT")
        else:
            assert (await auto.run("ChatGPT"))["stage"] == "done"
    asyncio.run(run())
    assert page.closed and popup.closed and nested_popup.closed
    assert not unrelated.closed
    assert not page.events and not popup.events and not nested_popup.events


def test_authorized_service_is_reused_without_removing_connector(tmp_path):
    auto, page, state = setup_fixture(tmp_path)
    state["authorized"] = True
    result = asyncio.run(auto.run("ChatGPT"))
    assert result["stage"] == "done" and "Already connected" in result["message"]
    auto.browser.service_page.assert_not_awaited()
    auto.remove_old.assert_not_awaited()


def test_approval_without_token_exchange_is_not_success(tmp_path, monkeypatch):
    from hivemind_assembly.integrations import auto_reconnect
    auto, page, _ = setup_fixture(tmp_path)
    auto.approve = AsyncMock()
    clock = iter([0, 31])
    monkeypatch.setattr(auto_reconnect, "time", SimpleNamespace(time=lambda: 0, monotonic=lambda: next(clock)))
    result = asyncio.run(auto.run("ChatGPT"))
    assert result["stage"] == "manual" and "not completed authorization" in result["message"]
    assert not page.closed


@pytest.mark.parametrize("same_profile", [False, True])
def test_connector_setup_serializes_only_shared_profiles(tmp_path, same_profile):
    async def run():
        auto, _, _ = setup_fixture(tmp_path)
        second = AutoReconnect(tmp_path / "second", auto.browser, auto.details, None,
            lambda: {"worker": {"provider": "openai", "profile": "openai" if same_profile else "other", "allowed_hosts": ["chatgpt.com"]}})
        active = 0
        peak = 0
        started = asyncio.Event()
        release = asyncio.Event()
        async def reconnect(provider):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            started.set()
            await release.wait()
            active -= 1
        auto.reconnect = second.reconnect = reconnect
        first = asyncio.create_task(auto.run("ChatGPT"))
        await started.wait()
        other = asyncio.create_task(second.run("ChatGPT"))
        await asyncio.sleep(0)
        assert active == (1 if same_profile else 2)
        release.set()
        await asyncio.gather(first, other)
        assert peak == (1 if same_profile else 2)
    asyncio.run(run())


def test_approval_selection_ignores_unrelated_tabs(tmp_path):
    auto, _, _ = setup_fixture(tmp_path)
    unrelated = SetupPage(ORIGIN + "/authorize")
    owned = SetupPage(ORIGIN + "/authorize")
    context = SimpleNamespace(pages=[unrelated, owned])
    selected = asyncio.run(AutoReconnect.approval_page(auto, context, ORIGIN, pages={owned}))
    assert selected is owned
    unrelated.wait_for_load_state.assert_not_awaited()


def test_approval_callback_must_return_to_same_provider(tmp_path):
    auto, page, _ = setup_fixture(tmp_path)
    locator = SimpleNamespace(input_value=AsyncMock(return_value="flow"), fill=AsyncMock(), click=AsyncMock())
    page.locator = lambda selector: locator
    auto.pair = lambda *args: {"pairing_code": "code"}
    async def wait_for_url(predicate, **kwargs):
        assert not predicate("https://claude.ai/return")
        assert not predicate("http://chatgpt.com/return")
        assert predicate("https://chatgpt.com/connector_platform_oauth_redirect")
    page.wait_for_url = wait_for_url
    asyncio.run(AutoReconnect.approve(auto, "ChatGPT", page))
