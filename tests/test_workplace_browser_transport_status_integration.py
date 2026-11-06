"""Source-level integration assertions for fail-closed HA browser status.

No Playwright process or external provider is used by these tests. They must
still be executed against the full repository once a permitted test route is
available; a passing session_trust helper fixture is not integration acceptance.
"""

import pytest

from hivemind_assembly.automation.browser_actions import BrowserActions
from hivemind_assembly.core.common import Blocked


class FakeBrowser:
    config = {'routes': {'single': {'profile': 'fixture'}}}


class FakePage:
    def __init__(self):
        self.url = 'https://example.invalid/setup'
        self.closed = False

    def is_closed(self):
        return self.closed


def make_actions(tmp_path):
    actions = BrowserActions(FakeBrowser(), tmp_path)
    page = FakePage()
    actions.sessions['original'] = {
        'page': page,
        'profile': 'fixture',
        'origin': 'https://example.invalid',
        'snapshot': 'snapshot-before-redirect',
        'handles': {'1': (object(), {})},
    }
    return actions, page


def test_status_fails_closed_for_redirected_or_disposed_page(tmp_path):
    actions, page = make_actions(tmp_path)
    assert actions.status()['sessions'][0]['open'] is True
    page.url = 'https://other.invalid/private'
    assert actions.status()['sessions'][0]['open'] is False
    page.url = 'http://example.invalid/insecure'
    assert actions.status()['sessions'][0]['open'] is False
    page.url = 'https://example.invalid/setup'
    page.closed = True
    assert actions.status()['sessions'][0]['open'] is False


def test_origin_guard_invalidates_stale_snapshot_without_dispatch(tmp_path):
    actions, page = make_actions(tmp_path)
    page.url = 'https://other.invalid/private'
    with pytest.raises(Blocked, match='authorized site'):
        actions.require_session_origin(actions.sessions['original'])
    assert actions.sessions['original']['snapshot'] is None
    assert actions.sessions['original']['handles'] == {}
