import asyncio
import hashlib
import json
import time
from pathlib import Path
import pytest
from hivemind_assembly.core.common import Blocked, ContractError
from hivemind_assembly.core.controller import Controller
from hivemind_assembly.core.broker import Broker
from hivemind_assembly.automation.team import NativeTeam
from hivemind_assembly.automation.policy import Availability, Window


@pytest.fixture(autouse=True)
def established_task_scope(store, monkeypatch):
    # These tests exercise delivery/lease behavior after classification.
    from hivemind_assembly.learning.scopes import KnowledgeScopes

    create = store.create_project

    def scoped_project(*args, **kwargs):
        task = create(*args, **kwargs)
        scopes = KnowledgeScopes(store)
        scopes.select(task["id"], [], scopes.catalog()["revision"])
        return task

    monkeypatch.setattr(store, "create_project", scoped_project)


def make_team(store, native):
    cfg = json.loads(
        (Path(__file__).parents[1] / "_app/config/default.json").read_text()
    )
    for route in cfg["routes"]:
        cfg["routes"][route]["conversation_url"] = "https://example.invalid/" + route
    c = Controller(store)
    broker = Broker(c, cfg)
    team = NativeTeam(c, broker, native, cfg)

    class Host:
        def record(self, *args):
            pass

    team.host = Host()
    for route in cfg["routes"]:
        team.observations[route] = Availability(
            route, True, True, False, time.time(), [Window("daily", 50)]
        )
    return team


def test_restart_reconciles_same_native_request(store):
    class Native:
        calls = []

        async def exchange(self, route, message):
            self.calls.append(message["id"])
            if len(self.calls) == 1:
                Controller(store).message_state(message["id"], "dispatching")
                raise Blocked("Connection interrupted after send")
            assert message["state"] == "delivery_uncertain"
            return {
                "request_id": message["id"],
                "type": "step_intent",
                "intent": {"goal": "Inspect", "method": "Read"},
            }

    native = Native()
    first = make_team(store, native)
    task = store.create_project("Restart", "Inspect")

    async def run():
        with pytest.raises(Blocked):
            await first.tick(task["id"])
        first.controller.recover()
        restarted = make_team(store, native)
        await restarted.tick(task["id"])
        assert restarted.flow(task["id"])["phase"] == "brief"

    asyncio.run(run())
    assert len(set(native.calls)) == 1
    assert len(store.rows("SELECT * FROM messages")) == 1


def test_pause_during_native_response_blocks_late_flow(store):
    task = store.create_project("Pause", "Inspect")

    class Native:
        async def exchange(self, route, message):
            store.state(task["id"], "paused")
            return {
                "request_id": message["id"],
                "type": "step_intent",
                "intent": {"goal": "late"},
            }

    team = make_team(store, Native())
    with pytest.raises(Blocked):
        asyncio.run(team.tick(task["id"]))
    assert team.flow(task["id"])["phase"] == "intent"
    assert store.task(task["id"])["status"] == "paused"


def test_supporting_role_requires_verified_allowance(store):
    class Native:
        async def exchange(self, *args):
            raise AssertionError(
                "Unverified supporting role must not receive a request"
            )

    team = make_team(store, Native())
    task = store.create_project("Quota", "Inspect")
    team.controller.acquire(task["id"], "worker.opus")
    team.observations.pop("adviser.extra")
    with pytest.raises(Blocked, match="Supporting role"):
        asyncio.run(
            team.ask(
                store.task(task["id"]),
                {"seq": 1, "phase": "brief"},
                "adviser.extra",
                {},
            )
        )


def test_returned_artifact_is_retained_once_and_can_be_saved(store):
    data = b"\x00\x7f\xffbinary"

    class Native:
        locks = {}
        calls = 0

        async def download(self, route, selector, destination, sha, filename=None):
            self.calls += 1
            Path(destination).write_bytes(data)
            assert hashlib.sha256(data).hexdigest() == sha

    native = Native()
    team = make_team(store, native)
    team.config["routes"]["worker.opus"]["selectors"]["download"] = ".download"
    task = store.create_project("Artifact", "Retain returned bytes")
    epoch = team.controller.acquire(task["id"], "worker.opus")
    task = store.task(task["id"])
    response = {
        "request_id": "msg_return",
        "filename": "result.bin",
        "sha256": hashlib.sha256(data).hexdigest(),
    }

    async def run():
        artifact = await team.receive_artifact(task, "worker.opus", response)
        assert await team.receive_artifact(task, "worker.opus", response) == artifact
        return artifact

    artifact = asyncio.run(run())
    assert native.calls == 1
    team.controller.brief(
        task["id"],
        {"revision": 0},
        {"procedure": "Save bytes", "acceptance": "Exact hash"},
        {"critical_gaps": []},
        [],
    )
    team.broker.execute(
        {
            "id": "save",
            "task_id": task["id"],
            "owner": "worker.opus",
            "epoch": epoch,
            "revision": 0,
            "tool": "write_file",
            "args": {
                "path": "result.bin",
                "artifact": artifact["id"],
                "expected_hash": None,
            },
        }
    )
    assert (team.broker.workspace(task["id"]) / "result.bin").read_bytes() == data


