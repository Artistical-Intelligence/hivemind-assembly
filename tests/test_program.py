import subprocess
import pytest
from native_fixtures import elf_compiler, LINUX_ORACLE
from hivemind_assembly.core.jobs import Jobs
from hivemind_assembly.core.common import Blocked, ContractError
from hivemind_assembly.domains.reverse_engineering.program import (
    build,
    replay,
    compare,
    load_image,
)


def example(root, wrong=False):
    root.mkdir(exist_ok=True)
    (root / "logic.c").write_text(
        "unsigned char state; unsigned char step(unsigned char x) { state = (state * 3 + x) % 251; return state; }"
    )
    (root / "main.c").write_text(
        "int ha_main(void) { unsigned char in[32], out[32]; long n=ha_read(in,32); for(long i=0;i<n;i++) out[i]=step(in[i])"
        + (" + 1" if wrong else "")
        + "; ha_write(out,n); return 0; }"
    )
    return {
        "sources": ["logic.c", "main.c"],
        "declarations": "unsigned char step(unsigned char x);",
    }


def test_multifunction_program_memory_io_and_negative(tmp_path):
    original = build(tmp_path, example(tmp_path), Jobs(), compiler=elf_compiler())
    assert original["passed"], original
    machine = bytes.fromhex(original["elf_hex"])
    result = replay(machine, b"abc")
    assert result["status"] == "completed", result
    expected = bytes([97, (97 * 3 + 98) % 251, (((97 * 3 + 98) % 251) * 3 + 99) % 251])
    assert bytes.fromhex(result["stdout_hex"]) == expected
    other = build(
        tmp_path,
        {**example(tmp_path), "optimization": "O0"},
        Jobs(),
        compiler=elf_compiler(),
    )
    cases = [
        {"id": "empty", "input_hex": ""},
        {"id": "state", "input_hex": b"abc".hex()},
        {"id": "limits", "input_hex": bytes(range(32)).hex()},
    ]
    assert compare(machine, bytes.fromhex(other["elf_hex"]), cases)["passed"]
    wrong = build(tmp_path, example(tmp_path, True), Jobs(), compiler=elf_compiler())
    assert not compare(machine, bytes.fromhex(wrong["elf_hex"]), cases)["passed"]
    endless = tmp_path / "main.c"
    endless.write_text("int ha_main(void) { for(;;) {} }")
    loop = build(tmp_path, {"sources": ["main.c"]}, Jobs(), compiler=elf_compiler())
    assert (
        replay(bytes.fromhex(loop["elf_hex"]), max_instructions=100)["status"]
        == "budget_exhausted"
    )


@LINUX_ORACLE
def test_multifunction_native_linux_oracle(tmp_path):
    original = build(tmp_path, example(tmp_path), Jobs(), compiler=elf_compiler())
    executable = tmp_path / "fixture"
    executable.write_bytes(bytes.fromhex(original["elf_hex"]))
    executable.chmod(0o700)
    live = subprocess.run(
        [str(executable)], input=b"abc", capture_output=True, timeout=5
    )
    expected = bytes([97, (97 * 3 + 98) % 251, (((97 * 3 + 98) % 251) * 3 + 99) % 251])
    assert live.returncode == 0 and live.stdout == expected


def test_image_and_build_boundaries(tmp_path):
    with pytest.raises(ContractError):
        load_image(b"bad")
    (tmp_path / "main.c").write_text(
        '#include "/etc/passwd"\nint ha_main(void){return 0;}'
    )
    with pytest.raises(Blocked):
        build(tmp_path, {"sources": ["main.c"]}, Jobs())
    with pytest.raises((ContractError, Blocked)):
        build(tmp_path, {"sources": ["../main.c"]}, Jobs())


def test_program_acceptance_pins_original_and_rechecks_all_sources(store):
    import json
    from hivemind_assembly.core.controller import Controller
    from hivemind_assembly.core.broker import Broker
    from hivemind_assembly.core.acceptance import Acceptance
    from hivemind_assembly.domains.reverse_engineering.domain import (
        ReverseEngineeringDomain,
    )

    task = store.create_project(
        "complete program", "Reconstruct stateful transform", paused=True
    )
    root = store.root / "projects" / task["project_id"] / "workspace"
    manifest = example(root)
    original = build(root, manifest, Jobs(), compiler=elf_compiler())
    (root / "original.elf").write_bytes(bytes.fromhex(original["elf_hex"]))
    (root / "build.json").write_text(json.dumps(manifest))
    controller = Controller(store)
    broker = Broker(
        controller,
        {"foundations": {"c_compiler": elf_compiler()}},
        ReverseEngineeringDomain(),
    )
    service = Acceptance(controller, broker)
    contract = service.configure(
        task["id"],
        {
            "scope": "static_x86_64_linux_program",
            "original_path": "original.elf",
            "manifest_path": "build.json",
            "cases": [
                {"id": "empty", "input_hex": ""},
                {"id": "message", "input_hex": "616263"},
            ],
        },
    )
    assert contract["checks"][0]["case_count"] == 2
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
            "id": "program-check",
            "task_id": task["id"],
            "owner": "worker.opus",
            "epoch": epoch,
            "revision": 0,
            "tool": "compare_program",
            "args": {
                "manifest_path": "build.json",
                "original_path": "original.elf",
                "cases": [{"input_hex": "0102"}],
            },
        }
    )
    assert result["passed"] and result["executable_artifact"]
    accepted = service.evaluate(
        store.task(task["id"]),
        {"result_operations": ["program-check"], "summary": "Recovered program"},
    )
    assert accepted["passed"]
    # Original overwrite after configuration cannot replace the protected oracle.
    (root / "original.elf").write_bytes(b"invalid replacement")
    retained = store.get("acceptance_contract", task["id"])
    again = broker.domain.acceptance.verify(
        root, retained, broker.artifacts, task["project_id"], broker.context(task["id"])
    )
    assert again["passed"] and "input_hex" not in json.dumps(again)
    (root / "logic.c").write_text("unsigned char step(unsigned char x){return 0;}")
    with pytest.raises(Exception, match="Candidate changed"):
        broker.domain.acceptance.recheck(root, again)
