"""Game play-testing operations: worker broker path, images, attachments, dashboard,
starter, protected game_play acceptance and the command line.

Scripted calls exercise real builds and emulation. They are not evidence that a
signed-in model played or repaired a game.
"""

import base64
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import test_app

from hivemind_assembly.application import game_example as ge
from hivemind_assembly.application.project_checks import run_checks, starter
from hivemind_assembly.core.acceptance import Acceptance
from hivemind_assembly.core.broker import Broker
from hivemind_assembly.core.common import file_hash
from hivemind_assembly.core.jobs import Jobs
from hivemind_assembly.domains.reverse_engineering.domain import ReverseEngineeringDomain

app = test_app.app
ROOT = Path(__file__).resolve().parents[1]


def _compiler():
    value = os.environ.get("HA_TEST_CLANG") or shutil.which("clang") or shutil.which("gcc")
    if not value:
        pytest.skip("A C compiler is required")
    return value


def _workspace(root, fixed=()):
    root.mkdir(parents=True, exist_ok=True)
    for name, text in ge.files(fixed).items():
        (root / name).write_text(text)
    (root / "original.elf").write_bytes(ge.build_original(Jobs(), _compiler()))
    return root


def _request(task, epoch, tool, args, key):
    return {
        "id": key,
        "task_id": task["id"],
        "owner": "worker.opus",
        "epoch": epoch,
        "revision": 0,
        "tool": tool,
        "args": args,
    }


def test_worker_operations_return_replayable_results_and_frame_artifacts(ready):
    controller, task, epoch = ready
    broker = Broker(controller, {"foundations": {"c_compiler": _compiler()}}, ReverseEngineeringDomain())
    root = _workspace(broker.workspace(task["id"]))
    described = broker.execute(_request(task, epoch, "describe_game", {}, "game_describe_1"))
    assert described["sides"]["candidate"]["capabilities"]["stepping"] == "live"
    assert described["sides"]["original"]["available"] and described["regressions"] == 2
    request = _request(task, epoch, "play_game", {"actions": ["run_right", "jump"], "side": "both", "images": 1}, "game_play_1")
    played = broker.execute(request)
    assert played["outcome"] == "pass" and played["ticks_added"] == 8
    assert [i["name"] for i in played["image_artifacts"]] == ["original-tick-7.png", "candidate-tick-7.png"]
    png = broker.artifacts.read(played["image_artifacts"][1]["id"], "worker", task["project_id"], task=task["id"])
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert broker.execute(request) == played
    resumed = broker.execute(
        _request(task, epoch, "play_game", {"trajectory": played["trajectory"], "actions": ["wait"]}, "game_play_2")
    )
    assert resumed["observation"]["ticks"] == 12
    edge = broker.execute(
        _request(task, epoch, "play_game", {"start": "upper_platform", "actions": ["step_left"], "side": "both"}, "game_play_3")
    )
    assert edge["outcome"] == "divergence"
    assert edge["comparison"]["divergence"]["signature"] == ["divergence", "state:y"]
    regressions = broker.execute(_request(task, epoch, "test_game", {"mode": "regressions"}, "game_test_1"))
    assert regressions["passed"] and regressions["total"] == 2
    # The defective candidate lands inside the platform, so its start is unreached.
    unreached = broker.execute(
        _request(task, epoch, "play_game", {"start": "upper_platform"}, "game_play_4")
    )
    assert unreached["outcome"] == "unreached"
    assert unreached["preconditions"][0]["actual"] == 7
    reached = broker.execute(
        _request(task, epoch, "play_game", {"start": "upper_platform", "side": "original"}, "game_play_5")
    )
    assert reached["outcome"] == "pass" and reached["observation"]["state"]["y"] == 6
    assert "frames" not in played and json.dumps(played)
    assert (root / "game.json").exists() and broker.capabilities["test_game"].recovery == "discard"


