"""Deterministic, browser-free limits for adversarial DOM snapshots and refs."""
import asyncio

import pytest

from hivemind_assembly.automation.browser_engine.element_refs import (
    ElementInspectionError,
    MAX_REFERENCE_HANDLES,
    MAX_SNAPSHOT_CHARS,
    collect_authorized_refs,
    require_bounded_snapshot,
)


@pytest.mark.parametrize('text', ['', 'Ordinary setup page', 'x' * MAX_SNAPSHOT_CHARS])
def test_valid_snapshot_is_preserved_exactly(text):
    assert require_bounded_snapshot(text) is text


@pytest.mark.parametrize('payload', [None, {}, ['control'], b'page', 'x' * (MAX_SNAPSHOT_CHARS + 1)])
def test_malformed_or_oversized_snapshot_fails_closed(payload):
    with pytest.raises(ElementInspectionError, match='safe read limit'):
        require_bounded_snapshot(payload)


class FakeElement:
    def __init__(self, ref):
        self.ref = str(ref)
        self.disposals = 0
        self.attributes = 0
        self.inspections = 0

    async def get_attribute(self, name):
        assert name == 'data-ha-ref'
        self.attributes += 1
        return self.ref

    async def evaluate(self, script):
        self.inspections += 1
        return {'connected': True, 'tag': 'BUTTON'}

    async def dispose(self):
        self.disposals += 1


def run_collect(elements, guard=lambda session: None):
    return asyncio.run(collect_authorized_refs(elements, {}, guard, 'identity'))


def test_oversized_handle_batch_rejected_before_dom_inspection_and_disposed():
    elements = [FakeElement(i) for i in range(MAX_REFERENCE_HANDLES + 1)]
    with pytest.raises(ElementInspectionError, match='too many'):
        run_collect(elements)
    assert all(e.disposals == 1 and e.attributes == 0 and e.inspections == 0 for e in elements)


def test_exact_cap_is_accepted_and_transferred_once():
    elements = [FakeElement(i) for i in range(MAX_REFERENCE_HANDLES)]
    result = run_collect(elements)
    assert len(result) == MAX_REFERENCE_HANDLES
    assert all(e.disposals == 0 and e.attributes == 1 and e.inspections == 1 for e in elements)


def test_nonlist_batch_fails_closed_without_inspection():
    elements = tuple([FakeElement(1)])
    with pytest.raises(ElementInspectionError, match='invalid action references'):
        run_collect(elements)
    assert elements[0].attributes == 0


def test_revoked_authorization_disposes_all_handles():
    elements = [FakeElement(1), FakeElement(2)]

    def guard(session):
        raise RuntimeError('route revoked')

    with pytest.raises(RuntimeError, match='route revoked'):
        run_collect(elements, guard)
    assert [e.disposals for e in elements] == [1, 1]
    assert all(e.attributes == 0 for e in elements)
