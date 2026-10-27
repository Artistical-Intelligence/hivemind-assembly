import asyncio, json, threading, urllib.request, urllib.error
from pathlib import Path
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
    body = r.read()
    assert b"<title>Hivemind Assembly</title>" in body and b'id="getting-started"' in body
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
    with pytest.raises(Blocked, match="didn't finish"):
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


def test_errors_do_not_echo_host_paths_or_internals(server, app, monkeypatch, tmp_path):
    secret_path = str(tmp_path / "private" / "deep" / "missing.bin")

    def missing(path, data):
        raise FileNotFoundError(2, "No such file", secret_path)

    monkeypatch.setattr(app, "action", missing)
    with pytest.raises(urllib.error.HTTPError) as e:
        call(server, "/api/project", app.token, {"name": "x", "objective": "y"})
    body = e.value.read().decode()
    assert e.value.code == 400 and "missing.bin" in body and str(tmp_path) not in body

    def broken(path, data):
        raise RuntimeError("sqlite failure at " + secret_path)

    monkeypatch.setattr(app, "action", broken)
    with pytest.raises(urllib.error.HTTPError) as e:
        call(server, "/api/project", app.token, {"name": "x", "objective": "y"})
    body = e.value.read().decode()
    assert e.value.code == 500 and str(tmp_path) not in body and "RuntimeError" in body
    assert secret_path in (app.store.root / "logs" / "dashboard-errors.log").read_text()
    with pytest.raises(urllib.error.HTTPError) as e:
        call(server, "/api/status", app.token + "x")
    assert e.value.code == 403


def test_first_run_reports_foundations_and_loads_them_after_install(app, monkeypatch, tmp_path):
    import time
    from hivemind_assembly.application import setup

    status = app.status()["foundations"]
    assert status["ready"] is False and not status["installing"]
    homes = {name: tmp_path / name for name in ("ghidra_home", "rea_home", "hermes_home")}
    seen = []

    def fake_install(root, config_path, progress=None):
        progress.begin("Downloading Ghidra", 480)
        progress.download(50, 100)
        seen.append(app.status()["foundations"]["progress"])
        for path in homes.values():
            path.mkdir()
        config = json.loads(Path(config_path).read_text())
        config["foundations"].update({k: str(v) for k, v in homes.items()})
        Path(config_path).write_text(json.dumps(config))
        return {"verification": {"passed": True}}

    monkeypatch.setattr(setup, "install_foundations", fake_install)
    monkeypatch.setattr(app, "install_optional_tools", lambda progress=None: {"github_cli": "ready"})
    app.action("/api/setup", {})
    for _ in range(100):
        if app.status()["foundations"]["ready"]:
            break
        time.sleep(0.05)
    assert app.status()["foundations"] == {
        "ready": True,
        "present": {name: True for name in homes},
        "installing": False,
        "restart_needed": False,
        "progress": None,
    }
    # While installing, the dashboard sees the current step and its download.
    assert seen[0]["label"] == "Downloading Ghidra"
    assert seen[0]["download"] == {"done_bytes": 50, "total_bytes": 100}
    assert 0 < seen[0]["percent"] < 100


def test_setup_progress_weights_steps_and_estimates_time_left(monkeypatch):
    from hivemind_assembly.application import setup

    clock = [0.0]
    monkeypatch.setattr(setup.time, "monotonic", lambda: clock[0])
    states = []
    progress = setup.SetupProgress(states.append)
    progress.expect("Installing Java (JDK 21)", 190)
    progress.expect("Downloading Ghidra", 480)
    progress.expect("Checking the installed tools", 30)
    progress.begin("Installing Java (JDK 21)")
    assert states[-1]["step"] == 1 and states[-1]["steps"] == 3 and states[-1]["percent"] == 0
    assert states[-1]["seconds_left"] is None
    clock[0] = 60.0
    progress.begin("Downloading Ghidra")
    clock[0] = 120.0
    progress.download(240, 480)
    # Java (190) plus half of Ghidra (240) of 700 in total.
    assert states[-1]["percent"] == round(430 / 700 * 100, 1)
    assert states[-1]["seconds_left"] == round(120 * (1 - 430 / 700) / (430 / 700))
    assert states[-1]["download"] == {"done_bytes": 240, "total_bytes": 480}
    progress.finish()
    assert states[-1]["label"] is None


