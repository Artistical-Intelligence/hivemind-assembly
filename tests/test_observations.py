import copy
import json
import struct
from pathlib import Path

import pytest
from hivemind_assembly.core.common import ContractError
from hivemind_assembly.core.observations import compare_capture, validate_comparators
from hivemind_assembly.core.tool_testing import execute, validate


def rule(**values):
    return validate_comparators({"capture": values}, ["capture"], 2097152)["capture"]


def test_frame_alpha_coordinates_and_explicit_tolerance():
    spec = rule(format="rgba8", width=2, height=2)
    baseline = bytes([0, 10, 20, 255] * 4)
    altered = bytearray(baseline)
    altered[11] = 253  # Alpha of pixel (0, 1), not an ignorable transparent color.
    result = compare_capture(altered, baseline, spec)
    assert not result["passed"]
    assert result["bad_pixel_bounds"] == [0, 1, 0, 1]
    assert result["bad_pixels"] == 1 and result["peak_channel_error"] == 2
    spec["max_channel_error"] = 2
    result = compare_capture(altered, baseline, spec)
    assert result["passed"] and not result["exact"] and result["different_pixels"] == 1
    spec["max_channel_error"] = 0
    spec["max_bad_pixels"] = 1
    assert compare_capture(altered, baseline, spec)["passed"]
    altered[0] = 1
    assert not compare_capture(altered, baseline, spec)["passed"]
    assert not compare_capture(b"", b"", spec)["passed"]
    assert not compare_capture(None, None, spec)["passed"]


def test_pcm_signed_extremes_channels_and_independent_rms_limit():
    spec = rule(
        format="pcm_s16le",
        channels=2,
        sample_rate=8000,
        frames=2,
        max_sample_error=65535,
        max_rms_error=65535,
    )
    baseline = struct.pack("<hhhh", -32768, 100, 32767, -100)
    candidate = struct.pack("<hhhh", 32767, 103, 32767, -104)
    result = compare_capture(candidate, baseline, spec)
    assert result["passed"]
    assert result["peak_sample_error"] == [65535, 4]
    assert result["rms_error"][1] == pytest.approx((25 / 2) ** 0.5)
    assert result["different_samples"] == [1, 2]
    assert result["first_difference"] == {"frame": 0, "channel": 0}
    spec["max_rms_error"] = 4
    assert not compare_capture(candidate, baseline, spec)["passed"]
    spec["max_rms_error"] = 65535
    spec["max_sample_error"] = 65534
    assert not compare_capture(candidate, baseline, spec)["passed"]
    assert not compare_capture(baseline[:-2], baseline, spec)["passed"]


@pytest.mark.parametrize(
    "bad",
    [
        {"format": "png", "width": 1, "height": 1},
        {"format": "rgba8", "width": True, "height": 1},
        {"format": "rgba8", "width": 10000, "height": 10000},
        {"format": "rgba8", "width": 1, "height": 1, "ignore_alpha": True},
        {"format": "rgba8", "width": 1, "height": 1, "max_bad_pixels": 2},
        {"format": "pcm_s16le", "channels": 2, "frames": 2, "sample_rate": 0},
        {
            "format": "pcm_s16le",
            "channels": 1,
            "frames": 1,
            "sample_rate": 8000,
            "max_rms_error": float("nan"),
        },
        {
            "format": "pcm_s16le",
            "channels": 1,
            "frames": 1,
            "sample_rate": 8000,
            "max_sample_error": -1,
        },
    ],
)
def test_invalid_capture_contract_rejected(bad):
    with pytest.raises(ContractError):
        rule(**bad)


def capture_suite():
    return {
        "version": 1,
        "programs": {
            "candidate": {
                "files": ["candidate.py"],
                "argv": ["{python}", "candidate.py"],
            }
        },
        "output_paths": ["capture"],
        "comparators": {
            "capture": {
                "format": "rgba8",
                "width": 1,
                "height": 1,
                "max_channel_error": 1,
            }
        },
        "cases": [
            {
                "id": "frame",
                "expected": {
                    "exit_code": 0,
                    "stdout_hex": "",
                    "stderr_hex": "",
                    "files": {"capture": "000000ff"},
                },
            }
        ],
    }


