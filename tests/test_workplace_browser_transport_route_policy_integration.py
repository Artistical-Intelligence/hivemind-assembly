"""Full HA-module regression for mutable route policy and browser receipts.

Offline fakes only. No real browser, network, login, or provider confirmation.
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
            'original': {'profile': 'fixture', 'surface': 'chat',
                         'prompt': {'scope': ['read'], 'mode': 'native'}},
            'secondary': {'profile': 'fixture', 'surface': 'chat'},
            'unrelated': {'profile': 'other', 'surface': 'chat'},
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


def request():
    return {'action': 'open', 'operation_id': 'policy-open-0001',
            'profile': 'fixture', 'url': 'https://example.invalid/setup'}


def test_in_place_prompt_change_during_open_closes_page_and_preserves_uncertain_receipt(tmp_path):
    browser = FakeBrowser(
        after_create=lambda b: b.config['routes']['original']['prompt']['scope'].append('send'))
    actions = BrowserActions(browser, tmp_path)
    result = asyncio.run(actions.run(request()))
    assert result['ok'] is False
    assert result['error']['code'] == 'NEED_ATTENTION'
    assert browser.page.is_closed()
    assert actions.sessions == {}
    assert actions.receipts[request()['operation_id']]['state'] == 'uncertain'
    retry = asyncio.run(actions.run(request()))
    assert retry['ok'] is False
    assert retry['error']['code'] == 'UNCERTAIN'
    assert browser.calls == 1


def test_in_place_route_change_revokes_cached_open_and_session_status(tmp_path):
    browser = FakeBrowser()
    actions = BrowserActions(browser, tmp_path)
    result = asyncio.run(actions.run(request()))
    assert result['ok'] is True
    sid = result['items'][0]['session']
    assert actions.sessions[sid]['route_policy_binding'].startswith('sha256:')
    assert actions.status()['sessions'][0]['open'] is True
    browser.config['routes']['original']['prompt']['mode'] = 'other'
    assert actions.status()['sessions'][0]['open'] is False
    replay = asyncio.run(actions.run(request()))
    assert replay['ok'] is False
    assert replay['error']['code'] == 'NEED_ATTENTION'
    assert browser.calls == 1


def test_revoked_prompt_refuses_read_without_accessing_dom(tmp_path):
    browser = FakeBrowser()
    actions = BrowserActions(browser, tmp_path)
    sid = asyncio.run(actions.run(request()))['items'][0]['session']
    browser.config['routes']['original']['prompt']['mode'] = 'other'
    read = {'action': 'read', 'operation_id': 'policy-read-0001', 'session': sid}
    outcome = asyncio.run(actions.run(read))
    assert outcome['ok'] is False
    assert actions.receipts[read['operation_id']]['state'] == 'uncertain'
    assert actions.sessions[sid]['snapshot'] is None


def test_unrelated_route_change_does_not_revoke_session(tmp_path):
    browser = FakeBrowser()
    actions = BrowserActions(browser, tmp_path)
    assert asyncio.run(actions.run(request()))['ok'] is True
    browser.config['routes']['unrelated']['surface'] = 'different'
    assert actions.status()['sessions'][0]['open'] is True
    assert asyncio.run(actions.run(request()))['ok'] is True
    assert browser.calls == 1


def test_malformed_policy_does_not_grant_page_or_replay(tmp_path):
    browser = FakeBrowser()
    actions = BrowserActions(browser, tmp_path)
    result = asyncio.run(actions.run(request()))
    sid = result['items'][0]['session']
    browser.config['routes']['original']['prompt'] = object()
    assert actions.status()['sessions'][0]['open'] is False
    replay = asyncio.run(actions.run(request()))
    assert replay['ok'] is False
    assert replay['error']['code'] == 'NEED_ATTENTION'
    assert browser.calls == 1
    # Even a valid route-ID binding is insufficient without a policy fence.
    actions.sessions[sid].pop('route_policy_binding')
    assert actions.session_route_is_authorized(actions.sessions[sid]) is False
