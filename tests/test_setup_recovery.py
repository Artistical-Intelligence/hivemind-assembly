"""Recovery uses existing request evidence; quota dialogs never authorize spending."""
import asyncio
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from hivemind_assembly.automation.native import NativeBrowser, DeliveryPending
from hivemind_assembly.automation.sessions import Sessions
from hivemind_assembly.automation.providers import dismiss_popups
from hivemind_assembly.automation.onboarding import NativeSetup
from hivemind_assembly.core.common import Blocked, AllowanceUnavailable
from hivemind_assembly.core.controller import Controller

CHROME = os.environ.get('WORKBENCH_TEST_CHROME')


def config():
    return {'routes': {'worker.extra': {
        'provider': 'openai', 'profile': 'openai', 'account_label': 'owner@example.test',
        'allowed_hosts': ['chatgpt.com'], 'conversation_url': 'https://chatgpt.com/',
        'model': 'GPT-6', 'mode': 'Chat', 'effort': 'Extra High',
        'selectors': {'user_messages': '.user', 'composer': '#composer', 'send': '#send'},
    }}}


@pytest.mark.skipif(not CHROME, reason='Requires Chromium')
@pytest.mark.parametrize('variant', ['history', 'hint', 'same_url_tabs', 'different_chats', 'no_match', 'clipped_marker', 'incomplete', 'message_link'])
def test_recover_original_request_without_sending(store, tmp_path, variant):
    from playwright.async_api import async_playwright

    async def run():
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(executable_path=CHROME, args=['--no-sandbox'])
            context = await browser.new_context()
            requests = []
            key = 'session_existing'
            async def site(route):
                url = route.request.url
                requests.append(url)
                if url.endswith('/c/unreachable'):
                    await route.abort();return
                if url.endswith('/'):
                    body = '<nav><a href="/c/original">Setup</a><a href="https://outside.invalid/c/other">Unrelated</a></nav>'
                    if variant == 'different_chats':
                        body += '<nav><a href="/c/duplicate">Another</a></nav>'
                    if variant == 'incomplete':
                        body += '<nav><a href="/c/unreachable">Another</a></nav>'
                    if variant == 'message_link':
                        body = '<article><nav><a href="/c/original">Injected link</a></nav></article>'
                    if variant == 'hint':
                        body = 'No history links'
                else:
                    text = ('WORKBENCH_REQUEST:' + key) if variant != 'no_match' else 'Unrelated user message'
                    if variant == 'clipped_marker':
                        text += '_other'
                    body = '<div class="user">'+text+'</div><button id="send" onclick="window.sent=true">Send</button>'
                await route.fulfill(body=body, content_type='text/html')
            await context.route('**/*', site)
            home = await context.new_page();await home.goto('https://chatgpt.com/')
            if variant == 'same_url_tabs':
                for _ in range(2):
                    page=await context.new_page();await page.goto('https://chatgpt.com/c/original')
            root=NativeBrowser(config(),tmp_path,Controller(store));root.contexts['openai']=context
            sessions=Sessions(root,tmp_path/'config.json')
            if variant=='hint':
                store.put('session_candidate',key,{'route':'worker.extra','profile':'openai','conversation':'https://chatgpt.com/c/original'})
            cfg=root.config['routes']['worker.extra'];before=dict(cfg)
            if variant in ('different_chats','no_match','clipped_marker','incomplete','message_link'):
                with pytest.raises(Blocked):
                    await sessions.recover_page('worker.extra',key,cfg)
                assert len(context.pages)==1  # temporary probes were closed
            else:
                recovered=await sessions.recover_page('worker.extra',key,cfg)
                assert recovered.url=='https://chatgpt.com/c/original'
                assert not await recovered.evaluate('Boolean(window.sent)')
            assert cfg==before
            assert all(url.startswith('https://chatgpt.com/') for url in requests)
            assert store.rows('SELECT * FROM messages')==[]
            await browser.close()
    asyncio.run(run())


@pytest.mark.skipif(not CHROME, reason='Requires Chromium')
@pytest.mark.parametrize('check_allowance', [True,False])
def test_usage_dialog_closes_without_changing_spending(check_allowance):
    from playwright.async_api import async_playwright

    async def run():
        async with async_playwright() as pw:
            browser=await pw.chromium.launch(executable_path=CHROME,args=['--no-sandbox'])
            page=await browser.new_page()
            await page.set_content('''<div role="dialog" style="display:none">Old dialog</div>
              <div role="dialog" id="usage"><h2>Need more usage?</h2>
              <p>You've reached your monthly spend limit, but you still have credits.</p>
              <button onclick="window.spent=true">Remove limit</button>
              <button onclick="window.spent=true">Save</button>
              <button onclick="document.querySelector('#usage').remove()">Cancel</button></div>''')
            if check_allowance:
                with pytest.raises(AllowanceUnavailable,match='spending limit'):
                    await dismiss_popups(page,check_allowance=True)
            else:
                await dismiss_popups(page)
            assert await page.locator('#usage').count()==0
            assert not await page.evaluate('Boolean(window.spent)')
            await dismiss_popups(page,check_allowance=True)  # hidden stale dialog ignored
            await browser.close()
    asyncio.run(run())


