"""Worker A supplementary literal-boolean external event admission contracts.

Local Store/SQLite only; no browser, model, API, Actions or external connection.
Verifier's test_native_event_inbox.py stays unmodified. These checks require
independent execution/review before claiming current-HEAD acceptance.
"""

import pytest

from hivemind_assembly.automation.event_inbox import NativeEventInbox
from hivemind_assembly.core.common import ContractError
from hivemind_assembly.core.store import Store


class ExplodingTruth:
    """An untrusted object's truthiness must never execute during admission."""

    def __bool__(self):
        raise AssertionError("Untrusted verified.__bool__ was evaluated")


@pytest.fixture
def event_scope(tmp_path):
    store = Store(tmp_path)
    task = store.create_project("external-auth-boundary", "Verify durable admission")
    inbox = NativeEventInbox(store)
    thread = "project:" + task["project_id"]
    inbox.subscribe(task["id"], thread)
    try:
        yield store, task, inbox, thread
    finally:
        store.close()


def _external(task, thread, source, source_id):
    return dict(
        project_id=task["project_id"], source=source, source_id=source_id,
        thread=thread, kind="ci_failed", summary="Untrusted source data only",
    )


@pytest.mark.parametrize("source", ["github_webhook", "grokbot_kit", "watchdog"])
@pytest.mark.parametrize(
    "forgery",
    [None, False, 0, 1, "True", "host-approved", [True], {"verified": True},
     ExplodingTruth()],
    ids=["none", "false", "zero", "integer-one", "text-true",
         "text-receipt", "list", "mapping", "dangerous-truthiness"],
)
def test_external_verification_rejects_every_nonliteral_boolean(
    event_scope, source, forgery
):
    store, task, inbox, thread = event_scope
    packet = _external(task, thread, source, "unauthenticated")
    with pytest.raises(ContractError, match="verified adapter"):
        inbox.receive(**packet, verified=forgery)
    assert store.rows(
        "SELECT id FROM ha_event_trigger WHERE project_id=?",
        (task["project_id"],),
    ) == []
    assert inbox.pending(task["id"]) == []


@pytest.mark.parametrize("source", ["github_webhook", "grokbot_kit", "watchdog"])
def test_literal_true_admits_one_durable_event_then_deduplicates(
    event_scope, source
):
    store, task, inbox, thread = event_scope
    packet = _external(task, thread, source, "stable-source-receipt")
    assert inbox.receive(**packet, verified=True) == "stored"
    assert inbox.receive(**packet, verified=True) == "duplicate"
    fresh = NativeEventInbox(store)
    pending = fresh.pending(task["id"])
    assert len(pending) == 1
    assert pending[0]["source"] == source
    assert pending[0]["source_id"] == "stable-source-receipt"
    assert fresh.acknowledge(task["id"], [pending[0]["event_id"]]) == 1
    assert NativeEventInbox(store).pending(task["id"]) == []


def test_rejected_truthy_marker_cannot_poison_future_real_receipt(event_scope):
    store, task, inbox, thread = event_scope
    packet = _external(task, thread, "github_webhook", "same-source-id")
    with pytest.raises(ContractError, match="verified adapter"):
        inbox.receive(**packet, verified={"verified": True})
    assert inbox.receive(**packet, verified=True) == "stored"
    assert inbox.receive(**packet, verified=True) == "duplicate"
    assert len(inbox.pending(task["id"])) == 1


def test_internal_native_journal_compatibility_needs_no_external_receipt(
    event_scope
):
    _, task, inbox, thread = event_scope
    packet = _external(task, thread, "native", "local-journal-source")
    assert inbox.receive(**packet) == "stored"
    assert [event["source_id"] for event in inbox.pending(task["id"])] == [
        "local-journal-source"
    ]
