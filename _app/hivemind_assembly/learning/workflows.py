"""Bounded executable workflows and independently measured optimization.

Plans contain registered pure operations, never Python, shell, or filesystem
access. Optimization reuses identical results within a single invocation.
"""

import copy
import json
import math
import statistics
import time
from hivemind_assembly.core.common import Blocked, ContractError, canonical, digest, uid
from hivemind_assembly.core.artifacts import Artifacts
from .engine import Learning


class WorkflowRunner:
    def __init__(self, operations, fingerprint):
        self.operations = operations
        self.fingerprint = fingerprint

    def validate(self, plan):
        if (
            not isinstance(plan, dict)
            or set(plan) != {"steps", "reuse_identical"}
            or type(plan["reuse_identical"]) is not bool
        ):
            raise ContractError("Workflow requires steps and a boolean reuse_identical")
        if not isinstance(plan["steps"], list) or not 1 <= len(plan["steps"]) <= 32:
            raise ContractError("Workflow must contain 1–32 steps")
        for step in plan["steps"]:
            if (
                not isinstance(step, dict)
                or set(step) != {"tool", "args"}
                or step["tool"] not in self.operations
                or not isinstance(step["args"], dict)
            ):
                raise ContractError(
                    "Workflow step must name a registered pure operation"
                )
        if len(canonical(plan)) > 100_000:
            raise ContractError("Workflow exceeds size limit")

    def run(self, plan, inputs):
        self.validate(plan)
        if not isinstance(inputs, dict) or len(canonical(inputs)) > 200_000:
            raise ContractError("Workflow input exceeds bounds")

        def resolve(value, depth=0):
            if depth > 20:
                raise ContractError("Workflow nesting exceeds limit")
            if isinstance(value, dict):
                if "$input" in value:
                    if (
                        set(value) != {"$input"}
                        or not isinstance(value["$input"], str)
                        or value["$input"] not in inputs
                    ):
                        raise ContractError("Missing workflow input")
                    return copy.deepcopy(inputs[value["$input"]])
                return {k: resolve(v, depth + 1) for k, v in value.items()}
            if isinstance(value, list):
                return [resolve(v, depth + 1) for v in value]
            return value

        cache, outputs = {}, []
        for step in plan["steps"]:
            args = resolve(step["args"])
            key = digest({"tool": step["tool"], "args": args})
            if not plan["reuse_identical"] or key not in cache:
                cache[key] = self.operations[step["tool"]](args)
            outputs.append(copy.deepcopy(cache[key]))
        return outputs


def matches(actual, expected):
    """Expected mappings select observations; arrays require exact cardinality."""
    if isinstance(expected, dict):
        return (
            isinstance(actual, dict)
            and bool(expected)
            and all(k in actual and matches(actual[k], v) for k, v in expected.items())
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(matches(a, e) for a, e in zip(actual, expected))
        )
    return type(actual) is type(expected) and actual == expected


