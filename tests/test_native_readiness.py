"""Identity recovery must neither repoll usage nor invent renewed allowance."""

import asyncio
import time
from types import SimpleNamespace

import pytest

from hivemind_assembly.automation.onboarding import NativeSetup
from hivemind_assembly.automation.policy import Availability, Window
from hivemind_assembly.automation.team import NativeTeam
from hivemind_assembly.core.common import AllowanceUnavailable, WaitingForSignIn
from test_startup_handoff import make_team


def readiness_team(store, error):
    team = make_team(store)
    route = "worker.opus"
    team.config["routes"][route]["usage"]["url"] = "https://claude.ai/usage"
    state = {"error": error, "polls": 0, "observations": 0, "accepted": True}

    async def usage(route):
        state["polls"] += 1
        return {
            "observed": time.time(),
            "no_numeric_limit": False,
            "windows": [{"name": "daily", "remaining": 50}],
        }

    async def observe(route):
        state["observations"] += 1
        if state["error"]:
            raise state["error"]

    team.browser.poll_usage = usage
    team.browser.observe = observe
    team.sessions = SimpleNamespace(accepted=lambda route: state["accepted"])
    return team, state, route


@pytest.mark.parametrize("restart", [False, True])
def test_completed_signin_restores_route_using_original_allowance(store, restart):
    team, state, route = readiness_team(store, WaitingForSignIn("Sign in"))
    asyncio.run(team.poll())
    assert not team.observations[route].eligible()
    timestamp = team.observations[route].observed
    if restart:
        resumed = NativeTeam(team.controller, team.broker, team.browser, team.config)
        resumed.sessions = team.sessions
        team = resumed
    state["error"] = None
    asyncio.run(team.poll())
    assert team.observations[route].eligible()
    assert team.observations[route].observed == timestamp
    assert state["polls"] == 1 and state["observations"] == 2
    assert not store.rows("SELECT * FROM messages")


def test_cleared_quota_banner_and_setup_do_not_restore_stale_balance(store, tmp_path):
    team, state, route = readiness_team(
        store, AllowanceUnavailable("Exhausted", route="worker.opus")
    )
    asyncio.run(team.poll())
    state["error"] = None
    asyncio.run(team.poll())
    assert not team.observations[route].eligible()
    assert state["polls"] == 1 and state["observations"] == 1
    setup = NativeSetup(
        SimpleNamespace(config=team.config),
        store,
        tmp_path / "settings.json",
        team=team,
    )
    allowance = asyncio.run(setup.allowance(route, team.config["routes"][route]))
    assert allowance.blocked_kind == "quota" and not allowance.eligible()


@pytest.mark.parametrize("blocker", ["stale", "unaccepted"])
def test_readiness_recheck_needs_fresh_allowance_and_accepted_transport(store, blocker):
    team, state, route = readiness_team(store, WaitingForSignIn("Sign in"))
    asyncio.run(team.poll())
    state["error"] = None
    if blocker == "stale":
        team.observations[route].observed -= 86401
    else:
        state["accepted"] = False
    asyncio.run(team.poll())
    assert not team.observations[route].eligible()
    assert state["observations"] == 1 and state["polls"] == 1


def test_failed_recheck_is_throttled_without_resetting_allowance(store):
    team, state, route = readiness_team(store, ConnectionError("Browser interrupted"))
    asyncio.run(team.poll())
    timestamp = team.observations[route].observed
    asyncio.run(team.poll())
    state["error"] = None
    asyncio.run(team.poll())
    assert not team.observations[route].eligible()
    assert state["observations"] == 2
    team.readiness_checked[route] -= 31
    asyncio.run(team.poll())
    assert team.observations[route].eligible()
    assert team.observations[route].observed == timestamp
    assert state["polls"] == 1


def test_concurrent_setup_observation_cannot_be_overwritten(store):
    team, state, route = readiness_team(store, WaitingForSignIn("Sign in"))
    asyncio.run(team.poll())
    newer = Availability(route, True, True, False, time.time(), [Window("daily", 2)])

    async def changed(route):
        team.observations[route] = newer

    team.browser.observe = changed
    asyncio.run(team.poll())
    assert team.observations[route] is newer
    assert not newer.eligible()


def test_adviser_quota_exhaustion_blocks_only_the_actual_route(store):
    team = make_team(store)
    task = store.create_project("quota", "Retain the active worker")
    team.controller.acquire(task["id"], "worker.opus")

    async def quota(task):
        raise AllowanceUnavailable("Adviser allowance exhausted", route="adviser.extra")

    team.tick = quota
    asyncio.run(team.supervise(task["id"]))
    assert team.observations["worker.opus"].eligible()
    assert not team.observations["adviser.extra"].eligible()
    assert team.observations["adviser.extra"].blocked_kind == "quota"
    assert store.task(task["id"])["status"] == "waiting_quota"
    resumed = NativeTeam(team.controller, team.broker, team.browser, team.config)
    assert resumed.observations["adviser.extra"].blocked_kind == "quota"


def test_setup_quota_wait_is_resumable_and_keeps_exhaustion(
    store, tmp_path, monkeypatch
):
    import hivemind_assembly.automation.onboarding as module

    team = make_team(store)
    setup = NativeSetup(team.browser, store, tmp_path / "settings.json", team=team)

    async def quota(route):
        raise AllowanceUnavailable("Wait for quota", route=route)

    async def stop_after_first_iteration(delay):
        raise asyncio.CancelledError()

    setup.step = quota
    monkeypatch.setattr(module.asyncio, "sleep", stop_after_first_iteration)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(setup.run("worker.opus"))
    assert setup.status("worker.opus")["stage"] == "waiting_quota"
    assert team.observations["worker.opus"].blocked_kind == "quota"
    assert not team.observations["worker.opus"].eligible()