def test_setup_installs_optional_tools_in_the_same_step(app, monkeypatch):
    from hivemind_assembly.application import prerequisites
    from hivemind_assembly.core.common import Blocked

    def gh_fails(extra=()):
        assert extra == ("gh",)
        raise Blocked("GitHub CLI could not be installed")

    def tunnel_fails():
        raise ConnectionError("offline")

    monkeypatch.setattr(prerequisites, "install_missing", gh_fails)
    monkeypatch.setattr(app.tunnel, "status", lambda: {"installed": False})
    monkeypatch.setattr(app.tunnel, "install", tunnel_fails)
    monkeypatch.setattr(app.quick, "installed", lambda: False)
    monkeypatch.setattr(app.quick, "install", lambda progress=None: tunnel_fails())
    retry = "Not installed (ConnectionError); select Install required tools in Settings to retry."
    assert app.install_optional_tools() == {
        "github_cli": "GitHub CLI could not be installed",
        "tunnel_client": retry,
        "browser_tunnel": retry,
    }
    monkeypatch.setattr(prerequisites, "install_missing", lambda extra=(): {"installed": []})
    monkeypatch.setattr(app.tunnel, "status", lambda: {"installed": True})
    monkeypatch.setattr(app.quick, "installed", lambda: True)
    assert app.install_optional_tools() == {
        "github_cli": "ready", "tunnel_client": "ready", "browser_tunnel": "ready"
    }


def test_status_lists_practice_sets_newest_first_with_the_default(app):
    from hivemind_assembly.learning.pipeline import DEFAULT_SUITE

    first = app.broker.artifacts.add('{"cases":[]}', "learning-holdouts.json", classification="protected")
    second = app.broker.artifacts.add('{"cases":[1]}', "learning-holdouts.json", classification="protected")
    app.broker.artifacts.add("other", "notes.txt")
    app.store.put(DEFAULT_SUITE, "binding-1", {"suite": first["id"], "route": None, "repeats": 3})
    sets = app.status()["practice_sets"]
    assert [s["id"] for s in sets] == [second["id"], first["id"]]
    assert [s["default"] for s in sets] == [False, True]


def test_private_repository_list_for_the_picker(app, monkeypatch):
    calls = []
    monkeypatch.setattr(app.github_auth, "credentials", lambda: {"access_token": "t"})

    def request(method, path, **kw):
        calls.append((method, path, kw))
        return [
            {"owner": {"login": "me"}, "name": "game", "description": None},
            {"owner": {"login": "team"}, "name": "tools", "description": "Shared"},
            "not a repository",
        ]

    monkeypatch.setattr(app.github_auth.http, "request", request)
    assert app.action("/api/github/repositories", {}) == [
        {"owner": "me", "name": "game", "description": ""},
        {"owner": "team", "name": "tools", "description": "Shared"},
    ]
    method, path, kw = calls[0]
    assert method == "GET" and "visibility=private" in path and kw["allow_list"] is True


