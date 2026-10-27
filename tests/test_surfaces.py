"""Today's ChatGPT and Claude controls, on local stand-ins of their pages (real Chromium).

The stand-ins copy the structure seen on the live pages on 2026-10-27: roles, labels,
menus, the Power slider and the account menus. They are NOT live-provider acceptance.
"""

import asyncio
import os

import pytest

from hivemind_assembly.automation import surfaces
from hivemind_assembly.automation.providers import CONTRACTS, discover, read_usage
from hivemind_assembly.core.common import Blocked

CHROME = os.environ.get("WORKBENCH_TEST_CHROME")
pytestmark = pytest.mark.skipif(not CHROME, reason="Requires real Chromium")

MENUS = """
function closeMenus(){document.querySelectorAll('[role=menu]').forEach(m=>m.remove())}
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeMenus()});
function item(role,parts,attrs){const d=document.createElement('div');d.setAttribute('role',role);
  for(const [k,v] of Object.entries(attrs||{}))d.setAttribute(k,v);
  for(const p of parts){const s=document.createElement('span');s.textContent=p;d.append(s)}return d}
function menu(){const m=document.createElement('div');m.setAttribute('role','menu');document.body.append(m);return m}
"""

CHATGPT = """<html><body>
<button aria-pressed="false" id="chat">Chat</button><button aria-pressed="true" id="work">Work</button>
<div contenteditable="true" role="textbox" aria-label="Work with ChatGPT" id="box"></div>
<button type="button" aria-label="Select ChatGPT model" id="picker"></button>
<button aria-label="Send" type="submit" disabled>&uarr;</button>
<button aria-label="Open profile menu" id="profile">OW</button>
<script>""" + MENUS + """
const MODELS={Chat:{'GPT-6':['Instant','Medium','High','Extra High','Pro'],'GPT-5.6 Sol':['Instant','High']},
  Work:{'Default':['High'],'GPT-6.1 Sol':['Light','Medium','High'],'GPT-6 Astra':['None','Minimal','High','Extra High','Max','Ultra'],'GPT-6 Sol':['Medium','High']}};
const S={mode:'Work',model:{Chat:'GPT-6',Work:'GPT-6 Astra'},effort:{'GPT-6':4,'GPT-5.6 Sol':0,'Default':0,'GPT-6.1 Sol':0,'GPT-6 Astra':2,'GPT-6 Sol':0}};
const cur=()=>S.model[S.mode], efforts=()=>MODELS[S.mode][cur()], label=()=>efforts()[S.effort[cur()]];
function draw(){
  chat.setAttribute('aria-pressed',String(S.mode==='Chat'));work.setAttribute('aria-pressed',String(S.mode==='Work'));
  box.setAttribute('aria-label',S.mode==='Chat'?'Ask ChatGPT':'Work with ChatGPT');
  // Like the real button: a hidden "Select effort", the visible label, and every effort name at opacity 0.
  picker.innerHTML='<span aria-hidden="true" style="visibility:hidden">Select effort</span>'
    +(S.mode==='Work'?'<span>'+cur()+'</span>':'')+'<span>'+label()+'</span>'
    +'<span aria-hidden="true" style="opacity:0">'+efforts().map(e=>'<span>'+e+'</span>').join('')+'</span>';
}
chat.onclick=()=>{S.mode='Chat';draw()}; work.onclick=()=>{S.mode='Work';draw()};
picker.addEventListener('click',()=>{
  closeMenus();const m=menu();
  const head=item('menuitem',[cur(),label()],{'aria-label':'Select model'});m.append(head);
  const d1=document.createElement('span');d1.id='d1';const d2=document.createElement('span');d2.id='d2';d2.textContent='Use Left and Right arrow keys to adjust power';
  const power=item('menuitem',[],{'aria-label':'Power','aria-describedby':'d1 d2',tabindex:'-1'});m.append(power,d1,d2);
  const say=()=>{d1.textContent=label()+', '+(S.effort[cur()]+1)+' of '+efforts().length+'.'};say();
  power.addEventListener('keydown',e=>{const n=efforts().length;
    if(e.key==='ArrowLeft')S.effort[cur()]=Math.max(0,S.effort[cur()]-1);
    if(e.key==='ArrowRight')S.effort[cur()]=Math.min(n-1,S.effort[cur()]+1);say();draw()});
  const page=document.createElement('div');page.style.display='none';m.append(page);
  for(const name of Object.keys(MODELS[S.mode])){
    const r=item('menuitemradio',name==='Default'?['Default','Recommended set of models']:[name],{'aria-checked':String(name===cur())});
    r.onclick=()=>{S.model[S.mode]=name;closeMenus();draw()};page.append(r)}
  head.onclick=()=>{page.style.display='block'};
});
profile.addEventListener('click',()=>{closeMenus();const m=menu();
  const who=item('menuitem',[],{'aria-haspopup':'menu'});const t=document.createElement('div');t.dataset.testid='workspace-switcher-trigger';t.textContent='Owner Pro';who.append(t);m.append(who);
  m.append(item('menuitem',['Settings']));
  const open=()=>{if(document.querySelectorAll('[role=menu]').length>1)return;const sub=menu();sub.append(item('menuitem',['owner@example.com'],{'aria-disabled':'true'}),item('menuitem',['Personal account']))};
  who.addEventListener('mouseenter',open);who.addEventListener('click',open)});
draw();
</script></body></html>"""

