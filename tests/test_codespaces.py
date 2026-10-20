import base64
import hashlib
import json
import os
import subprocess
import sys
import time
import pytest
from hivemind_assembly.integrations import cloud_runner
from hivemind_assembly.application.app import Application
from hivemind_assembly.core.common import Blocked, Conflict


def run_remote(tmp_path, request):
    env = {**os.environ, "HOME": str(tmp_path)}
    p = subprocess.run(
        [sys.executable, cloud_runner.__file__],
        input=json.dumps(request),
        text=True,
        capture_output=True,
        env=env,
        timeout=20,
    )
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


@pytest.mark.skipif(os.name == "nt", reason="Codespaces runner is Linux-only")
def test_remote_runner_result_recovery_and_no_repeat(tmp_path):
    text = b'print("hello")\n'
    request = {
        "id": "test-job",
        "request_hash": "one",
        "files": {"main.py": base64.b64encode(text).decode()},
        "hashes": {"main.py": hashlib.sha256(text).hexdigest()},
        "commands": [[sys.executable, "main.py"]],
        "outputs": [],
        "timeout": 10,
    }
    result = run_remote(tmp_path, request)
    assert result["passed"]
    assert result["commands"][0]["output"] == "hello\n"
    assert run_remote(tmp_path, {"id": "test-job", "action": "status"}) == result
    assert run_remote(tmp_path, request) == result


@pytest.mark.skipif(os.name == "nt", reason="Codespaces runner is Linux-only")
def test_remote_deadline_and_credentials_removed(tmp_path):
    request = {
        "id": "deadline",
        "request_hash": "one",
        "files": {},
        "hashes": {},
        "commands": [[sys.executable, "-c", "import time;time.sleep(10)"]],
        "outputs": [],
        "timeout": 1,
    }
    r = run_remote(tmp_path, request)
    assert not r["passed"] and r["commands"][0]["status"] == "timeout"
    request.update(
        id="env",
        timeout=10,
        commands=[[sys.executable, "-c", 'import os; print("GH_TOKEN" in os.environ)']],
    )
    assert run_remote(tmp_path, request)["commands"][0]["output"] == "False\n"


@pytest.fixture
def app(tmp_path):
    a = Application(tmp_path / "state")
    yield a
    a.close()


def test_optional_cloud_and_idempotent_queue(app, monkeypatch):
    task = app.store.create_project("test", "test", paused=True)
    app.workspace.write(task["id"], "main.py", "print(1)")
    data = {
        "task": task["id"],
        "space": "fixture",
        "request_id": "run-one",
        "files": ["main.py"],
        "commands": [["python3", "main.py"]],
    }
    with pytest.raises(Blocked):
        app.codespaces.submit(data)
    app.codespaces.save(
        {"enabled": True, "allow_execution": True, "spaces": ["fixture"]}
    )
    calls = []

    def remote(space, request, timeout=60):
        calls.append(request)
        return {
            "id": request["id"],
            "request_hash": request["request_hash"],
            "status": "completed",
            "passed": True,
            "outputs": {},
        }

    monkeypatch.setattr(app.codespaces, "remote", remote)
    app.codespaces.submit(data)
    for _ in range(50):
        result = app.codespaces.latest("cloud_job:run-one")
        if result["status"] == "completed":
            break
        time.sleep(0.02)
    assert result["passed"]
    assert app.codespaces.submit(data)["id"] == "run-one" and len(calls) == 1
    with pytest.raises(Conflict):
        app.codespaces.submit({**data, "commands": [["python3", "-V"]]})


def test_lost_create_is_not_replayed(app, monkeypatch):
    app.codespaces.save({"enabled": True, "allow_execution": False, "spaces": []})
    monkeypatch.setattr(
        app.codespaces, "machines", lambda *a: {"machines": [{"name": "cpu"}]}
    )
    calls = []

    def api(*args):
        calls.append(args)
        raise Blocked("connection lost")

    monkeypatch.setattr(app.codespaces, "api", api)
    for _ in range(2):
        with pytest.raises(Blocked):
            app.codespaces.create("owner", "repo", "cpu", "create-one")
    assert sum(args[0] == "POST" for args in calls) == 1


def test_parallel_spaces_and_cancel_queued_without_delivery(app, monkeypatch):
    import threading

    task = app.store.create_project("parallel", "test", paused=True)
    app.codespaces.save(
        {"enabled": True, "allow_execution": True, "spaces": ["one", "two"]}
    )
    started = {name: threading.Event() for name in ("one", "two")}
    release = threading.Event()
    delivered = []

    def remote(space, request, timeout=60):
        delivered.append(request["id"])
        started[space].set()
        assert release.wait(5)
        return {
            "id": request["id"],
            "request_hash": request["request_hash"],
            "status": "completed",
            "passed": True,
        }

    monkeypatch.setattr(app.codespaces, "remote", remote)
    base = {"task": task["id"], "commands": [["python3", "-V"]]}
    try:
        app.codespaces.submit({**base, "space": "one", "request_id": "first"})
        assert started["one"].wait(3)
        app.codespaces.submit({**base, "space": "one", "request_id": "queued"})
        app.codespaces.submit({**base, "space": "two", "request_id": "parallel"})
        assert all(event.wait(3) for event in started.values())
        assert "queued" not in delivered
        assert app.codespaces.cancel("queued")["status"] == "cancelled"
    finally:
        release.set()
        app.codespaces.close()
    assert sorted(delivered) == ["first", "parallel"]


