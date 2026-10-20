"""Real SDK checks, retained request identity, isolation and shutdown cleanup."""

import asyncio
import json
import threading
import time

import pytest
from mcp import Client
from hivemind_assembly.application.project_checks import starter
from hivemind_assembly.core.common import Blocked, Conflict
from hivemind_assembly.integrations.mcp import build_server
from hivemind_assembly.integrations.mcp_checks import CheckRequests
import test_mcp_connections
from test_mcp_connections import enable

app = test_mcp_connections.app


def shared_starter(app, kind="registers", native=False):
    enable(app)
    task = starter(app, kind, "mcp_check_starter_1234", native)
    settings = app.connections.settings()
    settings["projects"] = [task["project_id"]]
    app.connections.save(settings)
    return task


def wait(app, task, request):
    for _ in range(200):
        result = app.mcp_gateway.call("ha_check_status", {"task": task, "request_id": request})
        if result["status"] != "running":
            return result
        time.sleep(.01)
    raise AssertionError("Check did not complete")


def test_sdk_checks_retained_results_no_holdout_disclosure_and_changed_revision(app):
    task = shared_starter(app)
    args = {"task": task["id"], "request_id": "sdk_check"}

    async def exercise():
        async with Client(build_server(app.mcp_gateway.call)) as client:
            names = {t.name for t in (await client.list_tools()).tools}
            assert {"ha_run_checks", "ha_check_status"} <= names
            started = await client.call_tool("ha_run_checks", args)
            assert not started.is_error
            for _ in range(200):
                response = await client.call_tool("ha_check_status", args)
                assert not response.is_error
                result = response.structured_content
                if result["status"] != "running":
                    return result
                await asyncio.sleep(.01)
            raise AssertionError("MCP check did not finish")

    result = asyncio.run(exercise())
    assert result["status"] == "completed" and result["passed"] and not result["task_accepted"]
    assert set(result) == {"task", "request_id", "revision", "started", "current_revision", "stale", "status", "passed", "scope", "task_accepted", "finished"}
    assert app.store.task(task["id"])["status"] == "paused"
    candidate = app.workspace.read(task["id"], "candidate.hex")
    app.workspace.write(task["id"], "candidate.hex", "89f829f0", candidate["sha256"])
    retained = app.mcp_gateway.call("ha_run_checks", args)
    assert retained["passed"] and retained["stale"]
    assert len(app.store.rows("SELECT id FROM records WHERE kind=?", ("manual_check:" + task["id"],))) == 1
    app.mcp_gateway.call("ha_run_checks", {**args, "request_id": "changed_candidate"})
    assert not wait(app, task["id"], "changed_candidate")["passed"]
    # Another process sees a durable result and never repeats execution.
    reopened = CheckRequests(app, app.mcp_gateway.task)
    assert reopened.start(task["id"], "sdk_check")["passed"]
    assert not reopened.active


def test_interrupted_requests_and_access_revocation_do_not_rerun(app):
    task = shared_starter(app)
    app.store.put("mcp_check_request", "interrupted", {
        "task": task["id"], "request_id": "interrupted", "instance": "old_process",
        "revision": 0, "started": 0,
    })
    args = {"task": task["id"], "request_id": "interrupted"}
    assert app.mcp_gateway.call("ha_run_checks", args)["status"] == "interrupted"
    assert not app.mcp_gateway.checks.active
    settings = app.connections.settings()
    settings["projects"] = []
    app.connections.save(settings)
    with pytest.raises(Blocked):
        app.mcp_gateway.call("ha_check_status", args)
    other = app.store.create_project("other", "different scope", paused=True)
    settings["projects"] = [other["project_id"]]
    app.connections.save(settings)
    with pytest.raises(Conflict):
        app.mcp_gateway.call("ha_check_status", {**args, "task": other["id"]})


def test_native_mcp_checks_require_prior_owner_permission(app):
    from hivemind_assembly.core.test_acceptance import NativeTestAcceptance

    task = shared_starter(app, "native_python", True)
    verifier = NativeTestAcceptance(app.store)
    verifier.allow(task["project_id"], False)
    args = {"task": task["id"], "request_id": "permission_denied"}
    app.mcp_gateway.call("ha_run_checks", args)
    result = wait(app, task["id"], args["request_id"])
    assert result["status"] == "failed" and result["error_type"] == "Blocked"
    verifier.allow(task["project_id"], True)
    args["request_id"] = "authorized_native"
    app.mcp_gateway.call("ha_run_checks", args)
    result = wait(app, task["id"], args["request_id"])
    assert result["passed"] and result["scope"] == "native_tool_tests"
    assert "observations_artifact" not in json.dumps(result)


