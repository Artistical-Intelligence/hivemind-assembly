"""Real guest stop locations, independent image offsets, and cancellation."""

import hashlib
import io
import json
import os
import shutil
import threading
from types import SimpleNamespace

import pefile
import pytest
from elftools.elf.elffile import ELFFile

from hivemind_assembly.core.artifacts import Artifacts
from hivemind_assembly.core.common import Blocked
from hivemind_assembly.core.jobs import Jobs
from hivemind_assembly.domains.reverse_engineering import program, call_images as calls
from hivemind_assembly.domains.reverse_engineering import pe_dependencies
from hivemind_assembly.domains.reverse_engineering.program_acceptance import (
    ProgramAcceptance,
)
from hivemind_assembly.domains.reverse_engineering.call_acceptance import CallAcceptance
import test_pe_dependencies

dlls = test_pe_dependencies.dlls

CLANG = os.environ.get("HA_TEST_CLANG") or shutil.which("clang")
pytestmark = pytest.mark.skipif(not CLANG, reason="Clang required; set HA_TEST_CLANG")


def compiled(root, body, lane):
    (root / "main.c").write_text(body)
    manifest = {"sources": ["main.c"]}
    if lane in ("x86_64", "aarch64"):
        manifest["architecture"] = lane
        built = program.build(root, manifest, Jobs(), CLANG)
        key = "elf_hex"
    else:
        built = calls.build(root, manifest, "f", lane, Jobs(), CLANG)
        key = "image_hex"
    assert built["passed"], built
    return bytes.fromhex(built[key])


def check_location(raw, context):
    pc = context["program_counter"]
    if raw.startswith(b"MZ"):
        pe = pefile.PE(data=raw)
        try:
            offset = pe.get_offset_from_rva(pc - pe.OPTIONAL_HEADER.ImageBase)
        finally:
            pe.close()
    else:
        elf = ELFFile(io.BytesIO(raw))
        segment = next(
            s
            for s in elf.iter_segments()
            if s["p_type"] == "PT_LOAD"
            and s["p_vaddr"] <= pc < s["p_vaddr"] + s["p_filesz"]
        )
        offset = segment["p_offset"] + pc - segment["p_vaddr"]
    observed = bytes.fromhex(context["instruction_hex"])
    assert observed
    assert context["image_file_offset"] == offset
    assert (
        context["image_instruction_hex"] == raw[offset : offset + len(observed)].hex()
    )
    assert context["instruction_hex"] == context["image_instruction_hex"]
    assert context["image_sha256"] == hashlib.sha256(raw).hexdigest()
    assert "x" in context["mapping"]["permissions"]
    assert len(json.dumps(context)) < 4096


@pytest.mark.parametrize("arch", ["x86_64", "aarch64"])
@pytest.mark.parametrize(
    "body,status",
    [
        ('ha_write("X",1);return *(volatile int*)1;', "fault"),
        ('ha_open("missing",0,0);return 0;', "unsupported_syscall"),
        ("for(;;){}", "budget_exhausted"),
    ],
)
def test_static_failure_location_and_syscall(tmp_path, arch, body, status):
    raw = compiled(tmp_path, "int ha_main(void){" + body + "}", arch)
    result = program.replay(raw, max_instructions=1000)
    assert result["status"] == status, result
    context = result["stop_context"]
    check_location(raw, context)
    assert str(tmp_path) not in json.dumps(context)
    if status == "budget_exhausted":
        assert context["stop_reason"] == "instruction_limit"
    elif status == "fault":
        assert context["memory_access"] == {"access": "read", "address": 1, "size": 4}
        assert "syscall" not in context  # Prior successful write is no longer active.
    else:
        assert context["syscall"]["name"] == "unsupported"
        assert context["syscall"]["number"] == (2 if arch == "x86_64" else 56)


class CancelAfterBoundary:
    def __init__(self):
        self.calls = 0

    def is_set(self):
        self.calls += 1
        return self.calls >= 3


