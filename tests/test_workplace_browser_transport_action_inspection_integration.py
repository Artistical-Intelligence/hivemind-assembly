"""Source-integrated HA browser action inspection races (no real website).

These synthetic BrowserActions fixtures must run against the complete HA package;
syntax-only validation of this file is not executed integration acceptance.
"""
import asyncio
from contextlib import asynccontextmanager

import pytest

from hivemind_assembly.automation.browser_actions import BrowserActions, IDENTITY


IDENT = {
    'tag': 'BUTTON', 'type': '', 'id': '', 'name': '',
    'label': 'Confirm', 'text': 'Confirm', 'connected': True,
}


class FakeBrowser:
    def __init__(self):
        self.config = {'routes': {'authorized-route': {'profile': 'fixture'}}}

    @asynccontextmanager
    async def profile_lock(self, profile):
        assert profile == 'fixture'
        yield


class FakePage:
    url = 'https://example.invalid/setup'

    def is_closed(self):
        return False


class FakeElement:
    def __init__(self, browser, revoke_at=None, metadata='Confirm'):
        self.browser = browser
        self.revoke_at = revoke_at
        self.metadata = metadata
        self.calls = []

    async def inspect(self, stage, result):
        self.calls.append(stage)
        await asyncio.sleep(0)
        if self.revoke_at == stage:
            self.browser.config['routes'].clear()
        return result

    async def evaluate(self, script):
        if script == IDENTITY:
            return await self.inspect('identity', dict(IDENT))
        return await self.inspect('metadata', self.metadata)

    async def is_visible(self):
        return await self.inspect('visible', True)

    async def is_enabled(self):
        return await self.inspect('enabled', True)

    async def click(self, **kwargs):
        self.calls.append('click')


def prepare(tmp_path, revoke_at=None, metadata='Confirm'):
    browser = FakeBrowser()
    actions = BrowserActions(browser, tmp_path)
    element = FakeElement(browser, revoke_at, metadata)
    actions.sessions['fixture-session'] = {
        'page': FakePage(), 'profile': 'fixture',
        'origin': 'https://example.invalid', 'snapshot': 'fixture-snapshot',
        'handles': {'1': (element, dict(IDENT))},
    }
    request = {
        'action': 'click', 'operation_id': 'inspect-' + str(revoke_at or 'valid') + '-01',
        'session': 'fixture-session', 'snapshot': 'fixture-snapshot', 'ref': '1',
    }
    return actions, element, request


@pytest.mark.parametrize('revoke_at,expected_calls', [
    ('identity', ['identity']),
    ('visible', ['identity', 'visible']),
    ('enabled', ['identity', 'visible', 'enabled']),
    ('metadata', ['identity', 'visible', 'enabled', 'metadata']),
])
def test_revocation_during_inspection_stops_subsequent_dom_work_and_replay(
        tmp_path, revoke_at, expected_calls):
    actions, element, request = prepare(tmp_path, revoke_at)
    result = asyncio.run(actions.run(request))
    assert result['ok'] is False
    assert result['error']['code'] == 'NEED_ATTENTION'
    assert element.calls == expected_calls
    assert actions.receipts[request['operation_id']]['state'] == 'uncertain'
    assert actions.sessions['fixture-session']['snapshot'] is None
    assert actions.sessions['fixture-session']['handles'] == {}
    replay = asyncio.run(actions.run(request))
    assert replay['ok'] is False
    assert replay['error']['code'] == 'UNCERTAIN'
    assert element.calls == expected_calls


def test_authorized_inspection_still_dispatches_once(tmp_path):
    actions, element, request = prepare(tmp_path)
    first = asyncio.run(actions.run(request))
    assert first['ok'] is True
    assert first['items'][0]['outcome'] == 'dispatched'
    assert first['items'][0]['verification'] == 'read_page_required'
    assert element.calls == ['identity', 'visible', 'enabled', 'metadata', 'click']
    assert asyncio.run(actions.run(request)) == first
    assert element.calls.count('click') == 1


@pytest.mark.parametrize('metadata', [None, 'api_token'])
def test_invalid_or_sensitive_metadata_blocks_dispatch(tmp_path, metadata):
    actions, element, request = prepare(tmp_path, metadata=metadata)
    result = asyncio.run(actions.run(request))
    assert result['ok'] is False
    assert 'click' not in element.calls
    assert actions.receipts[request['operation_id']]['state'] == 'uncertain'
