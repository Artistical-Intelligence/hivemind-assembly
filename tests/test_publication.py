import base64
import copy
import hashlib
import json
import pytest
from test_repositories import GitHubFixture
from hivemind_assembly.core.broker import Broker
from hivemind_assembly.core.repositories import Repositories
from hivemind_assembly.core.common import Blocked, Conflict
from hivemind_assembly.domains.reverse_engineering.domain import (
    ReverseEngineeringDomain,
)
from hivemind_assembly.automation.team import NativeTeam


def sha(value):
    return hashlib.sha1(json.dumps(value, sort_keys=True).encode()).hexdigest()


class GitFixture(GitHubFixture):
    def __init__(self, empty=False):
        super().__init__()
        repo = self.create("owner", "existing", "User project")
        self.repos["owner", "existing"]["default_branch"] = "main"
        self.trees = {"base-tree": {"README.md": "Original readme"}}
        self.commits = {"base": {"tree": {"sha": "base-tree"}, "parents": []}}
        self.current = None if empty else "base"
        self.updates = 0
        self.initializations = 0
        self.fail_update = False
        self.fail_initial = False
        self.race = False

    def head(self, *a):
        return self.current

    def git(self, owner, name, method, endpoint, data=None):
        if method == "GET" and endpoint.startswith("git/commits/"):
            return copy.deepcopy(self.commits[endpoint.rsplit("/", 1)[-1]])
        if method == "GET" and endpoint.startswith("commits/"):
            return copy.deepcopy(self.commits[endpoint.rsplit("/", 1)[-1]])
        if method == "PUT" and endpoint.startswith("contents/"):
            self.initializations += 1
            assert self.current is None
            path = endpoint[len("contents/") :]
            content = base64.b64decode(data["content"])
            tree = {path: content.decode()}
            key = sha(tree)
            self.trees[key] = tree
            blob = hashlib.sha1(
                b"blob " + str(len(content)).encode() + b"\0" + content
            ).hexdigest()
            self.commits["initial"] = {
                "tree": {"sha": key},
                "parents": [],
                "files": [{"filename": path, "sha": blob}],
            }
            self.current = "initial"
            if self.fail_initial:
                raise TimeoutError("Initial response lost")
            return {"commit": {"sha": self.current}}
        if method == "POST" and endpoint == "git/trees":
            tree = copy.deepcopy(self.trees[data["base_tree"]])
            for item in data["tree"]:
                tree[item["path"]] = item["content"]
            key = sha(tree)
            self.trees[key] = tree
            return {"sha": key}
        if method == "POST" and endpoint == "git/commits":
            key = sha(data)
            self.commits[key] = {
                "tree": {"sha": data["tree"]},
                "parents": [{"sha": x} for x in data["parents"]],
            }
            return {"sha": key}
        if method == "PATCH" and endpoint == "git/refs/heads/main":
            assert data["force"] is False
            if self.race:
                self.current = "someone-else"
            assert (
                self.commits[data["sha"]]["parents"][0]["sha"] == self.current
            ), "No non-fast-forward updates"
            self.current = data["sha"]
            self.updates += 1
            if self.fail_update:
                raise TimeoutError("Updated but response lost")
            return {"object": {"sha": self.current}}
        raise AssertionError((method, endpoint, data))


@pytest.fixture
def publication(ready):
    c, t, epoch = ready
    remote = GitFixture()
    repos = Repositories(
        c.store, remote, {"github": {"allow_repository_creation": False}}
    )
    linked = repos.link(t["project_id"], "link", {"name": "existing"})
    assert linked["state"] == "verified"
    broker = Broker(c, {"foundations": {}}, ReverseEngineeringDomain(), repos)
    root = broker.workspace(t["id"])
    (root / "sum.c").write_text("unsigned sum(unsigned a,unsigned b){return a+b;}")
    req = {
        "id": "check",
        "task_id": t["id"],
        "owner": "worker.opus",
        "epoch": epoch,
        "revision": 0,
        "tool": "validate_c_function",
        "args": {
            "candidate_path": "sum.c",
            "function": "sum",
            "original_hex": "89f801f0c3",
        },
    }
    assert broker.execute(req)["passed"]
    publish = {
        **req,
        "id": "publish",
        "tool": "publish_checkpoint",
        "args": {"validation": "check"},
    }
    return c, t, remote, repos, broker, publish


