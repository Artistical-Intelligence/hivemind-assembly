"""PE replay, independent native Windows oracle, and protected owner workflow."""

import os
import shutil
import subprocess
import threading

import pytest
from hivemind_assembly.core.common import Blocked, ContractError
from hivemind_assembly.core.jobs import Jobs
from hivemind_assembly.domains.reverse_engineering.windows_program import (
    build,
    replay,
    compare,
    image_info,
)


def compiler():
    value = os.environ.get("HA_TEST_CLANG") or shutil.which("clang")
    if not value:
        pytest.skip("Clang and LLD required")
    return value


def compile_source(root, source, optimization="O2"):
    root.mkdir(exist_ok=True)
    (root / "main.c").write_text(source)
    result = build(
        root, {"sources": ["main.c"], "optimization": optimization}, Jobs(), compiler()
    )
    assert result["passed"], result
    return bytes.fromhex(result["pe_hex"])


SOURCE = 'int ha_main(void){unsigned char b[256];long long n=ha_read(b,256);for(long long i=0;i<n;i++)b[i]=(unsigned char)(3*b[i]+17);ha_write(b,n);ha_error("err",3);return 7;}'


def test_windows_replay_and_independent_transform(tmp_path):
    original = compile_source(tmp_path, SOURCE, "O0")
    candidate = compile_source(tmp_path, SOURCE.replace("3*b[i]", "b[i]+b[i]+b[i]"))
    inputs = [b"", b"abc", bytes(range(256))]
    cases = [{"input_hex": v.hex()} for v in inputs]
    for data in inputs:
        result = replay(original, data)
        assert result["status"] == "completed", result
        assert bytes.fromhex(result["stdout_hex"]) == bytes(
            (3 * x + 17) % 256 for x in data
        )
        assert result["stderr_hex"] == b"err".hex()
        assert result["exit_code"] == 7 and result["input_consumed"] == len(data)
    assert compare(original, candidate, cases)["passed"]
    mutant = compile_source(tmp_path, SOURCE.replace("+17", "+18"))
    report = compare(original, mutant, cases)
    assert not report["passed"] and "stdout_hex" in report["cases"][1]["differences"]


@pytest.mark.parametrize(
    "source,status",
    [
        ("int ha_main(void){for(;;){} }", "budget_exhausted"),
        ("int ha_main(void){return *(volatile int*)1;}", "fault"),
        (
            "int ha_main(void){char c=0;ha_dword n;WriteFile((void*)55,&c,1,&n,0);return 0;}",
            "unsupported",
        ),
        (
            "int ha_main(void){char c=0;ha_dword n;WriteFile(GetStdHandle((ha_dword)-11),&c,1,&n,(void*)1);return 0;}",
            "unsupported",
        ),
        ("int ha_main(void){char c=0;ha_write(&c,1000001);return 0;}", "unsupported"),
    ],
)
def test_noncompletion_never_passes_even_against_itself(tmp_path, source, status):
    image = compile_source(tmp_path, source)
    result = replay(image, max_instructions=1000)
    assert result["status"] == status, result
    assert not compare(image, image, [{"max_instructions": 1000}])["passed"]


def test_windows_clock_policy_cancellation_and_api_preflight(tmp_path):
    original = compile_source(
        tmp_path, "int ha_main(void){return (int)(GetTickCount64()-GetTickCount());}"
    )
    assert replay(original, clock_ms=2**32 + 19)["exit_code"] == 0
    replacement = compile_source(tmp_path, "int ha_main(void){return 0;}")
    assert not compare(original, replacement, [{}])["passed"]
    assert compare(original, replacement, [{"effect_policy": "observable"}])["passed"]
    cancelled = threading.Event()
    cancelled.set()
    assert replay(original, cancel=cancelled)["status"] == "cancelled"
    modified = original.replace(b"GetTickCount64\0", b"UnknownApiName\0")
    with pytest.raises(Blocked, match="Unsupported Windows API"):
        image_info(modified)
    for case in (
        {"files": {}},
        {"max_instructions": True},
        {"clock_ms": -1},
        {"input_hex": "xx"},
    ):
        with pytest.raises(ContractError):
            compare(original, replacement, [case])


