"""Lifecycle/concurrency regressions; these fixtures are not live acceptance."""
import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

from hivemind_assembly.automation.native import NativeBrowser
from hivemind_assembly.automation.onboarding import NativeSetup
from hivemind_assembly.core.controller import Controller


class Page:
    def __init__(self, context=None, url='https://chatgpt.com/'):
        self.context, self.url, self.closed = context, url, False

    def is_closed(self):
        return self.closed

    async def close(self):
        self.closed = True

    def get_by_role(self, *args, **kwargs):
        return SimpleNamespace(count=AsyncMock(return_value=0))

    def locator(self, *args):
        return SimpleNamespace(count=AsyncMock(return_value=0))


class Context:
    def __init__(self):
        self.handlers = {}
        self.pages = []
        self.browser = None

    def on(self, event, callback):
        self.handlers[event] = callback


def config():
    return {'routes': {'worker.extra': {
        'profile': 'openai', 'provider': 'openai', 'mode': 'chat',
        'model': 'GPT-6', 'effort': 'Extra High', 'allowed_hosts': ['chatgpt.com'],
        'conversation_url': '', 'usage': {},
    }}}


def test_context_close_invalidates_shared_mapping_in_place(tmp_path):
    browser = NativeBrowser(config(), tmp_path, None)
    contexts = browser.contexts
    context = Context()
    browser.track_context('openai', context)
    page = Page(context)
    browser.pages['worker.extra'] = page
    browser.service_pages.add(page)
    browser.deep_checked['worker.extra'] = {'stale': True}
    context.handlers['close'](context)
    assert browser.contexts is contexts
    assert not contexts and not browser.pages and not browser.service_pages
    assert not browser.deep_checked


def test_disconnect_uses_captured_contexts_after_browser_empties_them(tmp_path):
    browser = NativeBrowser(config(), tmp_path, None)
    owner = SimpleNamespace(contexts=[])
    old = Context()
    new = Context()
    browser.contexts.update(openai=old, claude=new)
    browser.owner_browser = owner
    browser.forget_owner(owner, (old,))
    assert browser.owner_browser is None
    assert browser.contexts == {'claude': new}


def test_draft_context_reconnects_through_owner(tmp_path):
    async def run():
        root = NativeBrowser(config(), tmp_path, None)
        root.context = AsyncMock(return_value=Context())
        draft = NativeBrowser(config(), tmp_path, None)
        draft.transport_owner = root
        assert await draft.context('openai') is root.context.return_value
        root.context.assert_awaited_once_with('openai', service=False)
    asyncio.run(run())


def test_setup_serializes_same_profile_but_allows_other_profiles(store, tmp_path):
    async def run():
        cfg = config()
        for name in ('reviewer', 'other'):
            cfg['routes'][name] = copy.deepcopy(cfg['routes']['worker.extra'])
        cfg['routes']['other']['profile'] = 'second-account'
        setup = NativeSetup(NativeBrowser(cfg, tmp_path, Controller(store)), store, tmp_path/'config.json')
        active, maximum, total = {}, {}, []
        async def step(route):
            profile = cfg['routes'][route]['profile']
            active[profile] = active.get(profile, 0) + 1
            maximum[profile] = max(maximum.get(profile, 0), active[profile])
            total.append(sum(active.values()))
            await asyncio.sleep(0.01)
            active[profile] -= 1
            return {'stage': 'waiting_quota'}
        setup._step = step
        await asyncio.gather(*(setup.step(route) for route in cfg['routes']))
        assert maximum == {'openai': 1, 'second-account': 1}
        assert max(total) == 2
        assert not any(lock.locked() for lock in setup.profile_locks.values())
    asyncio.run(run())


def test_six_routes_share_discovery_but_none_inherit_acceptance(store, tmp_path, monkeypatch):
    async def run():
        cfg = config()
        original = cfg['routes'].pop('worker.extra')
        cfg['routes'] = {f'worker.{i}': copy.deepcopy(original) for i in range(6)}
        browser = NativeBrowser(cfg, tmp_path, Controller(store))
        page = Page()
        browser.service_page = AsyncMock(return_value=page)
        setup = NativeSetup(browser, store, tmp_path/'config.json')
        monkeypatch.setattr('hivemind_assembly.automation.onboarding.discover',
                            AsyncMock(return_value={'missing': ['model']}))
        results = await asyncio.gather(*(setup.step(route) for route in cfg['routes']))
        assert browser.service_page.await_count == 1
        assert all(result['stage'] == 'binding_required' for result in results)
        assert all(not item['conversation_url'] for item in cfg['routes'].values())
    asyncio.run(run())


def test_closed_setup_has_two_reconnects_then_actionable_stop(store, tmp_path, monkeypatch):
    async def run():
        browser = NativeBrowser(config(), tmp_path, Controller(store))
        setup = NativeSetup(browser, store, tmp_path/'config.json')
        setup.step = AsyncMock(side_effect=RuntimeError('Locator.click: Target page, context or browser has been closed'))
        monkeypatch.setattr('hivemind_assembly.automation.onboarding.asyncio.sleep', AsyncMock())
        result = await setup.run('worker.extra')
        assert setup.step.await_count == 3
        assert result['stage'] == 'attention'
        assert 'Select Set up' in result['instruction']
        assert not store.rows('SELECT * FROM messages')
    asyncio.run(run())


def test_show_reopens_verified_chat_only_when_requested(store, tmp_path):
    async def run():
        cfg = config()
        cfg['routes']['worker.extra']['conversation_url'] = 'https://chatgpt.com/c/verified'
        browser = NativeBrowser(cfg, tmp_path, Controller(store))
        page = SimpleNamespace(bring_to_front=AsyncMock())
        browser.page = AsyncMock(return_value=page)
        setup = NativeSetup(browser, store, tmp_path/'config.json')
        assert await setup.show('worker.extra')
        browser.page.assert_awaited_once_with('worker.extra')
        page.bring_to_front.assert_awaited_once()
    asyncio.run(run())
