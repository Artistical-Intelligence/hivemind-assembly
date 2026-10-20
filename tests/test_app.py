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
