"""Durable, scoped event admission and native Chat Mode inbox.

Adapted (not copied) from the MIT-licensed DeepSeek dsh-superagent-prototype
src/core/intake.ts and src/core/tickets.ts: stable trigger ids, subscriptions
to threads, one-delivery-per-owner and explicit read acknowledgements.

This is entirely local SQLite. It NEVER invokes a model, calls an API,
sends a webhook, reschedules a task, or grants source/tool authorization.
Only native worker invocations can consume admitted events. External source
adapters must authenticate incoming events before setting verified=True.
See dev/continuous_execution/DEEPSEEK_HARNESS_INTEGRATION.md.
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Iterable
from itertools import islice

from hivemind_assembly.core.common import ContractError


_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS ha_event_trigger(
       id INTEGER PRIMARY KEY AUTOINCREMENT,
       project_id TEXT NOT NULL,
       source TEXT NOT NULL,
       source_id TEXT NOT NULL,
       thread TEXT NOT NULL,
       kind TEXT NOT NULL,
       summary TEXT NOT NULL,
       arrived REAL NOT NULL,
       UNIQUE(project_id, source, source_id))""",
    """CREATE TABLE IF NOT EXISTS ha_event_subscription(
       project_id TEXT NOT NULL,
       task_id TEXT NOT NULL,
       thread TEXT NOT NULL,
       PRIMARY KEY(task_id, thread))""",
    """CREATE TABLE IF NOT EXISTS ha_event_delivery(
       event_id INTEGER NOT NULL REFERENCES ha_event_trigger(id),
       task_id TEXT NOT NULL,
       read_at REAL,
       PRIMARY KEY(event_id, task_id))""",
    """CREATE TABLE IF NOT EXISTS ha_event_subscription_backfill(
       project_id TEXT NOT NULL,
       task_id TEXT NOT NULL,
       thread TEXT NOT NULL,
       cursor INTEGER NOT NULL DEFAULT 0,
       upto INTEGER NOT NULL DEFAULT 0,
       PRIMARY KEY(task_id, thread))""",
    """CREATE INDEX IF NOT EXISTS ha_event_delivery_unread
       ON ha_event_delivery(task_id, read_at, event_id)""",
    """CREATE INDEX IF NOT EXISTS ha_event_thread_cursor
       ON ha_event_trigger(project_id, thread, id)""",
    """CREATE TABLE IF NOT EXISTS ha_native_event_cursor(
       project_id TEXT PRIMARY KEY,
       last_seq INTEGER NOT NULL DEFAULT 0)""",
    """CREATE TABLE IF NOT EXISTS ha_work_ticket(
       project_id TEXT NOT NULL,
       task_id TEXT NOT NULL PRIMARY KEY,
       objective TEXT NOT NULL,
       state TEXT NOT NULL,
       last_artifact TEXT,
       last_run TEXT,
       updated REAL NOT NULL)""",
)

# Only meaningful native journal transitions are forwarded. The journal
# itself is the durable ground truth and is never consumed/deleted.
_STATE_KINDS = frozenset({
    "task_created", "accepted", "failed", "blocked", "paused",
    "waiting_dependencies", "waiting_dependency", "waiting_retry",
    "independent_check", "independent_check_stopped", "waiting_quota",
    "waiting_signin",
})

_TERMINAL_TICKET_STATES = frozenset({"accepted", "cancelled"})
_MAX_EVENT_ID = (1 << 63) - 1  # SQLite INTEGER PRIMARY KEY / bound parameters


def _bounded(value: str, name: str, limit: int = 512) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise ContractError(f"{name} must be a nonempty bounded string")
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ContractError(f"{name} contains control characters")
    return value


