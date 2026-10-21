"""Actionable guest failure locations without leaking sealed evidence to workers."""

import json
import threading
from types import SimpleNamespace

import pefile
import pytest

from hivemind_assembly.core.artifacts import Artifacts
from hivemind_assembly.core.common import Blocked
from hivemind_assembly.core.jobs import Jobs
from hivemind_assembly.domains.reverse_engineering.windows_acceptance import (
    WindowsAcceptance,
)
from hivemind_assembly.domains.reverse_engineering.windows_program import (
    replay,
    compare,
)
from test_windows_program import compile_source, compiler


@pytest.mark.parametrize(
    "body,status,api",
    [
        (
            "VirtualAlloc(0,4096,0x3000,64);return 0;",
            "unsupported",
            "kernel32.VirtualAlloc",
        ),
        (
            "void *p=VirtualAlloc(0,4096,0x3000,2);ha_read(p,1);return 0;",
            "fault",
            "kernel32.ReadFile",
        ),
        ("VirtualAlloc(0,4096,0x3000,4);for(;;){}", "budget_exhausted", None),
        ("return *(volatile int*)1;", "fault", None),
    ],
)
def test_failure_location_resolves_against_pe_bytes(tmp_path, body, status, api):
    image = compile_source(tmp_path, "int ha_main(void){" + body + "}")
    result = replay(image, b"X", max_instructions=1000)
    assert result["status"] == status, result
    context = result["stop_context"]
    assert context["phase"] == "application" and context["image"] == "program", result
    assert context.get("api", {}).get("name") == api
    assert "x" in context["mapping"]["permissions"]
    pe = pefile.PE(data=image)
    try:
        rva = context["program_counter"] - pe.OPTIONAL_HEADER.ImageBase
        offset = pe.get_offset_from_rva(rva)
        raw = bytes.fromhex(context["instruction_hex"])
        assert rva == context["image_offset"]
        assert offset == context["image_file_offset"]
        assert raw == image[offset : offset + len(raw)]
        assert raw.hex() == context["image_instruction_hex"]
    finally:
        pe.close()
    if api == "kernel32.ReadFile":
        access = context["memory_access"]
        assert access == {
            "address": context["api"]["arguments"][1],
            "size": 1,
            "access": "write",
        }
    assert str(tmp_path) not in json.dumps(context)
    assert "ha-windows-" not in json.dumps(context)
    assert len(json.dumps(context)) < 4096


def test_success_has_no_diagnostic_and_precancel_has_no_stale_guest_location(tmp_path):
    image = compile_source(tmp_path, "int ha_main(void){return 0;}")
    result = replay(image)
    assert result["status"] == "completed" and result["stop_context"] is None
    cancelled = threading.Event()
    cancelled.set()
    result = replay(image, cancel=cancelled)
    assert result["status"] == "cancelled"
    assert result["stop_context"] == {"phase": "initialization"}


def test_diagnostic_fields_are_not_equivalence_observations(tmp_path, monkeypatch):
    from hivemind_assembly.domains.reverse_engineering import windows_program

    image = compile_source(tmp_path, "int ha_main(void){return 0;}")
    actual = windows_program.replay
    serial = []

    def changing_diagnostic(*args, **kwargs):
        value = actual(*args, **kwargs)
        serial.append(1)
        return value | {"stop_context": {"program_counter": len(serial)}}

    monkeypatch.setattr(windows_program, "replay", changing_diagnostic)
    assert compare(image, image, [{}])["passed"]


def test_preflight_diagnostic_stays_protected(store, tmp_path):
    image = compile_source(
        tmp_path, "int ha_main(void){VirtualAlloc(0,4096,0x3000,64);return 0;}"
    )
    (tmp_path / "original.exe").write_bytes(image)
    (tmp_path / "build.json").write_text(json.dumps({"sources": ["main.c"]}))
    task = store.create_project("Windows diagnostic", "Recover a bounded target")
    artifacts = Artifacts(store)
    context = SimpleNamespace(
        jobs=Jobs(), config={"foundations": {"c_compiler": compiler()}}, cancel=None
    )
    spec = {
        "scope": "windows_program",
        "original_path": "original.exe",
        "manifest_path": "build.json",
        "cases": [{"input_hex": ""}, {"input_hex": "616263"}],
    }
    with pytest.raises(Blocked, match="protected diagnostic") as error:
        WindowsAcceptance().prepare(
            tmp_path, spec, artifacts, task["project_id"], context
        )
    key = str(error.value).split(": ")[-1]
    detail = json.loads(artifacts.read(key, "evaluator", task["project_id"]))
    assert detail["stop_context"]["api"]["name"] == "kernel32.VirtualAlloc"
    with pytest.raises(Blocked, match="Protected"):
        artifacts.read(key, "worker", task["project_id"])