def test_mcp_check_shutdown_cancels_before_closing_store(app, monkeypatch):
    task = shared_starter(app)
    started = threading.Event()

    def check(application, task_id, expected_revision=None):
        cancel = application.broker.cancel.setdefault(task_id, threading.Event())
        started.set()
        assert cancel.wait(5)
        return {"passed": False, "scope": "fixture"}

    monkeypatch.setattr("hivemind_assembly.application.project_checks.run_checks", check)
    args = {"task": task["id"], "request_id": "shutdown"}
    app.mcp_gateway.call("ha_run_checks", args)
    assert started.wait(2)
    with pytest.raises(Blocked, match="already running"):
        app.mcp_gateway.call("ha_run_checks", {**args, "request_id": "duplicate"})
    app.close()
    from hivemind_assembly.core.store import Store

    reopened = Store(app.store.root)
    try:
        assert reopened.get("mcp_check_result", "shutdown")["status"] == "completed"
    finally:
        reopened.close()
    assert app.closed
    assert all(not thread.is_alive() for _, thread in app.mcp_gateway.checks.active.values())


def test_checks_through_real_stdio_and_authenticated_controller(app):
    import sys
    from pathlib import Path
    from mcp import StdioServerParameters
    from hivemind_assembly.application.app import make_server

    task = shared_starter(app)
    server = make_server(app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        async def exercise():
            params = StdioServerParameters(command=sys.executable, args=[
                "-u", str(Path(__file__).resolve().parents[1] / "_app/launch.py"),
                "mcp", "--data-dir", str(app.store.root),
            ])
            args = {"task": task["id"], "request_id": "stdio_check"}
            async with Client(params) as client:
                started = await client.call_tool("ha_run_checks", args)
                assert not started.is_error
                for _ in range(200):
                    response = await client.call_tool("ha_check_status", args)
                    assert not response.is_error
                    result = response.structured_content
                    if result["status"] != "running":
                        assert result["passed"] and not result["task_accepted"]
                        return
                    await asyncio.sleep(.01)
                raise AssertionError("Stdio check did not finish")
        asyncio.run(exercise())
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("kind,native", [("registers", False), ("native_python", True)])
def test_check_request_rejects_revision_changed_before_lease(app, monkeypatch, kind, native):
    from hivemind_assembly.application.project_checks import run_checks

    task = shared_starter(app, kind, native)

    def intervening_edit(application, task_id, expected_revision=None):
        application.workspace.write(task_id, "new.txt", "Changed after request")
        return run_checks(application, task_id, expected_revision=expected_revision)

    monkeypatch.setattr("hivemind_assembly.application.project_checks.run_checks", intervening_edit)
    app.mcp_gateway.call("ha_run_checks", {"task": task["id"], "request_id": "stale_start"})
    result = wait(app, task["id"], "stale_start")
    assert result["status"] == "failed" and result["error_type"] == "Conflict" and result["stale"]
    assert app.store.task(task["id"])["status"] == "paused"
    assert not app.store.rows("SELECT id FROM operations WHERE task_id=?", (task["id"],))


def test_poll_during_retained_intent_never_reports_false_interruption(app, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    task = shared_starter(app)
    retained, release, polling, finished = (threading.Event() for _ in range(4))
    original_put = app.store.put

    def put(kind, key, payload, conn=None):
        result = original_put(kind, key, payload, conn)
        if kind == "mcp_check_request":
            retained.set()
            assert release.wait(3)
        return result

    monkeypatch.setattr(app.store, "put", put)
    api = app.mcp_gateway.checks

    def poll():
        polling.set()
        result = api.status(task["id"], "concurrent_poll")
        finished.set()
        return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        start = pool.submit(api.start, task["id"], "concurrent_poll")
        assert retained.wait(2)
        status = pool.submit(poll)
        assert polling.wait(2)
        try:
            assert not finished.wait(.05)
        finally:
            release.set()
        assert start.result(timeout=3)["status"] in ("running", "completed")
        assert status.result(timeout=3)["status"] in ("running", "completed")
    assert wait(app, task["id"], "concurrent_poll")["passed"]
