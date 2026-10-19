from __future__ import annotations
import time
from hivemind_assembly.core.common import (
    uid,
    digest,
    canonical,
    Conflict,
    Blocked,
    ContractError,
)


class Controller:
    """Domain ownership and operation journal. Never performs inference."""

    def __init__(self, store):
        self.store = store

    def acquire(self, task_id, owner, seconds=300):
        with self.store.tx() as c:
            t = dict(c.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())
            if t["status"] in (
                "cancelled",
                "accepted",
                "paused",
                "awaiting_acceptance",
            ):
                raise Blocked("Task is not runnable")
            pending = c.execute(
                "SELECT id FROM operations WHERE task_id=? AND state IN ('running','uncertain','applied')",
                (task_id,),
            ).fetchone()
            if pending:
                raise Blocked("Reconcile pending operations before ownership transfer")
            if t["owner"] and t["owner"] != owner and t["lease_until"] > time.time():
                raise Conflict("Writer lease is still held")
            epoch = t["epoch"] + 1
            c.execute(
                "UPDATE tasks SET owner=?,epoch=?,lease_until=?,status='running',updated=? WHERE id=?",
                (owner, epoch, time.time() + seconds, time.time(), task_id),
            )
            self.store.event(
                task_id, "lease_granted", {"owner": owner, "epoch": epoch}, c
            )
        return epoch

    def heartbeat(self, task, owner, epoch):
        with self.store.tx() as c:
            self._fence(c, task, owner, epoch)
            c.execute(
                "UPDATE tasks SET lease_until=? WHERE id=?", (time.time() + 300, task)
            )

    def _fence(self, c, task, owner, epoch):
        row = c.execute("SELECT * FROM tasks WHERE id=?", (task,)).fetchone()
        if not row:
            raise Conflict("Unknown task")
        t = dict(row)
        if t["owner"] != owner or t["epoch"] != epoch or t["lease_until"] < time.time():
            raise Conflict("Expired or stale writer lease")
        if t["status"] != "running":
            raise Blocked("Task is not running")
        return t

    def brief(self, task_id, intent, body, reading, skills):
        t = self.store.task(task_id)
        p = self.store.project(t["project_id"])
        if intent["revision"] != p["revision"]:
            raise Conflict("Stale step intent")
        if reading.get("critical_gaps"):
            raise Blocked("Critical reading obligations remain unresolved")
        if not body.get("acceptance") or not body.get("procedure"):
            raise ContractError("Brief requires procedure and falsifiable acceptance")
        key = uid("brief")
        payload = {
            "task_id": task_id,
            "intent": intent,
            "body": body,
            "reading": reading,
            "skills": skills,
            "revision": p["revision"],
        }
        with self.store.tx() as c:
            current = c.execute(
                "SELECT status FROM tasks WHERE id=?", (task_id,)
            ).fetchone()
            revision = c.execute(
                "SELECT revision FROM projects WHERE id=?", (t["project_id"],)
            ).fetchone()[0]
            if current[0] != "running" or revision != intent["revision"]:
                raise Conflict("Task or project changed before briefing was saved")
            self.store.put("brief", key, payload, c)
            c.execute(
                "UPDATE tasks SET brief_id=?,step=step+1 WHERE id=?", (key, task_id)
            )
        return key

    def begin(self, request, allowed):
        required = {"id", "task_id", "owner", "epoch", "revision", "tool", "args"}
        if not required <= request.keys():
            raise ContractError("Incomplete tool request")
        h = digest(request)
        now = time.time()
        with self.store.tx() as c:
            old = c.execute(
                "SELECT * FROM operations WHERE id=?", (request["id"],)
            ).fetchone()
            if old:
                if old["payload_hash"] != h:
                    raise Conflict("Operation ID reused with different payload")
                return dict(old), False
            t = self._fence(c, request["task_id"], request["owner"], request["epoch"])
            p = c.execute(
                "SELECT revision FROM projects WHERE id=?", (t["project_id"],)
            ).fetchone()
            if request["revision"] != p[0]:
                raise Conflict("Stale program revision")
            if request["tool"] not in allowed:
                raise Blocked("Capability not authorized for this role")
            if not t["brief_id"]:
                raise Blocked("Substantive operations require an adviser briefing")
            brief = self.store.get("brief", t["brief_id"])
            if brief["revision"] != request["revision"]:
                raise Blocked("Briefing invalidated by a revision change")
            if c.execute(
                "SELECT 1 FROM operations WHERE task_id=? AND state IN ('running','uncertain','applied')",
                (t["id"],),
            ).fetchone():
                raise Blocked("Previous operation must be reconciled first")
            c.execute(
                "INSERT INTO operations VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    request["id"],
                    t["id"],
                    request["owner"],
                    request["epoch"],
                    request["revision"],
                    request["tool"],
                    h,
                    canonical(request["args"]),
                    "running",
                    None,
                    now,
                    now,
                ),
            )
            self.store.event(
                t["id"],
                "operation_started",
                {"operation": request["id"], "tool": request["tool"]},
                c,
            )
        return (
            self.store.one("SELECT * FROM operations WHERE id=?", (request["id"],)),
            True,
        )

    def finish(self, op_id, result, mutated=False):
        with self.store.tx() as c:
            op = dict(
                c.execute("SELECT * FROM operations WHERE id=?", (op_id,)).fetchone()
            )
            if op["state"] not in ("running", "applied", "uncertain"):
                raise Conflict("Operation already settled")
            t = self._fence(c, op["task_id"], op["owner"], op["epoch"])
            revision = c.execute(
                "SELECT revision FROM projects WHERE id=?", (t["project_id"],)
            ).fetchone()[0]
            if revision != op["revision"]:
                raise Conflict("Project changed while operation was executing")
            if mutated:
                row = c.execute(
                    "SELECT revision FROM projects WHERE id=?", (t["project_id"],)
                ).fetchone()
                if row[0] != op["revision"]:
                    raise Conflict("Revision changed during operation")
                c.execute(
                    "UPDATE projects SET revision=revision+1 WHERE id=?",
                    (t["project_id"],),
                )
                c.execute("UPDATE tasks SET brief_id=NULL WHERE id=?", (t["id"],))
            state = "saved" if mutated else "completed"
            c.execute(
                "UPDATE operations SET state=?,result=?,updated=? WHERE id=?",
                (state, canonical(result), time.time(), op_id),
            )
            self.store.event(
                t["id"], "operation_" + state, {"operation": op_id, "result": result}, c
            )

    def fail(self, op_id, error, uncertain=False):
        with self.store.tx() as c:
            c.execute(
                "UPDATE operations SET state=?,result=?,updated=? WHERE id=?",
                (
                    "uncertain" if uncertain else "failed",
                    canonical({"error": str(error)}),
                    time.time(),
                    op_id,
                ),
            )

    def checkpoint(self, task, reason, next_action=""):
        t = self.store.task(task)
        p = self.store.project(t["project_id"])
        key = uid("checkpoint")
        pending = self.store.rows(
            "SELECT id,state FROM operations WHERE task_id=? AND state IN ('running','uncertain','applied')",
            (task,),
        )
        value = {
            "task": t,
            "project_revision": p["revision"],
            "reason": reason,
            "next_action": next_action,
            "pending_operations": pending,
            "operation_ids": [
                x["id"]
                for x in self.store.rows(
                    "SELECT id FROM operations WHERE task_id=?", (task,)
                )
            ],
        }
        self.store.put("checkpoint", key, value)
        return key

    def transfer(self, task, new_owner, reason):
        checkpoint = self.checkpoint(task, reason)
        with self.store.tx() as c:
            if c.execute(
                "SELECT 1 FROM operations WHERE task_id=? AND state IN ('running','uncertain','applied')",
                (task,),
            ).fetchone():
                raise Blocked("Unsafe handoff boundary")
            t = dict(c.execute("SELECT * FROM tasks WHERE id=?", (task,)).fetchone())
            if t["status"] in (
                "cancelled",
                "accepted",
                "paused",
                "awaiting_acceptance",
            ):
                raise Blocked("Task is not runnable")
            c.execute(
                "UPDATE tasks SET owner=?,epoch=epoch+1,lease_until=?,status='running',updated=? WHERE id=?",
                (new_owner, time.time() + 300, time.time(), task),
            )
            self.store.event(
                task,
                "handoff",
                {
                    "old": t["owner"],
                    "new": new_owner,
                    "checkpoint": checkpoint,
                    "reason": reason,
                },
                c,
            )
        return self.store.task(task)["epoch"]

    def recover(self):
        with self.store.tx() as c:
            c.execute(
                "UPDATE operations SET state='uncertain' WHERE state IN ('running','applied')"
            )
            c.execute(
                "UPDATE messages SET state='delivery_uncertain' WHERE state='dispatching'"
            )
            c.execute(
                "UPDATE tasks SET lease_until=0 WHERE status NOT IN ('accepted','cancelled')"
            )
        # Unknown external effects are never automatically replayed.
        return self.store.rows(
            "SELECT id,task_id,tool FROM operations WHERE state='uncertain'"
        )

    def prepare_message(self, task, route, conversation, payload, message_id=None):
        key = message_id or uid("msg")
        h = digest(payload)
        now = time.time()
        with self.store.tx() as c:
            old = c.execute("SELECT * FROM messages WHERE id=?", (key,)).fetchone()
            if old:
                if (
                    old["payload_hash"] != h
                    or old["route"] != route
                    or old["conversation"] != conversation
                ):
                    raise Conflict("Message identity changed")
                return dict(old)
            c.execute(
                "INSERT INTO messages VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    key,
                    task,
                    route,
                    conversation,
                    h,
                    canonical(payload),
                    "prepared",
                    None,
                    now,
                    now,
                ),
            )
        return self.store.one("SELECT * FROM messages WHERE id=?", (key,))

    def message_state(self, key, state, response=None):
        with self.store.tx() as c:
            c.execute(
                "UPDATE messages SET state=?,response=COALESCE(?,response),updated=? WHERE id=?",
                (state, response, time.time(), key),
            )
