"""Declared process inputs, host isolation and a native Windows string oracle."""

import json
import os
import subprocess

import pytest

from hivemind_assembly.core.common import ContractError
from hivemind_assembly.domains.reverse_engineering.windows_program import (
    compare,
    replay,
    validate_case,
)
from test_windows_program import compile_source, compiler

ORACLE = """int ha_main(void){
  char *a=GetCommandLineA();unsigned short *w=GetCommandLineW();
  ha_dword n=0;while(a[n]){if(w[n]!=(unsigned char)a[n])return 1;n++;}
  if(w[n]||a!=GetCommandLineA()||w!=GetCommandLineW())return 2;
  ha_write(a,n);ha_write("|",1);
  char value[64];unsigned short wide[64];
  unsigned short name[]={104,97,95,118,97,108,117,101,0};
  ha_dword size=GetEnvironmentVariableA("ha_value",0,0);
  if(size!=6)return 3;
  n=GetEnvironmentVariableA("HA_VALUE",value,64);
  if(n!=5||value[n])return 4;
  ha_write(value,n);ha_write("|",1);
  if(GetEnvironmentVariableW(name,wide,64)!=n||wide[n])return 5;
  for(ha_dword i=0;i<n;i++)if(wide[i]!=(unsigned char)value[i])return 6;
  ha_write(wide,n*2);
  if(GetEnvironmentVariableA("HA_ABSENT",value,64)||GetLastError()!=203)return 7;
  if(GetEnvironmentVariableA("HA_EMPTY",0,0)!=1)return 8;
  value[0]='x';if(GetEnvironmentVariableA("ha_empty",value,1)||value[0])return 9;
  return 0;
}"""

COMMAND = 'program.exe "two words" trailing\\\\ --flag'
ENV = {"Ha_Value": "value", "HA_EMPTY": ""}


def test_process_inputs_match_independent_bytes_and_ignore_host(tmp_path, monkeypatch):
    monkeypatch.setenv("HA_ABSENT", "must never reach the guest")
    image = compile_source(tmp_path, ORACLE)
    result = replay(image, command_line=COMMAND, env=ENV)
    assert result["status"] == "completed" and result["exit_code"] == 0, result
    assert bytes.fromhex(
        result["stdout_hex"]
    ) == COMMAND.encode() + b"|value|" + "value".encode("utf-16-le")
    assert result["files"] == {} and result["stderr_hex"] == ""


@pytest.mark.skipif(os.name != "nt", reason="Independent native Windows process oracle")
def test_native_windows_process_oracle(tmp_path):
    image = compile_source(tmp_path, ORACLE)
    exe = tmp_path / "process.exe"
    exe.write_bytes(image)
    native = subprocess.run(
        COMMAND,
        executable=str(exe),
        cwd=tmp_path,
        env=ENV,
        capture_output=True,
        timeout=10,
    )
    # Windows may qualify the executable name. The replay contract supplies the
    # observed command-line string, rather than promising CreateProcess quoting.
    observed = native.stdout.split(b"|", 1)[0].decode("ascii")
    result = replay(image, command_line=observed, env=ENV)
    assert result["status"] == "completed", result
    assert native.returncode == result["exit_code"] == 0, (native.returncode, result)
    assert native.stdout == bytes.fromhex(result["stdout_hex"])
    assert native.stderr == bytes.fromhex(result["stderr_hex"]) == b""


@pytest.mark.parametrize(
    "body,status",
    [
        ('char b[2];GetEnvironmentVariableA("X",b,2);', "unsupported"),
        ("GetCommandLineA()[0]='X';", "fault"),
        ("char *p=GetCommandLineA();ha_read(p,1);", "unsupported"),
        ("char *p=GetCommandLineA();ha_read(p+64,1);", "unsupported"),
        ('char *p=GetCommandLineA();GetEnvironmentVariableA("X",p,20);', "unsupported"),
    ],
)
def test_undefined_buffers_and_command_line_modification_fail(tmp_path, body, status):
    image = compile_source(tmp_path, "int ha_main(void){" + body + "return 0;}")
    result = compare(
        image,
        image,
        [{"env": {"X": "value"}, "input_hex": "58", "effect_policy": "observable"}],
    )
    assert not result["passed"]
    assert result["cases"][0]["original"]["status"] == status, result


