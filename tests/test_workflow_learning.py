import json
import pytest
from hivemind_assembly.learning.workflows import WorkflowRunner, WorkflowLearning
from hivemind_assembly.learning.engine import Learning
from hivemind_assembly.core.common import Blocked, ContractError

PLAN = {
    "steps": [{"tool": "square", "args": {"n": {"$input": "n"}}}] * 3,
    "reuse_identical": False,
}
CASES = [
    {
        "id": "r",
        "family": "positive",
        "split": "regression",
        "inputs": {"n": 3},
        "expected": [{"value": 9}] * 3,
    },
    {
        "id": "h",
        "family": "negative",
        "split": "holdout",
        "inputs": {"n": -4},
        "expected": [{"value": 16}] * 3,
    },
]


def service(store, monkeypatch):
    clock = [0.0]

    def square(args):
        clock[0] += 1.0
        return {"value": args["n"] ** 2}

    monkeypatch.setattr(
        "hivemind_assembly.learning.workflows.time.perf_counter", lambda: clock[0]
    )
    return WorkflowLearning(store, WorkflowRunner({"square": square}, "fixture-v1"))


def test_measured_promotion_execution_and_rollback(store, monkeypatch):
    learning = service(store, monkeypatch)
    suite = learning.protect_suite(CASES)
    candidate = learning.propose("square", PLAN, [suite])
    result = learning.evaluate(candidate, suite)
    assert result["eligible"] and result["speed_gain"] == pytest.approx(2 / 3)
    learning.learning.promote(candidate, result["evaluation"], "evaluator")
    assert learning.execute(candidate, {"n": 11})["outputs"] == [{"value": 121}] * 3
    learning.learning.rollback(candidate)
    with pytest.raises(Blocked):
        learning.execute(candidate, {"n": 11})


def test_wrong_independent_truth_blocks_promotion(store, monkeypatch):
    learning = service(store, monkeypatch)
    cases = json.loads(json.dumps(CASES))
    cases[1]["expected"] = [{"value": 0}] * 3
    suite = learning.protect_suite(cases)
    candidate = learning.propose("bad", PLAN, [suite])
    result = learning.evaluate(candidate, suite)
    assert not result["eligible"]
    with pytest.raises(Blocked):
        learning.learning.promote(candidate, result["evaluation"], "evaluator")


def test_optimizer_cannot_change_unselected_observations(store, monkeypatch):
    clock = [0.0]

    def impure(args):
        clock[0] += 1.0
        return {"value": args["n"] ** 2, "undeclared_side_effect": clock[0]}

    monkeypatch.setattr(
        "hivemind_assembly.learning.workflows.time.perf_counter", lambda: clock[0]
    )
    learning = WorkflowLearning(store, WorkflowRunner({"square": impure}, "bad"))
    suite = learning.protect_suite(CASES)
    candidate = learning.propose("impure", PLAN, [suite])
    assert not learning.evaluate(candidate, suite)["eligible"]


def test_suite_protection_and_family_split(store, monkeypatch):
    learning = service(store, monkeypatch)
    suite = learning.protect_suite(CASES)
    with pytest.raises(Blocked):
        learning.assets.read(suite, "worker")
    leaked = [CASES[0], {**CASES[1], "family": "positive"}]
    with pytest.raises(Blocked):
        learning.protect_suite(leaked)


def test_engine_change_requires_revalidation(store, monkeypatch):
    learning = service(store, monkeypatch)
    suite = learning.protect_suite(CASES)
    candidate = learning.propose("square", PLAN, [suite])
    ev = learning.evaluate(candidate, suite)
    learning.learning.promote(candidate, ev["evaluation"], "evaluator")
    learning.runner.fingerprint = "changed"
    with pytest.raises(Blocked):
        learning.execute(candidate, {"n": 2})
    replacement = learning.propose("square", PLAN, [suite])
    checked = learning.evaluate(replacement, suite)
    learning.learning.promote(replacement, checked["evaluation"], "evaluator")
    assert learning.execute(replacement, {"n": 2})["outputs"] == [{"value": 4}] * 3


def test_cache_is_per_invocation_and_keyed_by_arguments():
    calls = []

    def square(args):
        calls.append(args["n"])
        return {"value": args["n"] ** 2}

    runner = WorkflowRunner({"square": square}, "fixture")
    plan = {**PLAN, "reuse_identical": True}
    assert runner.run(plan, {"n": 3}) == [{"value": 9}] * 3
    assert runner.run(plan, {"n": 4}) == [{"value": 16}] * 3
    assert calls == [3, 4]
    plan["steps"] = [PLAN["steps"][0], {"tool": "square", "args": {"n": 5}}]
    assert runner.run(plan, {"n": 4}) == [{"value": 16}, {"value": 25}]


def test_no_arbitrary_code_or_missing_inputs():
    runner = WorkflowRunner({"square": lambda args: args}, "fixture")
    with pytest.raises(ContractError):
        runner.run(
            {"steps": [{"tool": "shell", "args": {}}], "reuse_identical": True}, {}
        )
    with pytest.raises(ContractError):
        runner.run(PLAN, {})


def test_unmeasured_holdout_does_not_count_as_improvement(store):
    learning = Learning(store)
    candidate = learning.propose(
        "x",
        "procedure",
        {
            "scope": ["x"],
            "preconditions": [],
            "exclusions": [],
            "evidence": ["x"],
            "content": "method",
        },
    )
    evaluation = learning.evaluate(
        candidate,
        {"reg": {"passed": True, "elapsed": 1}},
        {"reg": {"passed": True, "elapsed": 1}, "new": {"passed": True, "elapsed": 1}},
        ["new"],
        {},
        "evaluator",
    )
    assert not store.get("evaluation", evaluation)["eligible"]


def test_real_proof_optimizer_records_correctness_and_timings(store):
    from hivemind_assembly.domains.reverse_engineering.workflows import (
        optimize_repeated_proofs,
        runner,
    )

    result = optimize_repeated_proofs(store)
    evaluation = store.get("evaluation", result["evaluation"])
    assert len(evaluation["holdouts"]) == 2
    assert all(r["passed"] for r in evaluation["trial"].values())
    assert all(len(v["trial"]) == 5 for v in evaluation["samples"].values())
    if result["promoted"]:
        output = WorkflowLearning(store, runner()).execute(
            result["candidate"], {"original": "89f801f0", "candidate": "8d0437"}
        )
        assert all(r["result"] == "UNSAT" for r in output["outputs"])
