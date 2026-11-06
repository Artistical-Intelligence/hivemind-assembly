"""CHECKS PENDING: BrowserActions must fence every DOM ref await.

Deterministic in-memory fakes. These integration cases require the complete
HA package; they do not establish live browser/provider acceptance.
"""
import asyncio
from contextlib import asynccontextmanager

import pytest

from hivemind_assembly.automation.browser_actions import BrowserActions


class FakeBrowser:
    def __init__(self):
        self.config = {'routes': {'fixture': {'profile': 'fixture'}}}
        self.events = []

    @asynccontextmanager
    async def profile_lock(self, profile):
        assert profile == 'fixture'
        yield


class Element:
    def __init__(self, browser, ref, *, revoke_at=None, fail_dispose=False):
        self.browser = browser
        self.ref = ref
        self.revoke_at = revoke_at
        self.fail_dispose = fail_dispose
        self.disposed = False

    async def get_attribute(self, name):
        assert name == 'data-ha-ref'
        self.browser.events.append(('attribute', self.ref))
        if self.revoke_at == 'attribute':
            self.browser.config['routes'].clear()
        return self.ref

    async def evaluate(self, script):
        self.browser.events.append(('identity', self.ref))
        if self.revoke_at == 'identity':
            self.browser.config['routes'].clear()
        return {'tag': 'BUTTON', 'type': '', 'id': '', 'name': '',
                'label': 'Confirm', 'text': 'Confirm', 'connected': True}

    async def dispose(self):
        self.disposed = True
        self.browser.events.append(('dispose', self.ref))
        if self.fail_dispose:
            raise RuntimeError('Page was already disposed')


class Locator:
    def __init__(self, elements):
        self.elements = elements

    async def evaluate_all(self, script):
        return None

    async def element_handles(self):
        return self.elements


class Page:
    def __init__(self, elements):
        self.url = 'https://example.invalid/setup'
        self.elements = elements

    def is_closed(self):
        return False

    def locator(self, selector):
        assert selector == '[data-ha-ref]'
        return Locator(self.elements)

    async def evaluate(self, script):
        return 'Private page text that must be withheld if revoked'


def prepare(tmp_path, first, second):
    browser = first.browser
    actions = BrowserActions(browser, tmp_path)
    actions.sessions['sess'] = {
        'page': Page([first, second]), 'profile': 'fixture',
        'origin': 'https://example.invalid', 'snapshot': 'old', 'handles': {},
    }
    request = {'action': 'read', 'operation_id': 'read-ref-fence-0001', 'session': 'sess'}
    return actions, browser, request


@pytest.mark.parametrize('revoke_at', ['attribute', 'identity'])
def test_revocation_during_first_element_stops_later_inspection(tmp_path, revoke_at):
    browser = FakeBrowser()
    first = Element(browser, '1', revoke_at=revoke_at)
    second = Element(browser, '2')
    actions, _, request = prepare(tmp_path, first, second)
    response = asyncio.run(actions.run(request))
    assert response['ok'] is False
    assert response['error']['code'] == 'NEED_ATTENTION'
    assert 'Private page text' not in str(response)
    assert actions.receipts[request['operation_id']]['state'] == 'uncertain'
    assert first.disposed and second.disposed
    assert ('attribute', '2') not in browser.events
    assert ('identity', '2') not in browser.events
    assert actions.sessions['sess']['snapshot'] is None
    assert actions.sessions['sess']['handles'] == {}

    browser.config['routes']['fixture'] = {'profile': 'fixture'}
    before = list(browser.events)
    replay = asyncio.run(actions.run(request))
    assert replay['error']['code'] == 'UNCERTAIN'
    assert browser.events == before


def test_duplicate_reference_does_not_leave_live_handles(tmp_path):
    browser = FakeBrowser()
    first = Element(browser, '1')
    second = Element(browser, '1')
    actions, _, request = prepare(tmp_path, first, second)
    response = asyncio.run(actions.run(request))
    assert response['ok'] is False
    assert first.disposed and second.disposed
    assert actions.receipts[request['operation_id']]['state'] == 'uncertain'
    assert actions.sessions['sess']['handles'] == {}


def test_valid_batch_transfers_live_handles_and_expires_replay_text(tmp_path):
    browser = FakeBrowser()
    first = Element(browser, '1')
    second = Element(browser, '2')
    actions, _, request = prepare(tmp_path, first, second)
    response = asyncio.run(actions.run(request))
    assert response['ok'] is True
    assert not first.disposed and not second.disposed
    assert set(actions.sessions['sess']['handles']) == {'1', '2'}
    assert response['items'][0]['snapshot'] != 'old'
    before = list(browser.events)
    replay = asyncio.run(actions.run(request))
    assert replay['ok'] is True
    assert replay['items'][0]['snapshot_expired'] is True
    assert 'Private page text' not in str(replay)
    assert browser.events == before
