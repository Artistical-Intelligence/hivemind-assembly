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
import time
from collections.abc import Iterable

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
                     AND json_extract(payload,'$.task_id')=?
                   ORDER BY rowid DESC LIMIT 1""",
                (task_id,),
            )
            if not records:
                return self.record_ticket(task_id, "needs_check")
            try:
                result = json.loads(records[0]["payload"])
            except (ValueError, TypeError) as error:
                raise ContractError("Malformed retained acceptance evidence") from error
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

    def subscribe(self, task_id: str, thread: str) -> None:
        task = self.store.task(task_id)
        valid = {"project:" + task["project_id"], "task:" + task_id}
        if thread not in valid:
            raise ContractError("Cross-project or arbitrary thread subscription denied")
        self.ensure_ticket(task_id)
        with self.store.tx() as db:
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

    def unsubscribe(self, task_id: str, thread: str) -> int:
        """Revoke delivery without discarding the immutable source journal.

        Existing read receipts remain available for reconciliation. Unread
        deliveries on this thread are dropped; an existing task cannot revive
        them merely by re-subscribing after an owner/project route change.
        """
        task = self.store.task(task_id)
        allowed = {"project:" + task["project_id"], "task:" + task_id}
        if thread not in allowed:
            raise ContractError("Cross-project or arbitrary thread unsubscription denied")
        with self.store.tx() as db:
            db.execute(
                """DELETE FROM ha_event_subscription
                   WHERE project_id=? AND task_id=? AND thread=?""",
                (task["project_id"], task_id, thread),
            )
            removed = db.execute(
                """DELETE FROM ha_event_delivery
                   WHERE task_id=? AND read_at IS NULL AND event_id IN
                       (SELECT id FROM ha_event_trigger
                        WHERE project_id=? AND thread=?)""",
                (task_id, task["project_id"], thread),
            )
            # Remove only never-claimed *queued* effect intents for the
            # explicitly revoked thread. A leased/uncertain browser dispatch
            # is irreversible evidence: retain it for reconciliation rather
            # than silently erasing an external side effect.
            has_effects = db.execute(
                """SELECT 1 FROM sqlite_master
                   WHERE type='table' AND name='ha_native_effect'"""
            ).fetchone()
            if has_effects:
                db.execute(
                    """DELETE FROM ha_native_effect
                       WHERE task_id=? AND status='queued'
                         AND event_id IN (
                           SELECT id FROM ha_event_trigger
                           WHERE project_id=? AND thread=?
                         )""",
                    (task_id, task["project_id"], thread),
                )
            # An explicit unsubscribe revokes unfinished historic catch-up,
            # including pages never previously loaded. Later rejoin must not
            # reconstruct the revoked events from the immutable source journal.
            db.execute(
                """UPDATE ha_event_subscription_backfill SET cursor=upto
                   WHERE task_id=? AND thread=? AND project_id=?""",
                (task_id, thread, task["project_id"]),
            )
            return removed.rowcount

    def receive(self, *, project_id: str, source: str, source_id: str,
                thread: str, kind: str, summary: str,
                verified: bool = False) -> str:
        """Record one stable trigger and enqueue it for current subscribers.

        `verified` is supplied ONLY by an authenticated native adapter, never
        trusted from an external event payload. Internal journal events use
        source='native'. No new task, permission or model call is created.
        """
        _bounded(project_id, "project id", 128)
        _bounded(source, "source", 64)
        _bounded(source_id, "source id", 200)
        _bounded(thread, "thread", 256)
        _bounded(kind, "kind", 100)
        _bounded(summary, "summary", 500)
        if source != "native" and not verified:
            raise ContractError("External source event requires verified adapter")
        if thread != "project:" + project_id and not thread.startswith("task:"):
            raise ContractError("Thread must belong to the supplied project")
        self.store.project(project_id)
        if thread.startswith("task:"):
            if self.store.task(thread[5:])["project_id"] != project_id:
                raise ContractError("Event targets task in different project")

        with self.store.tx() as db:
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
            db.execute(
                """INSERT OR IGNORE INTO ha_event_delivery(event_id,task_id)
                   SELECT ?,task_id FROM ha_event_subscription
                   WHERE project_id=? AND thread=?""",
                (cur.lastrowid, project_id, thread),
            )
        return "stored"

    def pending(self, task_id: str, limit: int = 6) -> list[dict]:
        task = self.store.task(task_id)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
            raise ContractError("Event batch size out of range")
        with self.store.tx() as db:
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
        # Summaries are facts/data, not source instructions or permission grants.
        return [{"event_id": row["id"], "source": row["source"],
                 "source_id": row["source_id"], "thread": row["thread"],
                 "kind": row["kind"], "summary": row["summary"],
                 "arrived": row["arrived"]} for row in rows]

    def acknowledge(self, task_id: str, event_ids: Iterable[int]) -> int:
        self.store.task(task_id)
        ids = tuple(event_ids)
        if len(ids) > 20 or any(not isinstance(i, int) or isinstance(i, bool)
                               or i < 1 for i in ids):
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
        """Acknowledge only event IDs actually present in a validated request.

        Prepared/uncertain browser messages have no authority to consume
        deliveries. A replay uses the persisted request rather than any
        newly arrived event list supplied by the caller.
        """
        task = self.store.task(task_id)
        _bounded(message_id, "native message id", 128)
        _bounded(route, "native route", 128)
        messages = self.store.rows(
            """SELECT payload,route FROM messages
               WHERE id=? AND task_id=? AND state='validated'""",
            (message_id, task_id),
        )
        if not messages:
            return 0
        if messages[0]["route"] != route:
            raise ContractError("Validated native receipt route mismatch")
        try:
            request = json.loads(messages[0]["payload"])
            if (not isinstance(request, dict)
                    or request.get("task_id") != task_id
                    or request.get("project_id") != task["project_id"]):
                raise ContractError("Validated native receipt project binding mismatch")
            body = request.get("body", {})
            if not isinstance(body, dict):
                raise ContractError("Malformed validated event request body")
            delivered = body.get("event_inputs", [])
            if not isinstance(delivered, list):
                raise ContractError("Malformed validated native event inputs")
            if any(not isinstance(row, dict) or
                   "event_id" not in row for row in delivered):
                raise ContractError("Malformed validated native event receipt")
            ids = [row["event_id"] for row in delivered]
        except (ValueError, TypeError) as error:
            raise ContractError("Malformed validated native event request") from error

        # Older saved native requests recorded only event_id. Keep that
        # historical compatibility route without inventing a new source ACK.
        # Newer native packets include immutable source/thread/kind/summary
        # fields: refuse a partial or forged envelope that contradicts the
        # original project-scoped event journal.
        proof_fields = ("source", "source_id", "thread", "kind", "summary", "arrived")
        for item in delivered:
            if not any(field in item for field in proof_fields):
                continue
            # Pre-upgrade native receipts contained only an event ID. Once
            # ANY modern event metadata appears it must include the ENTIRE
            # immutable scoped envelope; a conveniently truthful subset
            # must not bypass source/project binding.
            if any(field not in item for field in proof_fields):
                raise ContractError(
                    "Malformed validated native event envelope: incomplete source proof"
                )
            if (type(item["event_id"]) is not int or
                    item["event_id"] <= 0):
                raise ContractError("Invalid saved native event identifier")
            matched = self.store.rows(
                """SELECT e.source,e.source_id,e.thread,e.kind,e.summary,
                          e.arrived FROM ha_event_trigger e
                   JOIN ha_event_delivery d ON d.event_id=e.id
                   WHERE e.id=? AND e.project_id=? AND d.task_id=?""",
                (item["event_id"], task["project_id"], task_id),
            )
            if not matched or any(
                item.get(field) != matched[0][field]
                for field in proof_fields if field in item
            ):
                raise ContractError(
                    "Validated native event envelope does not match "
                    "the immutable authorized project event"
                )
        return self.acknowledge(task_id, ids)

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
