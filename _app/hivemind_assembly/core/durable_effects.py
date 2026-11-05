"""Fenced, journal-backed effect receipts for existing HA native tickets.

Inspired by the durable effects/outbox mechanisms in DeepSeek's MIT-licensed
dsh-superagent-prototype (src/app/effects.ts and outbox.ts). This is original
Python over the existing HA Store, NOT a new model scheduler or agent runtime.

The queue contains REFERENCES to already authorized, scoped local events,
never arbitrary executable commands or external payload bodies. Only an owner
holding the current Controller lease can claim or finalize a delivery.
A validated native browser response is required before final acknowledgment.

This module performs NO HTTP calls, webhook requests, model inference,
ChatGPT API calls, scheduler changes, filesystem writes or user approvals.
"""

from __future__ import annotations

import json
import time

from hivemind_assembly.core.common import Blocked, Conflict, ContractError


_SCHEMA = """
CREATE TABLE IF NOT EXISTS ha_native_effect(
    task_id TEXT NOT NULL REFERENCES tasks(id),
    effect_key TEXT NOT NULL,
    project_id TEXT NOT NULL,
    event_id INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN
        ('queued','leased','uncertain','delivered')),
    generation INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    due_at REAL NOT NULL,
    lease_until REAL,
    receipt_id TEXT,
    claimed_at REAL,
    updated REAL NOT NULL,
    PRIMARY KEY(task_id,effect_key)
);
CREATE UNIQUE INDEX IF NOT EXISTS ha_native_effect_one_per_event
ON ha_native_effect(task_id,event_id);
CREATE INDEX IF NOT EXISTS ha_native_effect_due
ON ha_native_effect(task_id,status,due_at);
"""


def _key(value: str, description: str) -> str:
    if (not isinstance(value, str) or not 1 <= len(value) <= 180 or
            any(ord(char) < 33 or ord(char) > 126 for char in value)):
        raise ContractError("Invalid " + description)
    return value