def test_assistant_setups_default_save_overwrite_and_use(app):
    setups = app.status()["assistant_setups"]
    # The setup the owner already had is saved as Default and is in use.
    assert setups["active"] == "Default"
    default = setups["presets"]["Default"]
    assert default["worker.opus"] == {"provider": "claude", "mode": "native", "model": "Opus 5.5", "effort": "High"}
    fast = json.loads(json.dumps(default))
    fast["reviewer.high"] = {"provider": "claude", "mode": "native", "model": "Sonnet 5.5", "effort": "Low"}
    fast["adviser.extra"]["effort"] = "Pro"
    saved = app.action("/api/assistants/save", {"name": "Fast", "targets": fast})
    assert set(saved["presets"]) == {"Default", "Fast"} and saved["active"] == "Default"
    started = []
    app.native_setup.run = lambda route: started.append(route) or asyncio.sleep(0)
    used = app.action("/api/assistants/use", {"name": "Fast"})
    assert sorted(used["changed"]) == ["adviser.extra", "reviewer.high"] and used["active"] == "Fast"
    reviewer = app.config["routes"]["reviewer.high"]
    # Another service: its own host, sign-in, usage limits and a new conversation.
    assert reviewer["allowed_hosts"] == ["claude.ai"] and reviewer["profile"] == "claude"
    assert reviewer["usage"]["scope"] == "claude.native" and reviewer["conversation_url"] == ""
    assert app.config["routes"]["adviser.extra"]["effort"] == "Pro"
    assert sorted(started) == ["adviser.extra", "reviewer.high"]
    # Overwriting Default is allowed; unknown services and modes are refused.
    app.action("/api/assistants/save", {"name": "Default", "targets": fast})
    assert app.status()["assistant_setups"]["presets"]["Default"]["adviser.extra"]["effort"] == "Pro"
    # Saving what the assistants use now marks it in use; changing the setup in use unmarks it.
    assert app.status()["assistant_setups"]["active"] == "Default"
    app.action("/api/assistants/save", {"name": "Default", "targets": default})
    assert app.status()["assistant_setups"]["active"] is None
    assert app.action("/api/assistants/use", {"name": "Default"})["active"] == "Default"
    bad = json.loads(json.dumps(fast))
    bad["worker.extra"]["mode"] = "Turbo"
    with pytest.raises(Exception, match="no Turbo mode"):
        app.action("/api/assistants/save", {"name": "Bad", "targets": bad})
    with pytest.raises(Exception, match="1–60"):
        app.action("/api/assistants/save", {"name": " ", "targets": fast})
    # The services row: one entry per service, with the assistants using it.
    services = {s["provider"]: s for s in app.status()["services"]}
    assert services["claude"]["routes"] == ["worker.opus"]
    assert sorted(services["openai"]["routes"]) == ["adviser.extra", "reviewer.high", "worker.astra", "worker.extra"]


def test_model_lists_read_after_setup_per_service_and_kept_when_a_read_fails(app, monkeypatch):
    import time
    from hivemind_assembly.automation.surfaces import SURFACES

    signed_in = {"openai": True, "claude": True}
    read = []

    class Picker:
        def __init__(self, ok):
            self.ok = ok
            self.first = self

        async def wait_for(self, timeout=None):
            if not self.ok:
                raise TimeoutError("no model picker")

    class Tab:
        def __init__(self, profile):
            self.profile, self.closed = profile, False

        def locator(self, selector):
            return Picker(signed_in[self.profile])

        async def close(self):
            self.closed = True

    tabs = []

    async def service_page(profile, url, hosts=None):
        tabs.append(Tab(profile))
        return tabs[-1]

    def menu(provider, modes):
        async def options(page):
            read.append(provider)
            return modes
        return options

    monkeypatch.setattr(app.browser, "service_page", service_page)
    monkeypatch.setattr(SURFACES["openai"], "options", menu("openai", {"Chat": {"GPT-6": ["High", "Pro"]}}))
    monkeypatch.setattr(SURFACES["claude"], "options", menu("claude", {"native": {"Opus 5.5": ["High", "Max"]}}))

    async def verified(route):
        return {"stage": "verified"}

    monkeypatch.setattr(app.native_setup, "run", verified)
    # A service's menu is read once it is set up, then not again for a week.
    app.submit(app.setup_assistant("worker.extra")).result(10)
    assert read == ["openai"]
    assert app.model_choices()["openai"]["modes"] == {"Chat": {"GPT-6": ["High", "Pro"]}}
    app.submit(app.setup_assistant("adviser.extra")).result(10)
    assert read == ["openai"]
    app.submit(app.setup_assistant("worker.opus")).result(10)
    assert read == ["openai", "claude"]
    assert all(t.closed for t in tabs)  # its own tab, closed after reading
    # Signed out: the list read before stays, with the reason.
    signed_in["claude"] = False
    app.submit(app.read_choices(["claude"])).result(10)
    claude = app.model_choices()["claude"]
    assert claude["modes"] == {"native": {"Opus 5.5": ["High", "Max"]}}
    assert claude["error"].startswith("Sign in to Claude first")
    assert app.status()["model_choices"]["openai"]["modes"]
    # A week-old list is read again at the next setup.
    choices = app.model_choices()
    choices["openai"]["read_at"] = time.time() - 8 * 86400
    (app.store.root / "private" / app.CHOICES).write_text(json.dumps(choices))
    app.submit(app.setup_assistant("reviewer.high")).result(10)
    assert read == ["openai", "claude", "openai"]
