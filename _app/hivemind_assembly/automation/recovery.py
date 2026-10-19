from __future__ import annotations
import json
import time
from hivemind_assembly.core.common import digest, uid, Blocked


class Recovery:
    """Classify transport failures separately from evidence of repeated reasoning failure."""

    def __init__(self, store):
        self.store = store

    def defer(self, task, reason, now=None):
        now = time.time() if now is None else now
        delays = (5, 15, 60, 300, 900, 3600)
        with self.store.tx() as c:
            current = c.execute(
                "SELECT status FROM tasks WHERE id=?", (task,)
            ).fetchone()
            if not current or current[0] in (
                "paused",
                "cancelled",
                "accepted",
                "awaiting_acceptance",
            ):
                return False
            old = c.execute(
                "SELECT attempt FROM retry_schedule WHERE task_id=?", (task,)
            ).fetchone()
            attempt = (old[0] if old else 0) + 1
            due = now + delays[min(attempt - 1, len(delays) - 1)]
            c.execute(
                "INSERT INTO retry_schedule VALUES(?,?,?,?) ON CONFLICT(task_id) DO UPDATE SET attempt=excluded.attempt,due=excluded.due,reason=excluded.reason",
                (task, attempt, due, reason),
            )
            state = "waiting_retry" if attempt <= len(delays) else "waiting_dependency"
            c.execute(
                "UPDATE tasks SET status=?,blocker=?,updated=? WHERE id=?",
                (state, reason, now, task),
            )
            self.store.event(
                task,
                "retry_scheduled" if state == "waiting_retry" else "retry_exhausted",
                {"attempt": attempt, "due": due, "reason": reason},
                c,
            )
            return state == "waiting_retry"

    def clear_retry(self, task):
        with self.store.tx() as c:
            c.execute("DELETE FROM retry_schedule WHERE task_id=?", (task,))

    def retry_due(self, task, now=None):
        rows = self.store.rows(
            "SELECT due FROM retry_schedule WHERE task_id=?", (task,)
        )
        return bool(rows and rows[0]["due"] <= (time.time() if now is None else now))

    def record_attempt(self, task, method, inputs, result):
        signature = digest(
            {"method": method, "inputs": inputs, "failure": result.get("error", result)}
        )
        rows = self.store.rows(
            "SELECT payload FROM records WHERE kind=? ORDER BY created DESC LIMIT 8",
            ("attempt:" + task,),
        )
        unchanged = 1
        for row in rows:
            if json.loads(row["payload"])["signature"] != signature:
                break
            unchanged += 1
        entry = {
            "task": task,
            "signature": signature,
            "method": method,
            "inputs": inputs,
            "result": result,
            "consecutive": unchanged,
        }
        self.store.put("attempt:" + task, uid("attempt"), entry)
        return {"needs_reviewer": unchanged >= 3, "attempt": entry}

    def request(self, task, reason, permissions):
        requests = self.store.rows(
            "SELECT id FROM records WHERE kind=?", ("recovery:" + task,)
        )
        if len(requests) >= 2:
            raise Blocked(
                "Recovery review budget exhausted; retaining evidence and independent work"
            )
        value = {
            "task": task,
            "reason": reason,
            "permissions": permissions,
            "attempts": [
                json.loads(r["payload"])
                for r in self.store.rows(
                    "SELECT payload FROM records WHERE kind=? ORDER BY created DESC LIMIT 6",
                    ("attempt:" + task,),
                )
            ],
            "question": "Identify one discriminating next action and stopping condition. Do not weaken acceptance.",
        }
        self.store.put("recovery:" + task, uid("recovery"), value)
        return value

    @staticmethod
    def validate(decision):
        required = {
            "suspected_cause",
            "evidence",
            "next_discriminating_action",
            "expected_outcomes",
            "stopping_condition",
        }
        if not required <= decision.keys() or not all(decision[k] for k in required):
            raise Blocked(
                "Recovery decision lacks a discriminating test or stop condition"
            )
        return decision
