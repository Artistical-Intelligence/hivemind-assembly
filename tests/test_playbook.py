import copy
import pytest
from hivemind_assembly.core.common import Blocked, ContractError, Conflict, digest
from hivemind_assembly.learning.engine import Learning
from hivemind_assembly.learning.playbook import apply_delta, Playbook, select_context


def entry(text, evidence="measured"):
    return {
        "text": text,
        "conditions": ["unsigned scalar"],
        "exceptions": ["floating point"],
        "evidence": [evidence],
    }


def active(store, asset, content, **extras):
    l = Learning(store)
    key = l.propose(
        asset,
        "knowledge",
        {
            "scope": ["reverse_engineering"],
            "preconditions": ["scalar"],
            "exclusions": ["platform effects"],
            "evidence": ["measured"],
            "content": content,
            **extras,
        },
    )
    ev = l.evaluate(
        key,
        {"reg": {"passed": True, "elapsed": 2}},
        {"reg": {"passed": True, "elapsed": 1}, "held": {"passed": True, "elapsed": 1}},
        ["held"],
        {},
        "evaluator",
    )
    l.promote(key, ev, "evaluator")
    return key


def test_local_edit_preserves_other_details_and_original():
    original = {
        "overflow": entry("Unsigned overflow wraps."),
        "exceptions": entry("Retain ABI exceptions exactly."),
    }
    before = copy.deepcopy(original)
    edited = apply_delta(
        original,
        [
            {
                "action": "replace",
                "id": "overflow",
                "expected_hash": digest(original["overflow"]),
                "entry": entry("Unsigned overflow wraps at the declared width."),
            }
        ],
    )
    assert original == before
    assert edited["exceptions"] == before["exceptions"]
    with pytest.raises(Conflict):
        apply_delta(
            edited,
            [
                {
                    "action": "remove",
                    "id": "overflow",
                    "expected_hash": digest(original["overflow"]),
                }
            ],
        )
    with pytest.raises(Conflict):
        apply_delta(
            original,
            [
                {
                    "action": "add",
                    "id": "duplicate",
                    "entry": entry("  UNSIGNED overflow wraps."),
                }
            ],
        )


def test_worker_proposal_is_not_active_and_requires_real_evidence(ready):
    c, t, epoch = ready
    from hivemind_assembly.core.broker import Broker

    b = Broker(c, {})
    b.execute(
        {
            "id": "evidence",
            "task_id": t["id"],
            "owner": "worker.opus",
            "epoch": epoch,
            "revision": 0,
            "tool": "list_files",
            "args": {},
        }
    )
    base = active(
        c.store,
        "playbook",
        {"entries": {"one": entry("Prior observation")}},
        external_allowed=False,
    )
    edits = [
        {
            "action": "add",
            "id": "two",
            "entry": entry("New bounded observation", "evidence"),
        }
    ]
    result = Playbook(c.store).propose(t["id"], base, edits)
    assert result["status"] == "candidate"
    assert Playbook(c.store).propose(t["id"], base, edits) == result
    assert (
        c.store.one("SELECT status FROM lessons WHERE id=?", (base,))["status"]
        == "active"
    )
    assert (
        c.store.get(
            "evaluation",
            c.store.one("SELECT id FROM records WHERE kind='evaluation'")["id"],
        )["candidate"]
        == base
    )
    with pytest.raises(Blocked):
        Playbook(c.store).propose(
            t["id"],
            base,
            [
                {
                    "action": "add",
                    "id": "fake",
                    "entry": entry("Invented observation", "invented"),
                }
            ],
        )
    assert (
        select_context(c.store, "reverse_engineering", external=True)["selected"] == []
    )


def test_context_prioritizes_relevance_and_preserves_exceptions(store):
    first = active(
        store,
        "first",
        {"entries": {"x": entry("Overflow arithmetic")}},
        external_allowed=True,
    )
    active(
        store,
        "second",
        {"entries": {"y": entry("Unrelated strings")}},
        external_allowed=True,
    )
    context = select_context(
        store, "reverse_engineering", "overflow", external=True, max_chars=512
    )
    assert context["selected"][0]["id"] == first
    assert context["selected"][0]["exclusions"] == ["platform effects"]
    assert context["characters"] <= 512
    assert context["omitted"]


def test_changed_dependencies_and_other_routes_are_not_applied(store):
    base = active(store, "dependency", "base")
    dependent = active(
        store,
        "dependent",
        "use only current baseline",
        dependencies=[{"kind": "lesson", "id": base}],
    )
    route = active(store, "route", "procedure for one route", routes=["worker.opus"])
    Learning(store).rollback(base)
    result = select_context(store, "reverse_engineering", route="worker.extra")
    reasons = {r["id"]: r["reason"] for r in result["omitted"]}
    assert reasons[dependent] == "dependency changed or missing"
    assert reasons[route] == "route requires revalidation"
    assert not result["selected"]


def test_malformed_or_detail_dropping_delta_is_rejected():
    with pytest.raises(ContractError):
        apply_delta(
            {}, [{"action": "add", "id": "a", "entry": {"text": "Lost exceptions"}}]
        )
    with pytest.raises(ContractError):
        apply_delta(
            {"a": entry("x")},
            [{"action": "remove", "id": "a", "expected_hash": digest(entry("x"))}],
        )
