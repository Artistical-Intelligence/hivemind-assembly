"""Full HA-module regression for exact browser-route authorization binding.

Runs against the actual BrowserActions module and offline fake pages; these
fixtures do not prove a real website, login, Playwright route or provider ACK.
"""

import asyncio
from contextlib import asynccontextmanager

from hivemind_assembly.automation.browser_actions import BrowserActions


class FakePage:
    def __init__(self, url):
        self.url = url
        self.closed = False

    def is_closed(self):
        return self.closed

    async def close(self):
        self.closed = True


class FakeBrowser:
    def __init__(self, after_create=None):
        self.config = {'routes': {
            'original': {'profile': 'fixture'},
            'secondary': {'profile': 'fixture'},
            'unrelated': {'profile': 'other'},
        }}
        self.after_create = after_create
        self.calls = 0
        self.page = None

    async def service_page(self, profile, url, hosts, prepare=None):
        assert profile == 'fixture'
        assert hosts == {'example.invalid'}
        self.calls += 1
        self.page = FakePage(url)
        if self.after_create:
            self.after_create(self)
        return self.page

    @asynccontextmanager
    async def profile_lock(self, profile):
        assert profile == 'fixture'
        yield


def open_request():
    return {'action': 'open', 'operation_id': 'route-open-0001',
            'profile': 'fixture', 'url': 'https://example.invalid/setup'}


def test_route_removed_during_open_refuses_session_and_never_reopens(tmp_path):
    browser = FakeBrowser(after_create=lambda b: b.config['routes'].pop('original'))
    actions = BrowserActions(browser, tmp_path)
    request = open_request()
    result = asyncio.run(actions.run(request))
    assert result['ok'] is False
    assert result['error']['code'] == 'NEED_ATTENTION'
    assert browser.calls == 1
    assert browser.page.is_closed()
    assert actions.sessions == {}
    assert actions.receipts[request['operation_id']]['state'] == 'uncertain'
    retry = asyncio.run(actions.run(request))
    assert retry['error']['code'] == 'UNCERTAIN'
    assert browser.calls == 1


def test_original_route_removed_but_same_profile_still_available_invalidates_open_receipt(tmp_path):
    browser = FakeBrowser()
    actions = BrowserActions(browser, tmp_path)
    request = open_request()
    result = asyncio.run(actions.run(request))
    assert result['ok'] is True
    sid = result['items'][0]['session']
    assert actions.sessions[sid]['route_binding'] == ('original', 'secondary')
    browser.config['routes'].pop('original')
    assert actions.status()['sessions'][0]['open'] is False
    retry = asyncio.run(actions.run(request))
    assert retry['ok'] is False
    assert retry['error']['code'] == 'NEED_ATTENTION'
    assert browser.calls == 1


def test_revoked_route_refuses_read_before_page_inspection(tmp_path):
    browser = FakeBrowser()
    actions = BrowserActions(browser, tmp_path)
    result = asyncio.run(actions.run(open_request()))
    sid = result['items'][0]['session']
    browser.config['routes'].pop('original')
    read = {'action': 'read', 'operation_id': 'route-read-0001', 'session': sid}
    response = asyncio.run(actions.run(read))
    assert response['ok'] is False
    assert response['error']['code'] == 'NEED_ATTENTION'
    assert actions.receipts[read['operation_id']]['state'] == 'uncertain'
    assert actions.sessions[sid]['snapshot'] is None
    assert actions.sessions[sid]['handles'] == {}


def test_unrelated_profile_route_change_does_not_revoke_live_page(tmp_path):
    browser = FakeBrowser()
    actions = BrowserActions(browser, tmp_path)
    result = asyncio.run(actions.run(open_request()))
    assert result['ok'] is True
    browser.config['routes']['unrelated'] = {'profile': 'other2'}
    assert actions.status()['sessions'][0]['open'] is True
    replay = asyncio.run(actions.run(open_request()))
    assert replay['ok'] is True
    assert browser.calls == 1
