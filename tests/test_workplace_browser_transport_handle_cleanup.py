"""Offline no-API tests for prior browser handle cleanup on read."""

import asyncio

import pytest

from hivemind_assembly.automation.browser_engine.handle_cleanup import (
    PriorHandleCleanupError, dispose_prior_handles,
)


class Handle:
    def __init__(self, error=None):
        self.error = error
        self.disposals = 0

    async def dispose(self):
        self.disposals += 1
        if self.error is not None:
            raise self.error


def clean(items):
    return asyncio.run(dispose_prior_handles(items))


def test_empty_prior_snapshot_needs_no_browser_calls():
    assert clean({}) is None


def test_all_previous_handles_disposed_once():
    handles = [Handle() for _ in range(3)]
    assert clean({str(i): (handle, {'connected': True}) for i, handle in enumerate(handles)}) is None
    assert [h.disposals for h in handles] == [1, 1, 1]


def test_first_disposal_failure_does_not_abandon_other_handles():
    handles = [Handle(RuntimeError('private page content')), Handle(), Handle()]
    with pytest.raises(PriorHandleCleanupError, match='could not all be released') as info:
        clean({str(i): (h, {}) for i, h in enumerate(handles)})
    assert 'private page content' not in str(info.value)
    assert [h.disposals for h in handles] == [1, 1, 1]


def test_late_disposal_failure_still_fails_closed():
    handles = [Handle(), Handle(ValueError('unavailable'))]
    with pytest.raises(PriorHandleCleanupError):
        clean({str(i): (h, {}) for i, h in enumerate(handles)})
    assert [h.disposals for h in handles] == [1, 1]


@pytest.mark.parametrize('bad', [None, 'not a tuple', (None,), ('bad', {}, 3)])
def test_malformed_handle_entries_do_not_skip_other_disposals(bad):
    handle = Handle()
    with pytest.raises(PriorHandleCleanupError):
        clean({'bad': bad, 'good': (handle, {})})
    assert handle.disposals == 1


def test_invalid_handle_inventory_fails_closed():
    with pytest.raises(PriorHandleCleanupError, match='invalid'):
        clean([('1', Handle())])


def test_cancelled_disposal_attempts_remaining_cleanup_then_propagates():
    handles = [Handle(asyncio.CancelledError()), Handle(), Handle()]
    with pytest.raises(asyncio.CancelledError):
        clean({str(i): (h, {}) for i, h in enumerate(handles)})
    assert [h.disposals for h in handles] == [1, 1, 1]


def test_cancellation_takes_precedence_over_other_disposal_failures():
    handles = [Handle(RuntimeError('page gone')), Handle(asyncio.CancelledError()), Handle()]
    with pytest.raises(asyncio.CancelledError):
        clean({str(i): (h, {}) for i, h in enumerate(handles)})
    assert [h.disposals for h in handles] == [1, 1, 1]
