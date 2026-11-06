"""Source-scoped, no-browser/no-network checks for canonical HTTPS origins."""

import pytest
from hivemind_assembly.automation.browser_engine.url_origin import canonical_https_origin


@pytest.mark.parametrize(('url', 'origin'), [
    ('https://example.invalid/setup?token=opaque', 'https://example.invalid'),
    ('https://EXAMPLE.INVALID:443/path#section', 'https://example.invalid'),
    ('https://sub-domain.example.invalid', 'https://sub-domain.example.invalid'),
    ('https://127.0.0.1/path', 'https://127.0.0.1'),
    ('https://[2001:db8::1]:443/path', 'https://[2001:db8::1]'),
    ('https://[2001:0db8:0:0:0:0:0:1]/', 'https://[2001:db8::1]'),
])
def test_unambiguous_origins(url, origin):
    assert canonical_https_origin(url) == origin


@pytest.mark.parametrize('url', [
    'http://example.invalid/', 'file:///tmp/private', 'javascript:alert(1)',
    'https://@example.invalid/', 'https://user@example.invalid/',
    'https://user:password@example.invalid/',
    'https://example.invalid\\@outside.invalid/path',
    'https://example.invalid\\private',
    'https://exa\tmple.invalid/', 'https://exa\nmple.invalid/',
    'https://example.invalid/hey\rthere', ' https://example.invalid/',
    'https://example.invalid:444/', 'https://example.invalid:/',
    'https://example.invalid:000443/',
    'https://%65xample.invalid/', 'https://例え.invalid/',
    'https://example.invalid./', 'https://-invalid.example/',
    'https://invalid-.example/', 'https://a..example/',
    'https://127.1/', 'https://0177.0.0.1/', 'https://0x7f000001/',
    'https://127.000.0.1/', 'https://[::1%25eth0]/',
    'https://[bad_ipv6]/', 'https://', 'https://example.invalid' + 'a' * 8200,
    None, 42, [],
])
def test_rejects_browser_url_normalization_ambiguities(url):
    with pytest.raises(ValueError):
        canonical_https_origin(url)


def test_does_not_echo_sensitive_userinfo_in_exception():
    with pytest.raises(ValueError) as error:
        canonical_https_origin('https://private-user:secret@example.invalid/')
    assert 'secret' not in str(error.value)
    assert 'private-user' not in str(error.value)
