import json, threading, urllib.request, urllib.error
import pytest
from workbench.app import Application, make_server


@pytest.fixture
def app(tmp_path):
    a = Application(tmp_path / "state")
    yield a
    a.close()


@pytest.fixture
def server(app):
    s = make_server(app)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield s
    s.shutdown()
    s.server_close()


def call(server, path, token=None, data=None, origin=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Workbench-Token"] = token
    if origin:
        headers["Origin"] = origin
    req = urllib.request.Request(
        f"http://127.0.0.1:{server.server_port}{path}",
        headers=headers,
        data=json.dumps(data).encode() if data is not None else None,
    )
    return urllib.request.urlopen(req)


def test_unauthenticated_denied(server):
    with pytest.raises(urllib.error.HTTPError) as e:
        call(server, "/api/status")
    assert e.value.code == 403


def test_origin_denied(server, app):
    with pytest.raises(urllib.error.HTTPError) as e:
        call(server, "/api/status", app.token, origin="https://evil.example")
    assert e.value.code == 403


def test_create_pause_resume_cancel(server, app):
    t = json.load(
        call(
            server,
            "/api/project",
            app.token,
            {"name": "Example", "objective": "Investigate"},
        )
    )
    for action, status in [
        ("pause", "paused"),
        ("resume", "queued"),
        ("cancel", "cancelled"),
    ]:
        x = json.load(
            call(server, "/api/control", app.token, {"task": t["id"], "action": action})
        )
        assert x["status"] == status
    assert len(json.load(call(server, "/api/status", app.token))["projects"]) == 1


def test_dashboard_static(server):
    r = call(server, "/")
    assert b"Build on evidence" in r.read()
    assert "frame-ancestors" in r.headers["Content-Security-Policy"]


def test_no_arbitrary_http_command(server, app):
    with pytest.raises(urllib.error.HTTPError):
        call(server, "/api/execute", app.token, {"cmd": "echo unauthorized"})


def test_config_invalid_preserves_previous(app):
    old = app.config_path.read_bytes()
    config = json.loads(old)
    config["model_api_inference"] = True
    with pytest.raises(ValueError):
        app.action("/api/settings", {"config": config})
    assert app.config_path.read_bytes() == old


def test_update_preserves_data(tmp_path):
    root = tmp_path / "state"
    a = Application(root)
    t = a.store.create_project("keep", "objective")
    a.close()
    a = Application(root)
    try:
        assert a.store.task(t["id"])["objective"] == "objective"
    finally:
        a.close()


def test_prepare_import_and_configure_acceptance(app, tmp_path):
    task = app.action(
        "/api/project",
        {"name": "Prepared", "objective": "Recover a region", "start_paused": True},
    )
    assert task["status"] == "paused"
    source = tmp_path / "original.hex"
    source.write_text("89f801f0")
    imported = app.action(
        "/api/import-target", {"task": task["id"], "path": str(source)}
    )
    assert imported["original_artifact"]
    contract = {
        "scope": "x86_64_register_regions",
        "checks": [
            {
                "original_path": "original.hex",
                "candidate_path": "candidate.hex",
                "original_format": "hex",
                "candidate_format": "hex",
            }
        ],
    }
    description = app.action(
        "/api/acceptance", {"task": task["id"], "contract": contract}
    )
    assert "original_artifact" not in description["checks"][0]
    assert source.read_text() == "89f801f0"


def test_single_host_owner(tmp_path):
    from workbench.common import Blocked

    a = Application(tmp_path / "one-host")
    try:
        with pytest.raises(Blocked):
            Application(tmp_path / "one-host")
    finally:
        a.close()


def test_github_repository_dashboard_action_uses_broker_and_persists(app, monkeypatch):
    from test_repositories import GitHubFixture

    remote = GitHubFixture()
    monkeypatch.setattr(app.repositories, "client", remote)
    app.action(
        "/api/github/settings",
        {"allow_repository_creation": True, "allowed_organizations": []},
    )
    task = app.action(
        "/api/project",
        {"name": "coding", "objective": "Build a utility", "start_paused": True},
    )
    data = {"task": task["id"], "repository": {"name": "utility"}}
    result = app.action("/api/github/repository", data)
    assert result["private"] is True
    assert app.store.task(task["id"])["status"] == "paused"
    assert app.store.task(task["id"])["owner"] is None
    assert app.status()["repositories"][0]["state"] == "verified"
    assert (
        app.store.one("SELECT * FROM operations WHERE id=?", (result["operation_id"],))[
            "state"
        ]
        == "saved"
    )
    assert (
        app.action("/api/github/repository", data)["repository_id"]
        == result["repository_id"]
    )
    assert remote.creates == 1
    assert json.loads(app.config_path.read_text())["github"][
        "allow_repository_creation"
    ]


def test_github_uncertain_dashboard_recovery(app, monkeypatch):
    from test_repositories import GitHubFixture
    from workbench.common import Blocked

    remote = GitHubFixture()
    remote.create_failure = "after_effect"
    monkeypatch.setattr(app.repositories, "client", remote)
    app.action("/api/github/settings", {"allow_repository_creation": True})
    task = app.action(
        "/api/project",
        {"name": "recover", "objective": "Investigate", "start_paused": True},
    )
    data = {"task": task["id"], "repository": {"name": "recover"}}
    with pytest.raises(Blocked):
        app.action("/api/github/repository", data)
    assert app.store.task(task["id"])["status"] == "paused"
    with pytest.raises(Blocked, match="Reconcile"):
        app.action("/api/github/repository", data)
    op = app.store.one("SELECT id FROM operations WHERE task_id=?", (task["id"],))
    assert app.action("/api/reconcile", {"operation": op["id"]})["reconciled"]
    assert remote.creates == 1


def test_github_credentials_rejected_from_settings(app):
    old = app.config_path.read_bytes()
    with pytest.raises(ValueError, match="credentials"):
        app.action(
            "/api/github/settings",
            {"allow_repository_creation": True, "access_token": "do-not-save"},
        )
    assert app.config_path.read_bytes() == old


def test_owner_native_recipe_and_observations(app):
    from test_tool_testing import SOURCE, suite
    from workbench.common import Blocked

    task = app.store.create_project("trusted tools", "Check tool behavior", paused=True)
    root = app.broker.workspace(task["id"])
    (root / "candidate.py").write_text(SOURCE)
    payload = {"task": task["id"], "suite": suite(False), "allow_native": False}
    with pytest.raises(Blocked):
        app.action("/api/native-tests/configure", payload)
    payload["allow_native"] = True
    app.action("/api/native-tests/configure", payload)
    assert app.run_native_tests(task["id"])["passed"]
    assert app.store.task(task["id"])["status"] == "paused"
    observations = app.action("/api/native-tests/results", {"task": task["id"]})
    assert (
        observations["passed"]
        and observations["cases"][0]["runs"]["candidate"][0]["file_contents_hex"]
    )
    # Results belong to a task, not merely the last sibling run in its project.
    import time

    with app.store.tx() as db:
        db.execute(
            "INSERT INTO tasks(id,project_id,objective,status,updated) VALUES(?,?,?,'paused',?)",
            ("native-child", task["project_id"], "Different check", time.time()),
        )
    assert app.action("/api/native-tests/results", {"task": "native-child"}) == {
        "status": "not_run"
    }
    child_payload = {**payload, "task": "native-child"}
    child_root = app.broker.workspace("native-child")
    (child_root / "candidate.py").write_text("print('wrong output')")
    app.action("/api/native-tests/configure", child_payload)
    assert not app.run_native_tests("native-child")["passed"]
    assert not app.action("/api/native-tests/results", {"task": "native-child"})[
        "passed"
    ]
    assert app.action("/api/native-tests/results", {"task": task["id"]})["passed"]
    app.action(
        "/api/native-tests/permission",
        {"project": task["project_id"], "allowed": False},
    )
    with pytest.raises(Blocked):
        app.run_native_tests(task["id"])


def test_goal_http_commands(app):
    task = app.store.create_project("goals", "Persist the task", paused=True)
    result = app.action("/api/goal", {"task": task["id"], "command": "/goal"})
    assert (
        result["status"] == "active"
        and app.store.task(task["id"])["status"] == "queued"
    )
    app.action("/api/goal", {"task": task["id"], "command": "/goal pause"})
    assert app.status()["goals"][0]["status"] == "paused"


def test_project_retains_objective_without_starting_prepared_work(app):
    import threading
    from hivemind_assembly.core.goals import GoalStopped
    from hivemind_assembly.core.common import Blocked

    task = app.action(
        "/api/project",
        {"name": "automatic", "objective": "Build a tool", "start_paused": True},
    )
    goal = app.team.goals.status(task["id"])
    assert goal["objective"] == task["objective"] and goal["status"] == "active"
    assert goal["unlimited"]
    assert app.store.task(task["id"])["status"] == "paused"
    cancelled = app.broker.cancel.setdefault(task["id"], threading.Event())
    cancelled.set()
    app.action("/api/goal", {"task": task["id"], "action": "status"})
    assert cancelled.is_set()
    app.action("/api/goal", {"task": task["id"], "action": "start"})
    assert not cancelled.is_set()
    assert app.store.task(task["id"])["status"] == "queued"
    app.action("/api/goal", {"task": task["id"], "action": "pause"})
    # A retried start must not erase a subsequent explicit pause.
    assert (
        app.action("/api/goal", {"task": task["id"], "action": "start"})["status"]
        == "paused"
    )
    app.action("/api/goal", {"task": task["id"], "action": "budget", "max_turns": 1})
    app.action("/api/goal", {"task": task["id"], "action": "resume"})
    app.team.goals.reserve(task["id"], "first")
    with pytest.raises(GoalStopped):
        app.team.goals.reserve(task["id"], "second")
    app.action("/api/control", {"task": task["id"], "action": "pause"})
    with pytest.raises(Blocked, match="exhausted"):
        app.action("/api/control", {"task": task["id"], "action": "resume"})
    assert app.store.task(task["id"])["status"] == "paused" and cancelled.is_set()
    app.action("/api/goal", {"task": task["id"], "action": "budget", "max_turns": 0})
    assert app.team.goals.status(task["id"])["status"] == "exhausted"
    app.action("/api/control", {"task": task["id"], "action": "resume"})
    assert app.team.goals.runnable(task["id"]) and not cancelled.is_set()


def test_hosted_test_owner_actions_and_status(app, monkeypatch):
    from test_hosted_tests import HostedGitHub, SHA

    remote = HostedGitHub()
    app.repositories.client = remote
    app.config["github"]["allow_repository_creation"] = True
    task = app.store.create_project("hosted", "Native check", paused=True)
    app.repositories.create(task["project_id"], "repo", {"name": "hosted-fixture"})
    # Run jobs synchronously here to exercise the API result and state binding.
    monkeypatch.setattr(app, "background_job", lambda name, fn: fn())
    spec = {
        "request_id": "owner-hosted-request",
        "expected_sha": SHA,
        "runner": "ubuntu-latest",
        "suite": "_app/examples/native_cli/suite.json",
        "workspace": "_app/examples/native_cli",
        "spending_control_confirmed": True,
        "trusted_commit_confirmed": True,
    }
    result = app.action(
        "/api/hosted-tests/start", {"task": task["id"], "specification": spec}
    )
    assert (
        result["run_id"] == 1
        and app.status()["hosted_tests"][0]["id"] == spec["request_id"]
    )
    app.action("/api/hosted-tests/cancel", {"request_id": spec["request_id"]})
    result = app.action("/api/hosted-tests/refresh", {"request_id": spec["request_id"]})
    assert result["conclusion"] == "cancelled" and not result["local_acceptance"]


def test_resuming_legacy_project_prepares_continuation(app):
    task = app.store.create_project("old", "Continue old work", paused=True)
    assert app.team.goals.status(task["id"]) is None
    app.action("/api/control", {"task": task["id"], "action": "resume"})
    goal = app.team.goals.status(task["id"])
    assert goal["objective"] == task["objective"] and goal["unlimited"]
    assert app.store.task(task["id"])["status"] == "queued"