CLAUDE = """<html><body>
<div data-testid="chat-input" contenteditable="true" role="textbox" aria-label="Write your prompt to Claude"></div>
<button aria-label="Send message" style="display:none">Send</button>
<button data-testid="model-selector-dropdown" id="picker"></button>
<button data-testid="user-menu-button" id="user">Owner Max</button>
<script>""" + MENUS + """
const MODELS=['Fable 5.1','Opus 5.5','Sonnet 5.5','Haiku 5.5'], EFFORTS=['Low','Medium','High','Extra','Max'];
const S={model:'Opus 5.5',effort:'Max'};
function draw(){picker.innerHTML='<span>'+S.model+'</span><span>'+S.effort+'</span><span>⚠</span>'}
picker.addEventListener('click',()=>{closeMenus();const m=menu();
  for(const name of MODELS){const r=item('menuitemradio',[name,'Model description'],{'aria-checked':String(name===S.model)});r.onclick=()=>{S.model=name;closeMenus();draw()};m.append(r)}
  const eff=item('menuitem',['Effort',S.effort],{'aria-haspopup':'menu'});m.append(eff,item('menuitem',['More models'],{'aria-haspopup':'menu'}));
  const open=()=>{if(document.querySelectorAll('[role=menu]').length>1)return;const sub=menu();
    for(const e of EFFORTS){const r=item('menuitemradio',e==='Medium'?[e,'Recommended']:[e],{'aria-checked':String(e===S.effort)});r.onclick=()=>{S.effort=e;closeMenus();draw()};sub.append(r)}};
  eff.addEventListener('mouseenter',open);eff.addEventListener('click',open)});
user.addEventListener('click',()=>{closeMenus();const m=menu();const h=document.createElement('span');h.dataset.testid='user-menu-header';h.textContent='owner@example.com';m.append(h,item('menuitem',['Settings']))});
draw();
</script></body></html>"""

CHATGPT_USAGE = """<html><body><h2>Plan limits</h2><p>Shared across Codex, Work, Workspace Agents, and ChatGPT for Excel.
Chat conversations are not included.</p><div><div><div><div>Weekly limit</div><div>Resets in 6d 9h</div>
<progress max="100" value="89" aria-label="Usage remaining"></progress><div>89% left</div></div></div></div></body></html>"""

CLAUDE_USAGE = """<html><body><h3 id="a">Current session</h3><div role="meter" aria-labelledby="a" aria-valuenow="4" aria-valuemin="0" aria-valuemax="100" aria-valuetext="4% used" style="height:4px"></div>
<h3 id="b">This week</h3><div role="meter" aria-labelledby="b" aria-valuenow="25" aria-valuemin="0" aria-valuemax="100" aria-valuetext="25% used" style="height:4px"></div>
<h3 id="c">Included credit</h3><div role="meter" aria-labelledby="c" aria-valuenow="0" aria-valuemin="0" aria-valuemax="100" aria-valuetext="$250 of $250 left" style="height:4px"></div>
<h3 id="d">Cowork</h3><div role="meter" aria-labelledby="d" aria-valuenow="100" aria-valuemin="0" aria-valuemax="100" aria-valuetext="100%" style="height:4px"></div></body></html>"""


def route(provider, mode, model, effort, account=""):
    return {
        "provider": provider, "mode": mode, "model": model, "effort": effort,
        "account_label": account, "selectors": {},
        "allowed_hosts": ["chatgpt.com" if provider == "openai" else "claude.ai"],
    }


def run(html, body, url="https://chatgpt.com/"):
    async def go():
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(executable_path=CHROME, headless=True, args=["--no-sandbox"])
            page = await browser.new_page()
            await page.route(url, lambda r: r.fulfill(body=html, content_type="text/html"))
            await page.goto(url)
            try:
                return await body(page)
            finally:
                await browser.close()

    return asyncio.run(go())


