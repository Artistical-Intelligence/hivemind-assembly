import io
import os
import random
import shutil
import struct
import subprocess

import pytest

from hivemind_assembly.core.common import Blocked, ContractError
from hivemind_assembly.core.jobs import Jobs
from hivemind_assembly.domains.reverse_engineering import call_images as calls
from hivemind_assembly.domains.reverse_engineering.acceptance import AcceptanceSuite
from hivemind_assembly.domains.reverse_engineering.call_acceptance import CallAcceptance
from hivemind_assembly.domains.reverse_engineering.program import load_image
from hivemind_assembly.domains.reverse_engineering.workflows import function_call

CLANG = os.environ.get("HA_TEST_CLANG") or shutil.which("clang")
pytestmark = pytest.mark.skipif(not CLANG, reason="Clang required; set HA_TEST_CLANG")


def assembly(tmp_path, source):
    """Assemble source-known instructions; no target code executes on the host."""
    from elftools.elf.elffile import ELFFile

    path = tmp_path / "fixture.s"
    path.write_text(".text\n" + source + "\n", encoding="utf-8")
    obj = tmp_path / "fixture.o"
    subprocess.run(
        [CLANG, "--target=aarch64-linux-gnu", "-c", str(path), "-o", str(obj)],
        check=True,
        capture_output=True,
    )
    return (
        ELFFile(io.BytesIO(obj.read_bytes())).get_section_by_name(".text").data().hex()
    )


def run(tmp_path, source, case=None):
    return function_call(
        {
            "machine_hex": assembly(tmp_path, source),
            "abi": "aapcs64",
            "case": case or {},
        }
    )


@pytest.mark.parametrize("optimization", ["O0", "O2"])
def test_sixteen_integer_arguments_and_stack_alignment(tmp_path, optimization):
    args = ["unsigned long long a" + str(i) for i in range(16)]
    expression = "+".join(f"a{i}*{i+1}ull" for i in range(16))
    (tmp_path / "f.c").write_text(
        f"unsigned long long f({','.join(args)}){{return {expression};}}"
    )
    manifest = {"sources": ["f.c"], "optimization": optimization}
    images = []
    for abi in calls.ABIS:
        built = calls.build(tmp_path, manifest, "f", abi, Jobs(), CLANG)
        assert built["passed"], built
        images.append(calls.load(bytes.fromhex(built["image_hex"]), symbol="f"))
    rng = random.Random(8192)
    vectors = [[0] * 16, [2**64 - 1] * 16, [1 << i for i in range(16)]]
    vectors += [[rng.getrandbits(64) for _ in range(16)] for _ in range(12)]
    for values in vectors:
        expected = sum(v * (i + 1) for i, v in enumerate(values)) % 2**64
        for image in images:
            result = calls.execute(image, {"arguments": values})
            assert result["status"] == "completed" and result["abi_ok"], result
            assert result["value"] == expected


@pytest.mark.parametrize(
    "body,abi_ok",
    [
        ("mov x19, #0\nret", False),
        ("mov x29, #0\nret", False),
        ("mov x18, #0\nret", False),
        ("movi v8.16b, #0\nret", False),
        # Only the lower half must be preserved; upper-half clobber is legitimate.
        ("mov x9, #0\nins v8.d[1], x9\nret", True),
        ("sub sp, sp, #16\nret", False),
        ("sub sp, sp, #16\nstr x30, [sp]\nldr x30, [sp]\nadd sp, sp, #16\nret", True),
    ],
)
def test_callee_preserved_registers_and_stack(tmp_path, body, abi_ok):
    result = run(tmp_path, body)
    assert result["status"] == "completed", result
    assert result["abi_ok"] is abi_ok


@pytest.mark.parametrize(
    "body",
    [
        "svc #0\nret",
        "hvc #0\nret",
        "brk #0\nret",
        "wfe\nret",
        "mrs x0, cntvct_el0\nret",
        "mrs x0, tpidr_el0\nret",
        "msr fpcr, x0\nret",
        ".inst 0xd503233f\nret",  # PACIASP
        ".inst 0xd65f0bff",  # RETAA
        "sub sp, sp, #8\nadd sp, sp, #8\nret",
    ],
)
def test_system_state_and_invalid_stack_never_pass(tmp_path, body):
    result = run(tmp_path, body)
    assert result["status"] == "unsupported", result
    assert result["fault"]


