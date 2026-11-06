"""Private, fail-closed fingerprint for a browser session's route permissions.

Route IDs alone do not revoke an existing page when a route keeps the same ID
and profile but its model, surface, prompt, or permission fields change. A
snapshot hashes the *entire* JSON-like route definition for every route
currently granting the profile. Only the digest is retained in HA's ephemeral
session; no raw route configuration, credential, or prompt is exposed in a
browser response or persisted operation receipt.

This is a source-level check at each callsite, not an atomic provider action:
a configuration changed and restored between checks cannot be detected.
"""

import hashlib
import hmac
import json

from .route_binding import profile_route_binding


def route_policy_fingerprint(config, profile):
    """Return an opaque immutable policy fingerprint, or None on malformed data."""
    route_ids = profile_route_binding(config, profile)
    if not route_ids:
        return None
    try:
        routes = config['routes']
        selected = []
        for name in route_ids:
            route = routes[name]
            if not isinstance(route, dict) or route.get('profile') != profile:
                return None
            selected.append((name, route))
        serialized = json.dumps(selected, ensure_ascii=True, sort_keys=True,
                                separators=(',', ':'), allow_nan=False)
        return 'sha256:' + hashlib.sha256(serialized.encode('utf-8')).hexdigest()
    except (KeyError, TypeError, ValueError, UnicodeError, RecursionError, OverflowError):
        return None


def route_policy_is_current(config, profile, fingerprint):
    """Refuse absent/forged policy bindings or changed route definitions."""
    if not isinstance(fingerprint, str) or len(fingerprint) != 71 or not fingerprint.startswith('sha256:'):
        return False
    current = route_policy_fingerprint(config, profile)
    return current is not None and hmac.compare_digest(current, fingerprint)
