"""Actual upstream ARM64 loader, compiler output and protected reconstruction."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import tempfile
from types import SimpleNamespace

import pytest
from native_fixtures import elf_compiler, LINUX_ORACLE
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
from hivemind_assembly.domains.reverse_engineering.program_arm64 import SYSCALL_RUNTIME

CLANG = os.environ.get("HA_TEST_CLANG") or shutil.which("clang")
FIXTURES = Path(
    os.environ.get(
        "HA_TEST_ARM64_FIXTURE", str(Path(tempfile.gettempdir()) / "ha-arm64-fixture")
    )
)
MAIN = "extern unsigned mix(unsigned);int ha_main(void){unsigned char b[8];long n=ha_read(b,8);for(long i=0;i<n;i++)b[i]=mix(b[i]);ha_write(b,n);return 0;}"
HELPER = (
    "unsigned bias=17;unsigned *p=&bias;unsigned mix(unsigned x){return (x*3+*p)%251;}"
)


@pytest.fixture
def dynamic(tmp_path):
    if not CLANG or not (FIXTURES / "ld-linux-aarch64.so.1").is_file():
        pytest.skip("Clang/LLD and pinned ARM64 guest fixture required")
    source, build = tmp_path / "source", tmp_path / "build"
    source.mkdir()
    build.mkdir()
    common = [
        CLANG,
        "--target=aarch64-linux-gnu",
        "-fuse-ld=lld",
        "-march=armv8-a",
        "-ffixed-x18",
        "-O2",
        "-ffreestanding",
        "-fno-builtin",
        "-fno-stack-protector",
        "-nostdlib",
    ]

    def compile_image(helper=HELPER, main=MAIN):
        (source / "main.c").write_text(main)
        (source / "helper.c").write_text(helper)
        (build / "main.c").write_text(program.HEADER + main)
        (build / "runtime.c").write_text(
            program.HEADER + program.PROCESS_RUNTIME + SYSCALL_RUNTIME
        )
        subprocess.run(
            common
            + [
                "-shared",
                "-fPIC",
                str(source / "helper.c"),
                "-Wl,-soname,libfixture.so",
                "-o",
                str(build / "libfixture.so"),
            ],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            common
            + [
                "-fPIE",
                "-pie",
                str(build / "main.c"),
                str(build / "runtime.c"),
                "-L" + str(build),
                "-lfixture",
                "-Wl,--build-id=none,-e,_start,-rpath,/lib,--dynamic-linker=/lib/ld-linux-aarch64.so.1",
                "-o",
                str(build / "original"),
            ],
            check=True,
            capture_output=True,
        )
        return (build / "original").read_bytes(), {
            "/lib/ld-linux-aarch64.so.1": (
                FIXTURES / "ld-linux-aarch64.so.1"
            ).read_bytes(),
            "/lib/libfixture.so": (build / "libfixture.so").read_bytes(),
        }

    original, dependencies = compile_image()
    return SimpleNamespace(
        source=source,
        build=build,
        compile=compile_image,
        original=original,
        dependencies=dependencies,
    )


def candidate(dynamic, helper=HELPER):
    (dynamic.source / "helper.c").write_text(helper)
    built = program.build(
        dynamic.source, {"sources": ["main.c", "helper.c"]}, Jobs(), elf_compiler()
    )
    assert built["passed"], built
    return bytes.fromhex(built["elf_hex"])


def test_dynamic_arm_pie_and_cross_architecture_reconstruction(dynamic):
    rebuilt = candidate(dynamic)
    cases = [
        {"runtime": "qiling_linux", "input_hex": value.hex()}
        for value in (b"", b"abc", bytes(range(8)), b"\xff" * 8)
    ]
    for case in cases:
        data = bytes.fromhex(case["input_hex"])
        result = platform_runtime.replay(
            dynamic.original, data, dependencies=dynamic.dependencies
        )
        assert result["status"] == "completed" and result["loader_completed"], result
        assert bytes.fromhex(result["stdout_hex"]) == bytes(
            (x * 3 + 17) % 251 for x in data
        )
        assert result["input_consumed"] == len(data) and result["files"] == {}
        assert any(e["call"] == "thread_pointer" for e in result["loader_events"])
        assert all(e["call"] in ("read", "write", "exit") for e in result["events"])
    assert program.compare(
        dynamic.original, rebuilt, cases, dependencies=dynamic.dependencies
    )["passed"]
    wrong = candidate(dynamic, HELPER.replace("bias=17", "bias=18"))
    assert not program.compare(
        dynamic.original, wrong, cases, dependencies=dynamic.dependencies
    )["passed"]


@LINUX_ORACLE
def test_dynamic_arm_against_native_process(dynamic):
    executable = dynamic.build / "native-oracle"
    executable.write_bytes(candidate(dynamic))
    executable.chmod(0o700)
    for data in (b"", b"abc", bytes(range(8)), b"\xff" * 8):
        native = subprocess.run(
            [str(executable)], input=data, capture_output=True, timeout=5
        )
        result = platform_runtime.replay(
            dynamic.original, data, dependencies=dynamic.dependencies
        )
        assert result["status"] == "completed"
        assert (
            result["exit_code"],
            bytes.fromhex(result["stdout_hex"]),
            bytes.fromhex(result["stderr_hex"]),
        ) == (native.returncode, native.stdout, native.stderr)


def test_dynamic_arm_missing_mismatched_and_replaced_dependencies(dynamic):
    with pytest.raises(Blocked, match="interpreter"):
        platform_runtime.replay(dynamic.original)
    with pytest.raises(Blocked, match="library"):
        platform_runtime.replay(
            dynamic.original,
            dependencies={
                k: v
                for k, v in dynamic.dependencies.items()
                if k != "/lib/libfixture.so"
            },
        )
    with pytest.raises(Blocked, match="architecture"):
        platform_runtime.replay(
            dynamic.original,
            dependencies={**dynamic.dependencies, "/lib/wrong.so": candidate(dynamic)},
        )
    with pytest.raises(ContractError, match="replace"):
        platform_runtime.replay(
            dynamic.original,
            dependencies=dynamic.dependencies,
            files={"/lib/libfixture.so": "00"},
        )


def test_dynamic_arm_startup_budget_and_cancellation(dynamic):
    result = platform_runtime.replay(
        dynamic.original, b"abc", dependencies=dynamic.dependencies, max_instructions=30
    )
    assert result["status"] == "budget_exhausted" and not result["loader_completed"]
    assert result["input_consumed"] == 0 and result["events"] == []
    context = result["stop_context"]
    assert context["phase"] == "loader"
    assert context["image"] == "/lib/ld-linux-aarch64.so.1"
    assert context["image_offset"] >= 0
    assert "ha-qiling-" not in json.dumps(context)
    cancel = threading.Event()
    cancel.set()
    result = platform_runtime.replay(
        dynamic.original, b"abc", dependencies=dynamic.dependencies, cancel=cancel
    )
    assert result["status"] == "cancelled" and result["input_consumed"] == 0


def test_dynamic_arm_constructor_io_is_blocked(dynamic):
    constructor = """__attribute__((constructor)) void init(void){
        register long nr __asm__("x8")=64; register long fd __asm__("x0")=1;
        register const char *p __asm__("x1")="bad"; register long n __asm__("x2")=3;
        __asm__ volatile("svc #0":"+r"(fd):"r"(nr),"r"(p),"r"(n):"memory");
    }"""
    original, deps = dynamic.compile(HELPER + constructor)
    result = platform_runtime.replay(original, b"abc", dependencies=deps)
    assert (
        result["status"] == "unsupported_loader_effect"
        and not result["loader_completed"]
    ), result
    assert result["stdout_hex"] == "" and result["input_consumed"] == 0


@pytest.mark.parametrize(
    "instruction, status",
    [
        ("mrs x0, cntvct_el0", "unsupported_cpu_state"),
        ("dc zva, x0", "unsupported_cpu_state"),
        ("mov x0, #1; msr tpidr_el0, x0", "invalid_tls_memory"),
    ],
)
def test_dynamic_arm_unsupported_runtime_state(dynamic, instruction, status):
    main = (
        'extern unsigned mix(unsigned);int ha_main(void){__asm__ volatile("'
        + instruction
        + '":::"x0","memory");return (int)mix(0);}'
    )
    original, deps = dynamic.compile(main=main)
    result = platform_runtime.replay(original, dependencies=deps)
    assert result["status"] == status, result
    assert result["exit_code"] is None


@pytest.mark.parametrize("tls_model", ["initial-exec", "global-dynamic"])
def test_dynamic_arm_tls_and_capabilities(dynamic, tls_model):
    helper = """__thread unsigned bias __attribute__((tls_model("initial-exec")))=17;
    unsigned mix(unsigned x){return (x*3+bias++)%251;}"""
    original, deps = dynamic.compile(helper.replace("initial-exec", tls_model))
    result = platform_runtime.replay(original, b"abc", dependencies=deps)
    assert result["status"] == "completed", result
    assert bytes.fromhex(result["stdout_hex"]) == bytes(
        (x * 3 + 17 + i) % 251 for i, x in enumerate(b"abc")
    )
    assert linux_dependencies.inspect(original)["machine"] == "EM_AARCH64"
    assert any(
        e.get("register") == "dczid_el0" and e["value"] == 16
        for e in result["loader_events"]
    )


def test_dynamic_arm_protected_dependencies_and_legacy_scope(dynamic, store):
    root = dynamic.source
    (root / "original.elf").write_bytes(dynamic.original)
    (root / "build.json").write_text(json.dumps({"sources": ["main.c", "helper.c"]}))
    paths = {}
    for i, (name, content) in enumerate(dynamic.dependencies.items()):
        paths[name] = f"dep-{i}.elf"
        (root / paths[name]).write_bytes(content)
    artifacts = Artifacts(store)
    task = store.create_project("ARM64 linked program", "Recover transformation")
    context = SimpleNamespace(
        jobs=Jobs(), config={"foundations": {"c_compiler": elf_compiler()}}, cancel=None
    )
    spec = {
        "scope": "linux_program",
        "original_path": "original.elf",
        "manifest_path": "build.json",
        "original_dependencies": paths,
        "cases": [{"runtime": "qiling_linux", "input_hex": v} for v in ("", "616263")],
    }
    service = ProgramAcceptance()
    with pytest.raises(Blocked, match="protected diagnostic") as failed:
        service.prepare(
            root,
            {**spec, "cases": [{**c, "max_instructions": 30} for c in spec["cases"]]},
            artifacts,
            task["project_id"],
            context,
        )
    diagnostic_id = str(failed.value).split(": ")[-1]
    diagnostic = json.loads(
        artifacts.read(diagnostic_id, "evaluator", task["project_id"])
    )
    assert diagnostic["status"] == "budget_exhausted"
    assert diagnostic["stop_context"]["phase"] == "loader"
    assert "input_hex" not in diagnostic and "stdout_hex" not in diagnostic
    with pytest.raises(Blocked, match="Protected"):
        artifacts.read(diagnostic_id, "worker", task["project_id"])
    contract = service.prepare(root, spec, artifacts, task["project_id"], context)
    for path in ["original.elf", *paths.values()]:
        (root / path).write_bytes(b"changed after pinning")
    assert service.verify(root, contract, artifacts, task["project_id"], context)[
        "passed"
    ]
    (root / "helper.c").write_text(HELPER.replace("bias=17", "bias=18"))
    assert not service.verify(root, contract, artifacts, task["project_id"], context)[
        "passed"
    ]
    (root / "original.elf").write_bytes(dynamic.original)
    for name, path in paths.items():
        (root / path).write_bytes(dynamic.dependencies[name])
    with pytest.raises(ContractError, match="Dynamic"):
        service.prepare(
            root,
            {**spec, "scope": "static_x86_64_linux_program"},
            artifacts,
            task["project_id"],
            context,
        )


@pytest.fixture
def libc_program(dynamic):
    root = dynamic.build
    main = """extern int printf(const char*,...);
    extern unsigned long getauxval(unsigned long);
    int main(int n,char **a){
    #ifdef __aarch64__
        if(getauxval(16)!=3 || getauxval(26)!=0)return 3;
        const char *p=(const char*)getauxval(15), *expected="aarch64";
        for(int i=0;i<8;i++)if(p[i]!=expected[i])return 4;
    #endif
        printf("result:%s\\n",n>1?a[1]:"empty");return 0;
    }"""
    (root / "stdio.c").write_text(main)
    # Minimal ABI entry shim; libc performs normal initialization and exit.
    (root / "start.S").write_text(
        """.global _start
