"""No-provider browser session trust regressions; all page objects are fakes."""
from urllib.parse import urlsplit

from hivemind_assembly.automation.browser_engine.session_trust import live_browser_session


def strict_origin(url):
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username
            or parsed.password or parsed.port not in (None, 443)):
        raise ValueError('unsafe URL')
    return 'https://' + parsed.hostname.lower()


class Page:
    def __init__(self, url='https://example.invalid/setup', closed=False):
        self.url = url
        self.closed = closed

    def is_closed(self):
        return self.closed


def session(page=None):
    return {'page': Page() if page is None else page,
            'origin': 'https://example.invalid', 'profile': 'fixture'}


def test_live_same_origin_session_and_expected_profile():
    existing = session()
    assert live_browser_session(existing, strict_origin)
    assert live_browser_session(existing, strict_origin, expected_profile='fixture',
                                expected_origin='https://example.invalid')
    existing['page'].url = 'https://example.invalid/another-page'
    assert live_browser_session(existing, strict_origin)


def test_missing_or_wrong_profile_or_origin_denied():
    s = session()
    assert not live_browser_session(None, strict_origin)
    assert not live_browser_session({}, strict_origin)
    assert not live_browser_session(s, strict_origin, expected_profile=None)
    assert not live_browser_session(s, strict_origin, expected_profile='other')
    assert not live_browser_session(s, strict_origin, expected_origin='https://other.invalid')
    s['profile'] = 'other'
    assert not live_browser_session(s, strict_origin, expected_profile='fixture')


def test_cross_origin_or_insecure_navigation_invalidates_session():
    s = session()
    for url in ['https://other.invalid/private', 'http://example.invalid/path',
                'https://user:secret@example.invalid/', 'https://example.invalid:8080/path',
                'about:blank', 'file:///local']:
        s['page'].url = url
        assert not live_browser_session(s, strict_origin)


def test_closed_page_and_bad_page_objects_fail_closed():
    s = session()
    s['page'].closed = True
    assert not live_browser_session(s, strict_origin)
    s['page'] = object()
    assert not live_browser_session(s, strict_origin)
    s.pop('page')
    assert not live_browser_session(s, strict_origin)
