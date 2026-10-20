"""Protected comparative evaluation for knowledge, procedures and executables.

Evaluators are trusted host callables, never model-supplied code or scores.
The same interface supports domain rollouts without coupling learning to RE.
"""

import json
import math
import statistics
import time
from types import SimpleNamespace
import sqlite3
from .workflows import matches
from hivemind_assembly.core.artifacts import Artifacts
from hivemind_assembly.core.common import Blocked, ContractError, canonical, digest, uid
from hivemind_assembly.vendor.skillopt.gate import evaluate_gate
from hivemind_assembly.vendor.shinka.parents import BeamSearchSamplingStrategy


class EvolutionArchive:
    def __init__(self, store):
        self.store = store

    def record(self, asset, content, engine, evaluation, correct, score, parent=None):
        if type(correct) is not bool or not math.isfinite(score):
            raise ContractError("Archive fitness must be a finite measured score")
        key = (
            "program_"
            + digest(
                {
                    "asset": asset,
                    "content": content,
                    "engine": engine,
                    "evaluation": evaluation,
                }
            )[:32]
        )
        generation = 0
        if parent:
            previous = self.store.get("evolution_program", parent)
            if previous["asset"] != asset or previous["engine"] != engine:
                raise Blocked("Evolution parent belongs to a different asset or engine")
            generation = previous["generation"] + 1
        row = {
            "id": key,
            "asset": asset,
            "content": content,
            "engine": engine,
            "evaluation": evaluation,
            "correct": correct,
            "combined_score": score,
            "parent_id": parent,
            "generation": generation,
        }
        self.store.put("evolution_program", key, row)
        return key

    def parent(self, asset, engine):
        rows = [
            json.loads(r["payload"])
            for r in self.store.rows(
                "SELECT payload FROM records WHERE kind='evolution_program' ORDER BY rowid"
            )
        ]
        rows = [r for r in rows if r["asset"] == asset and r["engine"] == engine]
        good = [r for r in rows if r["correct"]]
        if not good:
            return None
        best = max(good, key=lambda r: (r["combined_score"], -r["generation"]))
        # Feed the upstream selector a bounded view of this asset's archive.
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            conn.execute(
                "CREATE TABLE programs(id TEXT,parent_id TEXT,correct INTEGER)"
            )
            conn.executemany(
                "INSERT INTO programs VALUES(?,?,?)",
                [(r["id"], r["parent_id"], r["correct"]) for r in rows],
            )
            lookup = {r["id"]: SimpleNamespace(**r) for r in rows}
            sampler = BeamSearchSamplingStrategy(
                conn.cursor(),
                conn,
                SimpleNamespace(num_beams=5),
                lookup.get,
                best_program_id=best["id"],
                get_best_program_func=lambda: lookup[best["id"]],
            )
            return vars(sampler.sample_parent())
        finally:
            conn.close()


