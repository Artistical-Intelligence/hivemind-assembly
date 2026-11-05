"""Deterministic progress watchdog for HA's native Chat Mode work tickets.

Derived conceptually from DeepSeek Super-agent's independent health/progress
observation and Grok Bot's event-triggered routines. This module watches
existing HA's durable local evidence; it neither asks a model nor changes a
task's ownership, schedule, permissions, or provider.

A signal means POSSIBLE stagnation, never a definitive AI quality judgment.
"""

from __future__ import annotations

import hashlib
import math
import time

from hivemind_assembly.core.common import ContractError
from .event_inbox import NativeEventInbox


_STATES_WITHOUT_ACTION = frozenset({
    "accepted", "cancelled", "paused", "awaiting_acceptance",
    "waiting_setup", "waiting_quota", "waiting_signin",
})

_SCHEMA = """CREATE TABLE IF NOT EXISTS ha_progress_watch(
    task_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    observed_owner TEXT NOT NULL DEFAULT '',
    observed_epoch INTEGER NOT NULL DEFAULT 0,
    observed_turns INTEGER NOT NULL,
    observed_operations INTEGER NOT NULL,
    consecutive_unproductive_turns INTEGER NOT NULL,
    last_alert_at REAL,
    updated_at REAL NOT NULL
)"""


class ProgressWatchdog:
    """Scan native project workers without a second AI supervisor.

    Model turns are *not* progress. Completed executed operations and an
    accepted final result are evidence; source research outside these
    counters can be valid work, so alerts request human/manager review and
    never automatically revoke, retask or pause any task.
    """

    def __init__(self, store, inbox: NativeEventInbox):
        self.store = store
        self.inbox = inbox
        with store.tx() as db:
            db.execute(_SCHEMA)
            # Migrate existing journals without discarding any watchdog state.
            columns = {row[1] for row in db.execute("PRAGMA table_info(ha_progress_watch)")}
            if "observed_owner" not in columns:
                db.execute("ALTER TABLE ha_progress_watch ADD COLUMN observed_owner TEXT NOT NULL DEFAULT ''")
            if "observed_epoch" not in columns:
                # A legacy observation cannot attest to the current owner
                # lease generation, so its next scan must reset the baseline.
                db.execute(
                    "ALTER TABLE ha_progress_watch "
                    "ADD COLUMN observed_epoch INTEGER NOT NULL DEFAULT -1"
                )

    def scan(self, project_id: str, *, threshold: int = 3,
             cooldown_seconds: float = 300, now: float | None = None,
             allowed_owners: frozenset[str] | None = None) -> list[dict]:
        self.store.project(project_id)
        if not isinstance(threshold, int) or isinstance(threshold, bool) or threshold < 2:
            raise ContractError("Watchdog threshold must be at least two completed model turns")
        try:
            cooldown = float(cooldown_seconds)
            current = time.time() if now is None else float(now)
        except (TypeError, ValueError, OverflowError) as error:
            raise ContractError("Invalid watchdog time value") from error
        if not math.isfinite(cooldown) or cooldown < 0:
            raise ContractError("Watchdog cooldown must be finite and nonnegative")
        if not math.isfinite(current) or current < 0:
            raise ContractError("Watchdog clock must be finite and nonnegative")
        signals = []
        tasks = self.store.rows(
            "SELECT id,project_id,status,owner,epoch,lease_until FROM tasks WHERE project_id=?",
            (project_id,),
        )
        for task in tasks:
            if allowed_owners is not None and task["owner"] not in allowed_owners:
                continue
            if task["status"] in _STATES_WITHOUT_ACTION or task["owner"] is None:
                continue
            task_id = task["id"]
            # Review current-owner evidence, not unrelated adviser/reviewer
            # turns or operations made by a previous worker.
            owner = task["owner"]
            turns = self.store.one(
                """SELECT COUNT(*) AS n FROM messages
                   WHERE task_id=? AND route=? AND state='validated'""",
                (task_id, owner),
            )["n"]
            operations = self.store.one(
                """SELECT COUNT(*) AS n FROM operations
                   WHERE task_id=? AND owner=? AND state='completed'""",
                (task_id, owner),
            )["n"]
            existing = self.store.rows(
                "SELECT * FROM ha_progress_watch WHERE task_id=?", (task_id,),
            )
            if not existing:
                with self.store.tx() as db:
                    db.execute(
                        """INSERT OR IGNORE INTO ha_progress_watch
                           (task_id,project_id,observed_owner,observed_epoch,
                            observed_turns,observed_operations,
                            consecutive_unproductive_turns,updated_at)
                           VALUES(?,?,?,?,?,?,0,?)""",
                        (task_id, project_id, owner, task["epoch"],
                         turns, operations, current),
                    )
                continue
            old = existing[0]
            if (old["observed_owner"] != owner
                    or old["observed_epoch"] != task["epoch"]
                    or turns < old["observed_turns"]
                    or operations < old["observed_operations"]):
                # Handoffs, journal upgrades and restorations do not prove stalls.
                with self.store.tx() as db:
                    db.execute(
                        """UPDATE ha_progress_watch SET observed_owner=?,
                           observed_epoch=?,observed_turns=?,
                           observed_operations=?,
                           consecutive_unproductive_turns=0,
                           last_alert_at=NULL,updated_at=? WHERE task_id=?""",
                        (owner, task["epoch"], turns, operations, current, task_id),
                    )
                continue
            new_turns = turns - old["observed_turns"]
            progress = operations > old["observed_operations"]
            consecutive = (0 if progress
                           else old["consecutive_unproductive_turns"] + new_turns)
            # Zero new turns is not progress and does not increment a stall.
            last_alert = old["last_alert_at"]
            with self.store.tx() as db:
                db.execute(
                    """UPDATE ha_progress_watch SET observed_turns=?,
                       observed_operations=?,consecutive_unproductive_turns=?,
                       updated_at=? WHERE task_id=?""",
                    (turns, operations, consecutive, current, task_id),
                )
            if (consecutive < threshold or new_turns == 0
                    or last_alert is not None and current - last_alert < cooldown):
                continue
            # A recent live lease is not itself progress; it does mean we
            # must not interrupt the ongoing worker or claim completion.
            # Signal the manager to review *after* the current turn instead.
            summary = (
                "Possible lack of executed-operation evidence for task "
                + task_id + " after " + str(consecutive)
                + " validated model turns; inspect current work and "
                  "assignment before any corrective change"
            )
            outcome = self.inbox.receive(
                project_id=project_id, source="watchdog", verified=True,
                source_id=("stall:" + task_id + ":" +
                           hashlib.sha256(owner.encode("utf-8")).hexdigest()[:16] +
                           ":" + str(turns)),
                thread="project:" + project_id, kind="possible_stall",
                summary=summary,
            )
            if outcome == "stored":
                with self.store.tx() as db:
                    db.execute(
                        "UPDATE ha_progress_watch SET last_alert_at=? WHERE task_id=?",
                        (current, task_id),
                    )
                signals.append({
                    "task_id": task_id, "unproductive_turns": consecutive,
                    "status": "needs_review", "running": task["lease_until"] > current,
                })
        return signals
