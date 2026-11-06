"""Regression: a DOM effect cannot complete after its browser origin changes.

All pages and handles are in-memory fakes; no provider, login or network call.
Full-app execution is required to validate BrowserActions integration.
"""
import asyncio
from contextlib import asynccontextmanager

import pytest

from hivemind_assembly.automation.browser_actions import BrowserActions, IDENTITY


class FakeBrowser:
    def __init__(self):
        self.config = {'routes': {'fixture-route': {'profile': 'fixture'}}}

    @asynccontextmanager
    async def profile_lock(self, profile):
        assert profile == 'fixture'
        yield


class FakePage:
    def __init__(self):
        self.url = 'https://example.invalid/setup'

    def is_closed(self):
        return False


class FakeElement:
    def __init__(self, page, tag, destination):
        self.page = page
        self.destination = destination
        self.calls = []
        self.identity = {
            'tag': tag, 'type': '', 'id': 'confirm', 'name': '',
            'label': 'Confirm', 'text': 'Confirm' if tag == 'BUTTON' else '',
            'connected': True,
        }

    async def evaluate(self, script):
        return dict(self.identity) if script == IDENTITY else 'Confirm'

    async def is_visible(self):
        return True

    async def is_enabled(self):
        return True

    async def click(self, **kwargs):
        self.calls.append('click')
        await asyncio.sleep(0)
        self.page.url = self.destination

    async def fill(self, value, **kwargs):
        self.calls.append('fill')
        await asyncio.sleep(0)
        self.page.url = self.destination

    async def select_option(self, **kwargs):
        self.calls.append('select')
        await asyncio.sleep(0)
        self.page.url = self.destination


def make_request(tmp_path, action, destination, tag='BUTTON'):
    actions = BrowserActions(FakeBrowser(), tmp_path)
    page = FakePage()
    element = FakeElement(page, tag, destination)
    actions.sessions['session-a'] = {
        'page': page, 'profile': 'fixture',
        'origin': 'https://example.invalid',
        'snapshot': 'authorized-snapshot',
        'handles': {'1': (element, dict(element.identity))},
    }
    request = {
        'action': action, 'operation_id': f'post-{action}-{tag.lower()}-001',
        'session': 'session-a', 'snapshot': 'authorized-snapshot', 'ref': '1',
    }
    if action == 'fill':
        request['value'] = 'nonsecret'
    return actions, page, element, request


@pytest.mark.parametrize('action,tag,method', [
    ('click', 'BUTTON', 'click'),
    ('fill', 'INPUT', 'fill'),
    ('fill', 'SELECT', 'select'),
])
def test_navigation_after_effect_is_uncertain_and_never_replayed(tmp_path, action, tag, method):
    actions, page, element, request = make_request(
        tmp_path, action, 'https://other.invalid/private', tag)
    result = asyncio.run(actions.run(request))
    assert result['ok'] is False
    assert result['error']['code'] == 'NEED_ATTENTION'
    assert element.calls == [method]
    assert actions.receipts[request['operation_id']]['state'] == 'uncertain'
    assert actions.sessions['session-a']['snapshot'] is None
    assert actions.sessions['session-a']['handles'] == {}

    page.url = 'https://example.invalid/setup'
    retry = asyncio.run(actions.run(request))
    assert retry['ok'] is False
    assert retry['error']['code'] == 'UNCERTAIN'
    assert element.calls == [method]


def test_same_origin_effect_still_reports_dispatch_only(tmp_path):
    actions, page, element, request = make_request(
        tmp_path, 'click', 'https://example.invalid/next')
    result = asyncio.run(actions.run(request))
    assert result['ok'] is True
    assert result['items'][0]['outcome'] == 'dispatched'
    assert result['items'][0]['verification'] == 'read_page_required'
    assert element.calls == ['click']
    assert actions.receipts[request['operation_id']]['state'] == 'completed'
    assert page.url == 'https://example.invalid/next'

def test_profile_revocation_during_effect_is_uncertain(tmp_path):
    actions, page, element, request = make_request(
        tmp_path, 'click', 'https://example.invalid/still-here')
    original_click = element.click

    async def click_then_revoke(**kwargs):
        await original_click(**kwargs)
        actions.browser.config['routes'].clear()

    element.click = click_then_revoke
    result = asyncio.run(actions.run(request))
    assert result['ok'] is False
    assert result['error']['code'] == 'NEED_ATTENTION'
    assert element.calls == ['click']
    assert actions.receipts[request['operation_id']]['state'] == 'uncertain'
    assert actions.sessions['session-a']['snapshot'] is None
    assert actions.sessions['session-a']['handles'] == {}
