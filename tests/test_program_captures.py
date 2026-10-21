"""Raw capture acceptance across real compiled Windows/x64/ARM program lanes."""

import copy
import json

import pytest
from hivemind_assembly.core.common import Blocked, ContractError
from hivemind_assembly.domains.reverse_engineering import program_captures as captures
from hivemind_assembly.domains.reverse_engineering.program import (
    compare as linux_compare,
)
from hivemind_assembly.domains.reverse_engineering.windows_program import (
    compare as win_compare,
)
from test_platform_runtime import _image
from test_windows_program import compile_source

RGBA = {"format": "rgba8", "width": 1, "height": 1}
PCM = {"format": "pcm_s16le", "channels": 1, "frames": 2, "sample_rate": 8000}


@pytest.mark.parametrize("lane", ["windows", "x86_64", "aarch64"])
def test_real_program_captures_tolerance_and_exact_other_outputs(tmp_path, lane):
    windows = lane == "windows"
    compile = lambda code: (
        compile_source(tmp_path, code)
        if windows
        else _image(tmp_path, code, architecture=lane)
    )
    compare = win_compare if windows else linux_compare
    code = 'int ha_main(void){unsigned char p[4]={10,20,30,255};ha_write(p,4);ha_error("ok",2);return 7;}'
    if not windows:
        code = code.replace('ha_error("ok",2)', 'ha_file_write(2,"ok",2)')
    original = compile(code)
    candidate = compile(code.replace("10,20", "11,20"))
    rule = RGBA | {"max_channel_error": 1}
    case = {"captures": {"stdout": rule}}
    saved = copy.deepcopy(case)
    assert not compare(original, candidate, [{}])["passed"]
    result = compare(original, candidate, [case])
    assert (
        result["passed"]
        and result["cases"][0]["capture_results"]["stdout"]["peak_channel_error"] == 1
    )
    assert case == saved  # Normalization never mutates the caller's rules.
    assert not compare(original, candidate, [{"captures": {"stdout": RGBA}}])["passed"]
    for changed in (code.replace('"ok"', '"no"'), code.replace("return 7", "return 8")):
        assert not compare(original, compile(changed), [case])["passed"]
    short = compile(code.replace("ha_write(p,4)", "ha_write(p,3)"))
    bad = compare(short, short, [case])
    assert (
        not bad["passed"]
        and bad["cases"][0]["capture_results"]["stdout"]["reason"]
        == "capture_size_mismatch"
    )


@pytest.mark.parametrize("lane", ["windows", "x86_64", "aarch64"])
def test_guest_file_pcm_capture_and_missing_file(tmp_path, lane):
    windows = lane == "windows"
    compile = lambda code: (
        compile_source(tmp_path, code)
        if windows
        else _image(tmp_path, code, architecture=lane)
    )
    compare = win_compare if windows else linux_compare
    emit = (
        'ha_dword n;void *f=CreateFileA("sound.pcm",0x40000000,0,0,2,0x80,0);WriteFile(f,p,4,&n,0);CloseHandle(f);'
        if windows
        else 'long f=ha_open("sound.pcm",577,384);ha_file_write(f,p,4);ha_close(f);'
    )
    source = "int ha_main(void){short p[2]={100,-200};" + emit + "return 0;}"
    original = compile(source)
    candidate = compile(source.replace("100,-200", "101,-199"))
    selector = "file:sound.pcm" if windows else "file:/sound.pcm"
    case = {
        "effect_policy": "observable",
        "captures": {selector: PCM | {"max_sample_error": 1, "max_rms_error": 1}},
    }
    if not windows:
        case["runtime"] = "qiling_linux"
    result = compare(original, candidate, [case])
    assert result["passed"], result
    assert result["cases"][0]["capture_results"][selector]["rms_error"] == [1.0]
    missing = compile("int ha_main(void){return 0;}")
    result = compare(missing, missing, [case])
    assert not result["passed"]
    assert (
        result["cases"][0]["capture_results"][selector]["reason"] == "missing_capture"
    )
    # Every unselected final file is still exact, including additions/removals.
    # Avoid redeclaring local handles in the same C scope.
    other = source.replace(
        "return 0;", "{" + emit.replace("sound.pcm", "other.pcm") + "}return 0;"
    )
    result = compare(original, compile(other), [case])
    assert not result["passed"] and "files" in result["cases"][0]["differences"]


