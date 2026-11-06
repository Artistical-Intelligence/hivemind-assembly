"""Offline no-provider cancellation journal tests; not live BrowserActions acceptance."""
import asyncio

import pytest

from hivemind_assembly.automation.browser_engine.cancellation_receipt import uncertain_on_cancellation


def _journal():
    records = {'click-no-retry-001': {'state': 'dispatching', 'hash': 'test-hash'}}
    writes = []

    def save():
        writes.append(records['click-no-retry-001']['state'])

    return records, writes, save


def test_real_asyncio_cancellation_records_uncertain_before_reraise():
    records, writes, save = _journal()
    async def run():
        started = asyncio.Event()
        async def effect():
            with uncertain_on_cancellation(records, 'click-no-retry-001', save):
                started.set()
                await asyncio.Event().wait()
        job = asyncio.create_task(effect())
        await started.wait()
        job.cancel()
        with pytest.raises(asyncio.CancelledError):
            await job
    asyncio.run(run())
    assert records['click-no-retry-001']['state'] == 'uncertain'
    assert writes == ['uncertain']


def test_normal_completion_does_not_change_dispatch_receipt():
    records, writes, save = _journal()
    async def run():
        with uncertain_on_cancellation(records, 'click-no-retry-001', save):
            return await asyncio.sleep(0, result=42)
    assert asyncio.run(run()) == 42
    assert records['click-no-retry-001']['state'] == 'dispatching'
    assert writes == []


@pytest.mark.parametrize('failure', [ValueError('validation failed'), TimeoutError('timed out')])
def test_ordinary_errors_remain_for_existing_browseractions_handler(failure):
    records, writes, save = _journal()
    async def run():
        with uncertain_on_cancellation(records, 'click-no-retry-001', save):
            raise failure
    with pytest.raises(type(failure)):
        asyncio.run(run())
    assert records['click-no-retry-001']['state'] == 'dispatching'
    assert writes == []


def test_cancelled_operation_after_possible_side_effect_is_not_reissued():
    records, writes, save = _journal()
    calls = []
    async def run():
        ready = asyncio.Event()
        async def effect():
            with uncertain_on_cancellation(records, 'click-no-retry-001', save):
                calls.append('click may have reached page')
                ready.set()
                await asyncio.Event().wait()
        job = asyncio.create_task(effect())
        await ready.wait()
        job.cancel()
        with pytest.raises(asyncio.CancelledError):
            await job
        # The same-ID recovery path must treat this record as uncertain.
        assert records['click-no-retry-001']['state'] != 'completed'
        if records['click-no-retry-001']['state'] not in ('dispatching', 'uncertain'):
            calls.append('replay would be attempted')
    asyncio.run(run())
    assert calls == ['click may have reached page']
    assert writes == ['uncertain']


def test_journal_write_failure_does_not_claim_success():
    records, writes, _ = _journal()
    def failed_save():
        writes.append('failed')
        raise OSError('simulated private-disk failure')
    async def run():
        with uncertain_on_cancellation(records, 'click-no-retry-001', failed_save):
            raise asyncio.CancelledError()
    with pytest.raises(OSError, match='private-disk'):
        asyncio.run(run())
    assert records['click-no-retry-001']['state'] == 'uncertain'
    assert writes == ['failed']


def test_direct_cancelled_error_without_task_cancellation_is_also_fenced():
    records, writes, save = _journal()
    async def run():
        with uncertain_on_cancellation(records, 'click-no-retry-001', save):
            raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run())
    assert records['click-no-retry-001']['state'] == 'uncertain'
    assert writes == ['uncertain']
