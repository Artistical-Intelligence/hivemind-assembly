"""Isolated, no-browser regression for the non-idempotent dispatch fence."""
import asyncio

import pytest

from hivemind_assembly.automation.browser_engine.dispatch_fence import (
    DispatchIndeterminate, fenced_browser_dispatch,
)


def test_same_origin_dispatch_completes_once():
    session = {'origin': 'https://example.invalid', 'page_origin': 'https://example.invalid'}
    checks, calls = [], []

    def verify(state):
        checks.append(state['page_origin'])
        if state['origin'] != state['page_origin']:
            raise RuntimeError('origin changed')

    async def effect():
        calls.append('click')
        return {'outcome': 'dispatched'}

    assert asyncio.run(fenced_browser_dispatch(session, verify, effect)) == {'outcome': 'dispatched'}
    assert calls == ['click']
    assert checks == ['https://example.invalid', 'https://example.invalid']


def test_navigation_during_dispatch_cannot_be_reported_as_success():
    session = {'origin': 'https://example.invalid', 'page_origin': 'https://example.invalid'}
    calls = []

    def verify(state):
        if state['origin'] != state['page_origin']:
            raise RuntimeError('origin changed')

    async def effect():
        calls.append('fill')
        await asyncio.sleep(0)
        session['page_origin'] = 'https://other.invalid'
        return {'outcome': 'dispatched'}

    with pytest.raises(DispatchIndeterminate, match='authority changed'):
        asyncio.run(fenced_browser_dispatch(session, verify, effect))
    assert calls == ['fill']


def test_revoked_before_dispatch_never_calls_browser():
    session = {'profile_authorized': False}
    calls = []

    def verify(state):
        if not state['profile_authorized']:
            raise PermissionError('revoked')

    async def effect():
        calls.append('click')

    with pytest.raises(PermissionError, match='revoked'):
        asyncio.run(fenced_browser_dispatch(session, verify, effect))
    assert calls == []


def test_effect_error_is_not_hidden_or_retried():
    checks, calls = [], []

    def verify(state):
        checks.append(True)

    async def effect():
        calls.append('click')
        raise TimeoutError('indeterminate')

    with pytest.raises(TimeoutError, match='indeterminate'):
        asyncio.run(fenced_browser_dispatch({}, verify, effect))
    assert checks == [True]
    assert calls == ['click']