def test_instruction_budget_and_code_bounds(tmp_path):
    result = run(tmp_path, "again: b again", {"max_instructions": 8})
    assert result["status"] == "budget_exhausted" and result["instructions"] == 8
    # Branches within the mapped page but beyond the actual supplied code fail.
    result = run(tmp_path, "b .+128")
    assert result["status"] == "unsupported", result
    assert "declared function bytes" in result["fault"]["reason"]


def test_aarch64_loader_and_program_scope_remain_distinct(tmp_path):
    (tmp_path / "f.c").write_text("unsigned f(unsigned x){return x+7;}")
    built = calls.build(tmp_path, {"sources": ["f.c"]}, "f", "aapcs64", Jobs(), CLANG)
    assert built["passed"], built
    raw = bytes.fromhex(built["image_hex"])
    image = calls.load(raw, symbol="f")
    assert image["abi"] == "aapcs64"
    with pytest.raises(Blocked):
        load_image(raw)  # Existing x86 whole-program runtime never interprets ARM.
    with pytest.raises(ContractError, match="aligned"):
        calls.load(raw, address=image["entry"] + 1)
    broken = bytearray(raw)
    struct.pack_into("<H", broken, 18, 40)  # ARM32 is not AArch64.
    with pytest.raises(Blocked):
        calls.load(bytes(broken), symbol="f")
    broken = bytearray(raw)
    broken[5] = 2  # Big-endian unsupported.
    with pytest.raises(ContractError):
        calls.load(bytes(broken), symbol="f")
    assert isinstance(AcceptanceSuite().verifier("linked_calls"), CallAcceptance)
    assert isinstance(AcceptanceSuite().verifier("x86_64_linked_calls"), CallAcceptance)


def test_original_globals_are_readable_but_mutation_is_rejected(tmp_path):
    for source, expected_status in [
        (
            "const unsigned x[3]={1,7,31}; unsigned f(unsigned i){return x[i];}",
            "completed",
        ),
        ("unsigned x=7; unsigned f(unsigned i){return x+=i;}", "unsupported"),
    ]:
        (tmp_path / "f.c").write_text(source)
        built = calls.build(
            tmp_path, {"sources": ["f.c"]}, "f", "aapcs64", Jobs(), CLANG
        )
        assert built["passed"], built
        result = calls.execute(
            calls.load(bytes.fromhex(built["image_hex"]), symbol="f"),
            {"arguments": [1]},
        )
        assert result["status"] == expected_status, result
        if expected_status == "completed":
            assert result["value"] == 7


def test_offset_and_one_past_end_pointers(tmp_path):
    code = "ldr w2, [x0]\nadd w2, w2, w1\nstr w2, [x0]\nmov w0, w2\nret"
    case = {
        "arguments": [{"buffer": "b", "offset": 4}, 2],
        "output_bits": 32,
        "buffers": [{"id": "b", "hex": "efbeaddeffffffff"}],
    }
    result = run(tmp_path, code, case)
    assert result["status"] == "completed" and result["abi_ok"]
    assert result["buffers"] == {"b": "efbeadde01000000"}
    assert result["value"] == 1
    case["arguments"][0]["offset"] = 8
    result = run(tmp_path, code, case)
    assert result["status"] != "completed"


def test_windows_arm64_pe_identity_and_c_data_model(tmp_path):
    (tmp_path / "f.c").write_text("unsigned f(void){return sizeof(unsigned long);}")
    images = {}
    for abi in ("aapcs64", "winarm64"):
        built = calls.build(tmp_path, {"sources": ["f.c"]}, "f", abi, Jobs(), CLANG)
        assert built["passed"], built
        raw = bytes.fromhex(built["image_hex"])
        images[abi] = calls.load(raw, symbol="f")
        assert images[abi]["abi"] == abi
        result = calls.execute(images[abi], {"output_bits": 32})
        assert result["status"] == "completed" and result["abi_ok"]
        assert result["value"] == (4 if abi == "winarm64" else 8)
    # Correct ABI handling exposes LP64/LLP64 differences rather than treating
    # the same C spelling as equivalent across platforms.
    assert not calls.compare(images["aapcs64"], images["winarm64"], [{}])["passed"]
    assert raw[:2] == b"MZ"
    header = struct.unpack_from("<I", raw, 0x3C)[0]
    for hybrid in (0xA641, 0xA64E):
        changed = bytearray(raw)
        struct.pack_into("<H", changed, header + 4, hybrid)
        with pytest.raises(Blocked, match="ARM64EC"):
            calls.load(bytes(changed), symbol="f")
