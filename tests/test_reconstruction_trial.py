"""Actual builds/replays behind scripted model turns; not live model acceptance."""

import asyncio
import json
import os
import shutil

import pytest
import test_app

from hivemind_assembly.application.project_checks import starter, run_checks
from hivemind_assembly.application.reconstruction_trial import SOURCE
from hivemind_assembly.core.common import file_hash
from test_startup_handoff import make_team

app = test_app.app


def test_unfinished_trial_requires_repair_and_continues_after_checkpoint(app):
    compiler = (
        os.environ.get("HA_TEST_CLANG") or shutil.which("clang") or shutil.which("gcc")
    )
    if not compiler:
        pytest.skip("A C compiler is required")
    app.config["foundations"]["c_compiler"] = compiler
    task = starter(app, "autonomous_program", "autonomous_trial_1234")
    key = task["id"]
    root = app.broker.workspace(key)
    assert task["status"] == "paused"
    assert not (root / "original.c").exists()
    assert not (root / "acceptance.json").exists()
    assert sorted(p.name for p in root.iterdir()) == [
        "README.txt",
        "build.json",
        "candidate.c",
        "development.json",
        "original.elf",
    ]
    initial = (root / "candidate.c").read_text()
    assert not run_checks(app, key)["result"]["passed"]
    assert starter(app, "autonomous_program", "autonomous_trial_1234")["id"] == key
    assert (root / "candidate.c").read_text() == initial
    development = json.loads((root / "development.json").read_text())

    team = make_team(app.store)
    team.config["foundations"]["c_compiler"] = compiler
    original_hash = file_hash(root / "original.elf")
    expected_hash = file_hash(root / "candidate.c")

    class Repair:
        index = 0

        async def exchange(self, route, message):
            nonlocal expected_hash
            body = json.loads(message["payload"])["body"]
            common = {"request_id": message["id"]}
            if "catalog" in body:
                return {
                    **common,
                    "type": "knowledge_scope",
                    "tags": [],
                    "catalog_revision": body["catalog"]["revision"],
                }
            if route.startswith("adviser"):
                return {
                    **common,
                    "type": "brief",
                    "brief": {
                        "procedure": "Repair and compare full program",
                        "acceptance": "Pinned independent complete-program replay",
                    },
                    "obligations": [],
                }
            if body.get("instruction"):
                return {
                    **common,
                    "type": "step_intent",
                    "intent": {
                        "goal": "Recover program output",
                        "method": "Compile and compare",
                    },
                }
            index = self.index
            self.index += 1
            if index in (0, 3):
                source = (
                    SOURCE.replace("state * 33u", "state * 32u")
                    if index == 0
                    else SOURCE
                )
                args = {
                    "path": "candidate.c",
                    "text": source,
                    "expected_hash": expected_hash,
                }
                import hashlib

                expected_hash = hashlib.sha256(source.encode()).hexdigest()
                return {
                    **common,
                    "type": "tool_request",
                    "tool": "write_file",
                    "args": args,
                }
            if index in (1, 4):
                return {
                    **common,
                    "type": "tool_request",
                    "tool": "compare_program",
                    "args": {
                        "original_path": "original.elf",
                        "manifest_path": "build.json",
                        "cases": development,
                    },
                }
            if index == 2:
                assert body["last_result"]["passed"] is False
                return {
                    **common,
                    "type": "tool_request",
                    "tool": "checkpoint",
                    "args": {"reason": "Failed candidate retained; continue repair"},
                }
            assert index == 5 and body["last_result"]["passed"] is True
            return {
                **common,
                "type": "complete",
                "result_operations": [body["last_result"]["operation_id"]],
                "summary": "Synthetic program reconstructed for the pinned corpus",
            }

    team.browser = Repair()
    from native_fixtures import PassingChecks

    team.sessions = PassingChecks(team.config)  # The independent check of what it wrote passes.
    # Keep the application's background scheduler idle; this test drives the real
    # controller explicitly with the isolated fixture transport.
    app.team.pause_dispatch = True
    team.goals.control(key, "start")

    async def run():
        saw_checkpoint = False
        for _ in range(40):
            await team.supervise(key)
            if app.store.rows(
                "SELECT id FROM operations WHERE task_id=? AND tool='checkpoint'",
                (key,),
            ):
                saw_checkpoint = True
                if team.browser.index == 3:
                    assert team.goals.status(key)["status"] == "active"
            if app.store.task(key)["status"] == "accepted":
                break
        assert saw_checkpoint

    asyncio.run(run())
    assert app.store.task(key)["status"] == "accepted", app.store.task(key)
    assert team.goals.status(key)["status"] == "achieved"
    assert file_hash(root / "original.elf") == original_hash
    report = json.loads(
        app.store.rows("SELECT payload FROM records WHERE kind='acceptance_result'")[
            -1
        ]["payload"]
    )
    assert report["passed"] and len(report["cases"]) == 9
    assert (
        len(app.store.rows("SELECT id FROM operations WHERE tool='compare_program'"))
        == 2
    )