def test_uncertain_navigation_is_saved_only_as_recovery_hint(store,tmp_path,monkeypatch):
    from hivemind_assembly.automation import native
    from hivemind_assembly.automation.webmcp import NativeUI
    controller=Controller(store);task=store.create_project('fixture','test')
    cfg=config();cfg['routes']['worker.extra']['draft_session']=True
    root=NativeBrowser(cfg,tmp_path,controller)
    page=SimpleNamespace(url='https://chatgpt.com/c/original')
    page.locator=lambda s:SimpleNamespace(fill=AsyncMock(),click=AsyncMock())
    root.page=AsyncMock(return_value=page);root.observe=AsyncMock();root.repair=AsyncMock()
    monkeypatch.setattr(native,'request_echo',AsyncMock(return_value=None))
    monkeypatch.setattr(native,'wait_request_echo',AsyncMock(side_effect=DeliveryPending('not yet')))
    monkeypatch.setattr(NativeUI,'available',AsyncMock(return_value=False))
    message=controller.prepare_message(task['id'],'worker.extra','https://chatgpt.com/',{'test':'canary'})
    async def run():
        with pytest.raises(DeliveryPending):await root.exchange('worker.extra',message)
        assert not root.dispatch_lock('worker.extra').locked()
    asyncio.run(run())
    hint=json.loads(store.one("SELECT payload FROM records WHERE kind='session_candidate' AND id=?",(message['id'],))['payload'])
    assert hint['conversation']==page.url
    assert store.rows("SELECT * FROM records WHERE kind='message_session'")==[]
    assert store.one('SELECT state FROM messages WHERE id=?',(message['id'],))['state']=='delivery_uncertain'
    assert cfg['routes']['worker.extra']['conversation_url']=='https://chatgpt.com/'


def test_show_uses_pending_session_page(store,tmp_path):
    home=SimpleNamespace(is_closed=lambda:False,bring_to_front=AsyncMock())
    draft=SimpleNamespace(is_closed=lambda:False,bring_to_front=AsyncMock())
    browser=SimpleNamespace(pages={})
    setup=NativeSetup(browser,store,tmp_path/'config.json',sessions=SimpleNamespace(setup_pages={'worker.extra':draft}))
    setup.pages['worker.extra']=home
    assert asyncio.run(setup.show('worker.extra'))
    draft.bring_to_front.assert_awaited_once();home.bring_to_front.assert_not_awaited()


def test_initial_quota_block_survives_retry_and_restart(store,tmp_path,monkeypatch):
    from test_startup_handoff import make_team
    from hivemind_assembly.automation import team as team_module
    team=make_team(store);route='worker.opus';cfg=team.config['routes'][route]
    now=2000000000.0
    monkeypatch.setattr(team_module.time,'time',lambda:now)
    team.observations.clear()
    team.block_allowance(route,'Monthly spend limit reached')
    assert team.observations[route].blocked_kind=='quota'
    scope=cfg['usage']['scope']
    assert not team.usage.claim_poll(scope,now=now+86399)
    restarted=make_team(store)
    assert restarted.observations[route].blocked_kind=='quota'
    assert not restarted.usage.claim_poll(scope,now=now+86399)
    setup=NativeSetup(team.browser,store,tmp_path/'config.json',team=team)
    team.browser.config=team.config
    team.browser.poll_usage=AsyncMock(side_effect=AssertionError('Early quota poll'))
    assert asyncio.run(setup.step(route))['stage']=='waiting_quota'
    assert restarted.usage.claim_poll(scope,now=now+86400)


def test_opening_original_chat_preserves_pending_intent_binding(store,tmp_path,monkeypatch):
    from hivemind_assembly.automation import onboarding
    cfg=config();route='worker.extra';before=cfg['routes'][route]['conversation_url']
    root=NativeBrowser(cfg,tmp_path,Controller(store))
    class Empty:
        async def count(self):return 0
    page=SimpleNamespace(url='https://chatgpt.com/c/original',is_closed=lambda:False,
                         get_by_role=lambda *a,**k:Empty(),locator=lambda *a:Empty())
    async def discovered(*args):
        return {'missing':[],'selectors':cfg['routes'][route]['selectors'],'account_label':'owner@example.test'}
    monkeypatch.setattr(onboarding,'discover',discovered)
    class Recovered(Exception):pass
    async def renew(*args):
        assert cfg['routes'][route]['conversation_url']==before
        raise Recovered()
    sessions=SimpleNamespace(pending=lambda r:[{'id':'old-setup'}],renew=renew)
    team=SimpleNamespace(observations={})
    setup=NativeSetup(root,store,tmp_path/'config.json',sessions=sessions,team=team)
    setup.pages[route]=page
    setup.allowance=AsyncMock(return_value=SimpleNamespace(eligible=lambda:True))
    with pytest.raises(Recovered):asyncio.run(setup.step(route))
    assert cfg['routes'][route]['conversation_url']==before
