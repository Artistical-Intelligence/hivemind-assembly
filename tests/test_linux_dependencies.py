import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from hivemind_assembly.core.artifacts import Artifacts
from hivemind_assembly.core.common import Blocked, ContractError
from hivemind_assembly.core.jobs import Jobs
from hivemind_assembly.domains.reverse_engineering import (
    program,
    platform_runtime,
    linux_dependencies,
)
from hivemind_assembly.domains.reverse_engineering.program_acceptance import (
    ProgramAcceptance,
)

LOADER = Path(os.environ.get("HA_TEST_ELF_INTERPRETER", "/lib64/ld-linux-x86-64.so.2"))
pytestmark = pytest.mark.skipif(
    not shutil.which("gcc") or not LOADER.is_file(),
    reason="GCC and Linux ELF interpreter required",
)
MAIN = "extern unsigned mix(unsigned);int ha_main(void){unsigned char b[8];long n=ha_read(b,8);for(long i=0;i<n;i++)b[i]=mix(b[i]);ha_write(b,n);return 0;}"
HELPER = (
    "unsigned bias=17;unsigned *p=&bias;unsigned mix(unsigned x){return (x*3+*p)%251;}"
)


@pytest.fixture
def dynamic(tmp_path):
    source, build = tmp_path / "source", tmp_path / "native"
    source.mkdir()
    build.mkdir()
    (source / "main.c").write_text(MAIN)
    (source / "helper.c").write_text(HELPER)
    (build / "main.c").write_text(program.HEADER + MAIN)
    (build / "runtime.c").write_text(program.RUNTIME)
    subprocess.run(
        [
            "gcc",
            "-O2",
            "-shared",
            "-fPIC",
            "-ffreestanding",
            "-fno-stack-protector",
            "-nostdlib",
            str(source / "helper.c"),
            "-Wl,-soname,libfixture.so",
            "-o",
            str(build / "libfixture.so"),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "gcc",
            "-O2",
            "-ffreestanding",
            "-fno-builtin",
            "-fno-stack-protector",
            "-nostdlib",
            "-no-pie",
            str(build / "main.c"),
            str(build / "runtime.c"),
            "-L" + str(build),
            "-lfixture",
            "-Wl,--build-id=none,-e,_start,-rpath,/lib",
            "-o",
            str(build / "original"),
        ],
        check=True,
        capture_output=True,
    )
    original = (build / "original").read_bytes()
    interpreter = linux_dependencies.inspect(original)["interpreter"]
    dependencies = {
        interpreter: LOADER.read_bytes(),
        "/lib/libfixture.so": (build / "libfixture.so").read_bytes(),
    }
    manifest = {"sources": ["main.c", "helper.c"]}
    rebuilt = program.build(source, manifest, Jobs(), compiler="gcc")
    assert rebuilt["passed"], rebuilt
    return (
        source,
        build,
        original,
        dependencies,
        manifest,
        bytes.fromhex(rebuilt["elf_hex"]),
    )


def test_dynamic_loading_native_oracle_and_static_reconstruction(dynamic):
    source, build, original, dependencies, manifest, candidate = dynamic
    for data in (b"", b"abc", bytes(range(8))):
        native = subprocess.run(
            [str(build / "original")],
            env={"LD_LIBRARY_PATH": str(build)},
            input=data,
            capture_output=True,
            timeout=5,
        )
        expected = bytes((x * 3 + 17) % 251 for x in data)
        assert native.returncode == 0 and native.stdout == expected
        result = platform_runtime.replay(
            original, data, dependencies=dependencies, clock_ns=123
        )
        assert result["status"] == "completed" and result["loader_completed"], result
        assert bytes.fromhex(result["stdout_hex"]) == native.stdout
        assert result["files"] == {} and result["input_consumed"] == len(data)
        assert any(
            e["call"] == "cpu_clock" and e["value"] == 123
            for e in result["loader_events"]
        )
        assert all(e["call"] in ("read", "write", "exit") for e in result["events"])
    cases = [
        {"runtime": "qiling_linux", "input_hex": value.hex()} for value in (b"", b"abc")
    ]
    assert program.compare(original, candidate, cases, dependencies=dependencies)[
        "passed"
    ]
    (source / "helper.c").write_text(HELPER.replace("bias=17", "bias=18"))
    wrong = program.build(source, manifest, Jobs(), compiler="gcc")
    assert not program.compare(
        original, bytes.fromhex(wrong["elf_hex"]), cases, dependencies=dependencies
    )["passed"]