@pytest.mark.parametrize("lane", ["x86_64", "aarch64", *calls.ABIS])
def test_success_precancel_and_midrun_cancel(tmp_path, lane):
    is_program = lane in ("x86_64", "aarch64")
    head = "int ha_main(void)" if is_program else "unsigned f(void)"
    raw = compiled(tmp_path, head + "{return 0;}", lane)
    invoke = (
        (lambda **kw: program.replay(raw, **kw))
        if is_program
        else (lambda **kw: calls.execute(calls.load(raw, symbol="f"), {}, **kw))
    )
    assert invoke()["stop_context"] is None
    cancelled = threading.Event()
    cancelled.set()
    result = invoke(cancel=cancelled)
    assert result["status"] == "cancelled" and result["instructions"] == 0
    assert result["stop_context"] == {
        "phase": "initialization",
        "stop_reason": "cancelled",
    }
    raw = compiled(tmp_path, head + "{for(;;){}}", lane)
    result = invoke(cancel=CancelAfterBoundary())
    assert result["status"] == "cancelled" and result["instructions"] == 1024, result
    assert result["stop_context"]["stop_reason"] == "cancelled"
    check_location(raw, result["stop_context"])


@pytest.mark.parametrize("lane", ["x86_64", "aarch64", *calls.ABIS])
def test_actual_engine_timeout_distinct_from_instruction_bound(
    tmp_path, lane, monkeypatch
):
    import unicorn

    actual = unicorn.Uc.emu_start

    def bounded(self, begin, until, timeout=0, count=0):
        return actual(self, begin, until, timeout=20_000, count=count)

    monkeypatch.setattr(unicorn.Uc, "emu_start", bounded)
    is_program = lane in ("x86_64", "aarch64")
    raw = compiled(
        tmp_path,
        ("int ha_main(void)" if is_program else "unsigned f(void)") + "{for(;;){}}",
        lane,
    )
    if is_program:
        result = program.replay(raw, max_instructions=5_000_000)
    else:
        result = calls.execute(
            calls.load(raw, symbol="f"), {"max_instructions": 1_000_000}
        )
    assert result["status"] == "budget_exhausted", result
    assert result["stop_context"]["stop_reason"] == "wall_clock_limit", result
    assert result["instructions"] < 1_000_000


@pytest.mark.parametrize("abi", calls.ABIS)
def test_linked_fault_and_caller_buffer_location(tmp_path, abi):
    raw = compiled(tmp_path, "unsigned f(unsigned *p){*p=7;return 0;}", abi)
    image = calls.load(raw, symbol="f")
    for size, permission in [(4, "r"), (1, "rw")]:
        result = calls.execute(
            image,
            {
                "arguments": [{"buffer": "output"}],
                "buffers": [
                    {
                        "id": "output",
                        "hex": bytes(size).hex(),
                        "permissions": permission,
                    }
                ],
            },
        )
        assert result["status"] in ("fault", "unsupported"), result
        context = result["stop_context"]
        check_location(raw, context)
        assert context["memory_access"] == {
            "access": "write",
            "address": calls.BUFFERS,
            "size": 4,
            "buffer": "output",
            "buffer_offset": 0,
            "buffer_size": size,
            "within_bounds": size == 4,
        }
    raw = compiled(tmp_path, "unsigned f(void){return *(volatile unsigned*)1;}", abi)
    result = calls.execute(calls.load(raw, symbol="f"), {})
    assert result["status"] == "fault", result
    check_location(raw, result["stop_context"])
    assert result["stop_context"]["memory_access"]["address"] == 1


@pytest.mark.parametrize("abi", calls.ABIS)
def test_abi_violation_identifies_register(abi):
    arm = abi in calls.ARM_ABIS
    code = "130080d2000080d2c0035fd6" if arm else "31db31c0c3"
    image = {
        "abi": abi,
        "entry": 0x10000,
        "segments": [
            {
                "address": 0x10000,
                "size": len(bytes.fromhex(code)),
                "hex": code,
                "permissions": "rx",
            }
        ],
    }
    result = calls.execute(image, {})
    assert result["status"] == "completed" and not result["abi_ok"]
    context = result["stop_context"]
    assert context["stop_reason"] == "abi_violation"
    assert [v["register"] for v in context["abi_violations"]] == [
        "X19" if arm else "RBX"
    ]
    assert context["abi_violations"][0]["actual"] == 0
    assert context["abi_violations"][0]["expected"] != 0