def test_checked_checkpoint_and_duplicate_delivery(publication):
    c, t, remote, repos, broker, publish = publication
    result = broker.execute(publish)
    assert result["status"] == "saved" and result["sha"] == remote.current
    tree = remote.trees[remote.commits[remote.current]["tree"]["sha"]]
    assert tree["README.md"] == "Original readme" and "sum.c" in tree
    assert broker.execute(publish) == result and remote.updates == 1
    assert broker.publications.status(t["project_id"])["sha"] == result["sha"]


def test_lost_push_response_reconciles_without_second_commit(publication):
    c, t, remote, repos, broker, publish = publication
    remote.fail_update = True
    with pytest.raises(TimeoutError):
        broker.execute(publish)
    assert (
        c.store.one("SELECT state FROM operations WHERE id='publish'")["state"]
        == "uncertain"
    )
    count = len(remote.commits)
    remote.fail_update = False
    recovered = broker.reconcile_domain("publish")
    assert (
        recovered["status"] == "saved"
        and remote.updates == 1
        and len(remote.commits) == count
    )


def test_empty_repository_initialization_lost_response(publication):
    c, t, remote, repos, broker, publish = publication
    # Reset fixture's binding baseline to empty via a fresh append-only record.
    remote.current = None
    broker.publications._save(
        "publication_head", t["project_id"], {"sha": None, "branch": "main"}
    )
    remote.fail_initial = True
    with pytest.raises(TimeoutError):
        broker.execute(publish)
    remote.fail_initial = False
    assert broker.reconcile_domain("publish")["status"] == "saved"
    assert remote.initializations == 1


def test_remote_change_and_stale_source_are_not_overwritten(publication):
    c, t, remote, repos, broker, publish = publication
    remote.current = "human-change"
    with pytest.raises(Conflict, match="Remote"):
        broker.execute(publish)
    assert remote.updates == 0
    remote.current = "base"
    (broker.workspace(t["id"]) / "sum.c").write_text(
        "unsigned sum(unsigned a,unsigned b){return a-b;}"
    )
    with pytest.raises(Conflict, match="Source changed"):
        broker.execute({**publish, "id": "publish-new"})


def test_automatic_schedule_only_after_verified_check(publication):
    c, t, remote, repos, broker, publish = publication
    team = object.__new__(NativeTeam)
    team.broker = broker
    team.store = c.store
    flow = {"phase": "execute"}
    team.queue_checkpoint(c.store.task(t["id"]), flow, {"operation_id": "check"})
    assert flow["phase"] == "tool" and flow["request"]["tool"] == "publish_checkpoint"
    assert flow["request"]["args"] == {"validation": "check"}
    repos.config["github"]["automatic_checkpoints"] = False
    flow = {"phase": "execute"}
    team.queue_checkpoint(c.store.task(t["id"]), flow, {"operation_id": "check"})
    assert flow["phase"] == "execute"


def test_local_only_projects_need_no_github(ready):
    c, t, epoch = ready
    repos = Repositories(c.store, GitFixture(), {})
    broker = Broker(c, {}, repositories=repos)
    assert not broker.publications.enabled(t["project_id"])
    assert (
        broker.publications.publish(
            t["id"], "noop", "unused", broker.workspace(t["id"])
        )["status"]
        == "disabled"
    )


def test_no_secret_restricted_or_private_paths(publication, tmp_path):
    c, t, remote, repos, broker, publish = publication
    from hivemind_assembly.learning.knowledge import Knowledge

    p = tmp_path / "private.c"
    p.write_text(
        "This is a restricted source passage that must never be copied into a published checkpoint without permission."
        * 2
    )
    Knowledge(c.store).ingest(p)
    with pytest.raises(Blocked):
        broker.publications._safe_text("src/a.c", p.read_bytes())
    for name, raw in [
        ("private/x.c", b"int f;"),
        ("src/token.json", b"{}"),
        ("src/x.c", ("ghp_" + "A" * 36).encode()),
    ]:
        with pytest.raises(Blocked):
            broker.publications._safe_text(name, raw)
