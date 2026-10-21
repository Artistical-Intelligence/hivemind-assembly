import subprocess
import os
import shutil
import pytest
from native_fixtures import elf_compiler, LINUX_ORACLE
from hivemind_assembly.core.jobs import Jobs
from hivemind_assembly.domains.reverse_engineering.program import build, compare
from hivemind_assembly.domains.reverse_engineering.platform_runtime import replay


def _image(root, source, optimization="O2", architecture="x86_64"):
    compiler = (os.environ.get("HA_TEST_CLANG") or shutil.which("clang")) if architecture == "aarch64" else elf_compiler()
    if not compiler:
        pytest.skip("Clang and LLD required for AArch64")
    root.mkdir(exist_ok=True)
    (root / "main.c").write_text(source)
    result = build(
        root,
        {"sources": ["main.c"], "optimization": optimization, "architecture": architecture},
        Jobs(),
        compiler=compiler,
    )
    assert result["passed"], result
    return bytes.fromhex(result["elf_hex"])


@pytest.fixture(params=["x86_64", "aarch64"])
def image(request):
    return lambda root, source, optimization="O2": _image(root, source, optimization, request.param)


def test_upstream_runtime_files_memory_and_native_oracle(tmp_path, image):
    code = """int ha_main(void){char *b=ha_map(4096); long f=ha_open("input.bin",0,0); if(f<0)return 9;long n=ha_file_read(f,b,32);ha_close(f);for(long i=0;i<n;i++)b[i]^=13;f=ha_open("output.bin",577,384);ha_file_write(f,b,n);ha_close(f);ha_write(b,n);ha_unmap(b,4096);return 0;}"""
    binary = image(tmp_path, code)
    source = b"upstream-runtime"
    actual = replay(binary, files={"/input.bin": source.hex()})
    assert actual["status"] == "completed", actual
    expected = bytes(x ^ 13 for x in source)
    assert bytes.fromhex(actual["stdout_hex"]) == expected
    assert bytes.fromhex(actual["files"]["/output.bin"]) == expected
    other = image(tmp_path, code, "O0")
    assert compare(
        binary,
        other,
        [{"runtime": "qiling_linux", "files": {"/input.bin": source.hex()}}],
    )["passed"]
    wrong = image(tmp_path, code.replace("^=13", "^=12"))
    assert not compare(
        binary,
        wrong,
        [{"runtime": "qiling_linux", "files": {"/input.bin": source.hex()}}],
    )["passed"]


def test_host_files_are_not_exposed_and_unknown_effects_stop(tmp_path, image):
    binary = image(
        tmp_path,
        'int ha_main(void){char a[16];long f=ha_open("/etc/passwd",0,0);return f<0?0:7;}',
    )
    assert replay(binary)["exit_code"] == 0
    guarded = image(tmp_path, 'int ha_main(void){return ha_open("/.ha/program",0,0);}')
    assert replay(guarded)["status"] == "filesystem_boundary"
    huge = image(tmp_path, "int ha_main(void){ha_map(100000000);return 0;}")
    assert replay(huge)["status"] == "memory_limit"


def test_guest_cannot_write_into_read_only_image_through_syscalls(tmp_path, image):
    binary = image(tmp_path, "int ha_main(void){return ha_read((void*)ha_main,1);}")
    result = replay(binary, b"X")
    assert result["status"] == "invalid_buffer_memory"
    assert result["input_consumed"] == 0


def test_directory_effects_clock_and_random_are_observed(tmp_path, image):
    source = """int ha_main(void){unsigned char b[4];long s,n;if(ha_clock(1,&s,&n)||s!=2||n!=17)return 8;
    if(ha_random(b,4,0)!=4)return 9;ha_mkdir("out",448);long f=ha_open("temporary",577,384);
    ha_file_write(f,b,4);ha_close(f);ha_rename("temporary","out/data");ha_mkdir("gone",448);ha_rmdir("gone");return 0;}"""
    original = image(tmp_path, source)
    case = {
        "runtime": "qiling_linux",
        "random_hex": "01020304",
        "clock_ns": 2_000_000_017,
        "effect_policy": "observable",
    }
    result = replay(original, random_hex=case["random_hex"], clock_ns=case["clock_ns"])
    assert result["status"] == "completed" and result["exit_code"] == 0, result
    assert result["files"] == {"/out/data": "01020304"}
    assert result["directories"] == ["/out"]
    wrong = image(tmp_path, source.replace('ha_rmdir("gone")', "0"))
    compared = compare(original, wrong, [case])
    assert (
        not compared["passed"] and "directories" in compared["cases"][0]["differences"]
    )


def test_unclosed_guest_files_are_closed_before_root_cleanup(tmp_path, monkeypatch, image):
    from qiling.os.filestruct import ql_file

    closed = []
    original_close = ql_file.close

    def close(file):
        closed.append(str(file.name))
        return original_close(file)

    monkeypatch.setattr(ql_file, "close", close)
    binary = image(tmp_path, 'int ha_main(void){ha_open("input.bin",0,0);return 0;}')
    assert replay(binary, files={"/input.bin": "01"})["status"] == "completed"
    assert any(path.replace("\\", "/").endswith("/input.bin") for path in closed)


