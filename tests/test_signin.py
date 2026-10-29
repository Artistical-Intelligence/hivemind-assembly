"""Account detection is independent of model readiness; connector setup waits for it."""
import asyncio
import copy
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from hivemind_assembly.automation.signin import NativeSignIn
from hivemind_assembly.automation.surfaces import SURFACES
from test_app import app


class Page:
    url = 'https://claude.ai/new'
    closed = False

    def is_closed(self):
        return self.closed

    async def bring_to_front(self):
        pass


def test_repeated_open_reuses_tab_and_monitor(monkeypatch):
    async def scenario():
        gate = asyncio.Event()
        page = Page()
        browser = SimpleNamespace(service_page=AsyncMock(return_value=page))
        signin = NativeSignIn(browser)
        signin.watch = AsyncMock(side_effect=lambda *args: gate.wait())
        # A real async stand-in keeps the monitor pending.
        async def watch(*args):
            await gate.wait()
        signin.watch = watch
        await asyncio.gather(*(signin.open('claude', 'claude', ['claude.ai']) for _ in range(3)))
        assert browser.service_page.await_count == 1
        task = signin.tasks['claude']
        await signin.open('claude', 'claude', ['claude.ai'])
        assert signin.tasks['claude'] is task
        await signin.close()
        assert task.cancelled()
        assert signin.status('claude') == {}
    asyncio.run(scenario())


def test_signin_recovers_from_transient_menu_failure_and_is_bounded():
    async def scenario():
        signin = NativeSignIn(None)
        signin.observe = AsyncMock(side_effect=[TimeoutError(), {'stage': 'signed_in', 'account': 'owner@example.test'}])
        result = await signin.watch('claude', Page(), ['claude.ai'], attempts=3, interval=0)
        assert result['stage'] == 'signed_in'
        assert signin.observe.await_count == 2
        signin.observe = AsyncMock(return_value={'stage': 'checking'})
        result = await signin.watch('claude', Page(), ['claude.ai'], attempts=2, interval=0)
        assert result['stage'] == 'attention'
        assert signin.observe.await_count == 2
        page = Page(); page.closed = True
        assert (await signin.watch('claude', page, ['claude.ai']))['stage'] == 'attention'
    asyncio.run(scenario())


@pytest.mark.skipif(not os.environ.get('WORKBENCH_TEST_CHROME'), reason='Requires Chromium')
@pytest.mark.parametrize('provider', ['openai', 'claude'])
def test_account_detected_without_model_picker_and_cleared_on_login(provider):
    from playwright.async_api import async_playwright
    from test_surfaces import CHATGPT, CLAUDE

    async def scenario():
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(executable_path=os.environ['WORKBENCH_TEST_CHROME'], args=['--no-sandbox'])
            page = await browser.new_page()
            host = 'chatgpt.com' if provider == 'openai' else 'claude.ai'
            await page.route('https://' + host + '/**', lambda r: r.fulfill(body=CHATGPT if provider == 'openai' else CLAUDE, content_type='text/html'))
            await page.goto('https://' + host + '/new')
            await page.locator(SURFACES[provider].picker).evaluate('(e) => e.remove()')
            signin = NativeSignIn(None)
            result = await signin.observe(provider, page, [host])
            assert result['stage'] == 'signed_in', result
            assert '@' in result['account']
            # Positive account evidence is required, not just absence of a login form.
            await page.set_content('<p>Loading</p>')
            assert (await signin.observe(provider, page, [host]))['account'] == ''
            await page.set_content('<button>Sign in</button>')
            assert (await signin.observe(provider, page, [host]))['stage'] == 'authentication'
            assert signin.status(provider)['account'] == ''
            await page.goto('https://' + host + '/login')
            assert (await signin.observe(provider, page, [host]))['stage'] == 'authentication'
            await browser.close()
    asyncio.run(scenario())


def test_observed_account_does_not_rebind_routes_or_claim_readiness(app):
    before = copy.deepcopy(app.config)
    app.native_signin.save('claude', 'signed_in', 'owner@example.test')
    status = next(s for s in app.services_status() if s['provider'] == 'claude')
    assert status['account'] == 'owner@example.test'
    assert app.config == before
    app.native_signin.save('claude', 'authentication')
    status = next(s for s in app.services_status() if s['provider'] == 'claude')
    assert status['account'] == '' and status['waiting']


def test_automated_connector_waits_for_signin_then_runs_once(app, monkeypatch):
    async def scenario():
        gate = asyncio.Event()
        async def watch():
            await gate.wait()
            return {'stage': 'signed_in', 'account': 'owner@example.test'}
        async def open_signin(*args):
            app.native_signin.tasks['claude'] = asyncio.create_task(watch())
        monkeypatch.setattr(app.native_signin, 'open', open_signin)
        started = []
        connection = SimpleNamespace(start=lambda: started.append('start'), status=lambda: {'state': 'ready'})
        monkeypatch.setattr(app, 'connection', lambda: connection)
        monkeypatch.setattr(app, 'ensure_access', lambda: started.append('access'))
        monkeypatch.setattr(app.auto_reconnect, 'run', AsyncMock())
        task = asyncio.create_task(app.connect_provider('Claude'))
        await asyncio.sleep(0)
        assert started == []
        assert app.auto_reconnect.state['Claude']['stage'] == 'working'
        gate.set(); await task
        assert started == ['access', 'start']
        app.auto_reconnect.run.assert_awaited_once_with('Claude')
        assert app.auto_reconnect.providers() == ['Claude']
    app.submit(scenario()).result(5)


def test_unconfirmed_signin_never_creates_connector(app, monkeypatch):
    async def scenario():
        async def open_signin(*args):
            app.native_signin.tasks['claude'] = asyncio.create_task(asyncio.sleep(0, result={'stage': 'attention', 'message': 'No account found'}))
        monkeypatch.setattr(app.native_signin, 'open', open_signin)
        create = AsyncMock()
        monkeypatch.setattr(app.auto_reconnect, 'run', create)
        await app.connect_provider('Claude')
        create.assert_not_awaited()
        assert app.auto_reconnect.state['Claude']['stage'] == 'manual'
        assert app.auto_reconnect.providers() == []
    app.submit(scenario()).result(5)