def test_missing_dependencies_and_startup_budget_do_not_reach_application(dynamic):
    source, build, original, dependencies, manifest, candidate = dynamic
    with pytest.raises(Blocked, match="interpreter"):
        platform_runtime.replay(original)
    with pytest.raises(Blocked, match="library"):
        platform_runtime.replay(
            original,
            dependencies={
                k: v for k, v in dependencies.items() if k != "/lib/libfixture.so"
            },
        )
    with pytest.raises(ContractError, match="replace"):
        platform_runtime.replay(
            original, dependencies=dependencies, files={"/lib/libfixture.so": "00"}
        )
    result = platform_runtime.replay(
        original, b"abc", dependencies=dependencies, max_instructions=30
    )
    assert result["status"] == "budget_exhausted" and not result["loader_completed"]
    assert result["input_consumed"] == 0 and result["events"] == []


def test_constructor_io_stops_before_application(dynamic):
    source, build, original, dependencies, manifest, candidate = dynamic
    constructor = """__attribute__((constructor)) void init(void){long r;__asm__ volatile("syscall":"=a"(r):"a"(1L),"D"(1L),"S"("unexpected"),"d"(10L):"rcx","r11","memory");}"""
    (build / "constructor.c").write_text(HELPER + constructor)
    subprocess.run(
        [
            "gcc",
            "-shared",
            "-fPIC",
            "-ffreestanding",
            "-fno-stack-protector",
            "-nostdlib",
            str(build / "constructor.c"),
            "-Wl,-soname,libfixture.so",
            "-o",
            str(build / "constructor.so"),
        ],
        check=True,
        capture_output=True,
    )
    dependencies["/lib/libfixture.so"] = (build / "constructor.so").read_bytes()
    result = platform_runtime.replay(original, b"abc", dependencies=dependencies)
    assert (
        result["status"] == "unsupported_loader_effect"
        and not result["loader_completed"]
    )
    assert result["stdout_hex"] == "" and result["input_consumed"] == 0


def test_dependencies_are_readonly_and_pinned_for_acceptance(dynamic, store):
    source, build, original, dependencies, manifest, candidate = dynamic
    (source / "original.elf").write_bytes(original)
    (source / "build.json").write_text(json.dumps(manifest))
    paths = {}
    for i, (name, value) in enumerate(dependencies.items()):
        path = f"dependency-{i}.elf"
        (source / path).write_bytes(value)
        paths[name] = path
    artifacts = Artifacts(store)
    task = store.create_project("Linked program", "Recover shared-library transform")
    context = SimpleNamespace(
        jobs=Jobs(), config={"foundations": {"c_compiler": "gcc"}}, cancel=None
    )
    service = ProgramAcceptance()
    spec = {
        "scope": "x86_64_linux_program",
        "original_path": "original.elf",
        "manifest_path": "build.json",
        "original_dependencies": paths,
        "cases": [{"runtime": "qiling_linux", "input_hex": v} for v in ("", "616263")],
    }
    contract = service.prepare(source, spec, artifacts, task["project_id"], context)
    for path in paths.values():
        (source / path).write_bytes(b"wrong replacement")
    assert service.verify(source, contract, artifacts, task["project_id"], context)[
        "passed"
    ]
    (source / "main.c").write_text(
        'int ha_main(void){return (int)ha_open("/lib/libfixture.so",1,0);}'
    )
    write = program.build(source, {"sources": ["main.c"]}, Jobs(), compiler="gcc")
    assert (
        platform_runtime.replay(
            bytes.fromhex(write["elf_hex"]), dependencies=dependencies
        )["status"]
        == "readonly_dependency"
    )