def test_windows_direct_cpu_effect_and_missing_exit_rejected(tmp_path):
    import pefile

    image = compile_source(tmp_path, "int ha_main(void){return 0;}")
    pe = pefile.PE(data=image)
    offset = pe.get_offset_from_rva(pe.OPTIONAL_HEADER.AddressOfEntryPoint)
    pe.close()
    for code, status in ((b"\x0f\x31\xc3", "unsupported"), (b"\xc3", "incomplete")):
        mutated = image[:offset] + code + image[offset + len(code) :]
        result = replay(mutated)
        assert result["status"] == status, result


@pytest.mark.skipif(os.name != "nt", reason="Independent native Windows OS oracle")
def test_native_windows_pe_oracle(tmp_path):
    # The contract uses redirected regular files, including EOF semantics.
    # No Speakeasy code participates in this expected-result execution.
    image = compile_source(tmp_path, SOURCE)
    path = tmp_path / "native.exe"
    path.write_bytes(image)
    for data in (b"", b"hivemind\0\xff", bytes(range(256))):
        (tmp_path / "in.bin").write_bytes(data)
        with (tmp_path / "in.bin").open("rb") as stdin, (tmp_path / "out.bin").open(
            "wb"
        ) as stdout, (tmp_path / "err.bin").open("wb") as stderr:
            native = subprocess.run(
                [str(path)], stdin=stdin, stdout=stdout, stderr=stderr, timeout=10
            )
        replayed = replay(image, data)
        assert native.returncode == replayed["exit_code"] == 7
        assert (tmp_path / "out.bin").read_bytes() == bytes.fromhex(
            replayed["stdout_hex"]
        )
        assert (tmp_path / "err.bin").read_bytes() == bytes.fromhex(
            replayed["stderr_hex"]
        )


def test_windows_worker_tool_protected_acceptance_and_checkpoint(store):
    import json
    from hivemind_assembly.core.controller import Controller
    from hivemind_assembly.core.broker import Broker
    from hivemind_assembly.core.acceptance import Acceptance
    from hivemind_assembly.domains.reverse_engineering.domain import (
        ReverseEngineeringDomain,
    )

    task = store.create_project(
        "Windows transform", "Recover console behavior", paused=True
    )
    root = store.root / "projects" / task["project_id"] / "workspace"
    image = compile_source(root, SOURCE)
    (root / "original.exe").write_bytes(image)
    (root / "build.json").write_text(json.dumps({"sources": ["main.c"]}))
    controller = Controller(store)
    broker = Broker(
        controller,
        {"foundations": {"c_compiler": compiler()}},
        ReverseEngineeringDomain(),
    )
    service = Acceptance(controller, broker)
    service.configure(
        task["id"],
        {
            "scope": "windows_program",
            "original_path": "original.exe",
            "manifest_path": "build.json",
            "cases": [
                {"id": "empty", "input_hex": ""},
                {"id": "sealed", "input_hex": "616263"},
            ],
        },
    )
    store.state(task["id"], "queued")
    epoch = controller.acquire(task["id"], "worker.opus")
    controller.brief(
        task["id"],
        {"revision": 0},
        {"procedure": "build and compare", "acceptance": "protected corpus"},
        {"critical_gaps": []},
        [],
    )
    result = broker.execute(
        {
            "id": "windows-check",
            "task_id": task["id"],
            "owner": "worker.opus",
            "epoch": epoch,
            "revision": 0,
            "tool": "compare_windows_program",
            "args": {
                "manifest_path": "build.json",
                "original_path": "original.exe",
                "cases": [{"input_hex": "0102"}],
            },
        }
    )
    assert result["passed"] and result["executable_artifact"]
    assert service.evaluate(
        store.task(task["id"]),
        {
            "result_operations": ["windows-check"],
            "summary": "Recovered Windows console",
        },
    )["passed"]
    (root / "original.exe").write_bytes(b"replacement")
    contract = store.get("acceptance_contract", task["id"])
    result = broker.domain.acceptance.verify(
        root, contract, broker.artifacts, task["project_id"], broker.context(task["id"])
    )
    assert result["passed"] and "input_hex" not in json.dumps(result)
    with pytest.raises(Blocked):
        broker.artifacts.read(result["protected_details"], "worker", task["project_id"])
    (root / "main.c").write_text(SOURCE.replace("+17", "+18"))
    with pytest.raises(Exception, match="Candidate changed"):
        broker.domain.acceptance.recheck(root, result)
    assert not broker.domain.acceptance.verify(
        root, contract, broker.artifacts, task["project_id"], broker.context(task["id"])
    )["passed"]
