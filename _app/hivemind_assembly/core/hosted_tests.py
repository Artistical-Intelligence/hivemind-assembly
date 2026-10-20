"""Durable optional GitHub Actions requests; remote success is not acceptance.

No automatic retry of an uncertain POST. Unique retained tags select an exact
reviewed commit without moving the project's branch or creating a repository.
"""

import base64
import json
from pathlib import Path
import re
import threading
import time
from urllib.parse import quote

from .common import Blocked, Conflict, ContractError, uid
from .tool_testing import relative

WORKFLOW = "native-tests.yml"
TEMPLATE = Path(__file__).parents[1] / "integrations" / WORKFLOW
TERMINAL = {"completed", "conflict", "cancelled"}


class HostedTests:
    def __init__(self, store, repositories):
        self.store, self.repositories = store, repositories
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.thread = None

    def state(self, request_id):
        rows = self.store.rows(
            "SELECT payload FROM records WHERE kind=? ORDER BY rowid DESC LIMIT 1",
            ("hosted_state:" + request_id,),
        )
        return json.loads(rows[0]["payload"]) if rows else {"status": "prepared"}

    def save(self, request_id, **values):
        state = self.state(request_id) | values | {"updated": time.time()}
        self.store.put("hosted_state:" + request_id, uid("hosted_state"), state)
        return state

    def status(self, request_id):
        return self.store.get("hosted_request", request_id) | self.state(request_id)

    def listing(self):
        return [
            self.status(r["id"])
            for r in self.store.rows(
                "SELECT id FROM records WHERE kind='hosted_request' ORDER BY rowid DESC"
            )
        ]

    def _remote(self, request):
        if self.stop.is_set():
            raise Blocked("Hosted monitor is stopping")
        row = self.repositories._row(request["project_id"])
        if (
            row["state"] != "verified"
            or str(row["repository_id"]) != request["repository_id"]
        ):
            raise Conflict("Hosted test repository binding changed")
        self.repositories._identity(row)
        if self.stop.is_set():
            raise Blocked("Hosted monitor is stopping")
        repo = self.repositories.client.lookup(row["owner"], row["name"])
        self.repositories._validate(row, repo)

        def call(method, endpoint, data=None):
            if self.stop.is_set():
                raise Blocked("Hosted monitor is stopping")
            return self.repositories.client.git(
                row["owner"], row["name"], method, endpoint, data
            )

        return call

    def start(self, task_id, specification):
        if not isinstance(specification, dict) or set(specification) != {
            "request_id",
            "expected_sha",
            "runner",
            "suite",
            "workspace",
            "spending_control_confirmed",
            "trusted_commit_confirmed",
        }:
            raise ContractError(
                "Supply a request ID, exact commit, runner, suite, workspace and both owner confirmations"
            )
        if (
            specification["spending_control_confirmed"] is not True
            or specification["trusted_commit_confirmed"] is not True
        ):
            raise Blocked(
                "Confirm the trusted commit and configured account spending boundary"
            )
        key = specification["request_id"]
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", key):
            raise ContractError("Invalid hosted request ID")
        if not isinstance(specification["expected_sha"], str) or not re.fullmatch(
            r"[a-f0-9]{40}", specification["expected_sha"]
        ):
            raise ContractError("Use the full reviewed commit SHA")
        if specification["runner"] not in ("ubuntu-latest", "windows-latest"):
            raise ContractError("Only standard Linux and Windows runners are supported")
        relative(specification["suite"])
        relative(specification["workspace"])
        task = self.store.task(task_id)
        binding = self.repositories.status(task["project_id"])
        if binding.get("state") != "verified":
            raise Blocked("Connect an existing project repository first")
        request = {
            **specification,
            "id": key,
            "task_id": task_id,
            "project_id": task["project_id"],
            "repository_id": binding["repository_id"],
            "owner": binding["owner"],
            "name": binding["name"],
            "tag": "ha-native-" + key,
        }
        with self.lock:
            previous = self.store.rows(
                "SELECT 1 FROM records WHERE kind='hosted_request' AND id=?", (key,)
            )
            if not previous:
                if any(
                    r["project_id"] == task["project_id"]
                    and r["status"] not in TERMINAL
                    for r in self.listing()
                ):
                    raise Blocked(
                        "Resolve the existing hosted request before starting another"
                    )
                remote = self._remote(request)
                # The managed workflow is fixed. The owner also reviews the code
                # and recipe at this commit; matching a workflow is not a sandbox.
                content = remote(
                    "GET",
                    "contents/.github/workflows/"
                    + WORKFLOW
                    + "?ref="
                    + request["expected_sha"],
                )
                if (
                    content.get("encoding") != "base64"
                    or len(content.get("content", "")) > 100000
                ):
                    raise Blocked(
                        "Managed native-test workflow is unavailable at this commit"
                    )
                try:
                    raw = base64.b64decode(
                        "".join(content["content"].split()), validate=True
                    )
                except ValueError as error:
                    raise Blocked("Invalid workflow response") from error
                if raw.replace(b"\r\n", b"\n") != TEMPLATE.read_bytes().replace(
                    b"\r\n", b"\n"
                ):
                    raise Conflict(
                        "Install this HA release's managed native-tests.yml workflow before dispatch"
                    )
                workflow = remote("GET", "actions/workflows/" + WORKFLOW)
                if (
                    workflow.get("path") != ".github/workflows/" + WORKFLOW
                    or workflow.get("state") != "active"
                ):
                    raise Blocked(
                        "Native workflow must be active on the repository's default branch"
                    )
                self.store.put("hosted_request", key, request)
            else:
                self.store.put(
                    "hosted_request", key, request
                )  # Reject changed retry inputs.
            return self.refresh(key)

    def _run(self, request, run):
        if (
            run.get("head_sha") != request["expected_sha"]
            or str(run.get("repository", {}).get("id")) != request["repository_id"]
            or run.get("event") != "workflow_dispatch"
            or run.get("display_title") != "HA native " + request["id"]
            or run.get("path", "").split("@")[0] != ".github/workflows/" + WORKFLOW
            or run.get("run_attempt") != 1
            or type(run.get("id")) is not int
            or run["id"] <= 0
        ):
            raise Conflict(
                "Hosted run identity, commit, workflow or attempt differs from the authorized request"
            )
        return {
            "run_id": run["id"],
            "run_attempt": 1,
            "run_url": f"https://github.com/{request['owner']}/{request['name']}/actions/runs/{run['id']}",
            "status": "completed" if run.get("status") == "completed" else "running",
            "remote_status": run.get("status"),
            "conclusion": run.get("conclusion"),
            "local_acceptance": False,
            "error": "",
        }

    def refresh(self, request_id):
        with self.lock:
            request = self.store.get("hosted_request", request_id)
            state = self.state(request_id)
            if state["status"] in ("conflict", "cancelled") or (
                state["status"] == "completed" and state.get("artifacts_fetched")
            ):
                return self.status(request_id)
            try:
                remote = self._remote(request)
                tag_endpoint = "git/ref/tags/" + quote(request["tag"], safe="")
                if state["status"] == "prepared":
                    self.save(request_id, status="tag_pending")
                    remote(
                        "POST",
                        "git/refs",
                        {
                            "ref": "refs/tags/" + request["tag"],
                            "sha": request["expected_sha"],
                        },
                    )
                    state = self.state(request_id)
                if state["status"] in ("tag_pending", "tag_ready"):
                    tag = remote("GET", tag_endpoint)
                    if (
                        tag.get("object", {}).get("sha") != request["expected_sha"]
                        or tag["object"].get("type") != "commit"
                    ):
                        raise Conflict(
                            "Hosted test tag no longer selects the reviewed commit"
                        )
                    # Store intent before dispatch. Absence from the run list is
                    # never sufficient evidence to repeat this paid effect.
                    self.save(request_id, status="dispatch_pending")
                    reply = remote(
                        "POST",
                        "actions/workflows/" + WORKFLOW + "/dispatches",
                        {
                            "ref": request["tag"],
                            "return_run_details": True,
                            "inputs": {
                                "request_id": request_id,
                                "expected_sha": request["expected_sha"],
                                "runner": request["runner"],
                                "suite": request["suite"],
                                "workspace": request["workspace"],
                                "spending_control_confirmed": True,
                            },
                        },
                    )
                    if (
                        type(reply.get("workflow_run_id")) is int
                        and reply["workflow_run_id"] > 0
                    ):
                        self.save(request_id, run_id=reply["workflow_run_id"])
                    state = self.state(request_id)
                if not state.get("run_id"):
                    matches = []
                    for page in range(1, 11):
                        response = remote(
                            "GET",
                            f"actions/workflows/{WORKFLOW}/runs?event=workflow_dispatch&per_page=100&page={page}",
                        )
                        runs = response["workflow_runs"]
                        matches.extend(
                            r
                            for r in runs
                            if r.get("display_title") == "HA native " + request_id
                        )
                        if len(runs) < 100:
                            break
                    else:
                        raise Blocked(
                            "Run search exceeded 1,000 entries; dispatch remains uncertain"
                        )
                    if len(matches) > 1:
                        raise Conflict(
                            "Multiple workflow runs carry this request identity"
                        )
                    if not matches:
                        self.save(
                            request_id,
                            error="Run not visible yet; dispatch will not be repeated",
                        )
                        return self.status(request_id)
                    state = self.save(request_id, **self._run(request, matches[0]))
                run = remote("GET", f"actions/runs/{state['run_id']}")
                observed = self._run(request, run)
                if state.get("cancel_requested") and observed["status"] != "completed":
                    observed["status"] = "cancel_pending"
                self.save(request_id, **observed)
                if observed["status"] == "completed":
                    artifacts = remote(
                        "GET", f"actions/runs/{run['id']}/artifacts?per_page=100"
                    )
                    self.save(
                        request_id,
                        artifacts=[
                            {
                                k: a.get(k)
                                for k in (
                                    "id",
                                    "name",
                                    "size_in_bytes",
                                    "expired",
                                    "digest",
                                )
                            }
                            for a in artifacts.get("artifacts", [])
                        ],
                        artifacts_truncated=artifacts.get("total_count", 0) > 100,
                        artifacts_fetched=True,
                    )
            except Conflict as error:
                self.save(request_id, status="conflict", error=str(error))
            except (
                Blocked,
                TimeoutError,
                OSError,
                KeyError,
                TypeError,
                ValueError,
                AttributeError,
            ):
                self.save(
                    request_id,
                    error="GitHub request could not be verified. Check connection and refresh; uncertain writes are not replayed.",
                )
            return self.status(request_id)

    def cancel(self, request_id):
        with self.lock:
            request = self.store.get("hosted_request", request_id)
            state = self.state(request_id)
            if state["status"] in TERMINAL or state.get("cancel_requested"):
                return self.status(request_id)
            if state["status"] in ("prepared", "tag_pending", "tag_ready"):
                self.save(
                    request_id,
                    status="cancelled",
                    error="Stopped before workflow dispatch; any created tag is retained",
                )
                return self.status(request_id)
            if not state.get("run_id"):
                raise Blocked(
                    "Identify the uncertain workflow run before requesting cancellation"
                )
            remote = self._remote(request)
            self._run(request, remote("GET", f"actions/runs/{state['run_id']}"))
            self.save(request_id, cancel_requested=True, status="cancel_pending")
            try:
                remote("POST", f"actions/runs/{state['run_id']}/cancel")
            except (Blocked, TimeoutError, OSError):
                self.save(
                    request_id,
                    error="Cancellation response uncertain; check run status",
                )
            return self.status(request_id)

    def start_monitor(self):
        def monitor():
            while not self.stop.wait(30):
                for request in self.listing():
                    if self.stop.is_set():
                        return
                    if request["status"] not in TERMINAL or (
                        request["status"] == "completed"
                        and not request.get("artifacts_fetched")
                    ):
                        self.refresh(request["id"])

        self.thread = threading.Thread(target=monitor, daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        if not self.lock.acquire(timeout=35):
            raise Blocked("Hosted request is still finishing; retry closing shortly")
        self.lock.release()
        if self.thread:
            self.thread.join(timeout=35)
            if self.thread.is_alive():
                raise Blocked(
                    "Hosted status check is still finishing; retry closing shortly"
                )
