"""Fault injection at external-write boundaries, plus domain-independent broker use."""

import copy
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from hivemind_assembly.core.broker import Broker
from hivemind_assembly.core.common import Blocked, Conflict, ContractError
from hivemind_assembly.core.repositories import Repositories
from hivemind_assembly.integrations.github import GitHubError


class GitHubFixture:
    def __init__(self):
        self.user = {"login": "owner", "id": 123}
        self.repos = {}
        self.creates = 0
        self.patches = 0
        self.create_failure = None
        self.patch_failure = False
        self.denied = False

    def identity(self):
        return dict(self.user)

    def lookup(self, owner, name):
        return copy.deepcopy(self.repos.get((owner.lower(), name.lower())))

    def create(self, owner, name, description, organization=False, private=True):
        self.creates += 1
        if self.denied:
            raise GitHubError(403)
        repo = {
            "id": 42,
            "full_name": owner + "/" + name,
            "private": private,
            "description": description,
            "permissions": {"push": True},
            "archived": False,
        }
        if self.create_failure != "before_effect":
            self.repos[owner.lower(), name.lower()] = repo
        if self.create_failure:
            raise TimeoutError("connection lost")
        return copy.deepcopy(repo)

    def describe(self, owner, name, description):
        self.patches += 1
        self.repos[owner.lower(), name.lower()]["description"] = description
        if self.patch_failure:
            raise TimeoutError("cleanup response lost")


@pytest.fixture
def provisioning(ready):
    controller, task, epoch = ready
    client = GitHubFixture()
    config = {"github": {"allow_repository_creation": True}}
    service = Repositories(controller.store, client, config)
    broker = Broker(controller, config, repositories=service)
    request = {
        "id": "repo-op",
        "task_id": task["id"],
        "owner": "worker.opus",
        "epoch": epoch,
        "revision": 0,
        "tool": "create_repository",
        "args": {"name": "recovered", "description": "Recovered application"},
    }
    return controller, task, client, service, broker, request


def test_private_creation_generic_broker_and_duplicate_delivery(provisioning):
    c, t, remote, service, broker, request = provisioning
    result = broker.execute(request)
    assert result["private"] is True and result["initialized"] is False
    assert result["url"] == "https://github.com/owner/recovered"
    assert broker.execute(request) == result
    assert remote.creates == 1 and remote.patches == 1
    assert remote.lookup("owner", "recovered")["description"] == "Recovered application"
    assert c.store.project(t["project_id"])["revision"] == 1
    assert service.status(t["project_id"])["state"] == "verified"
    assert "access_token" not in json.dumps(c.store.rows("SELECT * FROM records"))
    assert broker.domain is None


@pytest.mark.parametrize(
    "failure", ["creation_response", "cleanup_response", "local_finish"]
)
def test_lost_responses_reconcile_after_restart_without_recreation(
    provisioning, failure, monkeypatch
):
    c, t, remote, service, broker, request = provisioning
    if failure == "creation_response":
        remote.create_failure = "after_effect"
    elif failure == "cleanup_response":
        remote.patch_failure = True
    else:
        monkeypatch.setattr(
            c,
            "finish",
            lambda *a: (_ for _ in ()).throw(RuntimeError("lost local finish")),
        )
    with pytest.raises(Exception):
        broker.execute(request)
    assert (
        c.store.one("SELECT state FROM operations WHERE id='repo-op'")["state"]
        == "uncertain"
    )
    with pytest.raises(Blocked):
        c.acquire(t["id"], "worker.extra")
    c.recover()
    restarted = Broker(
        c, service.config, repositories=Repositories(c.store, remote, service.config)
    )
    results = restarted.recover_pending()
    assert results[0]["status"] == "saved"
    assert results[0]["result_artifact"]
    assert remote.creates == 1
    assert c.store.project(t["project_id"])["revision"] == 1
    assert restarted.recover_pending() == []
    assert remote.lookup("owner", "recovered")["description"] == "Recovered application"


def test_missing_after_uncertain_create_never_reposts(provisioning):
    c, t, remote, service, broker, request = provisioning
    remote.create_failure = "before_effect"
    with pytest.raises(Blocked):
        broker.execute(request)
    assert broker.recover_pending()[0]["status"] == "unresolved"
    with pytest.raises(Blocked):
        service.create(t["project_id"], "another-op", request["args"])
    assert remote.creates == 1


def test_permission_denial_is_definite_and_can_retry_after_reauthorization(
    provisioning,
):
    c, t, remote, service, broker, request = provisioning
    remote.denied = True
    with pytest.raises(GitHubError):
        broker.execute(request)
    assert (
        c.store.one("SELECT state FROM operations WHERE id='repo-op'")["state"]
        == "failed"
    )
    assert service.status(t["project_id"])["state"] == "rejected"
    remote.denied = False
    result = broker.execute({**request, "id": "retry-after-authorization"})
    assert result["private"] and remote.creates == 2


