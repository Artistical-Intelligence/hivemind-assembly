"""CHECKS PENDING: full-HA fake browser cancellation and restart regression.

Tests import the real BrowserActions module; a fake dispatch is deliberately
held in-flight and cancelled. No real website, model, or provider is used.
"""
import asyncio
import json

import pytest

from hivemind_assembly.automation.browser_actions import BrowserActions
from hivemind_assembly.core.common import Conflict


class _NoProviderBrowser:
    config = {'routes': {}}


def _request(action):
    request = {'action': action, 'operation_id': f'cancel-{action}-0001'}
    if action == 'open':
        request.update(profile='fixture', url='https://example.invalid/setup')
    else:
        request.update(session='session-not-actually-open')
    if action in ('fill', 'click'):
        request.update(snapshot='synthetic-snapshot', ref='1')
    if action == 'fill':
        request['value'] = 'SAFE VALUE'
    return request


@pytest.mark.parametrize('action', ['open', 'read', 'fill', 'click', 'close'])
def test_cancelled_inflight_action_is_uncertain_durable_and_never_replayed(tmp_path, action):
    async def exercise():
        actions = BrowserActions(_NoProviderBrowser(), tmp_path)
        request = _request(action)
        started = asyncio.Event()
        calls = []

        async def interrupted_dispatch(data):
            calls.append(data['action'])
            started.set()
            await asyncio.Event().wait()

        actions._run = interrupted_dispatch
        pending = asyncio.create_task(actions.run(request))
        await started.wait()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert actions.receipts[request['operation_id']]['state'] == 'uncertain'
        on_disk = json.loads(actions.path.read_text(encoding='utf-8'))
        assert on_disk[request['operation_id']]['state'] == 'uncertain'

        restarted = BrowserActions(_NoProviderBrowser(), tmp_path)
        async def forbidden_dispatch(_):
            calls.append('UNEXPECTED SECOND DISPATCH')
            raise AssertionError('cancelled operation was replayed')
        restarted._run = forbidden_dispatch
        replay = await restarted.run(request)
        assert replay['ok'] is False
        assert replay['error']['code'] == 'UNCERTAIN'
        with pytest.raises(Conflict):
            await restarted.run({**request, 'operation_id': request['operation_id'], 'ref': '999'})
        assert calls == [action]
    asyncio.run(exercise())
