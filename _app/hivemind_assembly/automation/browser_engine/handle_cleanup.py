"""Release previous DOM snapshot handles before inspecting a fresh page.

A disposed or navigated page can make one Playwright handle fail during
cleanup. Continue releasing the remaining handles, but fail the read closed
rather than treating an incomplete cleanup as a fresh authorized snapshot.
No browser or website effect is started by this helper.
"""

import asyncio


class PriorHandleCleanupError(RuntimeError):
    """A previous snapshot could not be completely released."""


async def dispose_prior_handles(handles):
    """Attempt each handle disposal; preserve cancellation and deny partial reads.

    The caller invalidates its old snapshot/handle map *before* awaiting this
    operation and must check current page/profile/route authority afterward.
    Cleanup errors are not returned to the agent, because Playwright exceptions
    can include page-controlled text. Cancellation must propagate so the
    caller's durable receipt remains uncertain and cannot be replayed.
    """
    if not isinstance(handles, dict):
        raise PriorHandleCleanupError('Previous browser controls are invalid')
    failed = False
    cancelled = None
    for item in tuple(handles.values()):
        if not isinstance(item, tuple) or len(item) != 2:
            failed = True
            continue
        try:
            await item[0].dispose()
        except asyncio.CancelledError as error:
            if cancelled is None:
                cancelled = error
        except Exception:
            failed = True
    if cancelled is not None:
        raise cancelled
    if failed:
        raise PriorHandleCleanupError('Previous browser controls could not all be released')
