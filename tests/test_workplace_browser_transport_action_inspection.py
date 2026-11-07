"""No-API regression of native browser action inspection's await fences.

These are isolated, in-memory Python fixtures, not BrowserActions integration
or live ChatGPT/provider/browser acceptance.
"""
import asyncio

import pytest

from hivemind_assembly.automation.browser_engine.action_inspection import (
    ActionInspectionError, inspect_action_target,
)


IDENTITY = {'tag': 'BUTTON', 'connected': True, 'label': 'Continue'}


class FakeElement:
    def __init__(self, session, revoke_at=None, *, identity=None, visible=True,
                 enabled=True, metadata='Continue'):
        self.session = session
        self.revoke_at = revoke_at
        self.identity = IDENTITY if identity is None else identity
        self.visible = visible
        self.enabled = enabled
        self.metadata = metadata
        self.calls = []

    async def _inspect(self, stage, result):
        self.calls.append(stage)
        await asyncio.sleep(0)
        if stage == self.revoke_at:
            self.session['authorized'] = False
        return result

    async def evaluate(self, script):
        if script == 'identity':
            return await self._inspect('identity', self.identity)
        if script == 'metadata':
            return await self._inspect('metadata', self.metadata)
        raise AssertionError('Unexpected browser-side script')

    async def is_visible(self):
        return await self._inspect('visible', self.visible)

    async def is_enabled(self):
        return await self._inspect('enabled', self.enabled)


def authority(session):
    if not session['authorized']:
        raise RuntimeError('browser origin or route authorization revoked')


def inspect(element, session):
    return asyncio.run(inspect_action_target(
        element, IDENTITY, 'identity', 'metadata', session, authority))


@pytest.mark.parametrize('revoke_at,expected_calls', [
    ('identity', ['identity']),
    ('visible', ['identity', 'visible']),
    ('enabled', ['identity', 'visible', 'enabled']),
    ('metadata', ['identity', 'visible', 'enabled', 'metadata']),
])
def test_mid_await_revocation_prevents_later_dom_inspections(revoke_at, expected_calls):
    session = {'authorized': True}
    element = FakeElement(session, revoke_at)
    with pytest.raises(RuntimeError, match='authorization revoked'):
        inspect(element, session)
    assert element.calls == expected_calls


@pytest.mark.parametrize('kwargs,expected_calls', [
    ({'identity': {'tag': 'BUTTON', 'connected': False, 'label': 'Continue'}}, ['identity']),
    ({'visible': False}, ['identity', 'visible']),
    ({'enabled': False}, ['identity', 'visible', 'enabled']),
    ({'metadata': None}, ['identity', 'visible', 'enabled', 'metadata']),
])
def test_malformed_or_nonactionable_control_fails_closed(kwargs, expected_calls):
    session = {'authorized': True}
    element = FakeElement(session, **kwargs)
    with pytest.raises(ActionInspectionError):
        inspect(element, session)
    assert element.calls == expected_calls


def test_authorized_inspection_returns_identity_and_metadata_once():
    session = {'authorized': True}
    element = FakeElement(session)
    identity, metadata = inspect(element, session)
    assert identity == IDENTITY and metadata == 'Continue'
    assert element.calls == ['identity', 'visible', 'enabled', 'metadata']


def test_preexisting_revocation_prevents_all_browser_dom_work():
    session = {'authorized': False}
    element = FakeElement(session)
    with pytest.raises(RuntimeError, match='authorization revoked'):
        inspect(element, session)
    assert element.calls == []
