"""Native model experiments with sealed truth and isolated trial conversations.

Only the task input and one treatment are sent to a trial. The model cannot
select cases, read expected outputs, see scores, or grade/promote its own work.
Paired repetitions are retained individually so quota waits and restarts resume.
"""

import asyncio
from contextlib import nullcontext
import json
import statistics
import time
from .engine import Learning
from .experiments import Experiments
from hivemind_assembly.core.common import (
    AllowanceUnavailable,
    Blocked,
    ContractError,
    digest,
    uid,
)


class NativeRollouts:
    def __init__(
        self,
        store,
        controller,
        sessions,
        availability,
        verifier,
        fingerprint,
        budget=None,
        policy=None,
    ):
        self.store, self.controller, self.sessions = store, controller, sessions
        self.availability, self.verifier, self.fingerprint = (
            availability,
            verifier,
            fingerprint,
        )
        self.experiments = Experiments(store, None, fingerprint)
        self.locks = {}
        self.budget = budget or (lambda *_: nullcontext())
        self.policy = policy

    def protect(self, cases):
        return self.experiments.protect(cases)

    def bind(self, candidate, suite, route=None, repeats=3):
        route = (
            self.policy.choose(route)
            if self.policy is not None
            else route or "worker.extra"
        )
        selection = self.policy.selection(route) if self.policy is not None else {}
        if route not in ("worker.opus", "worker.astra", "worker.extra"):
            raise ContractError("Native learning requires a designated worker route")
        if type(repeats) is not int or not 3 <= repeats <= 15:
            raise ContractError("Native trials require 3–15 paired repetitions")
        row = self.store.one("SELECT * FROM lessons WHERE id=?", (candidate,))
        if row["status"] != "candidate" or row["kind"] not in (
            "knowledge",
            "procedure",
        ):
            raise Blocked("Only knowledge/procedure candidates can enter native trials")
        payload = json.loads(row["payload"])
        if not Learning(self.store).external_allowed(row):
            raise Blocked(
                "Owner permission is required before sending this asset to a native provider"
            )
        baseline = None
        if row["predecessor"]:
            old = self.store.one(
                "SELECT * FROM lessons WHERE id=?", (row["predecessor"],)
            )
            if old["status"] != "active" or not Learning(self.store).external_allowed(
                old
            ):
                raise Blocked("Baseline must remain active and shareable")
            baseline = json.loads(old["payload"])["content"]
        info = self.store.one(
            "SELECT classification FROM artifacts WHERE id=?", (suite,)
        )
        if info["classification"] != "protected":
            raise Blocked("Native rollout truth must be protected")
        corpus = json.loads(self.experiments.assets.read(suite, "evaluator"))
        if corpus["engine"] != self.fingerprint:
            raise Blocked("Native evaluator changed; rebuild its corpus")
        key = (
            "native_eval_"
            + digest(
                {
                    "candidate": candidate,
                    "suite": suite,
                    "route": route,
                    "repeats": repeats,
                    "engine": self.fingerprint,
                    "model_selection": selection,
                }
            )[:32]
        )
        spec = {
            "candidate": candidate,
            "suite": suite,
            "route": route,
            "model_selection": selection,
            "repeats": repeats,
            "engine": self.fingerprint,
            "baseline": baseline,
            "trial": payload["content"],
            "predecessor": row["predecessor"],
            "asset": row["asset_key"],
        }
        with self.store.tx() as db:
            old = db.execute(
                "SELECT 1 FROM records WHERE kind='native_evaluation' AND id=?", (key,)
            ).fetchone()
            if not old:
                budget = db.execute(
                    "SELECT COUNT(*) FROM records WHERE kind='native_evaluation' AND json_extract(payload,'$.asset')=? AND json_extract(payload,'$.suite')=?",
                    (row["asset_key"], suite),
                ).fetchone()[0]
                if budget >= 8:
                    raise Blocked(
                        "This protected suite has reached its eight-candidate evaluation budget"
                    )
                self.store.put("native_evaluation", key, spec, db)
        return key

    def state(self, key, stage, **extra):
        value = {"id": key, "stage": stage, **extra}
        self.store.put("native_evaluation_state:" + key, uid("state"), value)
        return value

    def status(self, key):
        rows = self.store.rows(
            "SELECT payload FROM records WHERE kind=? ORDER BY created DESC LIMIT 1",
            ("native_evaluation_state:" + key,),
        )
        return (
            json.loads(rows[0]["payload"]) if rows else {"id": key, "stage": "queued"}
        )

    def resume(self, key):
        spec = self.store.get("native_evaluation", key)
        if self.status(key)["stage"] not in (
            "attention",
            "paused_policy",
            "waiting_quota",
        ):
            raise Blocked("Only a paused or blocked evaluation can be resumed")
        self.check_current(spec)
        # Keep the evaluation, pinned model, sample IDs and retained deliveries.
        # Retrying must never create a fresh trial to evade an uncertain send.
        return self.state(key, "queued")

    def check_current(self, spec, *, promoting=False):
        if self.policy is not None:
            self.policy.require(spec["route"])
        if spec["engine"] != self.fingerprint:
            raise Blocked("Native evaluator changed; trial cannot resume")
        candidate = self.store.one(
            "SELECT * FROM lessons WHERE id=?", (spec["candidate"],)
        )
        if not Learning(self.store).external_allowed(candidate):
            raise Blocked("Native evaluation permission was revoked")
        if json.loads(candidate["payload"])["content"] != spec["trial"]:
            raise Blocked("Native trial content changed")
        if candidate["status"] != "candidate" and not (
            promoting and candidate["status"] == "active"
        ):
            raise Blocked("Native trial candidate is no longer eligible")
        if spec["predecessor"] and candidate["status"] != "active":
            baseline = self.store.one(
                "SELECT * FROM lessons WHERE id=?", (spec["predecessor"],)
            )
            if baseline["status"] != "active" or not Learning(
                self.store
            ).external_allowed(baseline):
                raise Blocked(
                    "Native evaluation baseline changed or permission was revoked"
                )
            if json.loads(baseline["payload"])["content"] != spec["baseline"]:
                raise Blocked("Native evaluation baseline content changed")

    async def run(self, key):
        async with self.locks.setdefault(key, asyncio.Lock()):
            old = self.store.rows(
                "SELECT payload FROM records WHERE kind='native_evaluation_result' AND id=?",
                (key,),
            )
            if old:
                return self.finish(key, json.loads(old[0]["payload"]))
            spec = self.store.get("native_evaluation", key)
            self.check_current(spec)
            corpus = json.loads(
                self.experiments.assets.read(spec["suite"], "evaluator")
            )
            route = spec["route"]
            results, samples, timing_valid = {"baseline": {}, "trial": {}}, {}, True
            total = len(corpus["cases"]) * spec["repeats"] * 2
            done = 0
            for case in corpus["cases"]:
                timing = {"baseline": [], "trial": []}
                passed = {"baseline": True, "trial": True}
                for n in range(spec["repeats"]):
                    for treatment in (
                        ("baseline", "trial") if n % 2 == 0 else ("trial", "baseline")
                    ):
                        trial_id = (
                            "trial_"
                            + digest(
                                {
                                    "evaluation": key,
                                    "case": case["id"],
                                    "n": n,
                                    "arm": treatment,
                                }
                            )[:32]
                        )
                        retained = self.store.rows(
                            "SELECT payload FROM records WHERE kind='native_trial_result' AND id=?",
                            (trial_id,),
                        )
                        if retained:
                            value = json.loads(retained[0]["payload"])
                        else:
                            self.check_current(spec)
                            available = self.availability(route)
                            eligible = (
                                self.policy.eligible(route, available)
                                if self.policy is not None
                                else available is not None and available.eligible()
                            )
                            if not eligible:
                                self.state(
                                    key, "waiting_quota", completed=done, total=total
                                )
                                raise AllowanceUnavailable(
                                    "Native evaluation waits for scheduled allowance admission"
                                )
                            # All samples get a fresh context, including the baseline.
                            # Neither active project conversation nor another trial is reused.
                            reservation = (
                                self.policy.reservation_observation(available)
                                if self.policy is not None
                                else available
                            )
                            with self.budget(route, trial_id, reservation):
                                if self.policy is not None:
                                    self.policy.reserve(key, trial_id + "_session")
                                    self.policy.reserve(key, trial_id)
                                pinned = self.store.rows(
                                    "SELECT payload FROM records WHERE kind='native_evaluation_model' AND id=?",
                                    (key,),
                                )
                                selection = (
                                    {"target": json.loads(pinned[0]["payload"])}
                                    if pinned
                                    else spec.get("model_selection", {})
                                )
                                browser = await self.sessions.isolated_browser(
                                    key, route, trial_id + "_session", **selection
                                )
                                self.check_current(spec)
                                cfg = browser.config["routes"][route]
                                if self.policy is not None:
                                    selected = {
                                        field: cfg[field]
                                        for field in ("model", "effort")
                                    }
                                    if (
                                        pinned
                                        and json.loads(pinned[0]["payload"]) != selected
                                    ):
                                        raise Blocked(
                                            "Experimental model changed within the paired evaluation"
                                        )
                                    self.store.put(
                                        "native_evaluation_model", key, selected
                                    )
                                    self.store.event(
                                        key,
                                        "experimental_model_selected",
                                        {
                                            **selected,
                                            "route": route,
                                            "allowance_known": available.allowance_known,
                                            "ha_turn_limit": self.policy.settings()[
                                                "max_turns_per_evaluation"
                                            ],
                                        },
                                    )
                                payload = {
                                    "instruction": "Solve the bounded task below using the supplied method when applicable. Return one JSON object with request_id, type rollout_result and output. Do not evaluate or score your response. Do not claim any external execution.",
                                    "task": case["inputs"],
                                    "method": spec[treatment],
                                }
                                rows = self.store.rows(
                                    "SELECT * FROM messages WHERE id=?", (trial_id,)
                                )
                                message = (
                                    rows[0]
                                    if rows
                                    else self.controller.prepare_message(
                                        key,
                                        route,
                                        cfg["conversation_url"],
                                        payload,
                                        trial_id,
                                    )
                                )
                                # Recovery is valid correctness evidence; an interrupted
                                # sample is excluded from any speed-only promotion claim.
                                fresh = not rows
                                started = time.perf_counter()
                                self.state(key, "running", completed=done, total=total)
                                if message["state"] == "validated":
                                    response = json.loads(message["response"])
                                else:
                                    response = await browser.exchange(route, message)
                                elapsed = time.perf_counter() - started
                                self.check_current(spec)
                                if response.get("type") != "rollout_result":
                                    output = None
                                else:
                                    output = response.get("output")
                                try:
                                    ok = await asyncio.to_thread(
                                        self.verifier, output, case["expected"]
                                    )
                                    if type(ok) is not bool:
                                        raise ContractError(
                                            "Trusted native verifier must return a boolean"
                                        )
                                except Exception:
                                    ok = False
                                value = {
                                    "passed": ok,
                                    "elapsed": elapsed,
                                    "timing_valid": fresh,
                                    "response_hash": digest(output),
                                    "engine": self.fingerprint,
                                }
                                self.store.put("native_trial_result", trial_id, value)
                                release = getattr(
                                    self.sessions, "release_isolated", None
                                )
                                if release is not None:
                                    await release(trial_id + "_session")
                        passed[treatment] &= value["passed"]
                        timing[treatment].append(value["elapsed"])
                        timing_valid &= value["timing_valid"]
                        done += 1
                samples[case["id"]] = timing
                for treatment in results:
                    results[treatment][case["id"]] = {
                        "passed": bool(passed[treatment]),
                        "elapsed": statistics.median(timing[treatment]),
                    }
            result = self.experiments.finish(
                spec["candidate"],
                spec["baseline"],
                spec["suite"],
                results,
                samples,
                timing_valid,
            )
            # Store the scoring result before promotion so a lost acknowledgement
            # never triggers another model rollout or changes the baseline.
            self.store.put("native_evaluation_result", key, result)
            return self.finish(key, result)

    def finish(self, key, result=None):
        spec = self.store.get("native_evaluation", key)
        result = result or self.store.get("native_evaluation_result", key)
        row = self.store.one("SELECT * FROM lessons WHERE id=?", (spec["candidate"],))
        self.check_current(spec, promoting=True)
        if result["eligible"] and row["status"] == "candidate":
            self.store.put(
                "native_asset_engine",
                spec["candidate"],
                {"engine": self.fingerprint, "evaluation": key},
            )
            Learning(self.store).promote(
                spec["candidate"], result["evaluation"], "evaluator"
            )
        return self.state(
            key, "promoted" if result["eligible"] else "not_promoted", **result
        )