class NativeEventInbox:
    """A project-scoped event queue and lightweight work ticket projection.

    The public methods accept stable source identifiers, but no unverified
    external content is ever automatically promoted into authority. Consumers
    must still check the current task/project/route before model delivery.
    """

    def __init__(self, store):
        self.store = store
        with store.tx() as db:
            for statement in _SCHEMA:
                db.execute(statement)
            # When upgrading an existing HA database, existing active
            # subscriptions must NOT retroactively replay old deliveries:
            # historical ACKs and earlier revocations may already exist.
            # Only genuinely first-time subscriptions perform catch-up.
            db.execute(
                """INSERT OR IGNORE INTO ha_event_subscription_backfill
                   (project_id,task_id,thread,cursor,upto)
                   SELECT s.project_id,s.task_id,s.thread,
                          COALESCE(MAX(e.id),0),COALESCE(MAX(e.id),0)
                   FROM ha_event_subscription s
                   LEFT JOIN ha_event_trigger e ON
                       e.project_id=s.project_id AND e.thread=s.thread
                   GROUP BY s.project_id,s.task_id,s.thread"""
            )

    def ensure_ticket(self, task_id: str) -> dict:
        task = self.store.task(task_id)
        with self.store.tx() as db:
            db.execute(
                """INSERT OR IGNORE INTO ha_work_ticket
                   (project_id,task_id,objective,state,updated)
                   VALUES(?,?,?,?,?)""",
                (task["project_id"], task_id, task["objective"], "open", time.time()),
            )
        return self.ticket(task_id)

    def ticket(self, task_id: str) -> dict:
        self.store.task(task_id)  # no access to an unknown task
        return self.store.one(
            "SELECT * FROM ha_work_ticket WHERE task_id=?", (task_id,)
        )

    def record_ticket(self, task_id: str, state: str, *,
                      run_id: str | None = None,
                      artifact_sha: str | None = None) -> dict:
        """Record native evidence; never accept a model's bare 'done' as proof."""
        if state not in {"open", "working", "blocked", "needs_check",
                         "accepted", "cancelled"}:
            raise ContractError("Unknown work ticket state")
        if state == "accepted" and not artifact_sha:
            raise ContractError("Accepted work requires artifact evidence")
        if artifact_sha is not None:
            _bounded(artifact_sha, "artifact sha", 128)
        if run_id is not None:
            _bounded(run_id, "run id", 128)
        self.ensure_ticket(task_id)
        with self.store.tx() as db:
            # A ticket is a projection of controller state, never authority
            # granted by a caller-supplied digest or model completion claim.
            # Fence terminal promotion to the retained controller evidence
            # in the SAME transaction as the ticket update.
            if state in _TERMINAL_TICKET_STATES:
                live = db.execute(
                    "SELECT project_id,status FROM tasks WHERE id=?",
                    (task_id,),
                ).fetchone()
                if live is None or live["status"] != state:
                    raise ContractError(
                        "Terminal ticket requires matching controller state"
                    )
                if state == "accepted":
                    evidence = db.execute(
                        """SELECT payload FROM records
                           WHERE kind='acceptance_result'
                             AND CASE WHEN json_valid(payload)
                                      THEN json_extract(payload,'$.task_id')
                                 END=?
                           ORDER BY rowid DESC LIMIT 1""",
                        (task_id,),
                    ).fetchone()
                    if evidence is None:
                        raise ContractError(
                            "Accepted ticket requires retained controller acceptance"
                        )
                    try:
                        result = json.loads(evidence["payload"])
                    except (TypeError, ValueError) as error:
                        raise ContractError(
                            "Malformed retained controller acceptance"
                        ) from error
                    if (not isinstance(result, dict)
                            or result.get("task_id") != task_id
                            or result.get("status") != "accepted"
                            or result.get("passed") is not True
                            or not isinstance(result.get("artifact"), str)):
                        raise ContractError(
                            "Accepted ticket requires verified acceptance result"
                        )
                    artifact = db.execute(
                        """SELECT sha256 FROM artifacts
                           WHERE id=? AND project_id=?""",
                        (result["artifact"], live["project_id"]),
                    ).fetchone()
                    if artifact is None or artifact["sha256"] != artifact_sha:
                        raise ContractError(
                            "Accepted ticket artifact must match retained evidence"
                        )
            prior = db.execute(
                """SELECT state,last_run,last_artifact FROM ha_work_ticket
                   WHERE task_id=?""", (task_id,)
            ).fetchone()
            if prior["state"] in _TERMINAL_TICKET_STATES:
                if prior["state"] != state:
                    raise ContractError("Terminal ticket cannot be reopened implicitly")
                # Replayed finalization is a read, not permission to rewrite
                # accepted evidence or replace a cancelled work order.
                if ((run_id is not None and run_id != prior["last_run"])
                        or (artifact_sha is not None
                            and artifact_sha != prior["last_artifact"])):
                    raise ContractError("Conflicting terminal ticket evidence")
                return self.ticket(task_id)
            if (prior["state"] == state
                    and (run_id is None or run_id == prior["last_run"])
                    and (artifact_sha is None or
                         artifact_sha == prior["last_artifact"])):
                # A 120-second local watchdog scan is not a new task run.
                # Reobserving identical evidence must not churn the ticket
                # timestamp or masquerade as worker progress.
                return self.ticket(task_id)
            db.execute(
                """UPDATE ha_work_ticket SET state=?,last_run=COALESCE(?,last_run),
                   last_artifact=COALESCE(?,last_artifact),updated=?
                   WHERE task_id=?""",
                (state, run_id, artifact_sha, time.time(), task_id),
            )
        return self.ticket(task_id)

    def reconcile_ticket(self, task_id: str) -> dict:
        """Project the controller's durable task state, never a model claim.

        A native ticket is a local view of existing work. An accepted model
        answer alone is not acceptance: only the controller's accepted task
        with a matching retained independent-verifier artifact can close it.
        Repeatable after a crash, including one between Acceptance.evaluate()
        and this optional ticket projection.
        """
        task = self.store.task(task_id)
        state = task["status"]
        if state == "accepted":
            records = self.store.rows(
                """SELECT payload FROM records
                   WHERE kind='acceptance_result'
                     AND CASE WHEN json_valid(payload)
                              THEN json_extract(payload,'$.task_id')
                         END=?
                   ORDER BY rowid DESC LIMIT 1""",
                (task_id,),
            )
            if not records:
                return self.record_ticket(task_id, "needs_check")
            try:
                result = json.loads(records[0]["payload"])
            except (ValueError, TypeError) as error:
                raise ContractError("Malformed retained acceptance evidence") from error
            if not isinstance(result, dict):
                raise ContractError("Malformed retained acceptance evidence")
            if (result.get("task_id") != task_id
                    or result.get("status") != "accepted"
                    or result.get("passed") is not True
                    or not isinstance(result.get("artifact"), str)):
                return self.record_ticket(task_id, "needs_check")
            artifact = self.store.rows(
                """SELECT sha256 FROM artifacts WHERE id=? AND project_id=?""",
                (result["artifact"], task["project_id"]),
            )
            if not artifact:
                return self.record_ticket(task_id, "needs_check")
            return self.record_ticket(
                task_id, "accepted", artifact_sha=artifact[0]["sha256"]
            )
        if state == "cancelled":
            return self.record_ticket(task_id, "cancelled")
        if state == "awaiting_acceptance":
            return self.record_ticket(task_id, "needs_check")
        if state in {"running"}:
            return self.record_ticket(task_id, "working")
        if state == "queued":
            return self.record_ticket(task_id, "open")
        # Quota, sign-in, dependencies and scheduled retry are reasons to
        # review, not proof of a model failure or independent acceptance.
        return self.record_ticket(task_id, "blocked")

    @staticmethod
    def _refill_initial(db, task_id: str, thread: str, *, limit: int = 20) -> None:
        """Bounded, durable first-subscription catch-up, never a resubscribe replay.

        The high watermark is pinned when the FIRST subscription is created.
        A saved cursor makes long backlogs resumable without loading a full
        project journal into memory or reissuing an acknowledged delivery.
        """
        state = db.execute(
            """SELECT b.project_id,b.cursor,b.upto
               FROM ha_event_subscription_backfill b
               JOIN ha_event_subscription s ON s.task_id=b.task_id
                  AND s.thread=b.thread AND s.project_id=b.project_id
               WHERE b.task_id=? AND b.thread=?""",
            (task_id, thread),
        ).fetchone()
        if not state or state["cursor"] >= state["upto"]:
            return
        found = db.execute(
            """SELECT id FROM ha_event_trigger WHERE project_id=? AND thread=?
               AND id>? AND id<=? ORDER BY id LIMIT ?""",
            (state["project_id"], thread, state["cursor"], state["upto"], limit),
        ).fetchall()
        for event in found:
            db.execute(
                """INSERT OR IGNORE INTO ha_event_delivery(event_id,task_id)
                   VALUES(?,?)""",
                (event["id"], task_id),
            )
        # A one-time cursor advances through existing IDs only. An empty
        # page completes the batch even if IDs were skipped by other threads.
        cursor = found[-1]["id"] if found else state["upto"]
        db.execute(
            """UPDATE ha_event_subscription_backfill SET cursor=?
               WHERE task_id=? AND thread=?""",
            (cursor, task_id, thread),
        )

    @staticmethod
    def _require_current_native_reader(db, task_id: str, project_id: str,
                                       route: str, epoch: int) -> None:
        """Fence a Chat reader against ownership changes inside the read TX.

        The calling NativeTeam may have inspected the task *before* a handoff.
        An old owner must not see the successor's pending source summaries even
        if the previous eligibility check was valid when it ran. Epoch zero is
        retained solely for the pre-assignment, queued local catch-up path.
        """
        _bounded(route, "native reader route", 128)
        if type(epoch) is not int or epoch < 0:
            raise ContractError("Invalid native reader epoch")
        current = db.execute(
            """SELECT project_id,owner,epoch,status,lease_until
               FROM tasks WHERE id=?""", (task_id,),
        ).fetchone()
        if (current is None or current["project_id"] != project_id
                or current["epoch"] != epoch):
            raise ContractError("Native event reader task or epoch changed")
        if current["owner"] is None:
            if epoch != 0 or current["status"] != "queued":
                raise ContractError("Native event reader has no live owner")
        elif (current["owner"] != route or current["status"] != "running"
              or epoch <= 0 or current["lease_until"] <= time.time()):
            # Epoch zero is reserved for a never-assigned queued task.
            # An owner stamped onto epoch zero must not bypass lease checks.
            raise ContractError("Native event reader lost current Chat owner lease")

    def subscribe(self, task_id: str, thread: str, *,
                  route: str | None = None, epoch: int | None = None) -> None:
        task = self.store.task(task_id)
        valid = {"project:" + task["project_id"], "task:" + task_id}
        if thread not in valid:
            raise ContractError("Cross-project or arbitrary thread subscription denied")
        self.ensure_ticket(task_id)
        with self.store.tx() as db:
            current = db.execute(
                "SELECT project_id,status FROM tasks WHERE id=?", (task_id,)
            ).fetchone()
            if (current is None or current["project_id"] != task["project_id"]):
                raise ContractError("Native event subscription task binding changed")
            if route is not None:
                self._require_current_native_reader(
                    db, task_id, task["project_id"], route, epoch
                )
            if current["status"] in {
                "paused", "cancelled", "accepted", "awaiting_acceptance"
            }:
                raise ContractError(
                    "Stopped native work ticket cannot acquire a subscription"
                )
            db.execute(
                """INSERT OR IGNORE INTO ha_event_subscription
                   (project_id,task_id,thread) VALUES(?,?,?)""",
                (task["project_id"], task_id, thread),
            )
            # Only the first-ever subscription can catch previously admitted
            # authenticated events. A re-subscription after explicit revocation
            # inherits its old, already-consumed high watermark.
            upto = db.execute(
                """SELECT COALESCE(MAX(id),0) AS id FROM ha_event_trigger
                   WHERE project_id=? AND thread=?""",
                (task["project_id"], thread),
            ).fetchone()["id"]
            db.execute(
                """INSERT OR IGNORE INTO ha_event_subscription_backfill
                   (project_id,task_id,thread,cursor,upto)
                   VALUES(?,?,?,0,?)""",
                (task["project_id"], task_id, thread, upto),
            )
            self._refill_initial(db, task_id, thread)
            if route is not None:
                # Backfill may be long-running. Recheck the *live* lease at
                # the final subscription transition; an expired worker must
                # not commit either the subscription or hydrated deliveries.
                # Store.tx() rolls both inserts back when this fence fails.
                self._require_current_native_reader(
                    db, task_id, task["project_id"], route, epoch
                )

    @staticmethod
    def _revoke_locked(db, task_id: str, project_id: str,
                       thread: str) -> int:
        """Revoke an existing scoped thread inside the caller's SQLite fence.

        The effect row and immutable source trigger survive, but an in-flight
        browser receipt must NOT finalize after a hard revocation: removing
        the unread delivery is the original fail-closed authorization barrier.
        """
        db.execute(
            """DELETE FROM ha_event_subscription
               WHERE project_id=? AND task_id=? AND thread=?""",
            (project_id, task_id, thread),
        )
        removed = db.execute(
            """DELETE FROM ha_event_delivery
               WHERE task_id=? AND read_at IS NULL AND event_id IN
                   (SELECT id FROM ha_event_trigger
                    WHERE project_id=? AND thread=?)""",
            (task_id, project_id, thread),
        )
        has_effects = db.execute(
            """SELECT 1 FROM sqlite_master
               WHERE type='table' AND name='ha_native_effect'"""
        ).fetchone()
        if has_effects:
            # Never delete leased/uncertain effects: retain their evidence
            # for explicit investigation, without restoring revoked delivery
            # authority or permitting automatic retries.
            db.execute(
                """DELETE FROM ha_native_effect
                   WHERE task_id=? AND status='queued'
                     AND event_id IN (
                       SELECT id FROM ha_event_trigger
                       WHERE project_id=? AND thread=?
                     )""",
                (task_id, project_id, thread),
            )
        db.execute(
            """UPDATE ha_event_subscription_backfill SET cursor=upto
               WHERE task_id=? AND thread=? AND project_id=?""",
            (task_id, thread, project_id),
        )
        return removed.rowcount

    def unsubscribe(self, task_id: str, thread: str) -> int:
        """Revoke all unread deliveries, retaining only immutable evidence.

        An old owner cannot revive rejected deliveries by resubscribing.
        A possibly sent, late browser receipt is rejected after revocation.
        """
        task = self.store.task(task_id)
        if thread not in {"project:" + task["project_id"], "task:" + task_id}:
            raise ContractError("Cross-project or arbitrary thread unsubscription denied")
        with self.store.tx() as db:
            return self._revoke_locked(
                db, task_id, task["project_id"], thread
            )

    def revoke_ineligible(self, allowed_owners: frozenset[str], *,
                          limit: int = 100) -> int:
        """Prune stale native subscriptions atomically after restart/retasking.

        A local watchdog calls this without starting a model turn. The exact
        live task owner and status are inspected in the SAME transaction as
        removal, so a stale scan cannot revoke a newly valid Chat Mode owner.
        Batch size is bounded and later scans resume naturally. A new
        epoch-zero, unassigned task is left subscribed: its pre-assignment
        authenticated event belongs to first-subscription catch-up, whereas
        a formerly owned task with no current owner must be fenced.
        """
        if (not isinstance(allowed_owners, frozenset)
                or any(not isinstance(owner, str) or not owner
                       for owner in allowed_owners)):
            raise ContractError("Invalid native Chat owner allowlist")
        if (not isinstance(limit, int) or isinstance(limit, bool)
                or not 1 <= limit <= 500):
            raise ContractError("Invalid subscription prune batch size")
        routes = tuple(sorted(allowed_owners))
        predicate = (
            " OR t.owner NOT IN (" + ",".join("?" for _ in routes) + ")"
            if routes else " OR t.owner IS NOT NULL"
        )
        with self.store.tx() as db:
            rows = db.execute(
                """SELECT s.task_id,s.project_id,s.thread
                   FROM ha_event_subscription s
                   LEFT JOIN tasks t ON t.id=s.task_id
                   WHERE (t.id IS NULL OR t.project_id!=s.project_id
                          OR t.status IN ('paused','cancelled','accepted',
                                          'awaiting_acceptance')
                          OR (t.owner IS NULL AND t.epoch > 0)""" + predicate + """)
                   ORDER BY s.task_id,s.thread LIMIT ?""",
                (*routes, limit),
            ).fetchall()
            for row in rows:
                self._revoke_locked(
                    db, row["task_id"], row["project_id"], row["thread"]
                )
            return len(rows)

    def receive(self, *, project_id: str, source: str, source_id: str,
                thread: str, kind: str, summary: str,
                verified: bool = False,
                expected_task: tuple[str, str, int, str] | None = None,
                expected_effect: tuple[str, int, str, float] | None = None,
                expected_progress: tuple[int, int] | None = None) -> str:
        """Record one stable trigger and enqueue it for current subscribers.

        `verified` must be literal True from an authenticated native adapter;
        truthy non-booleans never authorize an external event. Never trust
        external event payloads. Internal journal events use
        source='native'. No new task, permission or model call is created.
        """
        _bounded(project_id, "project id", 128)
        _bounded(source, "source", 64)
        _bounded(source_id, "source id", 200)
        _bounded(thread, "thread", 256)
        _bounded(kind, "kind", 100)
        _bounded(summary, "summary", 500)
        if source != "native" and verified is not True:
            raise ContractError("External source event requires verified adapter")
        if thread != "project:" + project_id and not thread.startswith("task:"):
            raise ContractError("Thread must belong to the supplied project")
        self.store.project(project_id)
        if thread.startswith("task:"):
            if self.store.task(thread[5:])["project_id"] != project_id:
                raise ContractError("Event targets task in different project")

        # A watchdog observation is advisory. A task may be transferred or
        # stopped between its evidence scan and admission of the signal.
        # Recheck the *observed* owner, epoch and status in the same write
        # transaction as admission so an old owner's stale sample cannot
        # create a fresh project event. This is a restriction, not authority
        # granted by the caller or an alternative model wakeup.
        if expected_task is not None:
            if (source != "watchdog" or not verified
                    or not isinstance(expected_task, tuple)
                    or len(expected_task) != 4):
                raise ContractError("Invalid fenced watchdog event admission")
            task_id, owner, epoch, status = expected_task
            _bounded(task_id, "observed watchdog task", 128)
            _bounded(owner, "observed watchdog owner", 128)
            if type(epoch) is not int or epoch < 0:
                raise ContractError("Invalid observed watchdog epoch")
            _bounded(status, "observed watchdog status", 64)
        if expected_effect is not None:
            # A health-scan snapshot is not proof the browser effect remains
            # unresolved when its advisory is admitted. Fence the exact
            # effect generation and state inside the event write transaction.
            if (expected_task is None or source != "watchdog" or not verified
                    or not isinstance(expected_effect, tuple)
                    or len(expected_effect) != 4):
                raise ContractError("Invalid fenced watchdog effect admission")
            effect_key, generation, effect_status, observed_at = expected_effect
            _bounded(effect_key, "observed watchdog effect key", 180)
            if type(generation) is not int or generation < 0:
                raise ContractError("Invalid observed watchdog effect generation")
            if effect_status not in ("uncertain", "leased"):
                raise ContractError("Invalid observed watchdog effect status")
            if (isinstance(observed_at, bool)
                    or not isinstance(observed_at, (int, float))
                    or not math.isfinite(observed_at) or observed_at < 0):
                raise ContractError("Invalid observed watchdog effect clock")
        if expected_progress is not None:
            # An advisory based on two stale counts is not actual progress
            # evidence. Validate the complete snapshot before touching SQL;
            # only the deterministic local watchdog may use this extra fence.
            if (expected_task is None or source != "watchdog"
                    or verified is not True
                    or not isinstance(expected_progress, tuple)
                    or len(expected_progress) != 2
                    or any(type(number) is not int or number < 0
                           for number in expected_progress)):
                raise ContractError("Invalid fenced watchdog progress snapshot")
            observed_turns, observed_operations = expected_progress
        with self.store.tx() as db:
            if expected_task is not None:
                current = db.execute(
                    """SELECT project_id,owner,epoch,status,lease_until FROM tasks
                       WHERE id=?""", (task_id,)
                ).fetchone()
                if (current is None
                        or current["project_id"] != project_id
                        or current["owner"] != owner
                        or current["epoch"] != epoch
                        or current["status"] != status
                        or status in ("paused", "cancelled", "accepted",
                                      "awaiting_acceptance")):
                    return "stale"
            if expected_effect is not None:
                effect = db.execute(
                    """SELECT project_id,generation,status,lease_until
                       FROM ha_native_effect WHERE task_id=? AND effect_key=?""",
                    (task_id, effect_key),
                ).fetchone()
                if (effect is None or effect["project_id"] != project_id
                        or effect["generation"] != generation
                        or effect["status"] != effect_status):
                    return "stale"
                if (effect_status == "leased"
                        and not (
                            (effect["lease_until"] is not None
                             and effect["lease_until"] <= observed_at)
                            or (current["lease_until"] is not None
                                and current["lease_until"] <= observed_at)
                        )):
                    return "stale"
            if expected_progress is not None:
                # The initial scan's owner/epoch/status can stay unchanged
                # while an executed operation or a new validated turn appears.
                # Recheck BOTH actual counters in this same admission TX.
                # Reject an obsolete stall signal without recording any
                # trigger or delivery; the next scan takes a new baseline.
                latest = db.execute(
                    """SELECT
                         (SELECT COUNT(*) FROM messages
                          WHERE task_id=? AND route=? AND state='validated')
                            AS turns,
                         (SELECT COUNT(*) FROM operations
                          WHERE task_id=? AND owner=? AND state='completed')
                            AS operations""",
                    (task_id, owner, task_id, owner),
                ).fetchone()
                if (latest["turns"] != observed_turns
                        or latest["operations"] != observed_operations):
                    return "stale"
            prior = db.execute(
                """SELECT id,thread,kind,summary FROM ha_event_trigger
                   WHERE project_id=? AND source=? AND source_id=?""",
                (project_id, source, source_id),
            ).fetchone()
            if prior:
                if tuple(prior)[1:] != (thread, kind, summary):
                    raise ContractError("Same source event ID has conflicting content")
                return "duplicate"
            cur = db.execute(
                """INSERT INTO ha_event_trigger
                   (project_id,source,source_id,thread,kind,summary,arrived)
                   VALUES(?,?,?,?,?,?,?)""",
                (project_id, source, source_id, thread, kind, summary, time.time()),
            )
            # A retained subscription is not authority by itself: after an
            # owner stop or an interrupted cleanup it may refer to an orphaned
            # task or a task in a different project. Fence fan-out to the
            # *current* task row in this same admission transaction.
            db.execute(
                """INSERT OR IGNORE INTO ha_event_delivery(event_id,task_id)
                   SELECT ?,s.task_id FROM ha_event_subscription s
                   JOIN tasks t ON t.id=s.task_id
                     AND t.project_id=s.project_id
                   WHERE s.project_id=? AND s.thread=?
                     AND t.status NOT IN ('paused','cancelled','accepted',
                                          'awaiting_acceptance')""",
                (cur.lastrowid, project_id, thread),
            )
        return "stored"

    def pending(self, task_id: str, limit: int = 6, *,
                route: str | None = None, epoch: int | None = None) -> list[dict]:
        """Optionally bind a native worker's read to its current owner lease.

        Unbound reads are still available for deterministic local inspection;
        actual Chat Mode request assembly must supply its route and epoch.
        """
        task = self.store.task(task_id)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
            raise ContractError("Event batch size out of range")
        with self.store.tx() as db:
            if route is not None:
                self._require_current_native_reader(
                    db, task_id, task["project_id"], route, epoch
                )
            active = db.execute(
                """SELECT thread FROM ha_event_subscription
                   WHERE task_id=? AND project_id=?""",
                (task_id, task["project_id"]),
            ).fetchall()
            for row in active:
                self._refill_initial(db, task_id, row["thread"])
            rows = db.execute(
                """SELECT e.id,e.source,e.source_id,e.thread,e.kind,
                          e.summary,e.arrived
                   FROM ha_event_delivery d
                   JOIN ha_event_trigger e ON e.id=d.event_id
                   WHERE d.task_id=? AND d.read_at IS NULL AND e.project_id=?
                   ORDER BY e.id LIMIT ?""",
                (task_id, task["project_id"], limit),
            ).fetchall()
            # Build the read-only envelope inside the same fenced transaction,
            # not after releasing its lock. A long materialization must not
            # leak event summaries after the owning worker's lease expires.
            events = [{"event_id": row["id"], "source": row["source"],
                       "source_id": row["source_id"], "thread": row["thread"],
                       "kind": row["kind"], "summary": row["summary"],
                       "arrived": row["arrived"]} for row in rows]
            if route is not None:
                # Backfill, SELECT and envelope assembly can all span the
                # lease deadline, even with no intervening database writer.
                # Reject and roll back before returning any scoped data.
                self._require_current_native_reader(
                    db, task_id, task["project_id"], route, epoch
                )
        # Summaries are facts/data, not source instructions or permission grants.
        return events

    def acknowledge(self, task_id: str, event_ids: Iterable[int]) -> int:
        self.store.task(task_id)
        # Never exhaust a caller-owned iterable before applying the cap.
        # In particular, an infinite iterator must be rejected after at most
        # 21 values, not hang the native event loop or allocate unbounded RAM.
        try:
            ids = tuple(islice(iter(event_ids), 21))
        except TypeError as error:
            raise ContractError("Invalid bounded delivery acknowledgement") from error
        if len(ids) > 20 or any(not isinstance(i, int) or isinstance(i, bool)
                               or i < 1 or i > _MAX_EVENT_ID for i in ids):
            raise ContractError("Invalid bounded delivery acknowledgement")
        if len(set(ids)) != len(ids):
            raise ContractError("Duplicate event acknowledgement")
        with self.store.tx() as db:
            count = 0
            for identifier in ids:
                cur = db.execute(
                    """UPDATE ha_event_delivery SET read_at=?
                       WHERE event_id=? AND task_id=? AND read_at IS NULL""",
                    (time.time(), identifier, task_id),
                )
                count += cur.rowcount
        return count

    def acknowledge_validated_request(self, task_id: str, message_id: str,
                                      *, route: str) -> int:
        """ACK only a validated *saved* request under its current task lease.

        Legacy pre-effect messages must not drain a transferred owner's inbox
        or a stopped task. The owner/status/epoch and receipt verification
        happen in the same SQLite write transaction as the read markers, so
        a concurrent transfer/revocation cannot race the final ACK. New
        native event packets carry an explicit owner+epoch binding; older
        packets without one are accepted only on their original first
        live lease (or an epoch-zero, never-assigned compatibility fixture).
        """
        _bounded(message_id, "native message id", 128)
        _bounded(route, "native route", 128)
        proof_fields = ("source", "source_id", "thread", "kind", "summary", "arrived")
        with self.store.tx() as db:
            message = db.execute(
                """SELECT payload,route FROM messages
                   WHERE id=? AND task_id=? AND state='validated'""",
                (message_id, task_id),
            ).fetchone()
            if message is None:
                return 0
            current = db.execute(
                """SELECT project_id,owner,epoch,status,lease_until
                   FROM tasks WHERE id=?""", (task_id,),
            ).fetchone()
            if current is None:
                raise ContractError("Validated native receipt has no current task")
            if message["route"] != route:
                raise ContractError("Validated native receipt route mismatch")
            # The old message route alone never establishes that its saved
            # conversation still owns this task. Historical unassigned
            # epoch-zero fixtures remain compatible; a previously assigned
            # task with no owner is explicitly *not* equivalent.
            if current["owner"] is None:
                if current["epoch"] != 0 or current["status"] != "queued":
                    raise ContractError(
                        "Validated native receipt has no eligible current owner"
                    )
            elif (current["owner"] != route or current["status"] != "running"
                  or current["epoch"] <= 0
                  or current["lease_until"] <= time.time()):
                raise ContractError(
                    "Validated native receipt requires the current live owner lease"
                )
            try:
                request = json.loads(message["payload"])
                if (not isinstance(request, dict)
                        or request.get("task_id") != task_id
                        or request.get("project_id") != current["project_id"]):
                    raise ContractError(
                        "Validated native receipt project binding mismatch"
                    )
                body = request.get("body", {})
                if not isinstance(body, dict):
                    raise ContractError("Malformed validated event request body")
                delivered = body.get("event_inputs", [])
                if not isinstance(delivered, list):
                    raise ContractError("Malformed validated native event inputs")
                # Validate the batch bound BEFORE walking every saved envelope.
                # The standalone ACK path is already capped at 20; a retained
                # browser request must not evade the same resource bound.
                if len(delivered) > 20:
                    raise ContractError("Invalid bounded native event acknowledgement")
                ids = []
                for item in delivered:
                    if (not isinstance(item, dict)
                            or type(item.get("event_id")) is not int
                            or not 1 <= item["event_id"] <= _MAX_EVENT_ID):
                        raise ContractError("Malformed validated native event receipt")
                    ids.append(item["event_id"])
            except (ValueError, TypeError) as error:
                raise ContractError(
                    "Malformed validated native event request"
                ) from error
            if len(ids) > 20 or len(set(ids)) != len(ids):
                raise ContractError("Invalid bounded native event acknowledgement")
            if not ids:
                return 0

            # Exact lease epoch is part of all newly saved native event
            # packets. Older packets lack this evidence. Do not invent the
            # original owner/epoch after a transfer: replay of an unbound
            # receipt in epoch 2+ must be explicitly reconciled instead.
            # The explicit field is a modern-packet contract. A null or
            # malformed value cannot silently opt back into historical
            # event-id-only compatibility on the first owner epoch.
            modern = "native_event_owner" in request
            binding = request.get("native_event_owner")
            if modern:
                if (not isinstance(binding, dict)
                        or binding.get("owner") != current["owner"]
                        or type(binding.get("epoch")) is not int
                        or binding["epoch"] != current["epoch"]):
                    raise ContractError(
                        "Validated native receipt owner-epoch binding mismatch"
                    )
            elif current["epoch"] > 1:
                raise ContractError(
                    "Historical native receipt lacks a current owner-epoch binding"
                )

            # Validate *all* deliveries before writing *any* read marker.
            # Legacy event-id-only records still require an authorized,
            # project-bound delivery. Modern packets also require their
            # entire immutable source envelope, not a truthful subset.
            for item in delivered:
                has_proof = any(field in item for field in proof_fields)
                # All newly stamped native Chat packets must retain the
                # complete source envelope. Only truly historical packets
                # without an owner stamp may contain just an event ID.
                if (modern and not has_proof) or (has_proof and any(
                    field not in item for field in proof_fields
                )):
                    raise ContractError(
                        "Malformed validated native event envelope: "
                        "incomplete source proof"
                    )
                # Python compares True == 1.0. A forged boolean arrival
                # timestamp can otherwise pass an exact-envelope comparison
                # when a historic event's arrival value is 1.0. JSON numeric
                # timestamps remain compatible; boolean/string proofs do not.
                if has_proof and type(item["arrived"]) not in (int, float):
                    raise ContractError(
                        "Malformed validated native event arrival proof"
                    )
                matched = db.execute(
                    """SELECT e.source,e.source_id,e.thread,e.kind,e.summary,
                              e.arrived
                       FROM ha_event_trigger e
                       JOIN ha_event_delivery d ON d.event_id=e.id
                       WHERE e.id=? AND e.project_id=? AND d.task_id=?""",
                    (item["event_id"], current["project_id"], task_id),
                ).fetchone()
                if matched is None:
                    raise ContractError(
                        "Validated native receipt has no authorized project delivery"
                    )
                if has_proof and any(
                    item[field] != matched[field] for field in proof_fields
                ):
                    raise ContractError(
                        "Validated native event envelope does not match "
                        "the immutable authorized project event"
                    )
            now = time.time()
            # The task row is writer-fenced for this transaction, but wall
            # clock time can advance during the envelope/source queries.
            # Never ACK after the owner's lease expires mid-validation.
            if current["owner"] is not None and current["lease_until"] <= now:
                raise ContractError(
                    "Validated native receipt owner lease expired before ACK"
                )
            count = 0
            for event_id in ids:
                updated = db.execute(
                    """UPDATE ha_event_delivery SET read_at=?
                       WHERE task_id=? AND event_id=? AND read_at IS NULL""",
                    (now, task_id, event_id),
                )
                count += updated.rowcount
            # The lease is time-based even when no other SQLite writer can
            # alter this task during our transaction. A slow batch of ACK
            # writes may cross its deadline after the earlier validation.
            # Reject before COMMIT so *all* read markers roll back together.
            if (current["owner"] is not None
                    and current["lease_until"] <= time.time()):
                raise ContractError(
                    "Validated native receipt owner lease expired during ACK"
                )
            return count

    def bridge_native(self, project_id: str, limit: int = 100) -> int:
        """Read the local Store event journal into this project's inbox.

        Idempotent after restart and safe across projects. The Store's journal
        may contain arbitrary user-controlled text; only the event kind and
        entity identity are passed as summaries, never the raw payload.
        """
        self.store.project(project_id)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 500:
            raise ContractError("Invalid native bridge batch")
        cursor = self.store.rows(
            "SELECT last_seq FROM ha_native_event_cursor WHERE project_id=?",
            (project_id,),
        )
        seen = cursor[0]["last_seq"] if cursor else 0
        # Filter *inside SQLite* so unrelated projects or debug chatter
        # cannot starve this project's bounded native event bridge.
        kinds = tuple(sorted(_STATE_KINDS))
        marks = ",".join("?" for _ in kinds)
        rows = self.store.rows(
            """SELECT e.seq,e.entity,e.kind FROM events e
               LEFT JOIN tasks t ON t.id=e.entity
               WHERE e.seq>? AND (e.entity=? OR t.project_id=?)
                 AND e.kind IN (""" + marks + """)
               ORDER BY e.seq LIMIT ?""",
            (seen, project_id, project_id, *kinds, limit),
        )
        if not rows:
            return 0
        admitted = 0
        for row in rows:
            entity = row["entity"]
            outcome = self.receive(
                project_id=project_id, source="native",
                source_id="journal:" + str(row["seq"]),
                thread="project:" + project_id, kind=row["kind"],
                summary="Local HA state event " + row["kind"] + " for " + entity,
            )
            admitted += int(outcome == "stored")
        # Advance only after the whole batch was successfully admitted. Any
        # interrupted retry replays stable IDs, which receive() deduplicates.
        with self.store.tx() as db:
            db.execute(
                """INSERT INTO ha_native_event_cursor(project_id,last_seq)
                   VALUES(?,?) ON CONFLICT(project_id)
                   DO UPDATE SET last_seq=MAX(last_seq,excluded.last_seq)""",
                (project_id, rows[-1]["seq"]),
            )
        return admitted