@pytest.mark.parametrize("linked", [False, True])
def test_sealed_original_preflight_diagnostic_is_protected(tmp_path, store, linked):
    lane = "winarm64" if linked else "aarch64"
    body = (
        "unsigned f(void)" if linked else "int ha_main(void)"
    ) + "{return *(volatile int*)1;}"
    raw = compiled(tmp_path, body, lane)
    (tmp_path / "original.bin").write_bytes(raw)
    (tmp_path / "build.json").write_text(json.dumps({"sources": ["main.c"]}))
    project = store.create_project("diagnostic", "reconstruct")["project_id"]
    artifacts = Artifacts(store)
    context = SimpleNamespace(
        jobs=Jobs(),
        config={"foundations": {"c_compiler": CLANG}},
        cancel=threading.Event(),
    )
    spec = {
        "scope": "linked_calls" if linked else "linux_program",
        "original_path": "original.bin",
        "manifest_path": "build.json",
        "cases": [{}, {}],
    }
    if linked:
        spec.update(original_symbol="f", function="f", candidate_abi="winarm64")
    verifier = CallAcceptance() if linked else ProgramAcceptance()
    with pytest.raises(Blocked, match="protected diagnostic") as error:
        verifier.prepare(tmp_path, spec, artifacts, project, context)
    key = str(error.value).split(": ")[-1]
    detail = json.loads(artifacts.read(key, "evaluator", project))
    check_location(raw, detail["stop_context"])
    with pytest.raises(Blocked, match="Protected"):
        artifacts.read(key, "worker", project)


def test_relocated_dependency_names_its_own_image(dlls):
    root, dependencies = dlls
    helper = dependencies["helper.dll"]
    pe = pefile.PE(data=helper)
    export = pe.DIRECTORY_ENTRY_EXPORT.symbols[0]
    offset = pe.get_offset_from_rva(export.address)
    arm = pe.FILE_HEADER.Machine == 0xAA64
    code = bytes.fromhex("200080d2000040b9c0035fd6" if arm else "488b042501000000c3")
    raw = bytearray(helper)
    raw[offset : offset + len(code)] = code
    helper = bytes(raw)
    original_base = pe.OPTIONAL_HEADER.ImageBase
    image = pe_dependencies.load(root, "recovered", dependencies={"helper.dll": helper})
    result = calls.execute(image, {"arguments": [1]})
    assert result["status"] == "fault", result
    context = result["stop_context"]
    assert context["image"] == "helper.dll"
    assert context["image_base"] != original_base == context["original_image_base"]
    assert context["source_image_sha256"] == hashlib.sha256(helper).hexdigest()
    assert context["instruction_hex"] == context["image_instruction_hex"]
    n = len(bytes.fromhex(context["instruction_hex"]))
    assert (
        helper[context["image_file_offset"] : context["image_file_offset"] + n].hex()
        == context["instruction_hex"]
    )


def test_diagnostics_do_not_participate_in_comparisons(tmp_path, monkeypatch):
    raw = compiled(tmp_path, "unsigned f(void){return 7;}", "sysv")
    image = calls.load(raw, symbol="f")
    actual = calls.execute
    count = []

    def annotated(*args, **kwargs):
        result = actual(*args, **kwargs)
        count.append(1)
        return result | {"stop_context": {"program_counter": len(count)}}

    monkeypatch.setattr(calls, "execute", annotated)
    assert calls.compare(image, image, [{}])["passed"]
    raw = compiled(tmp_path, "int ha_main(void){return 0;}", "x86_64")
    replay = program.replay

    def annotated_program(*args, **kwargs):
        result = replay(*args, **kwargs)
        count.append(1)
        return result | {"stop_context": {"program_counter": len(count)}}

    monkeypatch.setattr(program, "replay", annotated_program)
    assert program.compare(raw, raw, [{}])["passed"]
