"""Bind a native browser page to the configured routes that authorized it.

A profile name alone is not sufficient: the route that originally granted it
may be removed or reassigned while an awaited browser operation is in flight.
This helper reads only the in-memory HA route configuration and never opens a
browser, changes configuration, or consults a provider.
"""


def profile_route_binding(config, profile):
    """Return the stable IDs of routes currently granting *profile* access."""
    if not isinstance(profile, str) or not profile or not isinstance(config, dict):
        return ()
    routes = config.get('routes')
    if not isinstance(routes, dict):
        return ()
    return tuple(sorted(key for key, route in routes.items()
                        if isinstance(key, str) and isinstance(route, dict)
                        and route.get('profile') == profile))


def bound_route_is_current(config, profile, binding):
    """Deny revoked, reassigned, added, and malformed route authority."""
    return (isinstance(binding, tuple) and bool(binding)
            and binding == profile_route_binding(config, profile))
