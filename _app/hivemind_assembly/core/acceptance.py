"""Controller-owned acceptance; model proposals never define their own checks."""

import json
import time
from .common import Blocked, Conflict, ContractError, canonical, digest


class Acceptance:
    def __init__(self, controller, broker):
        self.controller, self.broker = controller, broker
        self.store = controller.store

    def verifier(self, scope):
        if scope == "native_tool_tests":
            from .test_acceptance import NativeTestAcceptance

            return NativeTestAcceptance(self.store)
        return getattr(self.broker.domain, "acceptance", None)

    def configure(self, task_id, specification):
        verifier = self.verifier(specification.get("scope"))
        if verifier is None:
            raise Blocked("This domain has no independent acceptance verifier")
        task = self.store.task(task_id)
        if (
            task["owner"]
            or task["step"]
            or task["status"]
            not in ("queued", "paused", "waiting_quota", "waiting_setup")
        ):
            raise Blocked("Define acceptance before the task starts")
        previous = self.store.rows(
            "SELECT payload FROM records WHERE kind='acceptance_contract' AND id=?",
            (task_id,),
        )
        if previous:
            if json.loads(previous[0]["payload"]).get("specification_hash") == digest(
                specification
            ):
                return self.describe(task_id)
            raise Conflict("Acceptance contract is already pinned")
        # Preparation may read files; check state again inside the transaction.
        contract = verifier.prepare(
            self.broker.workspace(task_id),
            specification,
            self.broker.artifacts,
            task["project_id"],
            self.broker.context(task_id),
        )
        contract.update(
            task_id=task_id,
            domain=(
                "core.native_tests"
                if specification.get("scope") == "native_tool_tests"
                else self.broker.domain.id
            ),
            specification_hash=digest(specification),
        )
        with self.store.tx() as c:
            current = dict(
                c.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            )
            if (
                current["owner"]
                or current["step"]
                or current["status"]
                not in ("queued", "paused", "waiting_quota", "waiting_setup")
            ):
                raise Blocked("Define acceptance before the task starts")
            if c.execute(
                "SELECT 1 FROM operations WHERE task_id=?", (task_id,)
            ).fetchone():
                raise Blocked("Acceptance cannot be changed after execution")
            self.store.put("acceptance_contract", task_id, contract, c)
            if current["status"] == "waiting_setup":
                c.execute(
                    "UPDATE tasks SET status='queued',blocker='',updated=? WHERE id=?",
                    (time.time(), task_id),
                )
                self.store.event(task_id, "queued", {"blocker": ""}, c)
        return self.describe(task_id)

    def describe(self, task_id):
        rows = self.store.rows(
            "SELECT payload FROM records WHERE kind='acceptance_contract' AND id=?",
            (task_id,),
        )
        if not rows:
            return None
        contract = json.loads(rows[0]["payload"])
        return {
            "scope": contract["scope"],
            "checks": [
                {k: v for k, v in check.items() if not k.endswith("_artifact")}
                for check in contract["checks"]
            ],
        }

    def evaluate(self, task, response):
        ids = response.get("result_operations")
        if (
            not isinstance(ids, list)
            or not ids
            or len(ids) > 100
            or any(not isinstance(x, str) for x in ids)
        ):
            raise ContractError("Completion requires a bounded list of operation IDs")
        # A stable proposal ID makes a crash after validation safe to resume.
        proposal = "proposal_" + digest(
            {"task": task["id"], "epoch": task["epoch"], "response": response}
        )
        with self.store.tx() as c:
            current = self.controller._fence(
                c, task["id"], task["owner"], task["epoch"]
            )
            revision = c.execute(
                "SELECT revision FROM projects WHERE id=?", (current["project_id"],)
            ).fetchone()[0]
            previous = c.execute(
                "SELECT payload FROM records WHERE kind='acceptance_result' AND id=?",
                (proposal,),
            ).fetchone()
            if previous:
                value = json.loads(previous[0])
                if value["revision"] != revision:
                    raise Conflict("Completion evidence belongs to a previous revision")
                return value
            for key in ids:
                op = c.execute(
                    "SELECT * FROM operations WHERE id=? AND task_id=?",
                    (key, task["id"]),
                ).fetchone()
                if not op or op["state"] not in ("completed", "saved"):
                    raise Blocked("Completion cites a missing or unfinished operation")
            if c.execute(
                "SELECT 1 FROM operations o JOIN tasks t ON t.id=o.task_id WHERE t.project_id=? AND o.state IN ('running','uncertain','applied')",
                (task["project_id"],),
            ).fetchone():
                raise Blocked("Project operations must settle before acceptance")
            self.store.put(
                "completion_proposal",
                proposal,
                {"task_id": task["id"], "response": response},
                c,
            )

        contract = self.describe(task["id"])
        if contract is None:
            result = {
                "passed": False,
                "status": "awaiting_acceptance",
                "reason": "No objective-specific acceptance contract is configured",
            }
        else:
            retained = self.store.get("acceptance_contract", task["id"])
            if retained["domain"] != (
                "core.native_tests"
                if retained["scope"] == "native_tool_tests"
                else self.broker.domain.id
            ):
                raise Blocked("Acceptance domain changed")
            result = self.verifier(retained["scope"]).verify(
                self.broker.workspace(task["id"]),
                retained,
                self.broker.artifacts,
                task["project_id"],
                self.broker.context(task["id"]),
            )
            result["status"] = "accepted" if result["passed"] else "rejected"
        evidence = self.broker.artifacts.add(
            canonical(result), "acceptance.json", task["project_id"]
        )
        with self.store.tx() as c:
            self.controller._fence(c, task["id"], task["owner"], task["epoch"])
            if (
                c.execute(
                    "SELECT revision FROM projects WHERE id=?", (task["project_id"],)
                ).fetchone()[0]
                != revision
            ):
                raise Conflict("Project changed during independent acceptance")
            if contract is not None:
                self.verifier(retained["scope"]).recheck(
                    self.broker.workspace(task["id"]), result
                )
            if c.execute(
                "SELECT 1 FROM operations o JOIN tasks t ON t.id=o.task_id WHERE t.project_id=? AND o.state IN ('running','uncertain','applied')",
                (task["project_id"],),
            ).fetchone():
                raise Conflict("Project operation started during acceptance")
            value = {
                **result,
                "task_id": task["id"],
                "revision": revision,
                "artifact": evidence["id"],
                "proposal": proposal,
            }
            self.store.put("acceptance_result", proposal, value, c)
            task_status = (
                "running" if result["status"] == "rejected" else result["status"]
            )
            c.execute(
                "UPDATE tasks SET status=?,blocker=?,lease_until=CASE WHEN ?='running' THEN lease_until ELSE 0 END,updated=? WHERE id=?",
                (
                    task_status,
                    result.get("reason", ""),
                    task_status,
                    time.time(),
                    task["id"],
                ),
            )
            if task_status != "running":
                c.execute("DELETE FROM reservations WHERE task=?", (task["id"],))
            self.store.event(
                task["id"],
                result["status"],
                {"evidence": evidence["id"], "scope": result.get("scope")},
                c,
            )
            from .goals import Goals

            Goals(self.store).accepted(task["id"], value, c)
        return value