class Experiments:
    def __init__(self, store, evaluator, fingerprint):
        self.store, self.evaluator, self.fingerprint = store, evaluator, fingerprint
        self.assets = Artifacts(store)

    def protect(self, cases):
        if not isinstance(cases, list) or not 2 <= len(cases) <= 128:
            raise ContractError("Experiments require 2–128 independent cases")
        groups = {"regression": set(), "holdout": set()}
        projects = {"regression": set(), "holdout": set()}
        ids = set()
        for c in cases:
            if (
                set(c) != {"id", "family", "project", "split", "inputs", "expected"}
                or c["split"] not in groups
                or not all(
                    isinstance(c[k], str) and c[k] for k in ("id", "family", "project")
                )
                or c["id"] in ids
            ):
                raise ContractError("Invalid experiment case identity or split")
            ids.add(c["id"])
            groups[c["split"]].add(c["family"])
            projects[c["split"]].add(c["project"])
        if (
            not all(groups.values())
            or groups["regression"] & groups["holdout"]
            or projects["regression"] & projects["holdout"]
        ):
            raise Blocked(
                "Holdout families and projects must be disjoint from regression cases"
            )
        if len(canonical(cases)) > 2_000_000:
            raise ContractError("Experiment corpus exceeds bounds")
        return self.assets.add(
            canonical({"engine": self.fingerprint, "cases": cases}),
            "learning-holdouts.json",
            classification="protected",
        )["id"]

    def evaluate(self, candidate, baseline_content, suite, repeats=5):
        if type(repeats) is not int or not 3 <= repeats <= 15:
            raise ContractError("Use 3–15 paired repetitions")
        row = self.store.one("SELECT * FROM lessons WHERE id=?", (candidate,))
        if row["status"] != "candidate":
            raise Blocked("Only candidates can be evaluated")
        payload = json.loads(row["payload"])
        if row["predecessor"]:
            old = json.loads(
                self.store.one(
                    "SELECT payload FROM lessons WHERE id=?", (row["predecessor"],)
                )["payload"]
            )
            if old["content"] != baseline_content:
                raise Blocked("Baseline differs from the active asset")
        if (
            self.store.one("SELECT classification FROM artifacts WHERE id=?", (suite,))[
                "classification"
            ]
            != "protected"
        ):
            raise Blocked("Evaluation corpus must be protected")
        retained = json.loads(self.assets.read(suite, "evaluator"))
        if retained["engine"] != self.fingerprint:
            raise Blocked(
                "Evaluator fingerprint changed; rebuild the evaluation corpus"
            )
        results = {"baseline": {}, "trial": {}}
        samples = {}
        for case in retained["cases"]:
            timing = {"baseline": [], "trial": []}
            passed = {"baseline": True, "trial": True}
            for n in range(repeats):
                for name in (
                    ("baseline", "trial") if n % 2 == 0 else ("trial", "baseline")
                ):
                    start = time.perf_counter()
                    try:
                        content = (
                            baseline_content
                            if name == "baseline"
                            else payload["content"]
                        )
                        # Fresh copies prevent a rollout mutating the next trial or truth.
                        output = self.evaluator(
                            json.loads(canonical(content)),
                            json.loads(canonical(case["inputs"])),
                        )
                        ok = matches(output, case["expected"])
                    except Exception:
                        ok = False
                    timing[name].append(time.perf_counter() - start)
                    passed[name] &= ok
            samples[case["id"]] = timing
            for name in results:
                results[name][case["id"]] = {
                    "passed": bool(passed[name]),
                    "elapsed": statistics.median(timing[name]),
                }
        return self.finish(candidate, baseline_content, suite, results, samples)

    def finish(
        self, candidate, baseline_content, suite, results, samples, timing_valid=True
    ):
        row = self.store.one("SELECT * FROM lessons WHERE id=?", (candidate,))
        payload = json.loads(row["payload"])
        retained = json.loads(self.assets.read(suite, "evaluator"))
        if retained["engine"] != self.fingerprint:
            raise Blocked("Evaluation engine changed")
        ids = {case["id"] for case in retained["cases"]}
        if set(results) != {"baseline", "trial"} or set(samples) != ids:
            raise ContractError(
                "Evaluation evidence does not cover the protected corpus"
            )
        for arm in ("baseline", "trial"):
            if set(results[arm]) != ids:
                raise ContractError("Evaluation evidence is missing protected cases")
            for key, value in results[arm].items():
                measurements = samples[key].get(arm, [])
                if (
                    type(value.get("passed")) is not bool
                    or not 3 <= len(measurements) <= 15
                ):
                    raise ContractError(
                        "Evaluation requires boolean outcomes and paired repetitions"
                    )
                if any(
                    type(t) not in (int, float) or not math.isfinite(t) or t < 0
                    for t in measurements
                ):
                    raise ContractError(
                        "Evaluation timings must be finite and nonnegative"
                    )
                if value.get("elapsed") != statistics.median(measurements):
                    raise ContractError(
                        "Evaluation timing summary differs from retained samples"
                    )
                if len(measurements) != len(samples[key].get("baseline", [])):
                    raise ContractError("Evaluation repetitions are not paired")
        baseline, trial = results["baseline"], results["trial"]
        count = len(trial)
        bscore = sum(v["passed"] for v in baseline.values()) / count
        tscore = sum(v["passed"] for v in trial.values()) / count
        btime = sum(v["elapsed"] for v in baseline.values())
        ttime = sum(v["elapsed"] for v in trial.values())
        gain = 1 - ttime / btime if btime else 0
        no_regression = all(
            not baseline[k]["passed"] or v["passed"] for k, v in trial.items()
        )
        holdouts = [c["id"] for c in retained["cases"] if c["split"] == "holdout"]
        no_slowdown = all(
            trial[k]["elapsed"] <= v["elapsed"] * 1.15
            for k, v in baseline.items()
            if v["passed"]
        )
        gate = evaluate_gate(
            canonical(payload["content"]),
            tscore + max(0, gain) * 0.001,
            canonical(baseline_content),
            bscore,
            canonical(baseline_content),
            bscore,
            0,
            1,
        )
        eligible = (
            no_regression
            and all(trial[k]["passed"] for k in holdouts)
            and (tscore > bscore or (timing_valid and no_slowdown and gain >= 0.05))
            and gate.action != "reject"
        )
        result = {
            "candidate": candidate,
            "baseline": baseline,
            "trial": trial,
            "holdouts": holdouts,
            "suite": suite,
            "engine": self.fingerprint,
            "criteria": {"min_speed_gain": 0.05, "max_case_slowdown": 0.15},
            "eligible": eligible,
            "speed_gain": gain,
            "skillopt_gate": gate.action,
            "samples": samples,
            "cross_project": True,
            "timing_valid": timing_valid,
        }
        key = uid("evaluation")
        self.store.put("evaluation", key, result)
        archive = EvolutionArchive(self.store)
        parent = archive.parent(row["asset_key"], self.fingerprint)
        archive.record(
            row["asset_key"],
            payload["content"],
            self.fingerprint,
            key,
            all(v["passed"] for v in trial.values()),
            tscore + max(0, gain) * 0.001,
            parent["id"] if parent else None,
        )
        return {
            "evaluation": key,
            "eligible": eligible,
            "speed_gain": gain,
            "passed_cases": sum(v["passed"] for v in trial.values()),
            "cases": count,
        }