def test_existing_repository_preserved_and_different_name_allowed(provisioning):
    c, t, remote, service, broker, request = provisioning
    original = {"id": 99, "description": "keep this", "private": False}
    remote.repos["owner", "recovered"] = original.copy()
    with pytest.raises(Conflict, match="already exists"):
        broker.execute(request)
    assert remote.creates == remote.patches == 0
    assert remote.repos["owner", "recovered"] == original
    broker.execute({**request, "id": "different-name", "args": {"name": "other"}})
    assert remote.repos["owner", "recovered"] == original


@pytest.mark.parametrize(
    "tamper", ["marker", "push", "id", "account", "epoch", "revision"]
)
def test_recovery_rejects_identity_permission_and_fence_changes(provisioning, tamper):
    c, t, remote, service, broker, request = provisioning
    remote.create_failure = "after_effect"
    with pytest.raises(Blocked):
        broker.execute(request)
    repo = remote.repos["owner", "recovered"]
    if tamper == "marker":
        repo["description"] = "unrelated"
    elif tamper == "push":
        repo["permissions"]["push"] = False
    elif tamper == "account":
        remote.user["id"] = 456
    elif tamper == "id":
        service._update(t["project_id"], repository_id="999")
    elif tamper == "epoch":
        with c.store.tx() as db:
            db.execute("UPDATE tasks SET epoch=epoch+1 WHERE id=?", (t["id"],))
    else:
        with c.store.tx() as db:
            db.execute(
                "UPDATE projects SET revision=revision+1 WHERE id=?", (t["project_id"],)
            )
    assert broker.recover_pending()[0]["status"] == "unresolved"
    assert remote.creates == 1
    assert (
        c.store.one("SELECT state FROM operations WHERE id='repo-op'")["state"]
        == "uncertain"
    )


def test_reject_public_and_out_of_scope_owner_before_network(provisioning):
    c, t, remote, service, broker, request = provisioning
    for args in (
        {"name": "x", "private": False},
        {"name": "../x"},
        {"name": "x", "token": "secret"},
    ):
        with pytest.raises(ContractError):
            service.create(t["project_id"], "invalid", args)
    with pytest.raises(Blocked, match="owner"):
        service.create(
            t["project_id"], "invalid", {"name": "x", "owner": "other-owner"}
        )
    service.config["github"]["allow_repository_creation"] = False
    with pytest.raises(Blocked, match="Enable"):
        service.create(t["project_id"], "invalid", {"name": "x"})
    assert remote.creates == 0


def test_cancel_before_create(provisioning):
    c, t, remote, service, broker, request = provisioning
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Blocked):
        service.create(t["project_id"], "cancel", request["args"], cancel)
    assert remote.creates == 0
    assert service.reconcile(t["project_id"])["status"] == "not_applied"


def test_concurrent_requests_share_one_repository(provisioning):
    c, t, remote, service, broker, request = provisioning
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda i: service.create(t["project_id"], str(i), request["args"]),
                range(2),
            )
        )
    assert results[0]["repository_id"] == results[1]["repository_id"]
    assert remote.creates == 1
    second = c.store.create_project("second", "coding")
    with pytest.raises(Conflict, match="reserved"):
        service.create(second["project_id"], "second", request["args"])


def test_allowlisted_organization(provisioning):
    c, t, remote, service, broker, request = provisioning
    service.config["github"]["allowed_organizations"] = ["team"]
    result = service.create(
        t["project_id"], "org", {"name": "new-project", "owner": "team"}
    )
    assert result["owner"] == "team"


def test_invalid_new_operation_cannot_claim_previous_repository(provisioning):
    c, t, remote, service, broker, request = provisioning
    broker.execute(request)
    c.brief(
        t["id"],
        {"revision": 1},
        {"procedure": "another step", "acceptance": "verify"},
        {},
        [],
    )
    with pytest.raises(Conflict):
        broker.execute(
            {
                **request,
                "id": "wrong-name",
                "revision": 1,
                "args": {"name": "different"},
            }
        )
    assert (
        c.store.one("SELECT state FROM operations WHERE id='wrong-name'")["state"]
        == "failed"
    )
    assert broker.recover_pending() == []
    assert remote.creates == 1


def test_owner_can_choose_a_public_repository(provisioning):
    c, t, remote, service, broker, request = provisioning
    result = service.create(
        t["project_id"], "public-op", {"name": "shared", "visibility": "public"}
    )
    assert result["private"] is False and result["visibility"] == "public"
    assert remote.lookup("owner", "shared")["private"] is False
    assert service.status(t["project_id"])["visibility"] == "public"
    # Asking again for the same name as private is a different request.
    with pytest.raises(Conflict):
        service.create(t["project_id"], "private-op", {"name": "shared", "visibility": "private"})