def test_chatgpt_switches_mode_model_and_power_exactly():
    async def body(page):
        chatgpt = surfaces.SURFACES["openai"]
        assert await surfaces.detect(page, {"provider": "openai"}) is chatgpt
        # Work shows model and effort on the button; the hidden effort names are ignored.
        assert await chatgpt.shallow(page) == {"mode": "Work", "model": "GPT-6 Astra", "effort": "High"}
        adviser = route("openai", "Chat", "GPT-6", "Extra High")
        state = await chatgpt.ensure(page, adviser)
        assert state == {"mode": "Chat", "model": "GPT-6", "effort": "Extra High"}
        # Chat shows only the effort on the button; the model needs the menu.
        assert await chatgpt.shallow(page) == {"mode": "Chat", "model": None, "effort": "Extra High"}
        reviewer = route("openai", "Chat", "GPT-6", "High")
        assert (await chatgpt.ensure(page, reviewer))["effort"] == "High"
        astra = route("openai", "Work", "GPT-6 Astra", "High")
        assert await chatgpt.ensure(page, astra) == {"mode": "Work", "model": "GPT-6 Astra", "effort": "High"}
        sol = route("openai", "Work", "GPT-6.1 Sol", "Medium")
        assert (await chatgpt.ensure(page, sol))["model"] == "GPT-6.1 Sol"
        assert not await page.locator('[role="menu"]').count()
        assert await chatgpt.account(page) == "owner@example.com"
        assert not await page.locator('[role="menu"]').count()
        # A model or effort the account doesn't offer is named, and nothing else changes.
        with pytest.raises(Blocked, match="not GPT-7"):
            await chatgpt.ensure(page, route("openai", "Work", "GPT-7", "High"))
        with pytest.raises(Blocked, match=r"offers Light, Medium, High for GPT-6.1 Sol, not Pro"):
            await chatgpt.ensure(page, route("openai", "Work", "GPT-6.1 Sol", "Pro"))
        assert (await chatgpt.deep(page))["effort"] == "Medium"

    run(CHATGPT, body)


def test_chatgpt_discovery_binds_through_the_surface_and_finds_the_controls():
    async def body(page):
        cfg = route("openai", "Chat", "GPT-6", "Extra High")
        found = await discover(page, cfg)
        assert found["missing"] == [] and found["account_label"] == "owner@example.com"
        sel = found["selectors"]
        assert sel["model"] == sel["effort"] == sel["mode"] == sel["account"] == "surface:chatgpt"
        assert sel["composer"] == CONTRACTS["openai"]["selectors"]["composer"]
        assert await page.locator(sel["composer"]).count() == 1
        assert await page.locator(sel["send"]).count() == 1
        missing = await discover(page, route("openai", "Chat", "GPT-9", "Pro"))
        assert {"model", "effort"} <= set(missing["missing"]) and "GPT-9" in missing["detail"]

    run(CHATGPT, body)


def test_claude_sets_model_and_effort_and_reads_the_account():
    async def body(page):
        claude = surfaces.SURFACES["claude"]
        assert await claude.shallow(page) == {"mode": "native", "model": "Opus 5.5", "effort": "Max"}
        opus = route("claude", "native", "Opus 5.5", "High")
        assert (await claude.ensure(page, opus))["effort"] == "High"
        sonnet = route("claude", "native", "Sonnet 5.5", "Low")
        assert await claude.ensure(page, sonnet) == {"mode": "native", "model": "Sonnet 5.5", "effort": "Low"}
        with pytest.raises(Blocked, match="not Turbo"):
            await claude.ensure(page, route("claude", "native", "Sonnet 5.5", "Turbo"))
        assert await claude.account(page) == "owner@example.com"
        found = await discover(page, opus)
        assert found["missing"] == [] and found["selectors"]["model"] == "surface:claude"
        # The send button is hidden until there is text; it only needs to exist.
        assert await page.locator(found["selectors"]["send"]).count() == 1

    run(CLAUDE, body, "https://claude.ai/new")


def test_usage_pages_as_the_sites_show_them():
    async def chatgpt(page):
        work = await read_usage(page, route("openai", "Work", "GPT-6 Astra", "High"))
        chat = await read_usage(page, route("openai", "Chat", "GPT-6", "Extra High"))
        return work, chat

    work, chat = run(CHATGPT_USAGE, chatgpt, "https://chatgpt.com/settings/usage")
    assert work == {"windows": [{"name": "Weekly limit", "remaining": 89.0}], "no_numeric_limit": False}
    # The plan limits say chat conversations are not included.
    assert chat == {"windows": [], "no_numeric_limit": True}

    async def claude(page):
        return await read_usage(page, route("claude", "native", "Opus 5.5", "High"))

    assert run(CLAUDE_USAGE, claude, "https://claude.ai/settings/usage") == {
        "windows": [{"name": "Current session", "remaining": 96.0}, {"name": "This week", "remaining": 75.0}],
        "no_numeric_limit": False,
    }