def test_gpu_gate_and_output_import_conflict(app, monkeypatch):
    task = app.store.create_project("output", "test", paused=True)
    original = app.workspace.write(task["id"], "answer.txt", "old")
    app.codespaces.save({"enabled": True, "allow_execution": True, "spaces": ["cpu"]})
    data = {
        "task": task["id"],
        "space": "cpu",
        "request_id": "gpu",
        "commands": [["python3", "-V"]],
        "requires": {"gpu": True},
    }
    with pytest.raises(Blocked, match="Probe"):
        app.codespaces.submit(data)
    row = {
        "id": "output",
        "task": task["id"],
        "project": task["project_id"],
        "space": "cpu",
        "request_hash": "matching",
        "status": "completed",
    }
    app.store.put("cloud_request", "output", {"outputs": ["answer.txt"]})
    app.codespaces.retain(
        row,
        {
            "id": "output",
            "request_hash": "matching",
            "status": "completed",
            "outputs": {"answer.txt": base64.b64encode(b"new").decode()},
        },
    )
    with pytest.raises(Conflict):
        app.codespaces.import_output("output", "answer.txt")
    app.codespaces.import_output("output", "answer.txt", original["sha256"])
    assert app.workspace.read(task["id"], "answer.txt")["text"] == "new"
    latest = app.codespaces.latest("cloud_job:output")
    artifact = latest["output_artifacts"]["answer.txt"]["artifact"]
    assert app.broker.artifacts.read(artifact, "worker", task["project_id"]) == b"new"
    with pytest.raises(Blocked):
        app.broker.artifacts.read(artifact, "worker", "another-project")
    assert (
        app.codespaces.retain(
            row, {"id": "output", "request_hash": "matching", "status": "running"}
        )["status"]
        == "completed"
    )


def test_interrupted_job_requires_reconciliation(tmp_path):
    a = Application(tmp_path / "state")
    a.codespaces.state("cloud_job:lost", {"id": "lost", "status": "running"})
    a.close()
    b = Application(tmp_path / "state")
    try:
        assert b.codespaces.latest("cloud_job:lost")["status"] == "uncertain"
    finally:
        b.close()


def test_worker_cloud_dispatch_uses_operation_identity_and_fences(app, monkeypatch):
    task = app.store.create_project("worker cloud", "Compile a program")
    app.codespaces.save({"enabled": True, "allow_execution": True, "spaces": ["cpu"]})
    calls = []

    def remote(space, request, timeout=60):
        calls.append(request["id"])
        return {
            "id": request["id"],
            "request_hash": request["request_hash"],
            "status": "completed",
            "passed": True,
        }

    monkeypatch.setattr(app.codespaces, "remote", remote)
    c = app.controller
    epoch = c.acquire(task["id"], "worker.opus")
    c.brief(
        task["id"],
        {"revision": 0},
        {"procedure": "Compile snapshot", "acceptance": "Inspect compiler exit"},
        {"critical_gaps": []},
        [],
    )
    req = {
        "id": "worker-cloud",
        "task_id": task["id"],
        "owner": "worker.opus",
        "epoch": epoch,
        "revision": 0,
        "tool": "cloud_submit",
        "args": {"space": "cpu", "commands": [["cc", "--version"]]},
    }
    result = app.broker.execute(req)
    assert app.broker.execute(req) == result
    for _ in range(50):
        if calls:
            break
        time.sleep(0.01)
    assert calls == ["worker-cloud"]
    assert (
        app.codespaces.latest("cloud_job:worker-cloud")["project"] == task["project_id"]
    )


def test_uncertain_creation_reconciles_without_duplicate(app, monkeypatch):
    app.codespaces.save({"enabled": True, "allow_execution": False, "spaces": []})
    monkeypatch.setattr(
        app.codespaces, "machines", lambda *a: {"machines": [{"name": "cpu"}]}
    )
    calls = []
    created = {
        "name": "retained-space",
        "display_name": "HA-recover",
        "repository": {"full_name": "owner/repo.with.dots"},
        "machine": {"name": "cpu"},
    }

    def api(method, path, data=None):
        calls.append(method)
        if method == "POST":
            raise Blocked("response lost")
        return {"codespaces": [created]}

    monkeypatch.setattr(app.codespaces, "api", api)
    with pytest.raises(Blocked):
        app.codespaces.create("owner", "repo.with.dots", "cpu", "recover")
    assert app.codespaces.create("owner", "repo.with.dots", "cpu", "recover") == created
    assert calls == ["POST", "GET"]
    assert app.codespaces.settings()["spaces"] == ["retained-space"]
