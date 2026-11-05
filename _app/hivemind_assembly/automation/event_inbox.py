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
    """CREATE INDEX IF NOT EXISTS ha_event_delivery_unread
       ON ha_event_delivery(task_id, read_at, event_id)""",
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
                "SELECT state FROM ha_work_ticket WHERE task_id=?", (task_id,)
            ).fetchone()
            if prior[0] in _TERMINAL_TICKET_STATES and prior[0] != state:
                raise ContractError("Terminal ticket cannot be reopened implicitly")
            db.execute(
                """UPDATE ha_work_ticket SET state=?,last_run=COALESCE(?,last_run),
                   last_artifact=COALESCE(?,last_artifact),updated=?
                   WHERE task_id=?""",
                (state, run_id, artifact_sha, time.time(), task_id),
            )
        return self.ticket(task_id)

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
        rows = self.store.rows(
            """SELECT e.id,e.source,e.source_id,e.thread,e.kind,e.summary,e.arrived
               FROM ha_event_delivery d JOIN ha_event_trigger e ON e.id=d.event_id
               WHERE d.task_id=? AND d.read_at IS NULL AND e.project_id=?
               ORDER BY e.id LIMIT ?""",
            (task_id, task["project_id"], limit),
        )
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
        rows = self.store.rows(
            "SELECT seq,entity,kind FROM events WHERE seq>? ORDER BY seq LIMIT ?",
            (seen, limit),
        )
        if not rows:
            return 0
        admitted = 0
        for row in rows:
            if row["kind"] not in _STATE_KINDS:
                continue
            entity = row["entity"]
            if entity != project_id:
                task = self.store.rows(
                    "SELECT project_id FROM tasks WHERE id=?", (entity,),
                )
                if not task or task[0]["project_id"] != project_id:
                    continue
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
