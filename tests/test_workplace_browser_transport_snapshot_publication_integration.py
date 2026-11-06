"""BrowserActions final read authority transfer; offline fake browser only.

Full HA import/dependencies required. Source compilation is not a test pass.
"""
import asyncio
from contextlib import asynccontextmanager

import pytest

from hivemind_assembly.automation import browser_actions as browser_module
from hivemind_assembly.automation.browser_actions import BrowserActions
from hivemind_assembly.automation.browser_engine import snapshot_publication


class FakeBrowser:
    def __init__(self):
        self.config = {'routes': {'active': {'profile': 'fixture'}}}

    @asynccontextmanager
    async def profile_lock(self, profile):
        assert profile == 'fixture'
        yield


class Handle:
    def __init__(self):
        self.disposals = 0

    async def get_attribute(self, attr):
        assert attr == 'data-ha-ref'
        return '1'

    async def evaluate(self, _script):
        return {'connected': True, 'tag': 'BUTTON', 'type': '', 'id': '',
                'name': '', 'label': 'Continue', 'text': 'Continue'}

    async def dispose(self):
        self.disposals += 1


class Locator:
    def __init__(self, handle):
        self.handle = handle

    async def evaluate_all(self, _script):
        return None

    async def element_handles(self):
        return [self.handle]


class Page:
    url = 'https://example.invalid/screen'

    def __init__(self, snapshot_script, handle):
        self.snapshot_script = snapshot_script
        self.loc = Locator(handle)

    def is_closed(self):
        return False

    def locator(self, _selector):
        return self.loc

    async def evaluate(self, script):
        if script == self.snapshot_script:
            return 'Safe page body'
        return None


def setup(tmp_path):
    browser = FakeBrowser()
    actions = BrowserActions(browser, tmp_path)
    handle = Handle()
    page = Page(actions.scripts['snapshot'], handle)
    actions.sessions['fixture-session'] = {
        'page': page, 'profile': 'fixture', 'origin': 'https://example.invalid',
        'snapshot': None, 'handles': {},
    }
    request = {'action': 'read', 'operation_id': 'snapshot-publication-01',
               'session': 'fixture-session'}
    return actions, browser, page, handle, request


@pytest.mark.parametrize('revocation', ['route', 'origin'])
def test_revocation_after_control_summary_disposes_uncommitted_handles(
        tmp_path, monkeypatch, revocation):
    actions, browser, page, handle, request = setup(tmp_path)
    original = snapshot_publication.bounded_control_summaries

    def summarize_then_revoke(handles, redact):
        controls = original(handles, redact)
        if revocation == 'route':
            browser.config['routes'].clear()
        else:
            page.url = 'https://different.invalid/screen'
        return controls

    monkeypatch.setattr(snapshot_publication, 'bounded_control_summaries', summarize_then_revoke)
    response = asyncio.run(actions.run(request))
    assert response['ok'] is False
    assert handle.disposals == 1
    assert actions.sessions['fixture-session']['snapshot'] is None
    assert actions.sessions['fixture-session']['handles'] == {}
    assert actions.receipts[request['operation_id']]['state'] == 'uncertain'
    assert asyncio.run(actions.run(request))['error']['code'] == 'UNCERTAIN'
    assert handle.disposals == 1


def test_invalid_late_redactor_output_never_installs_handles(tmp_path, monkeypatch):
    actions, browser, page, handle, request = setup(tmp_path)
    original = browser_module.scrub_url_credentials
    monkeypatch.setattr(browser_module, 'scrub_url_credentials',
                        lambda value: None if value == 'Safe page body' else original(value))
    response = asyncio.run(actions.run(request))
    assert response['ok'] is False
    assert handle.disposals == 1
    assert actions.sessions['fixture-session']['snapshot'] is None
    assert actions.receipts[request['operation_id']]['state'] == 'uncertain'


def test_valid_read_transfers_handles_without_disposing(tmp_path):
    actions, browser, page, handle, request = setup(tmp_path)
    response = asyncio.run(actions.run(request))
    assert response['ok'] is True
    assert response['items'][0]['controls'][0]['label'] == 'Continue'
    assert response['items'][0]['text'] == 'Safe page body'
    assert actions.sessions['fixture-session']['snapshot']
    assert actions.sessions['fixture-session']['handles']['1'][0] is handle
    assert handle.disposals == 0
