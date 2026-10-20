import base64
import copy
from pathlib import Path

import pytest

from hivemind_assembly.core.common import Blocked, Conflict
from hivemind_assembly.core.hosted_tests import HostedTests, TEMPLATE
from hivemind_assembly.core.repositories import Repositories
from hivemind_assembly.core.store import Store
from hivemind_assembly.integrations.github import GitHubError
from test_repositories import GitHubFixture

SHA = "a" * 40


class HostedGitHub(GitHubFixture):
    def __init__(self):
        super().__init__()
        self.tags, self.runs = {}, {}
        self.posts, self.cancellations = 0, 0
        self.tag_failure = self.dispatch_failure = None
        self.hidden = False
        self.workflow = TEMPLATE.read_bytes()
        self.artifact_failure = False

    def git(self, owner, name, method, endpoint, data=None):
        if endpoint.startswith("contents/"):
            return {
                "encoding": "base64",
                "content": base64.b64encode(self.workflow).decode(),
            }
        if endpoint == "actions/workflows/native-tests.yml":
            return {"path": ".github/workflows/native-tests.yml", "state": "active"}
        if endpoint == "git/refs":
            if self.tag_failure != "before":
                self.tags[data["ref"].removeprefix("refs/")] = data["sha"]
            if self.tag_failure:
                raise TimeoutError()
            return {}
        if endpoint.startswith("git/ref/"):
            key = endpoint.removeprefix("git/ref/")
            if key not in self.tags:
                raise GitHubError(404)
            return {"object": {"sha": self.tags[key], "type": "commit"}}
        if endpoint.endswith("/dispatches"):
            self.posts += 1
            key = len(self.runs) + 1
            if self.dispatch_failure != "before":
                self.runs[key] = {
                    "id": key,
                    "repository": {"id": 42},
                    "head_sha": SHA,
                    "display_title": "HA native " + data["inputs"]["request_id"],
                    "event": "workflow_dispatch",
                    "run_attempt": 1,
                    "path": ".github/workflows/native-tests.yml",
                    "status": "queued",
                    "conclusion": None,
                }
            if self.dispatch_failure:
                raise TimeoutError()
            assert data["ref"].startswith("ha-native-")
            return {"workflow_run_id": key}
        if endpoint.startswith("actions/workflows/native-tests.yml/runs?"):
            return {
                "workflow_runs": (
                    [] if self.hidden else copy.deepcopy(list(self.runs.values()))
                )
            }
        if endpoint.endswith("/cancel"):
            self.cancellations += 1
            self.runs[int(endpoint.split("/")[2])].update(
                status="completed", conclusion="cancelled"
            )
            return {}
        if "/artifacts?" in endpoint:
            if self.artifact_failure:
                raise TimeoutError()
            return {
                "total_count": 1,
                "artifacts": [
                    {
                        "id": 123,
                        "name": "native-observations-Linux-1-1",
                        "expired": False,
                        "digest": "sha256:" + "b" * 64,
                    }
                ],
            }
        if endpoint.startswith("actions/runs/"):
            return copy.deepcopy(self.runs[int(endpoint.split("/")[2])])
        raise AssertionError((method, endpoint))


@pytest.fixture
def hosted(store):
    task = store.create_project("hosted", "Reconstruct a tool", paused=True)
    client = HostedGitHub()
    repos = Repositories(store, client, {"github": {"allow_repository_creation": True}})
    repos.create(task["project_id"], "repo", {"name": "test"})
    manager = HostedTests(store, repos)
    spec = {
        "request_id": "test-native-request",
        "expected_sha": SHA,
        "runner": "ubuntu-latest",
        "suite": "_app/examples/native_cli/suite.json",
        "workspace": "_app/examples/native_cli",
        "spending_control_confirmed": True,
        "trusted_commit_confirmed": True,
    }
    return task, manager, client, spec


def test_hosted_success_identity_and_no_local_acceptance(hosted):
    task, manager, remote, spec = hosted
    assert manager.start(task["id"], spec)["status"] == "running"
    assert manager.start(task["id"], spec)["run_id"] == 1
    assert remote.posts == 1
    remote.runs[1].update(status="completed", conclusion="success")
    result = manager.refresh(spec["request_id"])
    assert result["status"] == "completed" and result["conclusion"] == "success"
    assert not result["local_acceptance"] and result["artifacts"][0]["id"] == 123
    assert manager.store.task(task["id"])["status"] == "paused"
    assert manager.status(spec["request_id"])["expected_sha"] == SHA


@pytest.mark.parametrize("when", ["before", "after"])
def test_uncertain_dispatch_survives_restart_without_repeating(hosted, when):
    task, manager, remote, spec = hosted
    remote.dispatch_failure = when
    assert manager.start(task["id"], spec)["status"] == "dispatch_pending"
    other = Store(manager.store.root)
    try:
        restored = HostedTests(other, Repositories(other, remote, {}))
        for _ in range(3):
            result = restored.refresh(spec["request_id"])
        assert remote.posts == 1
        assert result["status"] == (
            "running" if when == "after" else "dispatch_pending"
        )
        with pytest.raises(Blocked, match="existing"):
            restored.start(task["id"], {**spec, "request_id": "another-request-id"})
    finally:
        other.close()