@pytest.mark.parametrize(
    "case",
    [
        {"command_line": "bad\0value"},
        {"command_line": "é"},
        {"command_line": 1},
        {"command_line": "x" * 8193},
        {"env": []},
        {"env": {"X": "\0"}},
        {"env": {"X": "1", "x": "2"}},
        {"env": {"=C:": "ignored"}},
        {"env": {"x": "z" * 8193}},
        {"env": {str(i): "x" for i in range(129)}},
        {"env": {"V" + str(i): "x" * 8192 for i in range(8)}},
    ],
)
def test_invalid_process_inputs_are_rejected_before_replay(case):
    with pytest.raises(ContractError):
        validate_case(case)


def test_process_query_policy_and_changed_environment_are_observed(tmp_path):
    source = 'int ha_main(void){char b[8];ha_dword n=GetEnvironmentVariableA("MODE",b,8);ha_write(b,n);return 0;}'
    image = compile_source(tmp_path, source)
    extra = compile_source(
        tmp_path, source.replace("char b[8];", "GetCommandLineW();char b[8];")
    )
    cases = [{"env": {"MODE": "one"}}, {"env": {"MODE": "two"}}]
    assert not compare(image, extra, cases)["passed"]
    assert compare(image, extra, [{**c, "effect_policy": "observable"} for c in cases])[
        "passed"
    ]
    for mode in ("one", "two"):
        assert replay(image, env={"mode": mode})["stdout_hex"] == mode.encode().hex()


def test_protected_process_inputs_survive_owner_and_host_changes(store, monkeypatch):
    from hivemind_assembly.core.controller import Controller
    from hivemind_assembly.core.broker import Broker
    from hivemind_assembly.core.acceptance import Acceptance
    from hivemind_assembly.domains.reverse_engineering.domain import (
        ReverseEngineeringDomain,
    )

    source = 'int ha_main(void){char b[64];ha_dword n=GetEnvironmentVariableA("MODE",b,64);ha_write(b,n);char *p=GetCommandLineA();ha_dword i=0;while(p[i])i++;ha_write(p,i);return 0;}'
    task = store.create_project(
        "Process inputs", "Recover settings-dependent tool", paused=True
    )
    root = store.root / "projects" / task["project_id"] / "workspace"
    image = compile_source(root, source)
    (root / "original.exe").write_bytes(image)
    (root / "build.json").write_text(json.dumps({"sources": ["main.c"]}))
    controller = Controller(store)
    broker = Broker(
        controller,
        {"foundations": {"c_compiler": compiler()}},
        ReverseEngineeringDomain(),
    )
    cases = [
        {"command_line": "program.exe private-" + v, "env": {"MODE": v}}
        for v in ("one", "two")
    ]
    Acceptance(controller, broker).configure(
        task["id"],
        {
            "scope": "windows_program",
            "original_path": "original.exe",
            "manifest_path": "build.json",
            "cases": cases,
        },
    )
    cases[1]["env"]["MODE"] = "changed"
    monkeypatch.setenv("MODE", "host only")
    contract = store.get("acceptance_contract", task["id"])
    result = broker.domain.acceptance.verify(
        root, contract, broker.artifacts, task["project_id"], broker.context(task["id"])
    )
    assert result["passed"] and "private-" not in json.dumps(result)
    (root / "main.c").write_text(source.replace("ha_write(b,n)", 'ha_write("one",3)'))
    assert not broker.domain.acceptance.verify(
        root, contract, broker.artifacts, task["project_id"], broker.context(task["id"])
    )["passed"]