@pytest.mark.parametrize(
    "field,value",
    [("filename", "../escape"), ("request_id", "../../escape"), ("sha256", "bad")],
)
def test_returned_artifact_rejects_invalid_identity(store, field, value):
    team = make_team(store, None)
    task = store.create_project("Bad", "Reject invalid response")
    response = {
        "request_id": "msg_return",
        "filename": "result.bin",
        "sha256": "0" * 64,
        field: value,
    }
    with pytest.raises(ContractError):
        asyncio.run(team.receive_artifact(task, "worker.opus", response))


def test_artifact_reads_are_project_scoped(ready, store):
    controller, task, epoch = ready
    broker = Broker(controller, {})
    private = broker.artifacts.add("other project", "other.txt", "another-project")
    with pytest.raises(Blocked):
        broker.execute(
            {
                "id": "read-other",
                "task_id": task["id"],
                "owner": "worker.opus",
                "epoch": epoch,
                "revision": 0,
                "tool": "read_artifact",
                "args": {"artifact": private["id"]},
            }
        )


def test_rejected_write_before_effect_is_not_uncertain(ready, store):
    controller, task, epoch = ready
    broker = Broker(controller, {})
    with pytest.raises(ContractError):
        broker.execute(
            {
                "id": "invalid-write",
                "task_id": task["id"],
                "owner": "worker.opus",
                "epoch": epoch,
                "revision": 0,
                "tool": "write_file",
                "args": {
                    "path": "out.bin",
                    "text": "x",
                    "artifact": "also-present",
                    "expected_hash": None,
                },
            }
        )
    assert (
        store.one("SELECT state FROM operations WHERE id='invalid-write'")["state"]
        == "failed"
    )
    assert not (broker.workspace(task["id"]) / "out.bin").exists()


def retained_request(team, task, key="retained", tool="list_files", args=None):
    epoch = team.controller.acquire(task["id"], "worker.opus")
    team.controller.brief(
        task["id"],
        {"revision": 0},
        {"procedure": "Independent checks", "acceptance": "Recorded results"},
        {"critical_gaps": []},
        [],
    )
    return {
        "id": key,
        "task_id": task["id"],
        "owner": "worker.opus",
        "epoch": epoch,
        "revision": 0,
        "tool": tool,
        "args": args or {},
    }


def test_prebriefed_work_runs_with_no_model_allowance(store):
    team = make_team(store, None)
    task = store.create_project("Offline work", "Inspect locally")
    request = retained_request(team, task)
    team.save_flow(task["id"], {"seq": 3, "phase": "tool", "request": request})
    team.observations.clear()
    asyncio.run(team.tick(task["id"]))
    assert (
        store.one("SELECT state FROM operations WHERE id='retained'")["state"]
        == "completed"
    )
    assert team.flow(task["id"])["phase"] == "execute"
    asyncio.run(team.tick(task["id"]))
    assert store.task(task["id"])["status"] == "waiting_quota"


def test_batch_continues_after_restart_and_failed_independent_check(store):
    team = make_team(store, None)
    task = store.create_project("Batch", "Independent local work")
    request = retained_request(team, task, "a")
    requests = [
        request,
        {**request, "id": "b", "tool": "read_file", "args": {"path": "missing.txt"}},
        {**request, "id": "c"},
    ]
    team.save_flow(
        task["id"],
        {"seq": 3, "phase": "batch", "requests": requests, "cursor": 0, "results": []},
    )
    team.observations.clear()
    asyncio.run(team.tick(task["id"]))
    team.controller.recover()
    team = make_team(store, None)
    team.observations.clear()
    # File read OSError becomes a failed operation. A restart must consume that
    # failure, preserve earlier results and continue the other independent work.
    asyncio.run(team.tick(task["id"]))
    asyncio.run(team.tick(task["id"]))
    flow = team.flow(task["id"])
    assert flow["phase"] == "execute"
    assert len(flow["last_result"]["batch_results"]) == 3
    assert len(store.rows("SELECT * FROM operations")) == 3
    assert flow["results"][0]["operation_id"] == "a"
    assert flow["results"][1]["operation_id"] == "b"


