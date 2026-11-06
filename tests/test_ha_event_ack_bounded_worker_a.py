"""Worker A finite ACK intake regression contracts (local Store/SQLite only).

No ChatGPT browser, provider call, model API or external event listener.
These tests remain CHECKS PENDING until run against the actual HA checkout.
"""

import json

import pytest

from hivemind_assembly.automation.event_inbox import NativeEventInbox
from hivemind_assembly.core.common import ContractError
from hivemind_assembly.core.store import Store


@pytest.fixture
def inbox_scope(tmp_path):
    store = Store(tmp_path)
    task = store.create_project("bounded-ack", "Keep local receipts bounded")
    inbox = NativeEventInbox(store)
    inbox.subscribe(task["id"], "project:" + task["project_id"])
    try:
        yield store, task, inbox
    finally:
        store.close()


def _admit(inbox, task, number):
    assert inbox.receive(
        project_id=task["project_id"],
        source="native", source_id=f"bounded-ack-{number}",
        thread="project:" + task["project_id"],
        kind="state", summary=f"Durable local event {number}",
    ) == "stored"


def test_oversize_iterator_is_rejected_before_exhaustion(inbox_scope):
    _, task, inbox = inbox_scope
    _admit(inbox, task, 1)
    unread = inbox.pending(task["id"])
    seen = []

    def hostile_iterable():
        # A prior tuple(event_ids) exhausted the iterator and reached this
        # assertion; bounded intake must consume no more than 21 candidates.
        for number in range(1, 23):
            seen.append(number)
            yield number
        raise AssertionError("ACK intake exhausted an unbounded producer")

    with pytest.raises(ContractError, match="bounded"):
        inbox.acknowledge(task["id"], hostile_iterable())
    assert len(seen) == 21
    assert inbox.pending(task["id"]) == unread


def test_exactly_twenty_iterator_receipts_persist_and_replay_idempotently(inbox_scope):
    store, task, inbox = inbox_scope
    for number in range(20):
        _admit(inbox, task, number)
    events = inbox.pending(task["id"], limit=20)
    assert len(events) == 20
    ids = [event["event_id"] for event in events]
    assert inbox.acknowledge(task["id"], (event_id for event_id in ids)) == 20
    assert NativeEventInbox(store).pending(task["id"], limit=20) == []
    assert inbox.acknowledge(task["id"], iter(ids)) == 0


@pytest.mark.parametrize(
    "candidate",
    [None, 13, [1, 1], [True], [0], [1.0], list(range(1, 22)),
     [1 << 63], [10 ** 100]],
)
def test_invalid_ack_input_is_fail_closed(inbox_scope, candidate):
    _, task, inbox = inbox_scope
    _admit(inbox, task, 1)
    unread = inbox.pending(task["id"])
    with pytest.raises(ContractError, match="(bounded|Duplicate)"):
        inbox.acknowledge(task["id"], candidate)
    assert inbox.pending(task["id"]) == unread


@pytest.mark.parametrize("oversized_id", [1 << 63, 10 ** 100])
def test_validated_saved_receipt_rejects_oversized_sqlite_id(inbox_scope, oversized_id):
    store, task, inbox = inbox_scope
    _admit(inbox, task, 1)
    unread = inbox.pending(task["id"])
    packet = {
        "task_id": task["id"], "project_id": task["project_id"],
        "body": {"event_inputs": [{"event_id": oversized_id}]},
    }
    with store.tx() as db:
        db.execute(
            """INSERT INTO messages
               (id,task_id,route,conversation,payload_hash,payload,state,
                response,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            ("ack_out_of_range", task["id"], "worker.chat", "chat-A",
             "oversized-hash", json.dumps(packet), "validated",
             '{"type":"step_intent"}', 1.0, 1.0),
        )
    # ContractError, not sqlite3.OverflowError or a partially consumed inbox.
    with pytest.raises(ContractError, match="Malformed validated native event receipt"):
        inbox.acknowledge_validated_request(
            task["id"], "ack_out_of_range", route="worker.chat"
        )
    assert inbox.pending(task["id"]) == unread
