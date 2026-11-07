"""Conservative HTTPS origin normalization for native HA browser actions.

Python's urlsplit and Chromium's WHATWG URL parser differ on backslashes,
controls, URL userinfo, and numeric/escaped hostnames. Reject ambiguous inputs
*before* creating a browser page or installing a navigation allowlist. This is
an origin parser, not an authorization to visit any particular website.
"""

import ipaddress
import re
from urllib.parse import urlsplit

_DNS_LABEL = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z')
_DOTTED_IP = re.compile(r'[0-9]+(?:\.[0-9]+){3}\Z')
_NUMERIC_TLD = re.compile(r'(?:[0-9]+|0x[0-9a-f]+)\Z')


def canonical_https_origin(url):
    """Return a single unambiguous HTTPS origin, or raise ValueError.

    An explicit default :443 is accepted, but empty/nonstandard ports,
    userinfo (including empty userinfo), Unicode/escaped authorities and
    browser-normalized numeric hostname aliases are not.
    """
    if (not isinstance(url, str) or not url or len(url) > 8192
            or any(ord(c) <= 32 or ord(c) == 127 or c == '\\' for c in url)):
        raise ValueError('Ambiguous URL characters')
    try:
        parsed = urlsplit(url)
        authority = parsed.netloc
        if (parsed.scheme != 'https' or not authority
                or '@' in authority or '%' in authority or not authority.isascii()
                or parsed.hostname is None or parsed.port not in (None, 443)):
            raise ValueError('Invalid HTTPS authority')
        host = parsed.hostname.lower()
        if ':' in host:
            # Brackets and canonical literal IPv6 disambiguate colons from ports.
            host = ipaddress.IPv6Address(host).compressed
            allowed = ('[' + parsed.hostname.lower() + ']', '[' + parsed.hostname.lower() + ']:443')
            if authority.lower() not in allowed:
                raise ValueError('Ambiguous IPv6 authority')
            return 'https://[' + host + ']'
        if len(host) > 253 or not host or any(
                not _DNS_LABEL.fullmatch(label) for label in host.split('.')):
            raise ValueError('Invalid DNS hostname')
        if authority.lower() not in (host, host + ':443'):
            raise ValueError('Ambiguous port or hostname')
        # Browsers interpret shorthand/octal/hexadecimal numeric hosts as IPs.
        # Permit canonical dotted-decimal IPv4 only; fail closed on aliases.
        if _NUMERIC_TLD.fullmatch(host.split('.')[-1]):
            if not _DOTTED_IP.fullmatch(host) or str(ipaddress.IPv4Address(host)) != host:
                raise ValueError('Noncanonical numeric hostname')
        return 'https://' + host
    except (ValueError, TypeError, UnicodeError) as exc:
        raise ValueError('Use an unambiguous HTTPS origin') from exc
