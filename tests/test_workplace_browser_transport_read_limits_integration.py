"""Source-integrated synthetic BrowserActions DOM budgets; not a live provider test.

Requires the complete HA runtime/dependencies. Syntax-only is not execution.
"""
import asyncio
from contextlib import asynccontextmanager

import pytest

from hivemind_assembly.automation.browser_actions import BrowserActions
from hivemind_assembly.automation.browser_engine.element_refs import (
    MAX_REFERENCE_HANDLES, MAX_SNAPSHOT_CHARS,
)


class FakeBrowser:
    config = {'routes': {'only': {'profile': 'fixture'}}}

    @asynccontextmanager
    async def profile_lock(self, profile):
        assert profile == 'fixture'
        yield


class Handle:
    def __init__(self):
        self.disposals = 0
        self.attributes = 0

    async def dispose(self):
        self.disposals += 1

    async def get_attribute(self, name):
        self.attributes += 1
        raise AssertionError('over-budget handles must not be inspected')


class Locator:
    def __init__(self, handles):
        self.handles = handles
        self.requested = False

    async def evaluate_all(self, script):
        return None

    async def element_handles(self):
        self.requested = True
        return self.handles


class Page:
    url = 'https://example.invalid/setup'

    def __init__(self, snapshot, handles):
        self.snapshot = snapshot
        self.loc = Locator(handles)

    def is_closed(self):
        return False

    def locator(self, selector):
        assert selector == '[data-ha-ref]'
        return self.loc

    async def evaluate(self, script):
        return self.snapshot if 'snapshot' in script or len(script) > 100 else None


def prepare(tmp_path, snapshot, handles):
    actions = BrowserActions(FakeBrowser(), tmp_path)
    page = Page(snapshot, handles)
    # Synthetic in-memory fixture; actual open establishes route/policy binding.
    actions.sessions['session-limit'] = {
        'page': page, 'profile': 'fixture',
        'origin': 'https://example.invalid', 'snapshot': 'old-snapshot',
        'handles': {},
    }
    request = {'action': 'read', 'operation_id': 'read-limit-fixture-0001',
               'session': 'session-limit'}
    return actions, page, request


@pytest.mark.parametrize('snapshot', ['x' * (MAX_SNAPSHOT_CHARS + 1), {'unsafe': 'data'}])
def test_read_refuses_oversized_or_malformed_text_before_handles(tmp_path, snapshot):
    actions, page, request = prepare(tmp_path, snapshot, [])
    result = asyncio.run(actions.run(request))
    assert result['ok'] is False
    assert page.loc.requested is False
    assert actions.sessions['session-limit']['snapshot'] is None
    assert actions.receipts[request['operation_id']]['state'] == 'uncertain'
    assert asyncio.run(actions.run(request))['error']['code'] == 'UNCERTAIN'


def test_over_budget_reference_handles_are_disposed_and_not_exposed(tmp_path):
    handles = [Handle() for _ in range(MAX_REFERENCE_HANDLES + 1)]
    actions, page, request = prepare(tmp_path, 'Ordinary page', handles)
    result = asyncio.run(actions.run(request))
    assert result['ok'] is False
    assert page.loc.requested is True
    assert all(h.disposals == 1 and h.attributes == 0 for h in handles)
    assert actions.sessions['session-limit']['handles'] == {}
    assert actions.receipts[request['operation_id']]['state'] == 'uncertain'
    assert asyncio.run(actions.run(request))['error']['code'] == 'UNCERTAIN'
