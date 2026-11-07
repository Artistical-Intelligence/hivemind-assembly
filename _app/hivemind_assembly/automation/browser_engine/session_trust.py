"""Fail-closed health check for an existing HA browser session.

This checks the current page, authorized origin and selected browser profile.
It does not prove website login, authorization to perform a new action, or a
completed external write. No browser is created and no page is navigated.
"""

_UNSET = object()


def live_browser_session(session, origin_of, *, expected_profile=_UNSET, expected_origin=_UNSET):
    """Whether the original session still identifies an authorized live page.

    The origin_of callback applies the browser transport's strict HTTPS,
    credential and custom-port policy; callers must not substitute a permissive
    URL parser. A missing, closed, redirected or malformed page fails closed.
    """
    if not isinstance(session, dict):
        return False
    try:
        if expected_profile is not _UNSET and session['profile'] != expected_profile:
            return False
        if expected_origin is not _UNSET and session['origin'] != expected_origin:
            return False
        page = session['page']
        return not page.is_closed() and session['origin'] == origin_of(page.url)
    except Exception:
        # A disposed Playwright page, stale in-memory session or malformed
        # origin cannot be treated as proof of continuing authorization.
        return False