def test_native_tolerance_keeps_streams_sizes_and_repeatability_strict(tmp_path):
    source = tmp_path / "candidate.py"
    source.write_text(
        "from pathlib import Path;Path('capture').write_bytes(bytes([1,0,0,255]))"
    )
    spec = capture_suite()
    result = execute(tmp_path, spec, allow_native=True)
    assert result["passed"] and result["cases"][0]["repeatable"]
    assert (
        result["cases"][0]["comparisons"]["candidate"][0]["files"]["capture"][
            "peak_channel_error"
        ]
        == 1
    )
    exact = copy.deepcopy(spec)
    del exact["comparators"]
    assert not execute(tmp_path, exact, allow_native=True)["passed"]
    source.write_text(source.read_text() + ";print('unexpected')")
    assert not execute(tmp_path, spec, allow_native=True)["passed"]
    source.write_text("from pathlib import Path;Path('capture').write_bytes(b'')")
    assert not execute(tmp_path, spec, allow_native=True)["passed"]
    # An external counter deliberately creates two individually tolerated captures.
    counter = tmp_path / "counter"
    source.write_text(
        f"from pathlib import Path;p=Path({str(counter)!r});n=int(p.read_text()) if p.exists() else 0;p.write_text(str(n+1));Path('capture').write_bytes(bytes([n,0,0,255]))"
    )
    result = execute(tmp_path, spec, allow_native=True)
    assert not result["passed"] and not result["cases"][0]["repeatable"]
    assert all(r["passed"] for r in result["cases"][0]["comparisons"]["candidate"])


def test_original_capture_must_satisfy_declared_shape(tmp_path):
    for name in ("original.py", "candidate.py"):
        (tmp_path / name).write_text(
            "from pathlib import Path;Path('capture').write_bytes(b'')"
        )
    spec = capture_suite()
    spec["programs"]["original"] = {
        "files": ["original.py"],
        "argv": ["{python}", "original.py"],
    }
    del spec["cases"][0]["expected"]
    result = execute(tmp_path, spec, allow_native=True)
    assert not result["passed"]
    assert (
        result["cases"][0]["comparisons"]["original"][0]["files"]["capture"]["reason"]
        == "capture_size_mismatch"
    )


def test_expected_capture_and_unobserved_comparators_rejected():
    spec = capture_suite()
    spec["cases"][0]["expected"]["files"]["capture"] = "00"
    with pytest.raises(ContractError, match="size"):
        validate(spec)
    spec = capture_suite()
    spec["comparators"]["typo"] = spec["comparators"]["capture"]
    with pytest.raises(ContractError, match="paths"):
        validate(spec)


def test_audio_replay_example_and_timing_mutant(tmp_path):
    import os
    import shutil

    compiler = os.environ.get("HA_TEST_CLANG") or shutil.which("cc")
    if not compiler:
        pytest.skip("C compiler unavailable")
    example = Path(__file__).parents[1] / "_app/examples/audio_replay"
    for path in example.iterdir():
        shutil.copyfile(path, tmp_path / path.name)
    spec = json.loads((tmp_path / "suite.json").read_text())
    result = execute(tmp_path, spec, allow_native=True, compiler=compiler)
    assert result["passed"] and len(result["cases"]) == 3
    candidate = tmp_path / "reconstructed.c"
    candidate.write_text(
        candidate.read_text().replace("tick == frame", "tick == frame - 1")
    )
    result = execute(tmp_path, spec, allow_native=True, compiler=compiler)
    assert not result["passed"]
    assert (
        result["cases"][1]["comparisons"]["candidate"][0]["files"]["audio.pcm"][
            "first_difference"
        ]["frame"]
        == 0
    )
