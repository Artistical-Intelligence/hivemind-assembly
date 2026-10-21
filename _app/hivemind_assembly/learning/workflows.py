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
    def __init__(self, operations, fingerprint, scope=("reverse_engineering",)):
        self.operations = operations
        self.fingerprint = fingerprint
        # The supplying domain names the scope; core learning does not assume one.
        self.scope = list(scope)

    def validate(self, plan):
        if (
            not isinstance(plan, dict)
            or not {"steps", "reuse_identical"} <= set(plan)
            or set(plan) - {"steps", "reuse_identical", "outputs"}
            or type(plan["reuse_identical"]) is not bool
        ):
            raise ContractError("Workflow requires steps and a boolean reuse_identical")
        if not isinstance(plan["steps"], list) or not 1 <= len(plan["steps"]) <= 32:
            raise ContractError("Workflow must contain 1–32 steps")
        for index, step in enumerate(plan["steps"]):
            if (
                not isinstance(step, dict)
                or set(step) != {"tool", "args"}
                or step["tool"] not in self.operations
                or not isinstance(step["args"], dict)
            ):
                raise ContractError(
                    "Workflow step must name a registered pure operation"
                )
            self._references(step["args"], index)
        if "outputs" in plan:
            if (
                not isinstance(plan["outputs"], list)
                or not 1 <= len(plan["outputs"]) <= 32
            ):
                raise ContractError("Workflow requires 1–32 selected outputs")
            self._references(plan["outputs"], len(plan["steps"]))
        if len(canonical(plan)) > 100_000:
            raise ContractError("Workflow exceeds size limit")

    def _references(self, value, before, depth=0):
        if depth > 20:
            raise ContractError("Workflow nesting exceeds limit")
        if isinstance(value, dict):
            if "$step" in value:
                index, path = value["$step"], value.get("path", [])
                if (
                    set(value) - {"$step", "path"}
                    or type(index) is not int
                    or not 0 <= index < before
                    or not isinstance(path, list)
                    or len(path) > 16
                    or any(
                        not isinstance(k, str) and not (type(k) is int and k >= 0)
                        for k in path
                    )
                ):
                    raise ContractError(
                        "Step references must select an earlier result with a bounded path"
                    )
                return
            for child in value.values():
                self._references(child, before, depth + 1)
        elif isinstance(value, list):
            for child in value:
                self._references(child, before, depth + 1)

    def run(self, plan, inputs):
        self.validate(plan)
        if not isinstance(inputs, dict) or len(canonical(inputs)) > 200_000:
            raise ContractError("Workflow input exceeds bounds")

        def resolve(value, depth=0):
            if depth > 20:
                raise ContractError("Workflow nesting exceeds limit")
            if isinstance(value, dict):
                if "$step" in value:
                    result = outputs[value["$step"]]
                    try:
                        for part in value.get("path", []):
                            if not (
                                (isinstance(result, dict) and isinstance(part, str))
                                or (isinstance(result, list) and type(part) is int)
                            ):
                                raise KeyError(part)
                            result = result[part]
                    except (KeyError, IndexError, TypeError) as error:
                        raise ContractError(
                            "Step result does not contain the selected output"
                        ) from error
                    return copy.deepcopy(result)
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
        return resolve(plan["outputs"]) if "outputs" in plan else outputs


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
                "scope": list(self.runner.scope),
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
            for name, plan in plans.items():
                try:
                    self.runner.run(plan, case["inputs"])
                except Exception:
                    # Invalid proposed paths are failed trials, not an escape
                    # from the independently retained evaluation record.
                    passed[name] = False
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
        from .experiments import EvolutionArchive
        from hivemind_assembly.vendor.skillopt.gate import evaluate_gate

        gate = evaluate_gate(
            canonical(payload["content"]),
            (1 if eligible_correct else 0) + max(0, speed_gain) * 0.001,
            canonical(payload["baseline"]),
            1,
            canonical(payload["baseline"]),
            1,
            0,
            1,
        )
        result["skillopt_gate"] = gate.action
        result["eligible"] &= gate.action != "reject"
        key = uid("evaluation")
        self.store.put("evaluation", key, result)
        archive = EvolutionArchive(self.store)
        parent = archive.parent(row["asset_key"], self.runner.fingerprint)
        archive.record(
            row["asset_key"],
            payload["content"],
            self.runner.fingerprint,
            key,
            eligible_correct,
            (1 if eligible_correct else 0) + max(0, speed_gain) * 0.001,
            parent["id"] if parent else None,
        )
        return {
            "evaluation": key,
            "eligible": result["eligible"],
            "speed_gain": speed_gain,
            "cases": len(cases),
        }

    def execute(self, lesson, inputs, external=False):
        row = self.store.one("SELECT * FROM lessons WHERE id=?", (lesson,))
        payload = json.loads(row["payload"])
        if external and not self.learning.external_allowed(row):
            raise Blocked("Workflow is not authorized for native-provider use")
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

    def propose_variant(self, task, baseline_id, plan, evidence, operation_id):
        """Native-model proposals use the registered evaluator, never supplied scores."""
        self.runner.validate(plan)
        base = self.store.one("SELECT * FROM lessons WHERE id=?", (baseline_id,))
        payload = json.loads(base["payload"])
        if (
            base["status"] != "active"
            or base["kind"] != "executable"
            or payload.get("engine") != self.runner.fingerprint
            or not self.learning.external_allowed(base)
        ):
            raise Blocked(
                "Workflow revision requires an active, current, externally authorized baseline"
            )
        if not isinstance(evidence, list) or not 1 <= len(evidence) <= 24:
            raise ContractError("Workflow revision requires bounded execution evidence")
        for key in evidence:
            op = self.store.one(
                "SELECT state FROM operations WHERE id=? AND task_id=?", (key, task)
            )
            if op["state"] not in ("completed", "saved"):
                raise Blocked(
                    "Workflow evidence must be completed operations from this task"
                )
        suite = self.store.get(
            "workflow_suite", base["asset_key"] + ":" + self.runner.fingerprint
        )["artifact"]
        # Repeated probing of a fixed holdout is not an unlimited optimization oracle.
        used = self.store.rows(
            "SELECT id FROM records WHERE kind='evaluation' AND json_extract(payload,'$.suite')=?",
            (suite,),
        )
        if len(used) >= 8:
            raise Blocked(
                "This protected suite has reached its evaluation budget; a fresh family-disjoint suite is required"
            )
        candidate = self.learning.propose(
            base["asset_key"],
            "executable",
            {
                **payload,
                "content": plan,
                "baseline": payload["content"],
                "evidence": sorted(set(payload["evidence"]) | set(evidence)),
                "parent_lesson": baseline_id,
            },
            identity="lesson_" + digest(operation_id)[:32],
        )
        result = self.evaluate(candidate, suite)
        if result["eligible"]:
            self.learning.promote(candidate, result["evaluation"], "evaluator")
        return {**result, "candidate": candidate, "promoted": result["eligible"]}
