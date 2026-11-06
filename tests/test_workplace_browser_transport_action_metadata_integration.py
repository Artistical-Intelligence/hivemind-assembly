"""Full-HA BrowserActions fake-page regressions; not live provider acceptance.

Requires the real HA package and dependencies. This file can be syntax-checked
in isolation, but its imports/test bodies must not be reported as executed.
"""
import asyncio
from contextlib import asynccontextmanager

import pytest

from hivemind_assembly.automation.browser_actions import BrowserActions, IDENTITY
from hivemind_assembly.automation.browser_engine.action_inspection import MAX_ACTION_METADATA_CHARS


IDENT = {'tag': 'BUTTON', 'type': '', 'id': '', 'name': '', 'label': 'Continue',
         'text': 'Continue', 'connected': True}


class Browser:
    def __init__(self):
        self.config = {'routes': {'setup': {'profile': 'fixture'}}}

    @asynccontextmanager
    async def profile_lock(self, profile):
        assert profile == 'fixture'
        yield


class Page:
    url = 'https://example.invalid/setup'

    def is_closed(self):
        return False


class Element:
    def __init__(self, browser, metadata, revoke=False):
        self.browser = browser
        self.metadata = metadata
        self.revoke = revoke
        self.calls = []

    async def evaluate(self, script):
        self.calls.append('identity' if script == IDENTITY else 'metadata')
        await asyncio.sleep(0)
        if script == IDENTITY:
            return dict(IDENT)
        if self.revoke:
            self.browser.config['routes'].clear()
        return self.metadata

    async def is_visible(self):
        self.calls.append('visible')
        return True

    async def is_enabled(self):
        self.calls.append('enabled')
        return True

    async def click(self, **kwargs):
        self.calls.append('click')


def fixture(tmp_path, metadata, revoke=False):
    browser = Browser()
    actions = BrowserActions(browser, tmp_path)
    element = Element(browser, metadata, revoke)
    actions.sessions['session'] = {
        'page': Page(), 'profile': 'fixture', 'origin': 'https://example.invalid',
        'snapshot': 'snap', 'handles': {'1': (element, dict(IDENT))},
    }
    data = {'action': 'click', 'operation_id': 'action-meta-001',
            'session': 'session', 'snapshot': 'snap', 'ref': '1'}
    return actions, element, data


@pytest.mark.parametrize('metadata', [
    'x' * (MAX_ACTION_METADATA_CHARS + 1), 'unexpected\x00attribute',
])
def test_malformed_action_metadata_refuses_effect_and_replay(tmp_path, metadata):
    actions, element, data = fixture(tmp_path, metadata)
    first = asyncio.run(actions.run(data))
    assert first['ok'] is False
    assert first['error']['code'] == 'NEED_ATTENTION'
    assert actions.receipts[data['operation_id']]['state'] == 'uncertain'
    assert 'click' not in element.calls
    assert asyncio.run(actions.run(data))['error']['code'] == 'UNCERTAIN'
    assert 'click' not in element.calls


def test_action_metadata_at_exact_boundary_still_clicks_once(tmp_path):
    actions, element, data = fixture(tmp_path, 'x' * MAX_ACTION_METADATA_CHARS)
    first = asyncio.run(actions.run(data))
    assert first['ok'] is True
    assert first['items'][0]['outcome'] == 'dispatched'
    assert element.calls.count('click') == 1
    assert asyncio.run(actions.run(data)) == first
    assert element.calls.count('click') == 1


def test_route_revocation_during_oversized_metadata_takes_precedence(tmp_path):
    actions, element, data = fixture(tmp_path, 'x' * (MAX_ACTION_METADATA_CHARS + 1), revoke=True)
    first = asyncio.run(actions.run(data))
    assert first['ok'] is False
    assert first['error']['code'] == 'NEED_ATTENTION'
    assert actions.receipts[data['operation_id']]['state'] == 'uncertain'
    assert 'click' not in element.calls
    assert actions.sessions['session']['snapshot'] is None
