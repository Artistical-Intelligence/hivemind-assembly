import time, json, math
from hivemind_assembly.core.common import uid, canonical, ContractError, Blocked


class Learning:
    def __init__(self, store):
        self.store = store

    def external_allowed(self, row):
        rows = self.store.rows(
            "SELECT payload FROM records WHERE kind=? ORDER BY created DESC LIMIT 1",
            ("lesson_permission:" + row["id"],),
        )
        return (
            json.loads(rows[0]["payload"])["allowed"]
            if rows
            else json.loads(row["payload"]).get("external_allowed", False)
        )

    def share(self, lesson, allowed):
        if type(allowed) is not bool:
            raise ContractError("External permission must be boolean")
        self.store.one("SELECT id FROM lessons WHERE id=?", (lesson,))
        self.store.put(
            "lesson_permission:" + lesson, uid("permission"), {"allowed": allowed}
        )
        return {"lesson": lesson, "external_allowed": allowed}

    def propose(self, asset_key, kind, payload, identity=None):
        if kind not in ("knowledge", "procedure", "executable", "counterexample"):
            raise ContractError("Unknown learning asset type")
        required = {"scope", "preconditions", "exclusions", "evidence", "content"}
        if not required <= payload.keys() or not payload["evidence"]:
            raise ContractError(
                "Learning requires scope, conditions and actual evidence"
            )
        key = identity or uid("lesson")
        with self.store.tx() as c:
            existing = c.execute(
                "SELECT asset_key,kind,payload FROM lessons WHERE id=?", (key,)
            ).fetchone()
            if existing:
                if tuple(existing) != (asset_key, kind, canonical(payload)):
                    raise ContractError("Learning proposal identity changed")
                return key
            version = c.execute(
                "SELECT COALESCE(MAX(version),0)+1 FROM lessons WHERE asset_key=?",
                (asset_key,),
            ).fetchone()[0]
            predecessor = c.execute(
                "SELECT id FROM lessons WHERE asset_key=? AND status='active'",
                (asset_key,),
            ).fetchone()
            c.execute(
                "INSERT INTO lessons VALUES(?,?,?,?,?,?,?,?)",
                (
                    key,
                    asset_key,
                    version,
                    kind,
                    "candidate",
                    canonical(payload),
                    predecessor[0] if predecessor else None,
                    time.time(),
                ),
            )
        return key

    def evaluate(
        self, candidate, baseline_results, trial_results, holdout_ids, criteria, role
    ):
        if role != "evaluator":
            raise Blocked("Only independent evaluator can create promotion evidence")
        if not holdout_ids or not set(holdout_ids) <= set(trial_results):
            raise Blocked("Missing held-out evaluations")
        if not set(baseline_results) <= set(trial_results):
            raise Blocked("Missing regression evaluations")
        gain = criteria.get("min_speed_gain", 0.05)
        if (
            not isinstance(gain, (int, float))
            or not math.isfinite(gain)
            or not 0 <= gain < 1
        ):
            raise ContractError("Invalid minimum speed improvement")
        for values in (baseline_results, trial_results):
            for value in values.values():
                if type(value.get("passed")) is not bool:
                    raise ContractError("Evaluation outcomes must be boolean")
                elapsed = value.get("elapsed", 0)
                if (
                    not isinstance(elapsed, (int, float))
                    or not math.isfinite(elapsed)
                    or elapsed < 0
                ):
                    raise ContractError(
                        "Evaluation timings must be finite and nonnegative"
                    )
        no_regression = all(
            not old["passed"] or trial_results[k]["passed"]
            for k, old in baseline_results.items()
        )
        holdouts = all(trial_results[k]["passed"] for k in holdout_ids)
        improved = any(
            v["passed"]
            and (
                not baseline_results[k]["passed"]
                or v.get("elapsed", 1e99)
                < baseline_results[k].get("elapsed", 0) * (1 - gain)
            )
            for k, v in trial_results.items()
            if k in baseline_results
        )
        result = {
            "candidate": candidate,
            "baseline": baseline_results,
            "trial": trial_results,
            "holdouts": holdout_ids,
            "criteria": criteria,
            "eligible": no_regression and holdouts and improved,
        }
        key = uid("evaluation")
        self.store.put("evaluation", key, result)
        return key

    def promote(self, candidate, evaluation, role):
        if role != "evaluator":
            raise Blocked("Protected evaluator promotion required")
        result = self.store.get("evaluation", evaluation)
        if result["candidate"] != candidate or not result["eligible"]:
            raise Blocked("Independent evaluation does not justify promotion")
        with self.store.tx() as c:
            row = c.execute("SELECT * FROM lessons WHERE id=?", (candidate,)).fetchone()
            if not row or row["status"] != "candidate":
                raise ContractError("Not a candidate")
            active = c.execute(
                "SELECT id FROM lessons WHERE asset_key=? AND status='active'",
                (row["asset_key"],),
            ).fetchone()
            if (active[0] if active else None) != row["predecessor"]:
                raise Blocked(
                    "Active learning baseline changed; re-evaluate against the current version"
                )
            c.execute(
                "UPDATE lessons SET status='superseded' WHERE asset_key=? AND status='active'",
                (row["asset_key"],),
            )
            c.execute("UPDATE lessons SET status='active' WHERE id=?", (candidate,))
            self.store.event(candidate, "promoted", {"evaluation": evaluation}, c)

    def rollback(self, candidate):
        with self.store.tx() as c:
            row = c.execute("SELECT * FROM lessons WHERE id=?", (candidate,)).fetchone()
            if not row or row["status"] != "active":
                raise ContractError("Only active assets can be rolled back")
            c.execute(
                "UPDATE lessons SET status='rolled_back' WHERE id=?", (candidate,)
            )
            if row["predecessor"]:
                c.execute(
                    "UPDATE lessons SET status='active' WHERE id=?",
                    (row["predecessor"],),
                )
            self.store.event(candidate, "rolled_back", {}, c)

    def applicable(self, domain, external=False):
        result = []
        for row in self.store.rows(
            "SELECT * FROM lessons WHERE status='active' ORDER BY created DESC"
        ):
            payload = json.loads(row["payload"])
            if domain not in payload["scope"] or (
                external and not self.external_allowed(row)
            ):
                continue
            result.append(
                {
                    "id": row["id"],
                    "kind": row["kind"],
                    "version": row["version"],
                    **{
                        k: payload[k]
                        for k in ("scope", "preconditions", "exclusions", "content")
                    },
                }
            )
            if len(result) == 12:
                break
        return result

    def capture_accepted(self, task_id, acceptance):
        """Retain evidence as candidates, without mistaking one success for generality."""
        if self.store.task(task_id)["status"] != "accepted" or not acceptance.get(
            "passed"
        ):
            raise Blocked("Learning trace requires an independently accepted task")
        old = self.store.rows(
            "SELECT payload FROM records WHERE kind='learning_capture' AND id=?",
            (acceptance["proposal"],),
        )
        if old:
            return json.loads(old[0]["payload"])
        operations = self.store.rows(
            "SELECT id,tool,args,result FROM operations WHERE task_id=? AND state IN ('completed','saved') ORDER BY created,id",
            (task_id,),
        )
        evidence = [acceptance["artifact"], *[op["id"] for op in operations]]
        common = {
            "scope": ["reverse_engineering"],
            "preconditions": [acceptance["scope"]],
            "exclusions": ["unverified platforms", "whole-program equivalence"],
            "evidence": evidence,
            "external_allowed": False,
        }
        knowledge = self.propose(
            "accepted-facts:" + task_id,
            "knowledge",
            {
                **common,
                "content": {
                    "checks": acceptance["checks"],
                    "revision": acceptance["revision"],
                },
            },
        )
        procedure = self.propose(
            "accepted-procedure:" + task_id,
            "procedure",
            {
                **common,
                "content": [
                    {"tool": op["tool"], "args": json.loads(op["args"])}
                    for op in operations
                ],
            },
        )
        result = {"knowledge": knowledge, "procedure": procedure}
        self.store.put("learning_capture", acceptance["proposal"], result)
        return result