.text
_start:
mov x29,xzr
mov x30,xzr
mov x5,x0
adr x0,main
ldr x1,[sp]
add x2,sp,#8
mov x3,xzr
mov x4,xzr
mov x6,sp
bl __libc_start_main
brk #0
"""
    )
    subprocess.run(
        [
            CLANG,
            "--target=aarch64-linux-gnu",
            "-fuse-ld=lld",
            "-march=armv8-a",
            "-nostdlib",
            "-fPIE",
            "-pie",
            str(root / "stdio.c"),
            str(root / "start.S"),
            "-L" + str(FIXTURES),
            "-l:libc.so.6",
            "-Wl,-e,_start,--dynamic-linker=/lib/ld-linux-aarch64.so.1,-rpath,/lib",
            "-o",
            str(root / "stdio"),
        ],
        check=True,
        capture_output=True,
    )
    dependencies = {
        "/lib/" + name: (FIXTURES / name).read_bytes()
        for name in ("ld-linux-aarch64.so.1", "libc.so.6")
    }
    return root, (root / "stdio").read_bytes(), dependencies


def test_arm_libc_startup_capabilities_printf_and_observable_contract(libc_program):
    root, original, dependencies = libc_program
    (root / "recovered.c").write_text(
        'int ha_main(void){const char *s=ha_argc()>1?ha_argv(1):"empty";long n=0;while(s[n])n++;ha_write("result:",7);ha_write(s,n);ha_write("\\n",1);return 0;}'
    )
    built = program.build(root, {"sources": ["recovered.c"]}, Jobs(), elf_compiler())
    assert built["passed"], built
    reconstructed = bytes.fromhex(built["elf_hex"])
    cases = [
        {"runtime": "qiling_linux", "argv": args, "random_hex": "00" * 64}
        for args in (["program"], ["program", "hello"])
    ]
    for case in cases:
        result = platform_runtime.replay(
            original,
            argv=case["argv"],
            random_hex=case["random_hex"],
            dependencies=dependencies,
        )
        expected = (
            b"result:"
            + (case["argv"][1].encode() if len(case["argv"]) > 1 else b"empty")
            + b"\n"
        )
        assert result["status"] == "completed" and result["exit_code"] == 0, result
        assert bytes.fromhex(result["stdout_hex"]) == expected
    assert not program.compare(
        original, reconstructed, cases, dependencies=dependencies
    )["passed"]
    observable = [{**case, "effect_policy": "observable"} for case in cases]
    assert program.compare(
        original, reconstructed, observable, dependencies=dependencies
    )["passed"]
    (root / "recovered.c").write_text(
        'int ha_main(void){ha_write("wrong",5);return 0;}'
    )
    wrong = program.build(root, {"sources": ["recovered.c"]}, Jobs(), elf_compiler())
    assert wrong["passed"]
    assert not program.compare(
        original, bytes.fromhex(wrong["elf_hex"]), observable, dependencies=dependencies
    )["passed"]


@LINUX_ORACLE
def test_arm_libc_printf_against_native_libc(libc_program):
    root, original, dependencies = libc_program
    subprocess.run(
        [elf_compiler(), str(root / "stdio.c"), "-o", str(root / "native-stdio")],
        check=True,
        capture_output=True,
    )
    for args in (["program"], ["program", "hello"]):
        native = subprocess.run(
            args, executable=str(root / "native-stdio"), capture_output=True, timeout=5
        )
        result = platform_runtime.replay(
            original, argv=args, random_hex="00" * 64, dependencies=dependencies
        )
        assert result["status"] == "completed"
        assert (
            result["exit_code"],
            bytes.fromhex(result["stdout_hex"]),
            bytes.fromhex(result["stderr_hex"]),
        ) == (native.returncode, native.stdout, native.stderr)