@pytest.mark.parametrize("when", ["before", "after"])
def test_tag_write_recovery_and_pre_dispatch_cancel(hosted, when):
    task, manager, remote, spec = hosted
    remote.tag_failure = when
    assert manager.start(task["id"], spec)["status"] == "tag_pending"
    remote.tag_failure = None
    result = manager.refresh(spec["request_id"])
    assert remote.posts == (1 if when == "after" else 0)
    if when == "before":
        assert result["status"] == "tag_pending"
        assert manager.cancel(spec["request_id"])["status"] == "cancelled"
        manager.refresh(spec["request_id"])
        assert remote.posts == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("head_sha", "c" * 40),
        ("run_attempt", 2),
        ("repository", {"id": 99}),
        ("path", ".github/workflows/other.yml"),
    ],
)
def test_changed_remote_evidence_rejected(hosted, field, value):
    task, manager, remote, spec = hosted
    manager.start(task["id"], spec)
    remote.runs[1][field] = value
    assert manager.refresh(spec["request_id"])["status"] == "conflict"
    assert remote.posts == 1


def test_repeated_cancel_and_artifact_lookup_recovery(hosted):
    task, manager, remote, spec = hosted
    manager.start(task["id"], spec)
    manager.cancel(spec["request_id"])
    manager.cancel(spec["request_id"])
    assert remote.cancellations == 1
    remote.artifact_failure = True
    assert manager.refresh(spec["request_id"])["status"] == "completed"
    remote.artifact_failure = False
    assert manager.refresh(spec["request_id"])["artifacts_fetched"]


def test_explicit_owner_gate_fixed_workflow_and_changed_retry(hosted):
    task, manager, remote, spec = hosted
    for key in ("trusted_commit_confirmed", "spending_control_confirmed"):
        with pytest.raises(Blocked):
            manager.start(task["id"], {**spec, key: False})
    remote.workflow += b"# altered"
    with pytest.raises(Conflict, match="managed"):
        manager.start(task["id"], spec)
    assert not manager.listing() and not remote.tags
    remote.workflow = TEMPLATE.read_bytes()
    manager.start(task["id"], spec)
    with pytest.raises(Conflict):
        manager.start(task["id"], {**spec, "runner": "windows-latest"})
    remote.user["id"] = 999
    assert manager.refresh(spec["request_id"])["error"]
    assert remote.posts == 1


def test_duplicate_correlated_runs_are_not_adopted(hosted):
    task, manager, remote, spec = hosted
    remote.dispatch_failure = "after"
    manager.start(task["id"], spec)
    remote.runs[2] = {**remote.runs[1], "id": 2}
    assert manager.refresh(spec["request_id"])["status"] == "conflict"


def test_workflow_template_and_commit_guard_are_shipped():
    root = Path(__file__).parents[1]
    assert (
        TEMPLATE.read_bytes()
        == (root / ".github/workflows/native-tests.yml").read_bytes()
    )
    assert b"inputs.expected_sha == github.sha" in TEMPLATE.read_bytes()
    assert b"persist-credentials: false" in TEMPLATE.read_bytes()


def test_worker_status_reads_its_project_without_remote_calls(hosted):
    from hivemind_assembly.core.broker import Broker
    from hivemind_assembly.core.controller import Controller

    task, manager, remote, spec = hosted
    manager.start(task["id"], spec)
    controller = Controller(manager.store)
    manager.store.state(task["id"], "queued")
    epoch = controller.acquire(task["id"], "worker.opus")
    controller.brief(
        task["id"],
        {"revision": 0},
        {
            "procedure": "inspect retained hosted run",
            "acceptance": "Independent checks",
        },
        {"critical_gaps": []},
        [],
    )
    broker = Broker(controller, {}, hosted_tests=manager)

    def no_network(*args, **kwargs):
        raise AssertionError("Status must not poll or dispatch GitHub")

    remote.git = no_network
    request = {
        "id": "read-hosted",
        "task_id": task["id"],
        "owner": "worker.opus",
        "epoch": epoch,
        "revision": 0,
        "tool": "hosted_test_status",
        "args": {},
    }
    assert broker.execute(request)["runs"][0]["run_id"] == 1
    other = manager.store.create_project("other", "Private task")
    other_epoch = controller.acquire(other["id"], "worker.opus")
    controller.brief(
        other["id"],
        {"revision": 0},
        {"procedure": "inspect", "acceptance": "checks"},
        {"critical_gaps": []},
        [],
    )
    assert (
        broker.execute(
            {
                **request,
                "id": "other-read",
                "task_id": other["id"],
                "epoch": other_epoch,
            }
        )["runs"]
        == []
    )