class DurableEventEffects:
    """Explicitly fenced, at-least-once *intent*, exactly-once *receipt*.

    The host must use Controller.acquire before claim(), and the existing
    NativeTeam.browser.exchange/NativeTransport must produce validated message
    receipts. A timed-out or uncertain delivery is never retried automatically.
    """

    def __init__(self, store):
        self.store = store
        with store.tx() as db:
            # sqlite3.executescript() implicitly COMMITs an active transaction.
            # Execute each fixed DDL statement under HA's own Store.tx fence.
            for statement in _SCHEMA.split(";"):
                if statement.strip():
                    db.execute(statement)
            # Existing installations may have the original table without
            # claimed_at. Never invent a verified claim time for ambiguous
            # older 'uncertain' deliveries: require manual reconciliation.
            names = {column["name"] for column in db.execute(
                "PRAGMA table_info(ha_native_effect)"
            )}
            if "claimed_at" not in names:
                db.execute("ALTER TABLE ha_native_effect ADD COLUMN claimed_at REAL")
                db.execute(
                    """UPDATE ha_native_effect SET claimed_at=updated
                       WHERE status='leased' AND claimed_at IS NULL"""
                )

    def enqueue(self, task_id: str, effect_key: str, event_id: int) -> str:
        """Idempotently queue an EXISTING project-matched local event.

        Requires NativeEventInbox to have admitted the event and assigned a
        delivery to this task. Does not grant new subscriptions or permissions.
        """
        _key(effect_key, "effect key")
        if not isinstance(event_id, int) or isinstance(event_id, bool) or event_id < 1:
            raise ContractError("Invalid local event ID")
        task = self.store.task(task_id)
        with self.store.tx() as db:
            event = db.execute(
                """SELECT e.id,d.read_at FROM ha_event_delivery d
                   JOIN ha_event_trigger e ON e.id=d.event_id
                   WHERE d.task_id=? AND d.event_id=? AND e.project_id=?""",
                (task_id, event_id, task["project_id"]),
            ).fetchone()
            if not event:
                raise Blocked("Effect refers to an unauthorized or unknown local event")
            existing = db.execute(
                "SELECT event_id FROM ha_native_effect WHERE task_id=? AND effect_key=?",
                (task_id, effect_key),
            ).fetchone()
            if existing:
                if existing["event_id"] != event_id:
                    raise Conflict("Effect key reused for a different event")
                return "duplicate"
            if event["read_at"] is not None:
                raise Blocked("Event delivery already acknowledged")
            second = db.execute(
                """SELECT effect_key FROM ha_native_effect
                   WHERE task_id=? AND event_id=?""",
                (task_id, event_id),
            ).fetchone()
            if second:
                raise Conflict("Event delivery already bound to another effect key")
            db.execute(
                """INSERT INTO ha_native_effect
                   (task_id,effect_key,project_id,event_id,status,due_at,updated)
                   VALUES(?,?,?,?,'queued',?,?)""",
                (task_id, effect_key, task["project_id"], event_id,
                 time.time(), time.time()),
            )
            return "queued"

    @staticmethod
    def _fence(db, task_id: str, owner: str, epoch: int) -> None:
        task = db.execute(
            "SELECT owner,epoch,lease_until,status FROM tasks WHERE id=?",
            (task_id,),
        ).fetchone()
        if (task is None or task["owner"] != owner or
                task["epoch"] != epoch or task["status"] != "running" or
                task["lease_until"] <= time.time()):
            raise Conflict("Native delivery requires the current live owner lease")

    def claim(self, task_id: str, owner: str, epoch: int, *,
              now: float | None = None, lease_seconds: int = 180) -> dict | None:
        """Claim the first due intent, but never preempt a leased/uncertain one."""
        _key(owner, "native owner")
        if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch <= 0:
            raise ContractError("Invalid worker epoch")
        if (not isinstance(lease_seconds, int) or isinstance(lease_seconds, bool)
                or not 30 <= lease_seconds <= 3600):
            raise ContractError("Native event lease must be 30–3600 seconds")
        clock = time.time() if now is None else float(now)
        with self.store.tx() as db:
            self._fence(db, task_id, owner, epoch)
            # Native chat exchanges are ordered per task/conversation. Never
            # start a second browser delivery while the first is in-flight or
            # uncertain; a crash must be reconciled, not blindly replayed.
            in_flight = db.execute(
                """SELECT 1 FROM ha_native_effect WHERE task_id=?
                   AND status IN ('leased','uncertain') LIMIT 1""",
                (task_id,),
            ).fetchone()
            if in_flight:
                return None
            row = db.execute(
                """SELECT e.* FROM ha_native_effect e
                   JOIN ha_event_delivery d ON d.task_id=e.task_id
                     AND d.event_id=e.event_id
                   WHERE e.task_id=? AND e.status='queued'
                     AND e.due_at<=? AND d.read_at IS NULL
                   ORDER BY e.due_at,e.effect_key LIMIT 1""",
                (task_id, clock),
            ).fetchone()
            if row is None:
                return None
            generation = row["generation"] + 1
            claimed_at = time.time()
            db.execute(
                """UPDATE ha_native_effect SET status='leased',
                   generation=?,attempts=attempts+1,lease_until=?,
                   claimed_at=?,updated=?
                   WHERE task_id=? AND effect_key=?""",
                (generation, claimed_at + lease_seconds, claimed_at,
                 claimed_at, task_id, row["effect_key"]),
            )
            return {
                "task_id": task_id, "effect_key": row["effect_key"],
                "event_id": row["event_id"], "generation": generation,
                "lease_until": claimed_at + lease_seconds,
            }

    def finalize(self, task_id: str, owner: str, epoch: int,
                 effect_key: str, generation: int, receipt_id: str) -> str:
        """Accept only an actual validated NativeTransport response that saw the event."""
        _key(effect_key, "effect key")
        _key(receipt_id, "validated message ID")
        if not isinstance(generation, int) or isinstance(generation, bool):
            raise ContractError("Invalid generation")
        with self.store.tx() as db:
            self._fence(db, task_id, owner, epoch)
            row = db.execute(
                "SELECT * FROM ha_native_effect WHERE task_id=? AND effect_key=?",
                (task_id, effect_key),
            ).fetchone()
            if not row:
                raise Conflict("Unknown native event effect")
            if row["status"] == "delivered":
                if row["receipt_id"] != receipt_id:
                    raise Conflict("Delivered effect has a different receipt")
                return "duplicate"
            if row["generation"] != generation or row["status"] not in (
                "leased", "uncertain",
            ):
                raise Conflict("Stale or non-leased event effect")
            delivery = db.execute(
                """SELECT d.read_at FROM ha_event_delivery d
                   JOIN ha_event_trigger t ON t.id=d.event_id
                   WHERE d.task_id=? AND d.event_id=? AND t.project_id=?""",
                (task_id, row["event_id"], row["project_id"]),
            ).fetchone()
            if delivery is None:
                raise Conflict("Event delivery was revoked or is no longer authorized")
            if delivery["read_at"] is not None:
                raise Blocked("Event delivery already acknowledged outside this effect")
            receipt = db.execute(
                """SELECT payload,created FROM messages
                   WHERE id=? AND task_id=? AND route=? AND state='validated'""",
                (receipt_id, task_id, owner),
            ).fetchone()
            if not receipt:
                raise Blocked("No validated native browser response for this effect")
            if row["claimed_at"] is None or receipt["created"] < row["claimed_at"]:
                raise Blocked("Validated receipt predates this effect claim")
            try:
                event_inputs = json.loads(receipt["payload"]).get(
                    "body", {},
                ).get("event_inputs", [])
            except (TypeError, ValueError, AttributeError) as error:
                raise ContractError("Malformed validated message payload") from error
            if not isinstance(event_inputs, list) or not any(
                isinstance(value, dict) and
                value.get("event_id") == row["event_id"]
                for value in event_inputs
            ):
                raise Blocked("Validated native browser turn never received this event")
            db.execute(
                """UPDATE ha_native_effect SET status='delivered',
                   receipt_id=?,lease_until=NULL,updated=?
                   WHERE task_id=? AND effect_key=?""",
                (receipt_id, time.time(), task_id, effect_key),
            )
            db.execute(
                """UPDATE ha_event_delivery SET read_at=COALESCE(read_at,?)
                   WHERE task_id=? AND event_id=?""",
                (time.time(), task_id, row["event_id"]),
            )
            return "delivered"

    def interrupted(self, task_id: str, owner: str, epoch: int,
                    effect_key: str, generation: int, *, definitely_not_sent: bool,
                    delay_seconds: int = 30) -> str:
        """Retry only proven pre-dispatch failure; otherwise require reconciliation."""
        _key(effect_key, "effect key")
        if type(definitely_not_sent) is not bool:
            raise ContractError("Pre-dispatch retry proof must be an explicit boolean")
        if (not isinstance(delay_seconds, int) or isinstance(delay_seconds, bool)
                or not 0 <= delay_seconds <= 3600):
            raise ContractError("Invalid event retry delay")
        with self.store.tx() as db:
            self._fence(db, task_id, owner, epoch)
            row = db.execute(
                "SELECT status,generation FROM ha_native_effect WHERE task_id=? AND effect_key=?",
                (task_id, effect_key),
            ).fetchone()
            if (not row or row["status"] != "leased"
                    or row["generation"] != generation):
                raise Conflict("Effect lease is stale or was already resolved")
            state = "queued" if definitely_not_sent else "uncertain"
            db.execute(
                """UPDATE ha_native_effect SET status=?,lease_until=NULL,
                   due_at=?,updated=? WHERE task_id=? AND effect_key=?""",
                (state, time.time() + delay_seconds, time.time(), task_id, effect_key),
            )
            return state

    def status(self, task_id: str) -> list[dict]:
        self.store.task(task_id)
        return self.store.rows(
            """SELECT effect_key,event_id,status,generation,attempts,
                      due_at,lease_until,receipt_id
               FROM ha_native_effect WHERE task_id=?
               ORDER BY effect_key""",
            (task_id,),
        )