@pytest.mark.parametrize(
    "case,windows",
    [
        ({"captures": []}, False),
        ({"captures": {"memory": RGBA}}, False),
        ({"captures": {"file:/out": RGBA}}, False),
        ({"runtime": "qiling_linux", "captures": {"file:/../out": RGBA}}, False),
        ({"captures": {"file:UPPER.bin": RGBA}}, True),
        ({"captures": {"file:c:\\work\\out.bin": RGBA}}, True),
        ({"captures": {"stdout": RGBA | {"width": 1000000}}}, False),
        ({"captures": {"stdout": PCM | {"max_rms_error": float("nan")}}}, True),
        ({"captures": {"stdout": RGBA | {"max_channel_error": True}}}, False),
        ({"captures": {"stdout": RGBA | {"format": "png"}}}, False),
    ],
)
def test_capture_contract_rejects_bad_selectors_shapes_and_limits(case, windows):
    with pytest.raises((ContractError, Blocked)):
        captures.validate(case, windows)


# Use the real application and protected acceptance path, not a mocked evaluator.
import test_app

app = test_app.app
from hivemind_assembly.application.project_checks import starter, run_checks
from test_windows_program import compiler


def test_emulated_frame_starter_seals_rules_and_exposes_owner_capture_view(app):
    app.config["foundations"]["c_compiler"] = compiler()
    task = starter(app, "program_frames", "emulated_frames_123456")
    key = task["id"]
    assert app.action("/api/project/captures", {"task": key})["status"] == "not_run"
    report = run_checks(app, key)
    assert report["result"]["passed"]
    full = app.action("/api/project/captures", {"task": key})
    assert len(full["cases"]) == 3
    # Independent Python rendering oracle, including all alpha and row-order bytes.
    events = [0, 1, 0, 1, 0, 0, 0, 0]
    expected = bytearray()
    x = 0
    for move in events:
        x = (x + bool(move)) % 8
        for row in range(8):
            for col in range(8):
                expected.extend((240 if col == x else 16, row * 16, 32, 255))
    assert bytes.fromhex(full["cases"][1]["original"]["stdout_hex"]) == expected
    with pytest.raises(Blocked):
        app.broker.artifacts.read(
            report["result"]["protected_details"], "worker", task["project_id"]
        )
    assert all(
        "capture_results" not in c and "captures" not in c
        for c in report["result"]["cases"]
    )
    candidate = app.workspace.read(key, "candidate.c")
    app.workspace.write(
        key,
        "candidate.c",
        candidate["text"].replace(
            "if (input[frame])", "if (frame > 0 && input[frame - 1])"
        ),
        candidate["sha256"],
    )
    # Workspace edits cannot alter owner-pinned tolerances or reference behavior.
    visible = app.workspace.read(key, "acceptance.json")
    app.workspace.write(key, "acceptance.json", "{}", visible["sha256"])
    assert (
        app.action("/api/project/captures", {"task": key})["current_revision"]
        != full["checked_revision"]
    )
    report = run_checks(app, key)
    assert not report["result"]["passed"]
    full = app.action("/api/project/captures", {"task": key})
    moved = full["cases"][1]
    assert moved["original"]["stderr_hex"] == moved["candidate"]["stderr_hex"]
    assert moved["capture_results"]["stdout"]["first_failed_frame"] == 1
    assert moved["differences"] == ["captures"]
    assert starter(app, "program_frames", "emulated_frames_123456")["id"] == key
    assert app.store.task(key)["status"] == "paused"


@pytest.mark.parametrize("windows", [False, True])
def test_acceptance_rejects_invalid_reference_capture_before_pinning(app, windows):
    from hivemind_assembly.core.acceptance import Acceptance

    task = app.store.create_project("invalid capture", "check", paused=True)
    root = app.broker.workspace(task["id"])
    image = (
        compile_source(root, "int ha_main(void){return 0;}")
        if windows
        else _image(root, "int ha_main(void){return 0;}")
    )
    name = "original.exe" if windows else "original.elf"
    (root / name).write_bytes(image)
    (root / "build.json").write_text(json.dumps({"sources": ["main.c"]}))
    with pytest.raises(Blocked, match="capture.*shape"):
        Acceptance(app.controller, app.broker).configure(
            task["id"],
            {
                "scope": "windows_program" if windows else "linux_program",
                "original_path": name,
                "manifest_path": "build.json",
                "cases": [{"captures": {"stdout": RGBA}}] * 2,
            },
        )
    assert Acceptance(app.controller, app.broker).describe(task["id"]) is None
