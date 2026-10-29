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