class WorkflowLearning:
    def __init__(self, store, runner):
        self.store, self.runner = store, runner
        self.assets = Artifacts(store)
        self.learning = Learning(store)

    def protect_suite(self, cases):
        if not isinstance(cases, list) or not 2 <= len(cases) <= 128:
            raise ContractError("Evaluation requires 2–128 cases")
        ids, families = set(), {"regression": set(), "holdout": set()}
        for case in cases:
            if not isinstance(case, dict) or set(case) != {
                "id",
                "family",
                "split",
                "inputs",
                "expected",
            }:
                raise ContractError(
                    "Case requires ID, family, split, inputs and independent expected results"
                )
            if (
                not isinstance(case["id"], str)
                or not case["id"]
                or case["id"] in ids
                or case["split"] not in families
                or not isinstance(case["family"], str)
                or not case["family"]
            ):
                raise ContractError("Invalid evaluation identity or split")
            if (
                not isinstance(case["expected"], list)
                or not case["expected"]
                or not isinstance(case["inputs"], dict)
            ):
                raise ContractError("Independent expected output observations required")
            ids.add(case["id"])
            families[case["split"]].add(case["family"])
        if not all(families.values()) or families["regression"] & families["holdout"]:
            raise Blocked(
                "Holdout and regression families must be nonempty and disjoint"
            )
        raw = canonical(cases)
        if len(raw) > 2_000_000:
            raise ContractError("Evaluation suite exceeds size limit")
        return self.assets.add(
            raw, "workflow-evaluation.json", classification="protected"
        )["id"]

    def propose(self, asset_key, baseline, evidence, external_allowed=False):
        self.runner.validate(baseline)
        if baseline["reuse_identical"]:
            raise Blocked("Baseline already reuses identical operations")
        candidate = {**copy.deepcopy(baseline), "reuse_identical": True}
        return self.learning.propose(
            asset_key,
            "executable",
            {
                "scope": ["reverse_engineering"],
                "preconditions": [
                    "registered pure operations",
                    "identical arguments within an invocation",
                ],
                "exclusions": [
                    "project mutations",
                    "browser calls",
                    "cross-invocation caching",
                ],
                "evidence": evidence,
                "content": candidate,
                "baseline": baseline,
                "engine": self.runner.fingerprint,
                "external_allowed": bool(external_allowed),
            },
        )

    def evaluate(self, candidate, suite, repeats=5, min_speed_gain=0.05):
        if (
            type(repeats) is not int
            or not 3 <= repeats <= 15
            or not isinstance(min_speed_gain, (int, float))
            or not math.isfinite(min_speed_gain)
            or not 0 < min_speed_gain < 1
        ):
            raise ContractError(
                "Use 3–15 repetitions and a finite speed gain between zero and one"
            )
        row = self.store.one("SELECT * FROM lessons WHERE id=?", (candidate,))
        payload = json.loads(row["payload"])
        if (
            row["status"] != "candidate"
            or row["kind"] != "executable"
            or payload.get("engine") != self.runner.fingerprint
        ):
            raise Blocked("Candidate is stale or belongs to another execution engine")
        # Never optimize against an unrelated active baseline.
        if row["predecessor"]:
            previous = json.loads(
                self.store.one(
                    "SELECT payload FROM lessons WHERE id=?", (row["predecessor"],)
                )["payload"]
            )
            expected_baseline = (
                previous["content"]
                if previous.get("engine") == self.runner.fingerprint
                else previous["baseline"]
            )
            if expected_baseline != payload["baseline"]:
                raise Blocked("Candidate baseline differs from the active executable")
        if (
            self.store.one("SELECT classification FROM artifacts WHERE id=?", (suite,))[
                "classification"
            ]
            != "protected"
        ):
            raise Blocked("Evaluation suite must be protected")
        cases = json.loads(self.assets.read(suite, "evaluator"))
        baseline_results, trial_results, timings = {}, {}, {}
        for case in cases:
            samples = {"baseline": [], "trial": []}
            passed = {"baseline": True, "trial": True}
            plans = {"baseline": payload["baseline"], "trial": payload["content"]}
            # Warm both paths; alternate timed order to reduce first-run bias.
            for plan in plans.values():
                self.runner.run(plan, case["inputs"])
            for iteration in range(repeats):
                outputs = {}
                for name in (
                    ("baseline", "trial")
                    if iteration % 2 == 0
                    else ("trial", "baseline")
                ):
                    start = time.perf_counter()
                    try:
                        outputs[name] = self.runner.run(plans[name], case["inputs"])
                        ok = matches(outputs[name], case["expected"])
                    except Exception:
                        outputs[name], ok = None, False
                    samples[name].append(time.perf_counter() - start)
                    passed[name] &= ok
                # Preserve *all* baseline observations, beyond selected truth fields.
                passed["trial"] &= outputs["baseline"] == outputs["trial"]
            for name, destination in (
                ("baseline", baseline_results),
                ("trial", trial_results),
            ):
                destination[case["id"]] = {
                    "passed": bool(passed[name]),
                    "elapsed": statistics.median(samples[name]),
                }
            timings[case["id"]] = samples
        holdouts = [c["id"] for c in cases if c["split"] == "holdout"]
        eligible_correct = all(x["passed"] for x in baseline_results.values()) and all(
            x["passed"] for x in trial_results.values()
        )
        base_time = sum(x["elapsed"] for x in baseline_results.values())
        trial_time = sum(x["elapsed"] for x in trial_results.values())
        speed_gain = 1 - trial_time / base_time if base_time else 0
        no_slowdown = all(
            trial_results[k]["elapsed"] <= v["elapsed"] * 1.15
            for k, v in baseline_results.items()
        )
        result = {
            "candidate": candidate,
            "baseline": baseline_results,
            "trial": trial_results,
            "holdouts": holdouts,
            "suite": suite,
            "engine": self.runner.fingerprint,
            "criteria": {"min_speed_gain": min_speed_gain, "max_case_slowdown": 0.15},
            "samples": timings,
            "speed_gain": speed_gain,
            "eligible": eligible_correct
            and no_slowdown
            and speed_gain >= min_speed_gain,
        }
        key = uid("evaluation")
        self.store.put("evaluation", key, result)
        return {
            "evaluation": key,
            "eligible": result["eligible"],
            "speed_gain": speed_gain,
            "cases": len(cases),
        }

    def execute(self, lesson, inputs):
        row = self.store.one("SELECT * FROM lessons WHERE id=?", (lesson,))
        payload = json.loads(row["payload"])
        if (
            row["status"] != "active"
            or row["kind"] != "executable"
            or payload.get("engine") != self.runner.fingerprint
        ):
            raise Blocked(
                "Executable is inactive or needs evaluation after an engine update"
            )
        return {
            "lesson": lesson,
            "version": row["version"],
            "outputs": self.runner.run(payload["content"], inputs),
        }
