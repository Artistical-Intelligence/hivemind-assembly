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


def test_composed_function_workflow_uses_prior_results_and_selected_outputs():
    from hivemind_assembly.domains.reverse_engineering.workflows import runner

    engine = runner()
    plan = {
        "steps": [
            {
                "tool": "function_call",
                "args": {
                    "machine_hex": "89f801f0c3",
                    "case": {
                        "arguments": [{"$input": "a"}, {"$input": "b"}],
                        "output_bits": 32,
                    },
                },
            },
            {
                "tool": "function_call",
                "args": {
                    "machine_hex": "89f801f8c3",
                    "case": {
                        "arguments": [{"$step": 0, "path": ["value"]}],
                        "output_bits": 32,
                    },
                },
            },
            {
                "tool": "function_call",
                "args": {
                    "machine_hex": "89f801f8c3",
                    "case": {
                        "arguments": [{"$step": 0, "path": ["value"]}],
                        "output_bits": 32,
                    },
                },
            },
        ],
        "reuse_identical": True,
        "outputs": [{"$step": 2}],
    }
    assert engine.run(plan, {"a": 3, "b": 4})[0]["value"] == 14
    assert engine.run(plan, {"a": 3, "b": 5})[0]["value"] == 16


@pytest.mark.parametrize(
    "reference",
    [{"$step": 0}, {"$step": -1}, {"$step": True}, {"$step": 2, "path": ["x"]}],
)
def test_forward_or_invalid_step_references_rejected(reference):
    engine = WorkflowRunner({"identity": lambda a: a}, "fixture")
    with pytest.raises(ContractError):
        engine.run(
            {
                "steps": [{"tool": "identity", "args": {"x": reference}}],
                "reuse_identical": False,
            },
            {},
        )


def test_missing_result_path_is_an_explicit_failure():
    engine = WorkflowRunner({"identity": lambda a: a}, "fixture")
    with pytest.raises(ContractError, match="selected output"):
        engine.run(
            {
                "steps": [{"tool": "identity", "args": {"n": 1}}],
                "reuse_identical": False,
                "outputs": [{"$step": 0, "path": ["missing"]}],
            },
            {},
        )


@pytest.mark.parametrize(
    "code", ["0f31c3", "0f01f9c3", "0fa2c3", "480fc7f0c3", "f3480fc7f8c3", "ecc3"]
)
def test_cpu_nondeterminism_is_not_a_pure_workflow(code):
    from hivemind_assembly.domains.reverse_engineering.workflows import function_call

    assert function_call({"machine_hex": code})["status"] == "unsupported"


def test_invalid_result_path_retains_failed_evaluation(store, monkeypatch):
    learning = service(store, monkeypatch)
    suite = learning.protect_suite(CASES)
    plan = {**PLAN, "outputs": [{"$step": 2, "path": ["missing"]}]}
    candidate = learning.propose("bad-path", plan, [suite])
    result = learning.evaluate(candidate, suite)
    assert not result["eligible"]
    assert all(
        not v["passed"]
        for v in store.get("evaluation", result["evaluation"])["trial"].values()
    )


def test_real_function_optimizer_preserves_independent_buffer_truth(store):
    from hivemind_assembly.domains.reverse_engineering.workflows import (
        optimize_repeated_calls,
        runner,
    )

    result = optimize_repeated_calls(store)
    evaluation = store.get("evaluation", result["evaluation"])
    assert set(evaluation["holdouts"]) == {"store", "offset"}
    assert all(v["passed"] for v in evaluation["trial"].values())
    assert all(len(v["trial"]) == 5 for v in evaluation["samples"].values())
    if result["promoted"]:
        output = WorkflowLearning(store, runner()).execute(
            result["candidate"],
            {"code": "89f801f0c3", "case": {"arguments": [10, 21], "output_bits": 32}},
        )
        assert output["outputs"][0]["value"] == 31
        assert optimize_repeated_calls(store)["already_active"]


def test_revoked_workflow_cannot_be_used_or_revised_by_native_worker(
    store, monkeypatch
):
    learning = service(store, monkeypatch)
    suite = learning.protect_suite(CASES)
    candidate = learning.propose("revocable", PLAN, [suite], external_allowed=True)
    evaluation = learning.evaluate(candidate, suite)
    learning.learning.promote(candidate, evaluation["evaluation"], "evaluator")
    assert (
        learning.execute(candidate, {"n": 4}, external=True)["outputs"]
        == [{"value": 16}] * 3
    )
    learning.learning.share(candidate, False)
    from hivemind_assembly.learning.scopes import KnowledgeScopes

    scopes = KnowledgeScopes(store)
    scopes.create_tag("workflow", "Workflow")
    scopes.assign("lesson", candidate, ["workflow"])
    task = store.create_project("workflow", "check workflow")
    scopes.select(task["id"], ["workflow"], scopes.catalog()["revision"])
    assert (
        learning.learning.applicable(
            "reverse_engineering", external=True, task=task["id"]
        )
        == []
    )
    with pytest.raises(Blocked, match="not authorized"):
        learning.execute(candidate, {"n": 4}, external=True)
    with pytest.raises(Blocked, match="externally authorized"):
        learning.propose_variant("task", candidate, PLAN, ["op"], "revise")
    assert learning.execute(candidate, {"n": 4})["outputs"] == [{"value": 16}] * 3


def test_promotion_cannot_switch_to_another_protected_suite(store, monkeypatch):
    learning = service(store, monkeypatch)
    first = learning.protect_suite(CASES)
    candidate = learning.propose("square", PLAN, [first])
    learning.learning.promote(candidate, learning.evaluate(candidate, first)["evaluation"], "evaluator")
    learning.learning.rollback(candidate)
    other = learning.protect_suite(CASES)
    retry = learning.propose("square", PLAN, [other])
    result = learning.evaluate(retry, other)
    assert result["eligible"]
    with pytest.raises(Blocked, match="bound to this asset"):
        learning.learning.promote(retry, result["evaluation"], "evaluator")