@LINUX_ORACLE
def test_file_io_native_linux_oracle(tmp_path):
    source = b"upstream-runtime"
    expected = bytes(x ^ 13 for x in source)
    binary = _image(
        tmp_path,
        'int ha_main(void){char b[32];long f=ha_open("input.bin",0,0);long n=ha_file_read(f,b,32);ha_close(f);for(long i=0;i<n;i++)b[i]^=13;f=ha_open("output.bin",577,384);ha_file_write(f,b,n);ha_close(f);ha_write(b,n);return 0;}',
    )
    # Independently execute only this known generated fixture, never user images.
    exe = tmp_path / "fixture"
    exe.write_bytes(binary)
    exe.chmod(0o700)
    (tmp_path / "input.bin").write_bytes(source)
    reference = subprocess.run([str(exe)], cwd=tmp_path, capture_output=True, timeout=5)
    assert reference.returncode == 0 and reference.stdout == expected
    assert (tmp_path / "output.bin").read_bytes() == expected
    arm = _image(tmp_path, (tmp_path / "main.c").read_text(), architecture="aarch64")
    observed = replay(arm, files={"/input.bin": source.hex()})
    assert observed["status"] == "completed", observed
    assert (observed["exit_code"], bytes.fromhex(observed["stdout_hex"]), bytes.fromhex(observed["stderr_hex"])) == (reference.returncode, reference.stdout, reference.stderr)
    assert bytes.fromhex(observed["files"]["/output.bin"]) == (tmp_path / "output.bin").read_bytes()


def test_cross_architecture_files_and_independent_expected_results(tmp_path):
    source = '''int ha_main(void){unsigned char *b=ha_map(4096);
    long f=ha_open("input",0,0),n=ha_file_read(f,b,256);ha_close(f);
    unsigned v=0;for(long i=0;i<n;i++){v=(v*3+b[i])%251;b[i]=v;}
    ha_mkdir("out",448);f=ha_open("temp",577,384);ha_file_write(f,b,n);
    ha_close(f);ha_rename("temp","out/result");ha_write(b,n);
    ha_mkdir("gone",448);ha_rmdir("gone");ha_unmap(b,4096);return 0;}'''
    original = _image(tmp_path, source, "O0", "aarch64")
    candidate = _image(tmp_path, source)
    cases = [{"runtime": "qiling_linux", "files": {"/input": data.hex()}, "effect_policy": "observable"}
             for data in (b"", bytes(range(256)), b"\xff" * 129)]
    compared = compare(original, candidate, cases)
    assert compared["passed"], compared
    for case in cases:
        expected, state = bytearray(), 0
        for value in bytes.fromhex(case["files"]["/input"]):
            state = (state * 3 + value) % 251
            expected.append(state)
        actual = replay(original, files=case["files"])
        assert actual["stdout_hex"] == expected.hex()
        assert actual["files"]["/out/result"] == expected.hex()
        assert actual["cpu_model"] == "cortex-a72"
    wrong = _image(tmp_path, source.replace("v*3", "v*2"))
    assert not compare(original, wrong, cases)["passed"]


@pytest.mark.parametrize("source,status", [
    ("mov x8, #999\nsvc #0", "unsupported_syscall"),
    ("mov x8, #93\nsvc #1", "unsupported_cpu_state"),
    ("mrs x0, cntvct_el0\nmov x8, #93\nsvc #0", "unsupported_cpu_state"),
    ("sub sp, sp, #8\nmov x8, #93\nsvc #0", "unsupported_cpu_state"),
    ("mov x0, #3\nmov x8, #34\nsvc #0", "unsupported_directory_fd"),
    ("mov x0, #-100\nmov x2, #1\nmov x8, #35\nsvc #0", "unsupported_unlink_flags"),
    ("b .", "budget_exhausted"),
    ("mov x0, #0\nldr x1, [x0]", "fault"),
])
def test_arm_qiling_rejects_unknown_effects(tmp_path, source, status):
    from test_arm64_program import assembly_elf, CLANG
    if not CLANG:
        pytest.skip("Clang and LLD required")
    actual = replay(assembly_elf(tmp_path, source), max_instructions=100)
    assert actual["status"] == status, actual
    assert actual["exit_code"] is None


def test_arm_qiling_cancellation_and_dependency_boundary(tmp_path):
    import threading
    from hivemind_assembly.core.common import ContractError
    binary = _image(tmp_path, 'int ha_main(void){for(;;){}return 0;}', architecture="aarch64")
    cancel = threading.Event()
    cancel.set()
    assert replay(binary, cancel=cancel)["status"] == "cancelled"
    with pytest.raises(ContractError, match="bounds"):
        replay(binary, dependencies={"/lib/unknown.so": b"not a library"})


def test_failed_replay_retains_guest_location_without_host_paths(tmp_path, image):
    import io
    import json
    from elftools.elf.elffile import ELFFile

    binary = image(tmp_path, 'int ha_main(void){return (int)ha_open("/proc/secret",0,0);}')
    result = replay(binary)
    assert result['status'] == 'filesystem_boundary'
    context = result['stop_context']
    assert context['phase'] == 'application' and context['image'] == 'program'
    assert context['syscall_number'] in (2, 56)
    assert context['instruction_hex'] in ('0f05', '010000d4')
    # Resolve the reported virtual address against the real ELF file, rather
    # than accepting a plausible-looking PC from the runtime itself.
    pc = context['image_virtual_address']
    elf = ELFFile(io.BytesIO(binary))
    segment = next(s for s in elf.iter_segments() if s['p_type'] == 'PT_LOAD' and s['p_vaddr'] <= pc < s['p_vaddr'] + s['p_filesz'])
    offset = segment['p_offset'] + pc - segment['p_vaddr']
    size = len(bytes.fromhex(context['instruction_hex']))
    assert binary[offset:offset+size].hex() == context['instruction_hex']
    assert 'x' in context['mapping']['permissions']
    assert 'ha-qiling-' not in json.dumps(context) and str(tmp_path) not in json.dumps(context)
    success = replay(image(tmp_path, 'int ha_main(void){return 0;}'))
    assert success['status'] == 'completed' and success['stop_context'] is None
