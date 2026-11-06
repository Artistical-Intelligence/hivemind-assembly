"""Full HA integration contracts for pre-navigation URL authority validation.

Synthetic browser only; no network, provider login, API, or live receipt.
These cases require a complete HA Python checkout and are not runnable from
an isolated helper-only reconstruction.
"""
import asyncio
import pytest

from hivemind_assembly.automation.browser_actions import BrowserActions, origin_of
from hivemind_assembly.core.common import ContractError


class FakePage:
    def __init__(self, url):
        self.url = url
        self.closed = False

    def is_closed(self):
        return self.closed

    async def close(self):
        self.closed = True


class FakeBrowser:
    def __init__(self, page_url=None):
        self.config = {'routes': {'chat': {'profile': 'native'}}}
        self.page_url = page_url
        self.calls = 0
        self.page = None
        self.allowed_hosts = None

    async def service_page(self, profile, url, hosts, prepare=None):
        self.calls += 1
        self.allowed_hosts = hosts
        self.page = FakePage(self.page_url or url)
        return self.page


def request(url):
    return {'action': 'open', 'operation_id': 'strict-origin-001',
            'profile': 'native', 'url': url}


@pytest.mark.parametrize('url', [
    'https://@example.invalid/',
    'https://example.invalid\\@other.invalid/',
    'https://%65xample.invalid/',
    'https://127.1/',
])
def test_ambiguous_authority_never_reaches_native_page_open(tmp_path, url):
    browser = FakeBrowser()
    actions = BrowserActions(browser, tmp_path)
    response = asyncio.run(actions.run(request(url)))
    assert not response['ok']
    assert browser.calls == 0
    assert actions.sessions == {}
    assert actions.receipts['strict-origin-001']['state'] == 'uncertain'
    assert asyncio.run(actions.run(request(url)))['error']['code'] == 'UNCERTAIN'
    assert browser.calls == 0


def test_explicit_default_port_and_case_normalize_for_authorization(tmp_path):
    browser = FakeBrowser(page_url='https://example.invalid/path')
    actions = BrowserActions(browser, tmp_path)
    opened = asyncio.run(actions.run(request('https://EXAMPLE.INVALID:443/path')))
    assert opened['ok'] is True
    assert browser.allowed_hosts == {'example.invalid'}
    assert opened['items'][0]['origin'] == 'https://example.invalid'
    assert actions.status()['sessions'][0]['open'] is True


def test_post_open_cross_parser_redirect_is_closed_uncertain(tmp_path):
    browser = FakeBrowser(page_url='https://example.invalid\\@other.invalid/path')
    actions = BrowserActions(browser, tmp_path)
    response = asyncio.run(actions.run(request('https://example.invalid/')))
    assert not response['ok']
    assert browser.calls == 1
    assert browser.page.closed
    assert actions.sessions == {}
    assert actions.receipts['strict-origin-001']['state'] == 'uncertain'


def test_public_origin_api_preserves_contract_error_type():
    with pytest.raises(ContractError):
        origin_of('https://@example.invalid/')