def test_response_timeout_retries_same_message_without_extra_quota_poll(store):
    from hivemind_assembly.core.common import Retryable

    class Native:
        calls = []

        async def exchange(self, route, message):
            self.calls.append(message["id"])
            if len(self.calls) == 1:
                raise Retryable("Response deadline")
            return {
                "type": "step_intent",
                "request_id": message["id"],
                "intent": {"goal": "Inspect"},
            }

    native = Native()
    team = make_team(store, native)
    task = store.create_project("Retry", "Continue response")
    asyncio.run(team.supervise(task["id"]))
    assert store.task(task["id"])["status"] == "waiting_retry"
    asyncio.run(team.supervise(task["id"]))
    assert len(native.calls) == 1
    with store.tx() as c:
        c.execute("UPDATE retry_schedule SET due=0")
    asyncio.run(team.supervise(task["id"]))
    assert len(native.calls) == 2 and len(set(native.calls)) == 1
    assert team.flow(task["id"])["phase"] == "brief"
    assert not store.rows("SELECT * FROM retry_schedule")
    assert not store.rows("SELECT * FROM polls")


def test_retry_backoff_survives_restart_and_honors_pause(store):
    from hivemind_assembly.automation.recovery import Recovery

    task = store.create_project("Retry budget", "Retain failures")
    for n in range(6):
        assert Recovery(store).defer(task["id"], "Temporary timeout", now=100)
        assert store.one("SELECT attempt FROM retry_schedule")["attempt"] == n + 1
    assert not Recovery(store).defer(task["id"], "Temporary timeout", now=100)
    assert store.task(task["id"])["status"] == "waiting_dependency"
    store.state(task["id"], "paused")
    assert not Recovery(store).defer(task["id"], "Temporary timeout", now=100)
    assert store.task(task["id"])["status"] == "paused"


def test_completed_mutation_is_consumed_after_crash_without_second_write(store):
    team = make_team(store, None)
    t = store.create_project("Saved crash", "Recover saved work")
    request = retained_request(
        team,
        t,
        "save-once",
        "write_file",
        {"path": "candidate.txt", "text": "retained", "expected_hash": None},
    )
    team.save_flow(t["id"], {"seq": 2, "phase": "tool", "request": request})
    team.broker.execute(request)
    assert store.project(t["project_id"])["revision"] == 1
    team.controller.recover()
    team.observations.clear()
    asyncio.run(team.tick(t["id"]))
    assert team.flow(t["id"])["phase"] == "intent"
    assert store.project(t["project_id"])["revision"] == 1
    assert len(store.rows("SELECT * FROM operations")) == 1


def test_supporting_quota_wait_is_automatic_and_does_not_spend_worker_messages(store):
    team = make_team(store, None)
    t = store.create_project("Adviser quota", "Wait for adviser")
    team.controller.acquire(t["id"], "worker.opus")
    team.save_flow(
        t["id"],
        {"seq": 1, "phase": "brief", "intent": {"goal": "Check", "revision": 0}},
    )
    team.observations.pop("adviser.extra")
    asyncio.run(team.tick(t["id"]))
    assert store.task(t["id"])["status"] == "waiting_quota"
    assert not store.rows("SELECT * FROM messages")


def test_already_validated_response_is_consumed_without_new_allowance(store):
    from hivemind_assembly.core.common import digest, canonical

    team = make_team(store, None)
    t = store.create_project("Retained response", "Consume existing work")
    team.controller.acquire(t["id"], "worker.opus")
    key = (
        "msg_"
        + digest(
            {"task": t["id"], "flow": 0, "phase": "intent", "route": "worker.opus"}
        )[:32]
    )
    team.controller.prepare_message(
        t["id"],
        "worker.opus",
        team.config["routes"]["worker.opus"]["conversation_url"],
        {"revision": 0, "knowledge_scope": team.scopes.fingerprint(t["id"])},
        key,
    )
    team.controller.message_state(
        key,
        "validated",
        canonical(
            {
                "type": "step_intent",
                "request_id": key,
                "intent": {"goal": "Use completed response"},
            }
        ),
    )
    team.observations.clear()
    team.host = None
    asyncio.run(team.tick(t["id"]))
    assert team.flow(t["id"])["phase"] == "brief"
    assert team.host is None


def test_shutdown_drains_fenced_threads_before_store_is_closed(store):
    import threading

    team = make_team(store, None)

    class Browser:
        async def close(self):
            pass

    team.browser = Browser()
    team.host = None
    started = threading.Event()
    release = threading.Event()

    def operation():
        started.set()
        release.wait(2)
        store.event("fixture", "finished", {})

    async def run():
        job = asyncio.create_task(team.blocking(operation))
        team.active["fixture"] = job
        while not started.is_set():
            await asyncio.sleep(0.01)
        shutdown = asyncio.create_task(team.stop())
        await asyncio.sleep(0.02)
        assert not shutdown.done()
        release.set()
        await shutdown

    asyncio.run(run())
    assert store.rows("SELECT * FROM events WHERE kind='finished'")
