"""Origin-authorization fence surrounding an awaited browser effect.

The caller owns the authenticated profile/origin check and the receipt journal.
Passing this fence means only that the page was still authorized immediately
before and after dispatch; it never proves an external write succeeded.
"""


async def fenced_browser_dispatch(session, verify_session, effect):
    """Do not report dispatch success after navigation or profile revocation.

    The effect is invoked once, never retried. A failure from either the effect
    or the post-dispatch check is deliberately propagated so the caller's
    durable receipt remains uncertain rather than falsely completed.
    """
    verify_session(session)
    result = await effect()
    verify_session(session)
    return result
