"""Origin-authorization fence surrounding an awaited browser effect.

The caller owns the authenticated profile/origin check and the receipt journal.
Passing this fence means only that the page was still authorized immediately
before and after dispatch; it never proves an external write succeeded.
"""


class DispatchIndeterminate(RuntimeError):
    """An effect was attempted, but authorization changed before acknowledgment."""


async def fenced_browser_dispatch(session, verify_session, effect):
    """Do not report dispatch success after navigation or profile revocation.

    The effect is invoked once, never retried. A failure from either the effect
    or the post-dispatch check is deliberately propagated so the caller's
    durable receipt remains uncertain rather than falsely completed.
    """
    verify_session(session)
    result = await effect()
    try:
        verify_session(session)
    except Exception as error:
        # The effect may already have reached the site. This must become an
        # uncertain receipt, never a BAD_INPUT result or a retry authorization.
        raise DispatchIndeterminate("Browser authority changed during dispatch") from error
    return result