def test_libc_program_against_native_and_explicit_observable_contract(tmp_path):
    libc = Path(os.environ.get("HA_TEST_LIBC", "/lib/x86_64-linux-gnu/libc.so.6"))
    if not libc.is_file():
        pytest.skip("Native glibc fixture unavailable")
    (tmp_path / "stdio.c").write_text(
        '#include <stdio.h>\nint main(int n,char **a){printf("result:%s\\n",n>1?a[1]:"empty");return 0;}'
    )
    executable = tmp_path / "stdio"
    subprocess.run(
        ["gcc", str(tmp_path / "stdio.c"), "-o", str(executable)],
        check=True,
        capture_output=True,
    )
    original = executable.read_bytes()
    dependencies = {
        linux_dependencies.inspect(original)["interpreter"]: LOADER.read_bytes(),
        "/lib/libc.so.6": libc.read_bytes(),
    }
    (tmp_path / "recovered.c").write_text(
        'int ha_main(void){const char *s=ha_argc()>1?ha_argv(1):"empty";long n=0;while(s[n])n++;ha_write("result:",7);ha_write(s,n);ha_write("\\n",1);return 0;}'
    )
    built = program.build(
        tmp_path, {"sources": ["recovered.c"]}, Jobs(), compiler="gcc"
    )
    assert built["passed"]
    candidate = bytes.fromhex(built["elf_hex"])
    case = {
        "runtime": "qiling_linux",
        "argv": ["program", "hello"],
        "env": {"LD_LIBRARY_PATH": "/lib"},
        "random_hex": "00" * 64,
    }
    native = subprocess.run(
        case["argv"], executable=str(executable), capture_output=True, timeout=5
    )
    observed = platform_runtime.replay(
        original,
        argv=case["argv"],
        env=case["env"],
        random_hex=case["random_hex"],
        dependencies=dependencies,
    )
    assert (
        observed["status"] == "completed" and observed["exit_code"] == native.returncode
    )
    assert bytes.fromhex(observed["stdout_hex"]) == native.stdout == b"result:hello\n"
    strict = program.compare(original, candidate, [case], dependencies=dependencies)
    assert (
        not strict["passed"] and "external_effects" in strict["cases"][0]["differences"]
    )
    assert program.compare(
        original,
        candidate,
        [{**case, "effect_policy": "observable"}],
        dependencies=dependencies,
    )["passed"]
    (tmp_path / "recovered.c").write_text(
        'int ha_main(void){ha_write("wrong",5);return 0;}'
    )
    wrong = program.build(
        tmp_path, {"sources": ["recovered.c"]}, Jobs(), compiler="gcc"
    )
    assert not program.compare(
        original,
        bytes.fromhex(wrong["elf_hex"]),
        [{**case, "effect_policy": "observable"}],
        dependencies=dependencies,
    )["passed"]


def test_empty_path_stat_uses_explicit_flags_and_current_directory(tmp_path):
    from qiling.const import QL_ARCH, QL_OS, QL_ENDIAN
    from hivemind_assembly.domains.reverse_engineering.linux_abi import LinuxABI

    returns, writes = [], []
    ql = SimpleNamespace(
        os=SimpleNamespace(
            type=QL_OS.LINUX, fd=[None] * 3, set_syscall_return=returns.append
        ),
        arch=SimpleNamespace(type=QL_ARCH.X8664, bits=64, endian=QL_ENDIAN.EL),
        mem=SimpleNamespace(
            write=lambda address, value: writes.append((address, value))
        ),
    )
    abi = LinuxABI(ql, tmp_path, 0, lambda *a: True)
    abi.stat(262, [0xFFFFFF9C, 0, 0x1000, 0], tmp_path, empty_path=True)
    assert returns[-1] == -2 and not writes
    abi.stat(262, [0xFFFFFF9C, 0, 0x1000, 0x1000], tmp_path, empty_path=True)
    assert returns[-1] == 0 and writes[-1][0] == 0x1000
    assert int.from_bytes(writes[-1][1][24:28], "little") == 0o40755
