"""Real owner editing, immutable checks and streamed HTTP transfers."""

import hashlib
import json
import urllib.request
import urllib.error
from urllib.parse import quote
import pytest
from test_app import app, server
from hivemind_assembly.application.project_checks import starter, run_checks
from hivemind_assembly.core.common import Blocked, Conflict, ContractError


def test_register_edit_check_and_pinned_original(app):
    task = starter(app, "registers", "register_starter_1234")
    key = task["id"]
    assert starter(app, "registers", "register_starter_1234")["id"] == key
    assert len(app.status()["projects"]) == 1
    assert run_checks(app, key)["result"]["passed"]
    candidate = app.workspace.read(key, "candidate.hex")
    app.workspace.write(key, "candidate.hex", "89f829f0", candidate["sha256"])
    # Editing the visible original cannot change the sealed original oracle.
    original = app.workspace.read(key, "original.hex")
    app.workspace.write(key, "original.hex", "89f829f0", original["sha256"])
    report = run_checks(app, key)
    assert not report["result"]["passed"]
    assert report["task_accepted"] is False
    assert app.store.task(key)["status"] == "paused"
    assert app.action("/api/project/check-result", {"task": key}) == report
    with pytest.raises(Blocked):
        app.broker.artifacts.read(report["artifact"], "worker", task["project_id"])


def test_native_edit_run_and_evidence(app):
    with pytest.raises(Blocked):
        starter(app, "native_python", "native_starter_1234")
    task = starter(app, "native_python", "native_starter_1234", True)
    key = task["id"]
    assert run_checks(app, key)["passed"]
    candidate = app.workspace.read(key, "candidate.py")
    app.workspace.write(key, "candidate.py", 'print("wrong")\n', candidate["sha256"])
    assert not run_checks(app, key)["passed"]
    assert app.store.task(key)["status"] == "paused"
    assert app.action("/api/project/check-result", {"task": key})["passed"] is False


def test_edit_conflict_preserves_versions_and_lost_ack_retry(app):
    task = app.store.create_project("edit", "edit", paused=True)
    key = task["id"]
    first = app.workspace.write(key, "folder/file.py", "old")
    changed = app.workspace.write(key, "folder/file.py", "new", first["sha256"])
    revision = app.store.project(task["project_id"])["revision"]
    assert app.workspace.write(key, "folder/file.py", "new", first["sha256"])[
        "unchanged"
    ]
    assert app.store.project(task["project_id"])["revision"] == revision
    with pytest.raises(Conflict):
        app.workspace.write(key, "folder/file.py", "stale", first["sha256"])
    assert app.workspace.read(key, "folder/file.py")["sha256"] == changed["sha256"]
    event = app.store.rows(
        "SELECT payload FROM events WHERE kind='owner_file_prepared' ORDER BY seq DESC"
    )[0]
    prior = json.loads(event["payload"])["previous_artifact"]
    assert app.broker.artifacts.read(prior, "controller") == b"old"
    app.store.state(key, "queued")
    with pytest.raises(Blocked):
        app.workspace.write(key, "new.txt", "no")
    assert not app.workspace.listing(key)["editable"]


@pytest.mark.parametrize(
    "name",
    [
        "../outside",
        "/outside",
        "a//b",
        "a/./b",
        ".GIT/config",
        "a\\b",
        "C:bad",
        "NUL",
        "aux.txt",
        "bad.",
        "bad ",
    ],
)
def test_invalid_owner_paths(app, name):
    t = app.store.create_project("paths", "paths", paused=True)
    with pytest.raises(ContractError):
        app.workspace.write(t["id"], name, "no")


def test_streamed_binary_upload_auth_hash_and_overwrite(server, app):
    t = app.store.create_project("upload", "upload", paused=True)
    path = "targets/é.bin"
    data = bytes(range(256)) * 10000
    url = f"http://127.0.0.1:{server.server_port}/api/workspace/upload"
    headers = {
        "Content-Type": "application/octet-stream",
        "X-HA-Task": t["id"],
        "X-HA-Path": quote(path),
    }
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers))
    assert error.value.code == 403
    headers["X-Workbench-Token"] = app.token
    result = json.load(
        urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers))
    )
    assert result["sha256"] == hashlib.sha256(data).hexdigest()
    assert app.workspace.read(t["id"], path)["text"] is None
    with pytest.raises(urllib.error.HTTPError):
        urllib.request.urlopen(
            urllib.request.Request(url, data=b"new", headers=headers)
        )
    assert app.workspace.path(t["id"], path).read_bytes() == data
    headers["X-HA-Expected-SHA256"] = result["sha256"]
    urllib.request.urlopen(
        urllib.request.Request(url, data=b"new", headers=headers)
    ).close()
    assert app.workspace.path(t["id"], path).read_bytes() == b"new"