def test_native_turn_attaches_png_artifacts_only_with_upload_bindings(ready, tmp_path):
    from hivemind_assembly.automation.team import NativeTeam
    from hivemind_assembly.core import game_spec as gs

    controller, task, _ = ready
    broker = Broker(controller, {}, ReverseEngineeringDomain())
    project = controller.store.task(task["id"])["project_id"]
    frame = gs.png(bytes([1, 2, 3, 255] * 4), 2, 2, 2)
    first = broker.artifacts.add(frame, "candidate-tick-3.png", project)
    other = broker.artifacts.add(b"not shown", "notes.txt", project)
    team = NativeTeam(controller, broker, None, {"routes": {}})
    last = {
        "batch_results": [
            {"image_artifacts": [{"id": first["id"], "name": "candidate-tick-3.png"}]},
            {"image_artifacts": [{"id": other["id"], "name": "notes.txt"}]},
        ]
    }
    bound = {"selectors": {"upload": "input[type=file]", "attachment_ready": "[data-testid=attachment]"}}
    attached = team.result_images(controller.store.task(task["id"]), "msg_fixture", bound, last)
    assert len(attached) == 1 and Path(attached[0]["path"]).name == "candidate-tick-3.png"
    assert file_hash(attached[0]["path"]) == attached[0]["sha256"] == first["sha256"]
    assert team.result_images(controller.store.task(task["id"]), "msg_fixture", {"selectors": {}}, last) == []


def test_game_starter_dashboard_play_regressions_and_protected_acceptance(app):
    app.config["foundations"]["c_compiler"] = _compiler()
    task = starter(app, "game_testing", "game_testing_starter_01")
    root = app.broker.workspace(task["id"])
    assert (root / "original.elf").exists() and not (root / "original.c").exists()
    described = Acceptance(app.controller, app.broker).describe(task["id"])
    assert described["scope"] == "game_play" and described["checks"][0]["trajectory_count"] == 4
    assert "inputs_hex" not in json.dumps(described) and "trajectories" not in json.dumps(described)
    first = run_checks(app, task["id"])["result"]
    assert first["passed"] is False
    outcomes = {case["id"]: case["outcome"] for case in first["cases"]}
    assert outcomes == {
        "coin_route": "pass",
        "hole_quirk": "pass",
        "platform_edge": "divergence",
        "spike_landing": "freeze",
    }
    assert "inputs_hex" not in json.dumps(first)
    details = app.store.one("SELECT * FROM artifacts WHERE id=?", (first["protected_details"],))
    assert details["classification"] == "protected"
    shown = app.action("/api/game/play", {"task": task["id"], "side": "both", "actions": ["run_right"]})
    assert {f["side"] for f in shown["frames"]} == {"original", "candidate"}
    assert len(base64.b64decode(shown["frames"][0]["rgba_base64"])) == 16 * 12 * 4
    saved = app.action(
        "/api/game/save-regression",
        {"task": task["id"], "trajectory": shown["trajectory"], "id": "manual_run", "expect": "match_original"},
    )
    assert saved["path"] == "game-regressions.json"
    items = json.loads((root / "game-regressions.json").read_text())["regressions"]
    assert [i["id"] for i in items] == ["coin_route", "hole_quirk", "manual_run"]
    result = app.game_call("test_game", {"task": task["id"], "mode": "regressions"})
    assert result["passed"] and result["total"] == 3
    for name in ("edge", "knockback"):
        unit, before, after = ge.FIXES[name]
        text = (root / unit).read_text()
        app.workspace.write(task["id"], unit, text.replace(before, after), file_hash(root / unit))
    second = run_checks(app, task["id"])["result"]
    assert second["passed"] is True
    assert {case["outcome"] for case in second["cases"]} == {"pass"}
    assert second["executable_artifact"]


def test_command_line_game_test(tmp_path):
    root = _workspace(tmp_path / "game")
    command = [sys.executable, str(ROOT / "_app" / "launch.py"), "game-test", "--workspace", str(root), "--compiler", _compiler()]
    result = subprocess.run(command + ["--mode", "regressions"], capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["total"] == 2
    result = subprocess.run(command + ["--mode", "compare", "--trajectory", "past_spikes"], capture_output=True, text=True, timeout=300)
    assert result.returncode == 0 and json.loads(result.stdout)["outcome"] == "pass"
    result = subprocess.run(command + ["--mode", "compare", "--trajectory", "upper_platform"], capture_output=True, text=True, timeout=300)
    assert result.returncode == 1 and json.loads(result.stdout)["outcome"] == "divergence"