def events(c, kind):
    return [json.loads(e["payload"]) for e in c.store.rows("SELECT payload FROM events WHERE kind=? ORDER BY seq", (kind,))]


def test_visibility_change_on_github_is_followed_and_announced(provisioning):
    c, t, remote, service, broker, request = provisioning
    broker.execute(request)
    remote.repos["owner", "recovered"]["private"] = False
    result = service.reconcile(t["project_id"])
    # GitHub is the authority: HA records the change, keeps saving, and says so.
    assert result["status"] == "saved" and result["visibility"] == "public"
    assert result["visibility_change"] == "This repository is now public on GitHub."
    status = service.status(t["project_id"])
    assert status["visibility"] == "public" and status["visibility_change"]["previous"] == "private"
    changes = events(c, "repository_visibility_changed")
    assert len(changes) == 1 and changes[0]["to"] == "public"
    assert "now public on GitHub" in changes[0]["message"]
    # Seen again unchanged: nothing new is announced. Made private again: followed again.
    service.reconcile(t["project_id"])
    assert len(events(c, "repository_visibility_changed")) == 1
    remote.repos["owner", "recovered"]["private"] = True
    assert service.reconcile(t["project_id"])["visibility"] == "private"
    assert [e["to"] for e in events(c, "repository_visibility_changed")] == ["public", "private"]
    # The other checks are unchanged: write access, archived, and the repository's ID.
    remote.repos["owner", "recovered"]["archived"] = True
    with pytest.raises(Conflict, match="archived"):
        service.reconcile(t["project_id"])
    remote.repos["owner", "recovered"]["archived"] = False
    remote.repos["owner", "recovered"]["id"] = 77
    with pytest.raises(Conflict, match="replacement"):
        service.reconcile(t["project_id"])


def test_visibility_change_after_a_lost_creation_response_is_followed(provisioning):
    c, t, remote, service, broker, request = provisioning
    remote.create_failure = "after_effect"
    with pytest.raises(Blocked):
        broker.execute(request)
    remote.repos["owner", "recovered"]["private"] = False
    assert broker.recover_pending()[0]["visibility"] == "public"
    assert remote.creates == 1
    assert events(c, "repository_visibility_changed")[0]["to"] == "public"


def test_assistants_can_create_public_repositories_and_the_log_says_who_chose(provisioning):
    c, t, remote, service, broker, request = provisioning
    public = {**request, "args": {**request["args"], "visibility": "public"}}
    result = broker.execute(public)
    assert result["visibility"] == "public" and remote.lookup("owner", "recovered")["private"] is False
    assert result["visibility_chosen_by"] == "the assistant"
    logged = events(c, "repository_creation_requested")[0]
    assert logged["visibility_chosen_by"] == "the assistant"
    assert "public repository (chosen by the assistant)" in logged["message"]


def test_new_repositories_follow_the_default_setting(provisioning):
    c, t, remote, service, broker, request = provisioning
    # Neither you nor the assistant said which: the setting decides.
    service.config["github"]["default_visibility"] = "public"
    result = broker.execute(request)
    assert result["visibility"] == "public" and result["visibility_chosen_by"] == "your default for new repositories"
    assert remote.lookup("owner", "recovered")["private"] is False
    # Asked explicitly, the request wins over the setting; the owner's own choice says so.
    second = c.store.create_project("second", "coding")
    explicit = service.create(
        second["project_id"], "owner-op", {"name": "mine", "visibility": "private"}
    )
    assert explicit["visibility"] == "private" and explicit["visibility_chosen_by"] == "you"
    # A repeated request that doesn't say which keeps what was first asked.
    service.config["github"]["default_visibility"] = "private"
    assert service.create(t["project_id"], "again", request["args"])["visibility"] == "public"
    from hivemind_assembly.automation.policy import validate_config

    base = json.loads(
        (__import__("pathlib").Path(__file__).parents[1] / "_app/config/default.json").read_text()
    )
    for value in ("private", "public"):
        validate_config({**base, "github": {"default_visibility": value}})
    with pytest.raises(ContractError, match="Private or Public"):
        validate_config({**base, "github": {"default_visibility": "internal"}})


def test_link_records_an_existing_public_repository(provisioning):
    c, t, remote, service, broker, request = provisioning
    remote.repos["owner", "open-source"] = {
        "id": 7,
        "full_name": "owner/open-source",
        "private": False,
        "description": "",
        "permissions": {"push": True},
        "archived": False,
        "default_branch": "main",
    }
    remote.head = lambda owner, name, branch: None
    saved = service.link(t["project_id"], "link-op", {"name": "open-source"})
    assert saved["visibility"] == "public" and saved["state"] == "verified"
