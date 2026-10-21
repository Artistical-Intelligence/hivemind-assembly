"""Startup regressions. Transport responses here are fixtures, not live acceptance."""

import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from hivemind_assembly.application.workspace import Workspace
from hivemind_assembly.automation.onboarding import NativeSetup
from hivemind_assembly.automation.policy import Availability, Window
from hivemind_assembly.automation.team import NativeTeam
from hivemind_assembly.core.acceptance import Acceptance
from hivemind_assembly.core.common import Blocked
from hivemind_assembly.core.controller import Controller
from hivemind_assembly.core.store import Store
from workbench.broker import Broker
from test_team import FixtureNative, RecordingHost


def configuration():
    return json.loads(
        (Path(__file__).parents[1] / "_app/config/default.json").read_text()
    )


def make_team(store):
    cfg = configuration()
    for name, route in cfg["routes"].items():
        route["conversation_url"] = "https://example.invalid/" + name
    controller = Controller(store)
    team = NativeTeam(controller, Broker(controller, cfg), FixtureNative(), cfg)
    team.host = RecordingHost()
    for name in ("worker.opus", "adviser.extra"):
        team.observations[name] = Availability(
            name, True, True, False, time.time(), [Window("daily", 50)]
        )
    return team


def contract():
    return {
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


def test_unattended_start_waits_across_restart_then_finishes(store):
    team = make_team(store)
    task = store.create_project("startup", "Recover the region", continuation=True)
    assert task["status"] == "waiting_setup"
    for _ in range(3):
        asyncio.run(team.tick(task["id"]))
    assert not team.browser.calls
    assert team.goals.status(task["id"])["turns"] == 0
    assert not store.task(task["id"])["owner"]
    # Starting through a direct controller path cannot race configuration either.
    with pytest.raises(Blocked, match="pin independent"):
        team.controller.acquire(task["id"], "worker.opus")

    reopened = Store(store.root)
    try:
        team = make_team(reopened)
        team.controller.recover()
        workspace = Workspace(team.broker)
        assert workspace.listing(task["id"])["editable"]
        workspace.write(task["id"], "original.hex", "89f801f0")
        workspace.write(task["id"], "candidate.hex", "8d0437")
        Acceptance(team.controller, team.broker).configure(task["id"], contract())
        assert reopened.task(task["id"])["status"] == "queued"
        assert not reopened.task(task["id"])["blocker"]

        # No additional resume, manual request relay or status override.
        async def run():
            for _ in range(8):
                await team.supervise(task["id"])

        asyncio.run(run())
        assert reopened.task(task["id"])["status"] == "accepted"
        assert team.goals.status(task["id"])["status"] == "achieved"
        assert "adviser.extra" in team.browser.calls
        assert reopened.rows("SELECT id FROM records WHERE kind='acceptance_result'")
    finally:
        reopened.close()


def test_pinning_checks_preserves_explicit_pause(store):
    team = make_team(store)
    task = store.create_project(
        "paused", "Prepare later", paused=True, continuation=True
    )
    workspace = Workspace(team.broker)
    workspace.write(task["id"], "original.hex", "89f801f0")
    Acceptance(team.controller, team.broker).configure(task["id"], contract())
    asyncio.run(team.tick(task["id"]))
    assert store.task(task["id"])["status"] == "paused"
    assert not team.browser.calls


def test_unconfigured_usage_page_does_not_reserve_poll(store):
    team = make_team(store)

    async def forbidden(route):
        raise AssertionError("No usage page is configured")

    team.browser.poll_usage = forbidden
    asyncio.run(team.poll())
    assert not store.rows("SELECT * FROM polls")


@pytest.mark.parametrize("accepted", [True, False])
def test_setup_resumes_after_session_commit_without_extra_send_or_poll(
    store, tmp_path, monkeypatch, accepted
):
    import hivemind_assembly.automation.onboarding as module

    team = make_team(store)
    route = "worker.extra"
    cfg = team.config["routes"][route]
    cfg.update(conversation_url="https://chatgpt.com/c/retained", account_label="test")
    cfg["usage"]["url"] = "https://chatgpt.com/usage"
    # The poll succeeded; transport was not ready when availability was saved.
    observed = time.time() - 60
    team.observations[route] = Availability(
        route,
        False,
        True,
        False,
        observed,
        [Window("daily", 50)],
        "Session acceptance pending",
    )
    team.usage.claim_poll(cfg["usage"]["scope"])
    calls = []

    class Empty:
        async def count(self):
            return 0

    class Page:
        url = cfg["conversation_url"]

        def is_closed(self):
            return False

        def get_by_role(self, *args, **kwargs):
            return Empty()

        def locator(self, *args):
            return Empty()

    page = Page()

    async def observe(name):
        calls.append("observe")
        return {"route": name}

    async def forbidden(name):
        raise AssertionError("A second usage-page fetch is forbidden")

    async def renew(task, name):
        calls.append("renew")

    async def discover(page, config):
        return {"missing": [], "selectors": {}, "account_label": "test"}

    browser = SimpleNamespace(
        config=team.config,
        pages={route: page},
        observe=observe,
        poll_usage=forbidden,
        validate_url=lambda *args: None,
    )
    sessions = SimpleNamespace(accepted=lambda name: accepted, renew=renew)
    monkeypatch.setattr(module, "discover", discover)
    setup = NativeSetup(browser, store, tmp_path / "settings.json", sessions, team)
    setup.pages[route] = page
    result = asyncio.run(setup.step(route))
    assert result["stage"] == "verified"
    assert calls == (["observe"] if accepted else ["observe", "renew"])
    assert team.observations[route].eligible()
    assert team.observations[route].observed == observed
    assert len(store.rows("SELECT * FROM polls")) == 1
    retained = store.rows("SELECT payload FROM records WHERE kind='availability'")
    assert json.loads(retained[-1]["payload"])["ready"] is True
