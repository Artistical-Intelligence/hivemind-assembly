import json
import subprocess
from types import SimpleNamespace

import pytest
from hivemind_assembly.core.artifacts import Artifacts
from hivemind_assembly.core.common import ContractError
from hivemind_assembly.core.jobs import Jobs
from hivemind_assembly.domains.reverse_engineering import program, platform_runtime
from hivemind_assembly.domains.reverse_engineering.process_inputs import normalize
from hivemind_assembly.domains.reverse_engineering.program_acceptance import (
    ProgramAcceptance,
)


SOURCE = """void emit(const char *s){if(s){long n=0;while(s[n])n++;ha_write(s,n);}ha_write("|",1);}
int ha_main(void){for(long i=0;i<ha_argc();i++)emit(ha_argv(i));emit(ha_getenv("HA_VALUE"));emit(ha_getenv("HOST_ONLY"));return ha_argv(-1)||ha_argv(ha_argc())||ha_getenv("HA_VALUE=") ? 99 : (int)ha_argc();}"""


@pytest.fixture
def compiled(tmp_path):
    (tmp_path / "main.c").write_text(SOURCE)
    manifest = {"sources": ["main.c"]}
    built = program.build(tmp_path, manifest, Jobs(), compiler="gcc")
    assert built["passed"], built
    binary = bytes.fromhex(built["elf_hex"])
    exe = tmp_path / "fixture"
    exe.write_bytes(binary)
    exe.chmod(0o700)
    return tmp_path, manifest, binary, exe


def test_arguments_environment_utf8_and_native_oracle(compiled, monkeypatch):
    root, manifest, binary, exe = compiled
    monkeypatch.setenv("HOST_ONLY", "must-not-leak")
    argv = ["recovered", "", "café λ"]
    env = {"HA_VALUE": "résumé", "HA_VALUE_SUFFIX": "wrong"}
    expected = "recovered||café λ|résumé||".encode()
    native = subprocess.run(
        argv, executable=str(exe), env=env, capture_output=True, timeout=5
    )
    assert native.returncode == 3 and native.stdout == expected
    for replay in (program.replay, platform_runtime.replay):
        result = replay(binary, argv=argv, env=env)
        assert result["status"] == "completed", result
        assert result["exit_code"] == native.returncode
        assert bytes.fromhex(result["stdout_hex"]) == native.stdout
        assert bytes.fromhex(replay(binary)["stdout_hex"]) == b"program|||"
    other = program.build(
        root, {**manifest, "optimization": "O0"}, Jobs(), compiler="gcc"
    )
    cases = [
        {"argv": argv, "env": env, "runtime": runtime}
        for runtime in ("unicorn_linux", "qiling_linux")
    ]
    assert program.compare(binary, bytes.fromhex(other["elf_hex"]), cases)["passed"]


def test_protected_process_inputs_and_wrong_environment_lookup(compiled, store):
    root, manifest, binary, exe = compiled
    (root / "original.elf").write_bytes(binary)
    (root / "build.json").write_text(json.dumps(manifest))
    task = store.create_project("Arguments", "Recover CLI behavior")
    artifacts = Artifacts(store)
    context = SimpleNamespace(
        jobs=Jobs(), config={"foundations": {"c_compiler": "gcc"}}, cancel=None
    )
    service = ProgramAcceptance()
    contract = service.prepare(
        root,
        {
            "scope": "static_x86_64_linux_program",
            "original_path": "original.elf",
            "manifest_path": "build.json",
            "cases": [
                {"argv": ["first", "a"], "env": {"HA_VALUE": "secret-one"}},
                {
                    "argv": ["second"],
                    "env": {"HA_VALUE": "secret-two"},
                    "runtime": "qiling_linux",
                },
            ],
        },
        artifacts,
        task["project_id"],
        context,
    )
    assert service.verify(root, contract, artifacts, task["project_id"], context)[
        "passed"
    ]
    (root / "main.c").write_text(
        SOURCE.replace('ha_getenv("HA_VALUE")', 'ha_getenv("WRONG")')
    )
    result = service.verify(root, contract, artifacts, task["project_id"], context)
    assert not result["passed"]
    assert "secret-one" not in json.dumps(result)


@pytest.mark.parametrize(
    "argv,env",
    [
        ([], {}),
        (["a\0b"], {}),
        (["a" * 4097], {}),
        (["a"] * 129, {}),
        (["ok"], {"BAD=KEY": "x"}),
        (["ok"], {"": "x"}),
        (["ok"], {"A": "\0"}),
        (["ok"], {"A": 1}),
        (["a" * 4096] * 17, {}),
    ],
)
def test_invalid_process_inputs_rejected(argv, env):
    with pytest.raises(ContractError):
        normalize(argv, env)


@pytest.mark.parametrize(
    "opcode", [b"\x0f\x31", b"\x0f\xa2", b"\x48\x0f\xc7\xf0", b"\xec"]
)
def test_program_cpu_external_state_is_rejected(compiled, opcode):
    root, manifest, binary, exe = compiled
    entry, segments = program.load_image(binary)
    segment = next(
        s for s in segments if s["address"] <= entry < s["address"] + s["size"]
    )
    # Patch a source-known fixture entry; never execute these variants natively.
    offset = binary.index(segment["data"]) + entry - segment["address"]
    patched = binary[:offset] + opcode + binary[offset + len(opcode) :]
    for replay in (program.replay, platform_runtime.replay):
        result = replay(patched)
        assert result["status"] == "unsupported_cpu_state", result
