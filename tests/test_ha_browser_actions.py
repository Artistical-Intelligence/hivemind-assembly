import asyncio
import os
import shutil
import pytest
from hivemind_assembly.automation.browser_actions import BrowserActions, origin_of
from hivemind_assembly.core.common import ContractError, Conflict

CHROME = os.environ.get('WORKBENCH_TEST_CHROME') or shutil.which('chromium') or shutil.which('google-chrome')
HTML = '''<html><body><h1>HA setup fixture</h1><label>Project name <input id="project" name="project" value="PRIVATE_INITIAL_VALUE"></label><label>API token <input id="api_token" value="DO_NOT_RETURN"></label><label>Password <input type="password" value="HIDDEN_PASSWORD"></label><textarea id="notes">PRIVATE_TEXTAREA</textarea><select id="choice" name="choice"><option>Read-only</option><option>Read and write</option></select><button id="save" onclick="window.saved=(window.saved||0)+1;document.getElementById('out').textContent='Saved'">Save settings</button><p id="out"></p></body></html>'''


@pytest.mark.parametrize('url', ['http://example.com','https://user:password@example.com','https://example.com:8443','file:///private','javascript:alert(1)'])
def test_origin_restrictions(url):
    with pytest.raises(ContractError):
        origin_of(url)


@pytest.mark.skipif(not CHROME, reason='A Chromium binary is required for local DOM acceptance')
@pytest.mark.parametrize('navigate', [False, pytest.param(True, marks=pytest.mark.skipif(os.environ.get('HA_TEST_NAVIGATION') != '1', reason='Navigation acceptance runs on a supported CI browser, not a restricted runtime'))])
def test_real_dom_fill_stale_refs_secrets_and_exactly_one_dispatch(tmp_path, navigate):
    async def run():
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(executable_path=CHROME, headless=True, args=['--no-sandbox'])
            context = await browser.new_context()
            await context.route('**/*', lambda route: route.fulfill(status=200, content_type='text/html', body=HTML))
            class Native:
                config = {'routes': {'worker': {'profile':'fixture'}}}
                lock = asyncio.Lock()
                def profile_lock(self, name): return self.lock
                async def service_page(self, profile, url, allowed_hosts, prepare=None):
                    raw = await context.new_page()
                    if navigate:
                        self.page = raw
                        if prepare: await prepare(raw)
                        await raw.goto(url)
                    else:
                        # Real DOM actions without navigation. A logical test
                        # origin does not establish real network-route behavior.
                        class FixturePage:
                            def __init__(self): self.url = url
                            def __getattr__(self, name): return getattr(raw, name)
                        self.page = FixturePage()
                        await raw.set_content(HTML)
                        if prepare: await prepare(self.page)
                    return self.page
            native = Native()
            actions = BrowserActions(native, tmp_path)
            opened = await actions.run({'action':'open','operation_id':'open-fixture','profile':'fixture','url':'https://ha-fixture.invalid/setup?token=DO_NOT_RETURN_URL'})
            assert opened['ok'], opened
            session = opened['items'][0]['session']
            counter = 0
            async def read():
                nonlocal counter
                counter += 1
                result = await actions.run({'action':'read','operation_id':f'read-fixture-{counter}','session':session})
                assert result['ok'], result
                return result['items'][0]
            state = await read()
            assert all(secret not in state['text'] for secret in ['PRIVATE_INITIAL_VALUE','DO_NOT_RETURN','HIDDEN_PASSWORD','PRIVATE_TEXTAREA','DO_NOT_RETURN_URL'])
            def ref(item, name):
                return next(x['ref'] for x in item['controls'] if x['label'] == name)
            filled = await actions.run({'action':'fill','operation_id':'fill-fixture','session':session,'snapshot':state['snapshot'],'ref':ref(state,'project'),'value':'HA project'})
            assert filled['ok'], filled
            assert await native.page.locator('#project').input_value() == 'HA project'
            stale = await actions.run({'action':'click','operation_id':'stale-fixture','session':session,'snapshot':state['snapshot'],'ref':'1'})
            assert not stale['ok'] and 'stale' in stale['error']['message']
            state = await read()
            secret = await actions.run({'action':'fill','operation_id':'secret-fixture','session':session,'snapshot':state['snapshot'],'ref':ref(state,'api_token'),'value':'not-accepted'})
            assert not secret['ok']
            assert await native.page.locator('#api_token').input_value() == 'DO_NOT_RETURN'
            state = await read()
            selected = await actions.run({'action':'fill','operation_id':'select-fixture','session':session,'snapshot':state['snapshot'],'ref':ref(state,'choice'),'value':'Read and write'})
            assert selected['ok'], selected
            assert await native.page.locator('#choice').input_value() == 'Read and write'
            state = await read()
            request = {'action':'click','operation_id':'click-fixture','session':session,'snapshot':state['snapshot'],'ref':ref(state,'Save settings')}
            once = await actions.run(request)
            twice = await actions.run(request)
            assert once == twice and once['ok']
            assert await native.page.evaluate('window.saved') == 1
            with pytest.raises(Conflict):
                await actions.run({**request,'ref':'500'})
            state = await read()
            await native.page.locator('#save').evaluate('e=>e.replaceWith(e.cloneNode(true))')
            stale = await actions.run({'action':'click','operation_id':'replaced-fixture','session':session,'snapshot':state['snapshot'],'ref':ref(state,'Save settings')})
            assert not stale['ok']
            persisted = actions.path.read_text()
            assert 'HA project' not in persisted and 'DO_NOT_RETURN' not in persisted and 'PRIVATE_TEXTAREA' not in persisted
            await browser.close()
    asyncio.run(run())
