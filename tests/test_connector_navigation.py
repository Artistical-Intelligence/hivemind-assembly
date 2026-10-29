"""Connector navigation uses trusted input and preserves a failed setup for recovery."""
import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from hivemind_assembly.integrations.auto_reconnect import AutoReconnect, Stuck

CHROME = os.environ.get("WORKBENCH_TEST_CHROME")


@pytest.mark.skipif(not CHROME, reason="Requires Chromium")
@pytest.mark.parametrize("variant", ["pointerdown", "labelledby", "hidden_duplicate", "claude"])
def test_real_navigation_opens_pointer_menu_and_form(tmp_path, variant):
    from playwright.async_api import async_playwright

    async def run():
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
            page = await browser.new_page()
            provider = "Claude" if variant == "claude" else "ChatGPT"
            heading = "Connectors" if provider == "Claude" else "Plugins"
            url = "https://claude.ai/new#customize/connectors" if provider == "Claude" else "https://chatgpt.com/plugins"
            title = "Add custom connector" if provider == "Claude" else "Add custom MCP server"
            label = 'aria-labelledby="plus-label"' if variant == "labelledby" else 'aria-label="Add '+("connector" if provider == "Claude" else "plugin")+'"'
            hidden = '<div aria-hidden="true"><button aria-label="Add plugin">+</button></div>' if variant == "hidden_duplicate" else ''
            body = f'''<header><h1>{heading}</h1><span id="plus-label">+</span><button id="plus" {label} aria-haspopup="menu" aria-expanded="false">+</button></header>{hidden}
            <script>
            window.realEvents=[];
            document.querySelector('#plus').addEventListener('pointerdown', e=>{{
              if(!e.isTrusted)return;
              window.realEvents.push('menu');e.currentTarget.setAttribute('aria-expanded','true');
              document.body.insertAdjacentHTML('beforeend','<div role="menu"><button role="menuitem" id="custom">{title}</button></div>');
              document.querySelector('#custom').addEventListener('pointerdown', e=>{{
                if(!e.isTrusted)return;window.realEvents.push('form');
                document.querySelector('[role=menu]').remove();
                document.body.insertAdjacentHTML('beforeend','<div role="dialog"><h2>{title}</h2><label>Name<input></label><label>Server URL<input></label><button type="submit" onclick="window.submitted=true">Create</button></div>');
              }});
            }});
            </script>'''
            await page.route("**/*", lambda r: r.fulfill(body=body, content_type="text/html"))
            await page.goto(url)
            auto = AutoReconnect(tmp_path, None, None, None, lambda: {})
            await auto.inject(page)
            # Previous synthetic-click behavior cannot open this provider-style menu.
            await page.evaluate("globalThis.__haSetupNavigator.step()")
            assert await page.locator('[role=menu]').count() == 0
            await auto.open_form(provider, page)
            assert await page.locator('[role=dialog]').count() == 1
            assert await page.evaluate("window.realEvents") == ["menu", "form"]
            assert not await page.evaluate("!!window.submitted")
            await browser.close()
    asyncio.run(run())


@pytest.mark.skipif(not CHROME, reason="Requires Chromium")
@pytest.mark.parametrize("body,note", [
    ('<button>Add plugin</button><button>Add plugin</button>', 'More than one'),
    ('<div role="dialog"><button>Add plugin</button></div>', 'Another dialog'),
    ('<form><button type="submit">Add plugin</button></form>', 'Waiting'),
])
def test_navigation_does_not_act_on_ambiguous_overlay_or_submit(tmp_path, body, note):
    from playwright.async_api import async_playwright
    async def run():
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
            page = await browser.new_page()
            await page.route("**/*", lambda r: r.fulfill(body=body+'<script>document.addEventListener("click",()=>window.clicked=true)</script>', content_type="text/html"))
            await page.goto('https://chatgpt.com/plugins')
            auto=AutoReconnect(tmp_path,None,None,None,lambda:{})
            await auto.inject(page)
            step=await page.evaluate('globalThis.__haSetupNavigator.plan()')
            assert note in step['note']
            assert step['state'] != 'click'
            assert not await page.evaluate('!!window.clicked')
            await browser.close()
    asyncio.run(run())


@pytest.mark.skipif(not CHROME, reason="Requires Chromium")
def test_retry_budget_bounds_ignored_controls(tmp_path):
    from playwright.async_api import async_playwright
    async def run():
        async with async_playwright() as pw:
            browser=await pw.chromium.launch(executable_path=CHROME,args=['--no-sandbox'])
            page=await browser.new_page()
            await page.route('**/*',lambda r:r.fulfill(body='<button>Add plugin</button>',content_type='text/html'))
            await page.goto('https://chatgpt.com/plugins')
            auto=AutoReconnect(tmp_path,None,None,None,lambda:{})
            await auto.inject(page)
            await page.evaluate('window.clock=10000;Date.now=()=>window.clock')
            assert (await page.evaluate('globalThis.__haSetupNavigator.plan()'))['state']=='click'
            assert (await page.evaluate('globalThis.__haSetupNavigator.plan()'))['state']=='pending'
            await page.evaluate('window.clock+=1600')
            assert (await page.evaluate('globalThis.__haSetupNavigator.plan()'))['state']=='click'
            await page.evaluate('window.clock+=1600')
            assert (await page.evaluate('globalThis.__haSetupNavigator.plan()'))['state']=='blocked'
            await browser.close()
    asyncio.run(run())


@pytest.mark.parametrize("cancelled", [False, True])
def test_failed_setup_keeps_provider_page_but_cancellation_closes(tmp_path, cancelled):
    page=SimpleNamespace(url='https://chatgpt.com/plugins',wait_for_load_state=AsyncMock(),is_closed=lambda:False,close=AsyncMock(),bring_to_front=AsyncMock())
    page.context=SimpleNamespace(pages=[page])
    # Real pages are hashable; a tiny object substitutes without network or a browser.
    class Page:
        pass
    retained=Page()
    retained.__dict__.update(page.__dict__)
    retained.context=SimpleNamespace(pages=[retained])
    auto=AutoReconnect(tmp_path,SimpleNamespace(service_page=AsyncMock(return_value=retained)),lambda p:{'origin':'https://fixture.trycloudflare.com'},None,lambda:{'worker.extra':{'provider':'openai','profile':'openai','allowed_hosts':['chatgpt.com']}})
    auto.remove_old=AsyncMock()
    auto.open_form=AsyncMock(side_effect=asyncio.CancelledError() if cancelled else Stuck('Fixture menu missing'))
    async def run():
        if cancelled:
            with pytest.raises(asyncio.CancelledError):
                await auto.run('ChatGPT')
        else:
            result=await auto.run('ChatGPT')
            assert result['stage']=='manual' and 'tab stays open' in result['message']
    asyncio.run(run())
    assert retained.close.await_count == int(cancelled)
    assert retained.bring_to_front.await_count == int(not cancelled)
