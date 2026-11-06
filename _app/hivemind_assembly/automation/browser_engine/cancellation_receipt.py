"""Preserve durable browser-operation uncertainty when a task is cancelled.

asyncio.CancelledError does not inherit from Exception on supported Python.
The ordinary BrowserActions exception handler therefore cannot record a
cancelled in-flight browser request as explicitly uncertain. The saved
'dispatching' state already fences replay after restart; making cancellation
explicit also fences the current process and records the true recovery state.
"""

import asyncio
from contextlib import contextmanager


@contextmanager
def uncertain_on_cancellation(receipts, operation_id, persist):
    """Persist an uncertain fence before propagating cancellation unchanged.

    BrowserActions must have already durably recorded 'dispatching' before
    entering the protected await. No operation is repeated here. If persistence
    fails, the original on-disk dispatching entry remains a no-replay fence;
    the persistence error propagates instead of claiming the journal was saved.
    """
    try:
        yield
    except asyncio.CancelledError:
        receipts[operation_id]['state'] = 'uncertain'
        persist()
        raise
