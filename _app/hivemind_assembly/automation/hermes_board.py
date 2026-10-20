"""Hermes Kanban is the dependency graph and claim authority for native work.

HA leases fence domain writes; they do not choose or override Hermes dependency
readiness. Native transport replaces inference, never launches API workers.
"""

import time
from contextlib import contextmanager
from pathlib import Path
from hivemind_assembly.core.common import Blocked, ContractError, canonical, digest


class HermesBoard:
    def __init__(self, root):
        from hermes_cli import kanban_db
        from hermes_cli.kanban_db_connect import connect

        self.api, self.connect = kanban_db, connect
        self.path = Path(root) / "hermes-kanban.sqlite3"

    @contextmanager
    def connection(self):
        conn = self.connect(self.path)
        try:
            yield conn
        finally:
            conn.close()

    def register(self, conn, task, parents=()):
        return self.api.create_task(
            conn,
            title=task["objective"][:200],
            body=task["objective"],
            tenant=task["project_id"],
            workspace_kind="scratch",
            idempotency_key="ha:" + task["id"],
            parents=parents,
            created_by="hivemind-native",
        )

    def claim(self, task):
        with self.connection() as conn:
            key = self.register(conn, task)
            self.api.recompute_ready(conn)
            card = self.api.get_task(conn, key)
            owner = "ha:" + task["id"]
            if card.status == "running" and card.claim_lock == owner:
                return self.api.heartbeat_claim(
                    conn, key, claimer=owner, ttl_seconds=1800
                )
            if card.status != "ready":
                return False
            return (
                self.api.claim_task(conn, key, claimer=owner, ttl_seconds=1800)
                is not None
            )

    def complete(self, task, evidence):
        with self.connection() as conn:
            key = self.register(conn, task)
            card = self.api.get_task(conn, key)
            if card.status == "done":
                return
            if not self.api.complete_task(
                conn,
                key,
                result=canonical(evidence),
                expected_run_id=card.current_run_id,
                fire_lifecycle_hook=False,
            ):
                raise Blocked(
                    "Hermes did not accept task completion; dependencies remain"
                )
            self.api.recompute_ready(conn)

    def plan(self, store, task, nodes, configure):
        if not isinstance(nodes, list) or not 1 <= len(nodes) <= 24:
            raise ContractError("A task plan requires 1–24 bounded children")
        for i, node in enumerate(nodes):
            if not isinstance(node, dict) or set(node) != {
                "objective",
                "parents",
                "acceptance",
            }:
                raise ContractError(
                    "Each child needs objective, earlier-parent indices and acceptance"
                )
            if (
                not isinstance(node["objective"], str)
                or not 1 <= len(node["objective"]) <= 10000
            ):
                raise ContractError("Invalid child objective")
            if (
                not isinstance(node["parents"], list)
                or any(type(p) is not int or not 0 <= p < i for p in node["parents"])
                or len(set(node["parents"])) != len(node["parents"])
            ):
                raise ContractError("Dependencies must refer to distinct earlier nodes")
            if not isinstance(node["acceptance"], dict):
                raise ContractError("Child acceptance must be a contract")
        # One retained plan per root; recovery cannot silently substitute a graph.
        store.put("hermes_plan", task["id"], {"nodes": nodes})
        with self.connection() as conn:
            root = self.register(conn, task)
            root_card = self.api.get_task(conn, root)
            children = []
            cards = []
            for i, node in enumerate(nodes):
                child = {
                    "id": "task_" + digest({"root": task["id"], "index": i})[:32],
                    "project_id": task["project_id"],
                    "objective": node["objective"],
                }
                cards.append(
                    self.register(conn, child, [cards[p] for p in node["parents"]])
                )
                children.append(child)
            for card in cards:
                # Replaying an existing edge is idempotent; the run fence permits
                # the orchestrating root to hand itself off to its prerequisites.
                exists = conn.execute(
                    "SELECT 1 FROM task_links WHERE parent_id=? AND child_id=?",
                    (card, root),
                ).fetchone()
                if not exists:
                    self.api.link_tasks(
                        conn, card, root, expected_child_run_id=root_card.current_run_id
                    )
            for child in children:
                with store.tx() as db:
                    db.execute(
                        "INSERT OR IGNORE INTO tasks(id,project_id,objective,status,updated) VALUES(?,?,?,'paused',?)",
                        (
                            child["id"],
                            child["project_id"],
                            child["objective"],
                            time.time(),
                        ),
                    )
            for child, node in zip(children, nodes):
                # Pin acceptance before making any child runnable.
                if not store.rows(
                    "SELECT 1 FROM records WHERE kind='acceptance_contract' AND id=?",
                    (child["id"],),
                ):
                    configure(child["id"], node["acceptance"])
            card = self.api.get_task(conn, root)
            if card.status == "running":
                self.api.block_task(
                    conn,
                    root,
                    reason="Waiting for accepted child results",
                    kind="dependency",
                    expected_run_id=card.current_run_id,
                )
            with store.tx() as db:
                for child in children:
                    db.execute(
                        "UPDATE tasks SET status='queued' WHERE id=? AND status='paused'",
                        (child["id"],),
                    )
                db.execute(
                    "UPDATE tasks SET status='waiting_dependencies',owner=NULL,lease_until=0,brief_id=NULL WHERE id=?",
                    (task["id"],),
                )
                store.put(
                    "hermes_plan_published",
                    task["id"],
                    {"children": [c["id"] for c in children]},
                    db,
                )
                store.event(
                    task["id"],
                    "hermes_plan_created",
                    {"children": [c["id"] for c in children]},
                    db,
                )
            return {"children": [c["id"] for c in children]}

    def status(self):
        with self.connection() as conn:
            return [
                {
                    "id": t.id,
                    "title": t.title,
                    "status": t.status,
                    "project": t.tenant,
                    "claim": t.claim_lock,
                }
                for t in self.api.list_tasks(conn, limit=200)
            ]
