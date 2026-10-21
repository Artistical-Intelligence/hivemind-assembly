"""Temporal mistakes must fail even when final output and state agree."""
import copy
import json
import os
import shutil
from pathlib import Path

import pytest
import test_app
from hivemind_assembly.core.common import Blocked, ContractError
from hivemind_assembly.core.observations import compare_capture, validate_comparators
from hivemind_assembly.application.project_checks import starter, run_checks
from hivemind_assembly.core.test_acceptance import NativeTestAcceptance
from hivemind_assembly.core.tool_testing import execute, validate

app = test_app.app


def rule(**overrides):
    spec = dict(format="rgba8_sequence", width=2, height=1, frames=3,
                frame_rate_num=30000, frame_rate_den=1001)
    spec.update(overrides)
    return validate_comparators({"frames.rgba": spec}, ["frames.rgba"], 2097152)["frames.rgba"]


def test_sequence_checks_every_frame_and_preserves_alpha_and_bounds():
    baseline = bytes([0, 0, 0, 255] * 6)
    changed = bytearray(baseline)
    changed[15] = 252  # Frame 1, pixel (1, 0), alpha.
    result = compare_capture(changed, baseline, rule())
    assert not result["passed"] and result["first_failed_frame"] == 1
    assert result["first_difference_frame"] == 1
    assert result["different_frames"] == result["failed_frames"] == 1
    assert result["frames"][1]["bad_pixel_bounds"] == [1, 0, 1, 0]
    assert result["frames"][1]["peak_channel_error"] == 3
    assert result["frames"][2]["exact"]
    assert result["declared_duration_seconds"] == pytest.approx(3 * 1001 / 30000)
    tolerated = compare_capture(changed, baseline, rule(max_channel_error=3))
    assert tolerated["passed"] and not tolerated["exact"]
    assert tolerated["first_failed_frame"] is None
    assert tolerated["first_difference_frame"] == 1
    # One bad pixel in each frame is allowed; two in one frame cannot be
    # diluted by two perfect frames or borrowed from another frame's allowance.
    changed = bytearray(baseline)
    for offset in (0, 8, 16):
        changed[offset] = 10
    assert compare_capture(changed, baseline, rule(max_bad_pixels=1))["passed"]
    changed[12] = 10
    assert not compare_capture(changed, baseline, rule(max_bad_pixels=1))["passed"]


def test_sequence_cannot_reorder_drop_duplicate_or_align_frames():
    frames = [bytes([value, 0, 0, 255] * 2) for value in (1, 2, 3)]
    baseline = b"".join(frames)
    for candidate in (b"".join(reversed(frames)), frames[0] + frames[0] + frames[2]):
        assert not compare_capture(candidate, baseline, rule())["passed"]
    for candidate in (baseline[:-8], baseline + frames[2], b"", None):
        assert not compare_capture(candidate, baseline, rule())["passed"]
    assert compare_capture(baseline, baseline, rule())["exact"]


@pytest.mark.parametrize("override", [
    {"frames": 0}, {"frames": True}, {"frames": 4097}, {"frames": 1.5},
    {"frame_rate_num": 0}, {"frame_rate_den": 0}, {"frame_rate_den": -1},
    {"frame_rate_num": True}, {"frame_rate_num": 1000001},
    {"frame_rate_den": float("nan")}, {"frames": 4096, "width": 1024},
    {"align_frames": True}, {"max_bad_pixels": 3},
])
def test_sequence_invalid_contracts(override):
    with pytest.raises(ContractError):
        rule(**override)


def example():
    return Path(__file__).parents[1] / "_app/examples/frame_replay"


def compiler():
    value = os.environ.get("HA_TEST_CLANG") or shutil.which("cc") or shutil.which("clang")
    if not value:
        pytest.skip("C compiler unavailable")
    return value


def test_expected_sequence_must_have_all_declared_frames():
    spec = json.loads((example() / "suite.json").read_text())
    del spec["programs"]["original"]
    spec["cases"] = [{"id": "incomplete", "expected": {
        "exit_code": 0, "stdout_hex": "", "stderr_hex": "",
        "files": {"frames.rgba": "000000ff" * 256, "final.bin": "0101"},
    }}]
    with pytest.raises(ContractError, match="size"):
        validate(spec)


def test_compiled_frame_replay_catches_late_input_with_identical_final_state(tmp_path):
    cc = compiler()
    for path in example().iterdir():
        if path.is_file():
            shutil.copyfile(path, tmp_path / path.name)
    spec = json.loads((tmp_path / "suite.json").read_text())
    result = execute(tmp_path, copy.deepcopy(spec), allow_native=True, compiler=cc)
    assert result["passed"] and len(result["cases"]) == 3
    candidate = tmp_path / "candidate.c"
    candidate.write_text(candidate.read_text().replace("tick == frame", "tick == frame - 1"))
    result = execute(tmp_path, spec, allow_native=True, compiler=cc)
    assert not result["passed"]
    assert result["cases"][0]["passed"]  # Stationary scene still agrees.
    for case in result["cases"][1:]:
        assert case["repeatable"] and not case["passed"]
        for comparison in case["comparisons"]["candidate"]:
            assert comparison["files"]["final.bin"]["passed"]
            sequence = comparison["files"]["frames.rgba"]
            assert not sequence["passed"] and sequence["first_failed_frame"] == 0
            assert sequence["frames"][-1]["exact"]


def test_frame_starter_pins_oracle_recipe_and_retains_protected_captures(app):
    app.config["foundations"]["c_compiler"] = compiler()
    with pytest.raises(Blocked):
        starter(app, "native_frames", "frames_starter_1234")
    task = starter(app, "native_frames", "frames_starter_1234", True)
    key, project = task["id"], task["project_id"]
    assert run_checks(app, key)["passed"]
    candidate = app.workspace.read(key, "candidate.c")
    changed = candidate["text"].replace("tick == frame", "tick == frame - 1")
    app.workspace.write(key, "candidate.c", changed, candidate["sha256"])
    original = app.workspace.read(key, "original.py")
    app.workspace.write(key, "original.py", original["text"].replace("when == tick", "when == tick - 1"), original["sha256"])
    # Neither editing the visible oracle nor relaxing visible suite thresholds
    # may overwrite the owner's pinned evaluator.
    suite = app.workspace.read(key, "suite.json")
    spec = json.loads(suite["text"])
    spec["comparators"]["frames.rgba"]["max_bad_pixels"] = 256
    app.workspace.write(key, "suite.json", json.dumps(spec), suite["sha256"])
    assert starter(app, "native_frames", "frames_starter_1234", True)["id"] == key
    assert app.workspace.read(key, "candidate.c")["text"] == changed
    report = run_checks(app, key)
    assert not report["passed"] and report["case_count"] == 3
    captures = app.action("/api/native-tests/results", {"task": key})
    assert captures["comparators"]["frames.rgba"]["max_bad_pixels"] == 0
    assert captures["cases"][1]["comparisons"]["candidate"][0]["files"]["frames.rgba"]["first_failed_frame"] == 0
    with pytest.raises(Blocked):
        app.broker.artifacts.read(report["observations_artifact"], "worker", project)
    assert app.store.task(key)["status"] == "paused"
    NativeTestAcceptance(app.store).allow(project, False)
    with pytest.raises(Blocked, match="enabled"):
        run_checks(app, key)
