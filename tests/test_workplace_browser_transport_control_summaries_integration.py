"""Full BrowserActions fixture for control-output privacy and limits.

No real browser/provider/network; requires HA runtime and dependencies. Do not
count Python syntax compilation as execution of these integration cases.
"""
import asyncio
from contextlib import asynccontextmanager

import pytest

from hivemind_assembly.automation.browser_actions import BrowserActions
from hivemind_assembly.automation.browser_engine.control_summaries import (
    MAX_CONTROL_FIELD_CHARS, MAX_CONTROL_LABEL_CHARS,
)


class FakeBrowser:
    config = {'routes': {'sole': {'profile': 'fixture'}}}

    @asynccontextmanager
    async def profile_lock(self, profile):
        assert profile == 'fixture'
        yield


class Handle:
    def __init__(self, ref, label):
        self.ref = str(ref)
        self.label = label
        self.disposals = 0

    async def get_attribute(self, key):
        assert key == 'data-ha-ref'
        return self.ref

    async def evaluate(self, script):
        return {'connected': True, 'tag': 'BUTTON', 'type': '', 'id': '',
                'name': '', 'label': self.label, 'text': 'Save'}

    async def dispose(self):
        self.disposals += 1


class Locator:
    def __init__(self, handles):
        self.handles = handles

    async def evaluate_all(self, script):
        return None

    async def element_handles(self):
        return self.handles


class Page:
    url = 'https://example.invalid/settings'

    def __init__(self, snapshot_script, handles):
        self.snapshot_script = snapshot_script
        self.loc = Locator(handles)

    def is_closed(self):
        return False

    def locator(self, selector):
        assert selector == '[data-ha-ref]'
        return self.loc

    async def evaluate(self, script):
        return 'Safe page body' if script == self.snapshot_script else None


def prepare(tmp_path, handles):
    actions = BrowserActions(FakeBrowser(), tmp_path)
    page = Page(actions.scripts['snapshot'], handles)
    actions.sessions['fixture-session'] = {
        'page': page, 'profile': 'fixture',
        'origin': 'https://example.invalid',
        'snapshot': None, 'handles': {},
    }
    request = {'action': 'read', 'operation_id': 'control-summary-read-01',
               'session': 'fixture-session'}
    return actions, request


def test_url_credentials_hidden_from_controls_and_receipt(tmp_path):
    label = 'Open https://alice:passphrase@example.com/path?token=secretvalue'
    h = Handle(1, label)
    actions, request = prepare(tmp_path, [h])
    response = asyncio.run(actions.run(request))
    assert response['ok'] is True
    control = response['items'][0]['controls'][0]
    assert 'passphrase' not in str(control) and 'secretvalue' not in str(control)
    assert '***@' in control['label'] and 'token=***' in control['label']
    assert actions.sessions['fixture-session']['snapshot']
    assert h.disposals == 0
    assert 'secretvalue' not in actions.path.read_text(encoding='utf-8')


@pytest.mark.parametrize('bad', ['x' * (MAX_CONTROL_FIELD_CHARS + 1), None])
def test_invalid_identity_fails_closed_without_leaking_handles(tmp_path, bad):
    h = Handle(1, bad)
    actions, request = prepare(tmp_path, [h])
    response = asyncio.run(actions.run(request))
    assert response['ok'] is False
    assert actions.sessions['fixture-session']['snapshot'] is None
    assert actions.sessions['fixture-session']['handles'] == {}
    assert h.disposals == 1
    assert actions.receipts[request['operation_id']]['state'] == 'uncertain'
    assert asyncio.run(actions.run(request))['error']['code'] == 'UNCERTAIN'


def test_aggregate_control_budget_does_not_return_partial_snapshot(tmp_path):
    handles = [Handle(i, 'z' * MAX_CONTROL_FIELD_CHARS)
               for i in range(MAX_CONTROL_LABEL_CHARS // MAX_CONTROL_FIELD_CHARS + 1)]
    actions, request = prepare(tmp_path, handles)
    response = asyncio.run(actions.run(request))
    assert response['ok'] is False
    assert actions.sessions['fixture-session']['snapshot'] is None
    assert all(h.disposals == 1 for h in handles)
    assert actions.receipts[request['operation_id']]['state'] == 'uncertain'
