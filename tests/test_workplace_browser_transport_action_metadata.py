"""Isolated, source-pinned no-provider tests of action-target metadata bounds.

A page can provide arbitrarily long label text outside HA's separately bounded
snapshot and control list. This fixture has no real browser or external effect.
"""
import asyncio

import pytest

from hivemind_assembly.automation.browser_engine.action_inspection import (
    ActionInspectionError, MAX_ACTION_METADATA_CHARS, inspect_action_target,
)


IDENTITY = {'tag': 'INPUT', 'connected': True, 'label': 'Description'}


class FakeElement:
    def __init__(self, session, metadata, revoke_at=None):
        self.session = session
        self.metadata = metadata
        self.revoke_at = revoke_at
        self.calls = []

    async def _answer(self, step, answer):
        self.calls.append(step)
        await asyncio.sleep(0)
        if self.revoke_at == step:
            self.session['authorized'] = False
        return answer

    async def evaluate(self, script):
        if script == 'identity':
            return await self._answer('identity', dict(IDENTITY))
        if script == 'metadata':
            return await self._answer('metadata', self.metadata)
        raise AssertionError('Unexpected script')

    async def is_visible(self):
        return await self._answer('visible', True)

    async def is_enabled(self):
        return await self._answer('enabled', True)


def guard(session):
    if not session['authorized']:
        raise PermissionError('route authority revoked')


def check(metadata, revoke_at=None):
    session = {'authorized': True}
    element = FakeElement(session, metadata, revoke_at)
    def execute():
        return asyncio.run(inspect_action_target(
            element, IDENTITY, 'identity', 'metadata', session, guard))
    return execute, element


def test_exact_limit_is_accepted_without_truncation():
    payload = 'x' * MAX_ACTION_METADATA_CHARS
    execute, element = check(payload)
    identity, result = execute()
    assert identity == IDENTITY
    assert result == payload
    assert element.calls == ['identity', 'visible', 'enabled', 'metadata']


@pytest.mark.parametrize('payload', [
    'x' * (MAX_ACTION_METADATA_CHARS + 1),
    'password' + 'x' * MAX_ACTION_METADATA_CHARS,
    'ordinary\x00label',
    None,
    5,
    ['label'],
    {'text': 'label'},
])
def test_invalid_page_metadata_fails_closed_without_truncation(payload):
    execute, element = check(payload)
    with pytest.raises(ActionInspectionError, match='invalid or excessive metadata'):
        execute()
    assert element.calls == ['identity', 'visible', 'enabled', 'metadata']


def test_empty_metadata_maintains_existing_contract():
    execute, _ = check('')
    assert execute()[1] == ''


def test_authorization_revoked_during_metadata_has_priority_over_validation():
    execute, element = check('x' * (MAX_ACTION_METADATA_CHARS + 1), revoke_at='metadata')
    with pytest.raises(PermissionError, match='route authority revoked'):
        execute()
    assert element.calls == ['identity', 'visible', 'enabled', 'metadata']


def test_preexisting_revocation_requires_zero_dom_work():
    session = {'authorized': False}
    element = FakeElement(session, 'ok')
    with pytest.raises(PermissionError, match='route authority revoked'):
        asyncio.run(inspect_action_target(element, IDENTITY, 'identity', 'metadata', session, guard))
    assert element.calls == []
