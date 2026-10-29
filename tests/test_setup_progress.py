"""Setup stall regressions; local fixtures do not prove live account acceptance."""
import asyncio
import json
import os
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import test_app
from test_setup_recovery import config
from test_startup_handoff import make_team
from hivemind_assembly.automation.native import NativeBrowser
from hivemind_assembly.automation.onboarding import NativeSetup
from hivemind_assembly.automation.sessions import Sessions
from hivemind_assembly.automation.team import NativeTeam
from hivemind_assembly.core.common import Blocked, digest
from hivemind_assembly.core.controller import Controller

app, server = test_app.app, test_app.server


def test_recovery_deadline_releases_account_and_preserves_uncertain_delivery(store, tmp_path, monkeypatch):
    from hivemind_assembly.automation import sessions as module
    monkeypatch.setattr(module, 'RECOVERY_SECONDS', 0.2)
    monkeypatch.setattr(module, 'request_echo', AsyncMock(return_value=None))
    monkeypatch.setattr(NativeBrowser, 'exchange', AsyncMock(side_effect=AssertionError('Must not send')))

    async def run():
        controller = Controller(store)
        root = NativeBrowser(config(), tmp_path, controller)
        route = 'worker.extra'
        key = 'session_' + digest({'route': route, 'previous': 'https://chatgpt.com/'})[:32]
        message = controller.prepare_message('session_setup', route, 'https://chatgpt.com/', {'saved': 'request'}, message_id=key)
        controller.message_state(key, 'delivery_uncertain')
        before = dict(store.one('SELECT * FROM messages WHERE id=?', (key,)))
        entered = asyncio.Event()
        class Page:
            url = 'https://chatgpt.com/'
            closed = False
            def locator(self, *args): return self
            @property
            def first(self): return self
            async def evaluate_all(self, *args): return ['https://chatgpt.com/c/original']
            async def goto(self, url, **kwargs):
                self.url = url
                entered.set()
                await asyncio.Event().wait()
            async def close(self): self.closed = True
        home, probe = Page(), Page()
        root.contexts['openai'] = SimpleNamespace(pages=[home], new_page=AsyncMock(return_value=probe))
        sessions = Sessions(root, tmp_path/'config.json')
        lock = root.dispatch_lock(route)
        await lock.acquire()
        task = asyncio.create_task(sessions.renew('session_setup', route))
        await asyncio.sleep(0)
        assert 'Waiting for another assistant' in sessions.progress[route]['instruction']
        lock.release()
        await entered.wait()
        assert 'Checking saved setup chat 1 of 1' in sessions.progress[route]['instruction']
        with pytest.raises(Blocked, match='time limit.*original setup conversation.*No request was resent'):
            await asyncio.wait_for(task, 2)
        assert not lock.locked()
        assert probe.closed and not home.closed
        assert before == dict(store.one('SELECT * FROM messages WHERE id=?', (key,)))
        assert message['payload'] == before['payload']
        NativeBrowser.exchange.assert_not_awaited()
        assert root.config == config()
    asyncio.run(run())


def test_progress_keeps_phase_start_and_never_masks_attention(store, tmp_path, monkeypatch):
    from hivemind_assembly.automation import sessions as module
    root = NativeBrowser(config(), tmp_path, Controller(store))
    sessions = Sessions(root, tmp_path/'config.json')
    setup = NativeSetup(root, store, tmp_path/'config.json', sessions=sessions)
    route = 'worker.extra'
    monkeypatch.setattr(module.time, 'time', lambda: 100)
    setup.save(route, stage='ready_for_session', instruction='Old stage label')
    sessions.report(route, 'Checking saved delivery and waiting for the setup reply.')
    monkeypatch.setattr(module.time, 'time', lambda: 200)
    sessions.report(route, 'Checking saved delivery and waiting for the setup reply.')
    assert setup.progress(route)['since'] == 100
    assert 'waiting for the setup reply' in setup.progress(route)['instruction']
    sessions.report(route, 'Verifying returned file.')
    assert setup.progress(route)['since'] == 200
    setup.save(route, stage='attention', instruction='Open the original conversation.')
    assert setup.progress(route)['instruction'] == 'Open the original conversation.'


@pytest.mark.parametrize('reset,later,cleared', [
    ({'stage': 'not_started', 'instruction': 'Its model changed; setting it up again.'}, False, True),
    ({'stage': 'not_started', 'reset_allowance': True}, False, True),
    ({'stage': 'not_started', 'instruction': 'Retry setup'}, False, False),
    ({'stage': 'not_started', 'reset_allowance': False}, False, False),
    ({'stage': 'not_started', 'reset_allowance': True}, True, False),
])
def test_restart_replays_target_reset_without_erasing_account_poll(store, reset, later, cleared):
    team = make_team(store)
    route = 'worker.opus'
    team.block_allowance(route, 'Account exhausted')
    polls = [dict(row) for row in store.rows('SELECT * FROM polls')]
    observation = team.observations[route]
    store.put('native_setup:'+route, 'reset', reset)
    if later:
        store.put('availability', 'after-reset', asdict(observation))
    restarted = NativeTeam(team.controller, team.broker, team.browser, team.config)
    assert (route not in restarted.observations) == cleared
    assert [dict(row) for row in store.rows('SELECT * FROM polls')] == polls
    if not cleared:
        assert restarted.exhausted(route)
        assert restarted.poll_interval([route]) == 86400


def test_target_change_persists_allowance_reset_and_same_target_retains_quota(app):
    route = 'worker.opus'
    cfg = app.config['routes'][route]
    target = {key: cfg[key] for key in ('provider', 'mode', 'model', 'effort')}
    app.team.block_allowance(route, 'Old account exhausted')
    assert asyncio.run(app.apply_targets({route: target})) == []
    assert app.team.exhausted(route)
    target.update(provider='openai', mode='Work', model='GPT-6 Astra', effort='High')
    assert asyncio.run(app.apply_targets({route: target})) == [route]
    assert app.native_setup.status(route)['reset_allowance'] is True
    assert route not in app.team.observations
    restarted = NativeTeam(app.controller, app.broker, app.browser, app.config)
    assert route not in restarted.observations
    assert json.loads(app.config_path.read_text())['routes'][route]['model'] == 'GPT-6 Astra'


@pytest.mark.skipif(not os.environ.get('WORKBENCH_TEST_CHROME'), reason='Requires Chromium')
def test_dashboard_shows_actual_phase_and_then_actionable_attention(server, app):
    from playwright.sync_api import sync_playwright, expect
    route = 'worker.extra'
    app.native_setup.save(route, stage='ready_for_session')
    app.sessions.report(route, 'Checking saved setup chat 2 of 8; search budget is 45 seconds.')
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ['WORKBENCH_TEST_CHROME'], args=['--no-sandbox'])
        page = browser.new_page()
        page.goto(f'http://127.0.0.1:{server.server_port}/#{app.token}')
        page.locator('[data-tab="routes"]').click()
        row = page.locator(f'tr[data-route="{route}"]')
        expect(row).to_contain_text('Checking saved setup chat 2 of 8')
        expect(row).not_to_contain_text('Starting its own conversation')
        app.native_setup.save(route, stage='attention', instruction='Open the original conversation. No request was resent.')
        page.evaluate('refresh()')
        expect(row).to_contain_text('Open the original conversation. No request was resent.')
        expect(row).not_to_contain_text('Checking saved setup chat')
        browser.close()
