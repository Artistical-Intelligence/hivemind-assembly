"""Offline element-ref transfer and revocation checks; no live browser/API.

The helper tests run without the full HA application. Integration of the
helper into BrowserActions and a real browser still require separate checks.
"""
import asyncio

import pytest

from hivemind_assembly.automation.browser_engine.element_refs import (
    ElementInspectionError, collect_authorized_refs,
)


class Handle:
    def __init__(self, ref='1', *, mutate=None, connected=True, fail_dispose=False):
        self.ref = ref
        self.mutate = mutate
        self.connected = connected
        self.fail_dispose = fail_dispose
        self.calls = []

    async def get_attribute(self, name):
        assert name == 'data-ha-ref'
        self.calls.append('attribute')
        if self.mutate == 'attribute':
            self.session['authorized'] = False
        return self.ref

    async def evaluate(self, script):
        assert script == 'IDENTITY'
        self.calls.append('identity')
        if self.mutate == 'identity':
            self.session['authorized'] = False
        return {'connected': self.connected, 'tag': 'BUTTON'}

    async def dispose(self):
        self.calls.append('dispose')
        if self.fail_dispose:
            raise RuntimeError('disposal failed')


def inspect(handles, *, authorized=True):
    session = {'authorized': authorized}
    for handle in handles:
        handle.session = session

    def check(value):
        if not value['authorized']:
            raise PermissionError('Profile or origin was revoked')

    return asyncio.run(collect_authorized_refs(handles, session, check, 'IDENTITY'))


def test_success_keeps_only_validated_handles():
    first, second = Handle('1'), Handle('2')
    refs = inspect([first, second])
    assert list(refs) == ['1', '2']
    assert refs['1'][0] is first
    assert 'dispose' not in first.calls + second.calls


@pytest.mark.parametrize('stage', ['attribute', 'identity'])
def test_revocation_during_await_disposes_all_and_stops_inspecting(stage):
    first, second = Handle('1', mutate=stage), Handle('2')
    with pytest.raises(PermissionError):
        inspect([first, second])
    assert second.calls == ['dispose']
    assert first.calls[-1] == 'dispose'


def test_initial_revocation_never_inspects_dom_and_disposes_handles():
    first, second = Handle('1'), Handle('2')
    with pytest.raises(PermissionError):
        inspect([first, second], authorized=False)
    assert first.calls == ['dispose']
    assert second.calls == ['dispose']


@pytest.mark.parametrize('ref', [None, '', '000000', 'x1'])
def test_malformed_reference_fails_closed_and_disposes_batch(ref):
    first, second = Handle(ref), Handle('2')
    with pytest.raises(ElementInspectionError):
        inspect([first, second])
    assert second.calls == ['dispose']
    assert first.calls[-1] == 'dispose'


def test_duplicate_reference_disposes_entire_batch():
    first, second = Handle('1'), Handle('1')
    with pytest.raises(ElementInspectionError):
        inspect([first, second])
    assert first.calls[-1] == second.calls[-1] == 'dispose'


def test_disposal_error_does_not_mask_original_revocation():
    first, second = Handle('1', mutate='identity', fail_dispose=True), Handle('2')
    with pytest.raises(PermissionError):
        inspect([first, second])
    assert second.calls == ['dispose']


def test_detached_element_is_not_an_authorized_ref():
    first = Handle('1', connected=False)
    with pytest.raises(ElementInspectionError):
        inspect([first])
    assert first.calls[-1] == 'dispose'
