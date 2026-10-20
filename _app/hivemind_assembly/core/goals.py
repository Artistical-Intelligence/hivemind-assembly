"""Persistent goal policy over existing tasks, leases and acceptance.

A turn is one unique native request (including adviser/reviewer requests).
Reservations survive uncertain sends and restarts. No extra inference judge.
"""

import time
from .common import Blocked, Conflict, ContractError, uid


class GoalStopped(Blocked):
    pass


class Goals:
    def __init__(self, store):
        self.store = store

    def status(self, task):
        project = self.store.task(task)["project_id"]
        rows = self.store.rows("SELECT * FROM goals WHERE project_id=?", (project,))
        if not rows:
            return None
        goal = rows[0]
        root = self.store.task(goal["task_id"])
        goal["task_status"] = root["status"]
        goal["blocker"] = root["blocker"]
        goal["remaining_turns"] = (
            max(0, goal["max_turns"] - goal["turns"]) if goal["max_turns"] else None
        )
        goal["unlimited"] = goal["max_turns"] == 0
        return goal

    def prepare(self, task_id, db):
        """Attach continuation atomically with project creation; never start a paused task."""
        task = dict(db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())
        existing = db.execute(
            "SELECT id FROM goals WHERE project_id=?", (task["project_id"],)
        ).fetchone()
        if existing:
            return
        goal = dict(
            id=uid("goal"),
            project_id=task["project_id"],
            task_id=task_id,
            objective=task["objective"],
            status="active",
            max_turns=0,
            turns=0,
            updated=time.time(),
        )
        db.execute(
            "INSERT INTO goals VALUES(:id,:project_id,:task_id,:objective,:status,:max_turns,:turns,:updated)",
            goal,
        )
        self.store.event(task_id, "goal_prepared", {"goal": goal}, db)

    def command(self, task_id, command):
        """Compatibility adapter for old clients; automation uses control directly."""
        if not isinstance(command, str) or len(command) > 20010:
            raise ContractError("Expected a bounded /goal command")
        parts = command.strip().split(maxsplit=1)
        if not parts or parts[0] != "/goal":
            raise ContractError(
                "Use /goal, /goal status, pause, resume, clear or budget N"
            )
        arg = parts[1].strip() if len(parts) == 2 else ""
        if arg in ("status", "pause", "resume", "clear"):
            return self.control(task_id, arg)
        if arg.startswith("budget "):
            try:
                budget = 0 if arg[7:].strip().lower() == "unlimited" else int(arg[7:])
            except ValueError as error:
                raise ContractError(
                    "Goal budget must be an integer or unlimited"
                ) from error
            return self.control(task_id, "budget", max_turns=budget)
        return self.control(task_id, "start", objective=arg or None)

    def control(self, task_id, action="status", *, objective=None, max_turns=None):
        """Structured controller policy, independent of any provider chat syntax."""
        if action not in ("status", "start", "pause", "resume", "clear", "budget"):
            raise ContractError("Unknown objective action")
        if objective is not None and (
            action != "start"
            or not isinstance(objective, str)
            or not objective.strip()
            or len(objective) > 20000
        ):
            raise ContractError(
                "Provide objective text only when starting an objective"
            )
        if max_turns is not None and (
            action not in ("start", "budget")
            or type(max_turns) is not int
            or not 0 <= max_turns <= 100000
        ):
            raise ContractError("Request limit must be 1–100000, or 0 for unlimited")
        if action == "budget" and max_turns is None:
            raise ContractError("Provide a request limit, or 0 for unlimited")
        if action == "status":
            return self.status(task_id)
        with self.store.tx() as db:
            task = dict(
                db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            )
            row = db.execute(
                "SELECT * FROM goals WHERE project_id=?", (task["project_id"],)
            ).fetchone()
            goal = dict(row) if row else None
            if goal and goal["task_id"] != task_id:
                raise Conflict("Control this project's objective through its root task")
            if task["status"] in ("accepted", "cancelled"):
                raise Blocked(
                    "Task is terminal; create a new task for another objective"
                )
            if action == "budget":
                if not goal:
                    raise Conflict("No standing goal")
                goal["max_turns"] = max_turns
            elif action in ("pause", "resume", "clear"):
                if not goal:
                    raise Conflict("No standing goal")
                if (
                    action == "resume"
                    and goal["max_turns"]
                    and goal["turns"] >= goal["max_turns"]
                ):
                    raise Blocked(
                        "Goal turn budget exhausted; increase it before resuming"
                    )
                goal["status"] = {
                    "pause": "paused",
                    "resume": "active",
                    "clear": "cleared",
                }[action]
            elif goal:
                if objective is not None and objective != goal["objective"]:
                    raise Conflict(
                        "A goal's objective is immutable; create a new project to change scope"
                    )
                if max_turns is not None and max_turns != goal["max_turns"]:
                    raise Conflict(
                        "Use the budget action to change an existing request limit"
                    )
                # Repeated starts cannot undo an explicit pause, clear or exhaustion.
                if goal["status"] != "active":
                    return self.status(task_id)
            else:
                objective = objective or task["objective"]
                if objective != task["objective"]:
                    if (
                        task["owner"]
                        or task["step"]
                        or db.execute(
                            "SELECT 1 FROM records WHERE kind='acceptance_contract' AND id=?",
                            (task_id,),
                        ).fetchone()
                    ):
                        raise Blocked(
                            "Goal text must match the existing objective once work or acceptance is pinned"
                        )
                    db.execute(
                        "UPDATE tasks SET objective=? WHERE id=?", (objective, task_id)
                    )
                    db.execute(
                        "UPDATE projects SET objective=? WHERE id=?",
                        (objective, task["project_id"]),
                    )
                goal = dict(
                    id=uid("goal"),
                    project_id=task["project_id"],
                    task_id=task_id,
                    objective=objective,
                    status="active",
                    max_turns=0 if max_turns is None else max_turns,
                    turns=0,
                    updated=time.time(),
                )
            if (
                goal["status"] == "active"
                and action in ("start", "resume")
                and task["status"] == "paused"
            ):
                db.execute(
                    "UPDATE tasks SET status='queued',blocker='',updated=? WHERE id=?",
                    (time.time(), task_id),
                )
            goal["updated"] = time.time()
            db.execute(
                "INSERT INTO goals VALUES(:id,:project_id,:task_id,:objective,:status,:max_turns,:turns,:updated) "
                "ON CONFLICT(project_id) DO UPDATE SET status=excluded.status,max_turns=excluded.max_turns,updated=excluded.updated",
                goal,
            )
            self.store.event(
                task_id, "goal_control", {"action": action, "goal": goal}, db
            )
        return self.status(task_id)

    def runnable(self, task_id):
        goal = self.status(task_id)
        return goal is None or goal["status"] == "active"

    def reserve(self, task_id, message_id):
        exhausted = False
        with self.store.tx() as db:
            task = db.execute(
                "SELECT project_id FROM tasks WHERE id=?", (task_id,)
            ).fetchone()
            row = db.execute(
                "SELECT * FROM goals WHERE project_id=?", (task[0],)
            ).fetchone()
            if not row:
                return
            goal = dict(row)
            if goal["status"] != "active":
                raise GoalStopped("Standing goal is " + goal["status"])
            if db.execute(
                "SELECT 1 FROM goal_turns WHERE goal_id=? AND message_id=?",
                (goal["id"], message_id),
            ).fetchone():
                return
            if goal["max_turns"] and goal["turns"] >= goal["max_turns"]:
                db.execute(
                    "UPDATE goals SET status='exhausted',updated=? WHERE id=?",
                    (time.time(), goal["id"]),
                )
                self.store.event(
                    task_id, "goal_budget_exhausted", {"goal": goal["id"]}, db
                )
                exhausted = True
            else:
                db.execute(
                    "INSERT INTO goal_turns VALUES(?,?,?)",
                    (goal["id"], message_id, task_id),
                )
                db.execute(
                    "UPDATE goals SET turns=turns+1,updated=? WHERE id=?",
                    (time.time(), goal["id"]),
                )
        if exhausted:
            raise GoalStopped("Standing goal turn budget exhausted")

    def accepted(self, task_id, result, db):
        # Called in the acceptance transaction, never from a worker's claim.
        if result.get("passed") and result.get("status") == "accepted":
            db.execute(
                "UPDATE goals SET status='achieved',updated=? WHERE task_id=?",
                (time.time(), task_id),
            )
            self.store.event(
                task_id, "goal_acceptance_checked", {"proposal": result["proposal"]}, db
            )

    def context(self, task_id):
        goal = self.status(task_id)
        if goal is None:
            return None
        return {
            k: goal[k]
            for k in ("objective", "status", "turns", "max_turns", "remaining_turns")
        } | {
            "continuation": "Continue authorized work until the root acceptance contract passes. A checkpoint or progress summary does not finish the goal. Resolve routine choices using project evidence. Preserve real blockers, unsupported behavior, exact routes and usage limits."
        }
