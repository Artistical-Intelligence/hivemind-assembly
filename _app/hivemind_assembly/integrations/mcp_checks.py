"""Resumable MCP requests for owner-pinned checks, without exposing holdouts."""

import json
import re
import threading
import time

from hivemind_assembly.core.common import Blocked, Conflict, ContractError, uid


class CheckRequests:
    def __init__(self, app, authorize):
        self.app, self.store, self.authorize = app, app.store, authorize
        self.instance = uid("mcp_checks")
        self.lock = threading.RLock()
        self.active = {}
        self.closed = False

    def key(self, request_id):
        if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", request_id):
            raise ContractError("Provide a stable check request ID")
        return request_id

    def retained(self, request_id):
        rows = self.store.rows(
            "SELECT payload FROM records WHERE kind='mcp_check_request' AND id=?",
            (self.key(request_id),),
        )
        return json.loads(rows[0]["payload"]) if rows else None

    def status(self, task_id, request_id):
        self.authorize(task_id)
        request = self.retained(request_id)
        if request is None:
            return {"request_id": request_id, "task": task_id, "status": "not_found"}
        if request["task"] != task_id:
            raise Conflict("Check request belongs to a different task")
        result = self.store.rows(
            "SELECT payload FROM records WHERE kind='mcp_check_result' AND id=?",
            (request_id,),
        )
        value = {k: request[k] for k in ("task", "request_id", "revision", "started")}
        current = self.store.project(self.store.task(task_id)["project_id"])["revision"]
        value.update(current_revision=current, stale=current != request["revision"])
        if result:
            return {**value, **json.loads(result[0]["payload"])}
        active = self.active.get(request_id)
        running = request["instance"] == self.instance and active and active[1].is_alive()
        return {
            **value,
            "status": "running" if running else "interrupted",
            "task_accepted": False,
            "instruction": "Poll this request; an interrupted request is never automatically repeated. Review HA evidence before starting another request.",
        }

    def start(self, task_id, request_id):
        with self.lock:
            if self.closed or self.app.shutdown:
                raise Blocked("HA is shutting down")
            task = self.authorize(task_id)
            if self.retained(request_id):
                return self.status(task_id, request_id)
            self.active = {key: item for key, item in self.active.items() if item[1].is_alive()}
            # Reserve the project before the worker thread claims its task lease.
            if any(project == task["project_id"] and thread.is_alive()
                   for project, thread in self.active.values()):
                raise Blocked("A check is already running for this project")
            self.app.workspace.guard(task_id)
            from hivemind_assembly.core.acceptance import Acceptance

            if Acceptance(self.app.controller, self.app.broker).describe(task_id) is None:
                raise Blocked("Pin independent acceptance in HA before requesting checks")
            self.store.put("mcp_check_request", request_id, {
                "task": task_id, "request_id": request_id, "instance": self.instance,
                "revision": self.store.project(task["project_id"])["revision"],
                "started": time.time(),
            })
            revision = self.retained(request_id)["revision"]

            def work():
                try:
                    self.authorize(task_id)
                    if self.closed or self.app.shutdown:
                        raise Blocked("HA is shutting down")
                    from hivemind_assembly.application.project_checks import run_checks

                    report = run_checks(self.app, task_id, expected_revision=revision)
                    result = report.get("result", report)
                    summary = {
                        "status": "completed", "passed": result.get("passed") is True,
                        "scope": result.get("scope"), "task_accepted": False,
                        "finished": time.time(),
                    }
                except Exception as error:
                    # Provider/compiler errors and evaluator results can include
                    # protected data. Retain only an error category for MCP.
                    evidence = self.app.broker.artifacts.add(
                        json.dumps({"type": type(error).__name__, "message": str(error)}),
                        "mcp-check-error.json", task["project_id"], "protected",
                    )
                    self.store.event(task_id, "mcp_check_failed", {
                        "request_id": request_id, "artifact": evidence["id"],
                    })
                    summary = {
                        "status": "failed", "error_type": type(error).__name__,
                        "instruction": "Review the project's checks and permissions in HA.",
                        "task_accepted": False, "finished": time.time(),
                    }
                self.store.put("mcp_check_result", request_id, summary)

            thread = threading.Thread(target=work, daemon=True)
            self.active[request_id] = (task["project_id"], thread)
            try:
                thread.start()
            except RuntimeError:
                self.store.put("mcp_check_result", request_id, {
                    "status": "failed", "error_type": "ThreadStartError", "task_accepted": False,
                })
            return self.status(task_id, request_id)

    def close(self):
        with self.lock:
            self.closed = True
            running = [thread for _, thread in self.active.values() if thread.is_alive()]
            for request_id, (_, thread) in self.active.items():
                if thread.is_alive():
                    task_id = self.retained(request_id)["task"]
                    self.app.broker.cancel.setdefault(task_id, threading.Event()).set()
        deadline = time.monotonic() + 20
        for thread in running:
            thread.join(max(0, deadline - time.monotonic()))
        if any(thread.is_alive() for thread in running):
            raise Blocked("Check cleanup is still running; keep HA open until it finishes")
