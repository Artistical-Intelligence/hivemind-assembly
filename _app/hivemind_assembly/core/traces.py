"""Local, append-only transport evidence. Never supplied as worker context.

The transcript is captured before parsing, including partial and invalid replies.
Search is paginated; exports are explicit owner actions, never telemetry uploads.
"""

import json
import time
from hashlib import sha256

from .common import ContractError, canonical


class Traces:
    def __init__(self, store):
        self.store = store

    def append(self, task, correlation, route, kind, payload, *, connection=None):
        raw = canonical(payload)
        # Deduplicate identical DOM snapshots across polling and crash recovery.
        key = sha256(
            canonical([correlation, route, kind, payload]).encode()
        ).hexdigest()

        def write(db):
            db.execute(
                "INSERT OR IGNORE INTO traces(identity,task_id,correlation,route,kind,payload,created) VALUES(?,?,?,?,?,?,?)",
                (key, task, correlation, route, kind, raw, time.time()),
            )

        if connection is not None:
            write(connection)
        else:
            with self.store.tx() as db:
                write(db)
        return key

    def search(self, *, task=None, route=None, kind=None, query="", after=0, limit=100):
        if not isinstance(limit, int) or not 1 <= limit <= 500 or int(after) < 0:
            raise ContractError("Invalid trace pagination")
        clauses, args = ["seq > ?"], [int(after)]
        for field, value in (("task_id", task), ("route", route), ("kind", kind)):
            if value:
                clauses.append(field + "=?")
                args.append(value)
        if query:
            clauses.append("instr(lower(payload),lower(?)) > 0")
            args.append(str(query)[:500])
        rows = self.store.rows(
            "SELECT * FROM traces WHERE "
            + " AND ".join(clauses)
            + " ORDER BY seq LIMIT ?",
            (*args, limit),
        )
        for row in rows:
            row["payload"] = json.loads(row["payload"])
        return {"items": rows, "after": rows[-1]["seq"] if rows else int(after)}

    def annotate(self, seq, text):
        if not isinstance(text, str) or not 1 <= len(text) <= 10000:
            raise ContractError("Review notes must contain 1–10000 characters")
        row = self.store.one("SELECT * FROM traces WHERE seq=?", (int(seq),))
        return self.append(
            row["task_id"],
            row["identity"],
            "owner",
            "annotation",
            {"trace": int(seq), "text": text},
        )

    def export(self, **filters):
        after = 0
        while True:
            batch = self.search(**filters, after=after, limit=500)
            if not batch["items"]:
                return
            for row in batch["items"]:
                yield canonical(row) + "\n"
            after = batch["after"]
