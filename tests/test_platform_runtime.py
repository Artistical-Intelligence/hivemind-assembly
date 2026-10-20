import subprocess
from pathlib import Path
from hivemind_assembly.core.jobs import Jobs
from hivemind_assembly.domains.reverse_engineering.program import build, compare
from hivemind_assembly.domains.reverse_engineering.platform_runtime import replay


def image(root, source, optimization="O2"):
    root.mkdir(exist_ok=True)
    (root / "main.c").write_text(source)
    result = build(
        root,
        {"sources": ["main.c"], "optimization": optimization},
        Jobs(),
        compiler="gcc",
    )
    assert result["passed"], result
    return bytes.fromhex(result["elf_hex"])


def test_upstream_runtime_files_memory_and_native_oracle(tmp_path):
    code = """int ha_main(void){char *b=ha_map(4096); long f=ha_open("input.bin",0,0); if(f<0)return 9;long n=ha_file_read(f,b,32);ha_close(f);for(long i=0;i<n;i++)b[i]^=13;f=ha_open("output.bin",577,384);ha_file_write(f,b,n);ha_close(f);ha_write(b,n);ha_unmap(b,4096);return 0;}"""
    binary = image(tmp_path, code)
    source = b"upstream-runtime"
    actual = replay(binary, files={"/input.bin": source.hex()})
    assert actual["status"] == "completed", actual
    expected = bytes(x ^ 13 for x in source)
    assert bytes.fromhex(actual["stdout_hex"]) == expected
    assert bytes.fromhex(actual["files"]["/output.bin"]) == expected
    # Independently execute only this known generated fixture, never user images.
    exe = tmp_path / "fixture"
    exe.write_bytes(binary)
    exe.chmod(0o700)
    (tmp_path / "input.bin").write_bytes(source)
    reference = subprocess.run([str(exe)], cwd=tmp_path, capture_output=True, timeout=5)
    assert reference.returncode == 0 and reference.stdout == expected
    assert (tmp_path / "output.bin").read_bytes() == expected
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


def test_host_files_are_not_exposed_and_unknown_effects_stop(tmp_path):
    binary = image(
        tmp_path,
        'int ha_main(void){char a[16];long f=ha_open("/etc/passwd",0,0);return f<0?0:7;}',
    )
    assert replay(binary)["exit_code"] == 0
    guarded = image(tmp_path, 'int ha_main(void){return ha_open("/.ha/program",0,0);}')
    assert replay(guarded)["status"] == "filesystem_boundary"
    huge = image(tmp_path, "int ha_main(void){ha_map(100000000);return 0;}")
    assert replay(huge)["status"] == "memory_limit"


def test_guest_cannot_write_into_read_only_image_through_syscalls(tmp_path):
    binary = image(tmp_path, "int ha_main(void){return ha_read((void*)ha_main,1);}")
    result = replay(binary, b"X")
    assert result["status"] == "invalid_buffer_memory"
    assert result["input_consumed"] == 0
