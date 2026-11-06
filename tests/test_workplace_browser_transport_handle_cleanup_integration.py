"""Synthetic BrowserActions cleanup integration; requires the full HA runtime.

No live website, login, model API or native provider is accessed.
"""

import asyncio
from contextlib import asynccontextmanager

import pytest

from hivemind_assembly.automation.browser_actions import BrowserActions


class Browser:
    config = {'routes': {'route': {'profile': 'fixture'}}}

    @asynccontextmanager
    async def profile_lock(self, profile):
        assert profile == 'fixture'
        yield


class Handle:
    def __init__(self, error=None):
        self.error = error
        self.disposals = 0

    async def dispose(self):
        self.disposals += 1
        if self.error is not None:
            raise self.error


class Locator:
    def __init__(self):
        self.calls = 0

    async def evaluate_all(self, _script):
        self.calls += 1

    async def element_handles(self):
        self.calls += 1
        return []


class Page:
    url = 'https://example.invalid/setup'

    def __init__(self, snapshot_script):
        self.snapshot_script = snapshot_script
        self.loc = Locator()
        self.evaluations = 0

    def is_closed(self):
        return False

    def locator(self, _selector):
        self.loc.calls += 1
        return self.loc

    async def evaluate(self, script):
        self.evaluations += 1
        return 'Authorized snapshot' if script == self.snapshot_script else None


def prepare(tmp_path, handles, operation_id):
    actions = BrowserActions(Browser(), tmp_path)
    page = Page(actions.scripts['snapshot'])
    actions.sessions['fixture-session'] = {
        'page': page, 'profile': 'fixture', 'origin': 'https://example.invalid',
        'snapshot': 'old-snapshot', 'handles': {
            str(i): (h, {'connected': True}) for i, h in enumerate(handles, 1)
        },
    }
    data = {'action': 'read', 'operation_id': operation_id,
            'session': 'fixture-session'}
    return actions, page, data


@pytest.mark.parametrize('fault_index', [0, 2])
def test_failed_prior_cleanup_fences_new_dom_read_and_replay(tmp_path, fault_index):
    handles = [Handle() for _ in range(3)]
    handles[fault_index].error = RuntimeError('page was disposed')
    actions, page, data = prepare(tmp_path, handles, 'cleanup-failure-0001')
    response = asyncio.run(actions.run(data))
    assert response['ok'] is False
    assert [h.disposals for h in handles] == [1, 1, 1]
    assert page.loc.calls == 0 and page.evaluations == 0
    assert actions.sessions['fixture-session']['snapshot'] is None
    assert actions.sessions['fixture-session']['handles'] == {}
    assert actions.receipts[data['operation_id']]['state'] == 'uncertain'
    assert asyncio.run(actions.run(data))['error']['code'] == 'UNCERTAIN'
    assert [h.disposals for h in handles] == [1, 1, 1]


def test_prior_cleanup_cancellation_preserves_durable_no_replay_receipt(tmp_path):
    handles = [Handle(asyncio.CancelledError()), Handle()]
    actions, page, data = prepare(tmp_path, handles, 'cleanup-cancel-0001')
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(actions.run(data))
    assert [h.disposals for h in handles] == [1, 1]
    assert page.loc.calls == 0
    assert actions.receipts[data['operation_id']]['state'] == 'uncertain'
    assert asyncio.run(actions.run(data))['error']['code'] == 'UNCERTAIN'
    restart = BrowserActions(Browser(), tmp_path)
    assert asyncio.run(restart.run(data))['error']['code'] == 'UNCERTAIN'


def test_successful_cleanup_allows_authorized_new_snapshot(tmp_path):
    handles = [Handle(), Handle()]
    actions, page, data = prepare(tmp_path, handles, 'cleanup-success-0001')
    response = asyncio.run(actions.run(data))
    assert response['ok'] is True
    assert response['items'][0]['text'] == 'Authorized snapshot'
    assert [h.disposals for h in handles] == [1, 1]
    assert page.loc.calls > 0 and page.evaluations == 2
    assert actions.receipts[data['operation_id']]['state'] == 'completed'
