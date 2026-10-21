"""File-driven PE reconstruction and an independent native Windows oracle."""

import json
import os
import subprocess

import pytest

from hivemind_assembly.core.common import ContractError
from hivemind_assembly.domains.reverse_engineering.windows_program import (
    compare,
    replay,
)
from test_windows_program import compile_source, compiler


COPY = """int ha_main(void){
  unsigned char b[256];ha_dword n=0,k=0;
  void *in=CreateFileA("input.bin",0x80000000UL,1,0,3,128,0);
  if(in==(void*)-1)return 1;
  if(!ReadFile(in,b,256,&n,0))return 2;
  CloseHandle(in);
  for(ha_dword i=0;i<n;i++)b[i]=(unsigned char)(3*b[i]+17);
  void *out=CreateFileA("output.bin",0x40000000UL,0,0,2,128,0);
  if(out==(void*)-1)return 3;
  if(!WriteFile(out,b,n,&k,0)||k!=n)return 4;
  CloseHandle(out);return 0;
}"""


def test_file_outputs_policies_and_independent_expected_bytes(tmp_path):
    image = compile_source(tmp_path, COPY, "O0")
    replacement = compile_source(tmp_path, COPY.replace("3*b[i]", "b[i]+b[i]+b[i]"))
    cases = [
        {"files": {"input.bin": data.hex(), "output.bin": "ffee"}}
        for data in (b"", b"abc", bytes(range(256)))
    ]
    assert compare(image, replacement, cases)["passed"]
    for case in cases:
        result = replay(image, files=case["files"])
        assert result["status"] == "completed" and result["exit_code"] == 0, result
        assert bytes.fromhex(result["files"]["output.bin"]) == bytes(
            (3 * x + 17) % 256 for x in bytes.fromhex(case["files"]["input.bin"])
        )
        assert result["files"]["input.bin"] == case["files"]["input.bin"]
    mutant = compile_source(tmp_path, COPY.replace("+17", "+18"))
    result = compare(image, mutant, [{**cases[1], "effect_policy": "observable"}])
    assert not result["passed"] and result["cases"][0]["differences"] == ["files"]
    # Metadata queries can differ only when the owner chooses observable results.
    extra = compile_source(
        tmp_path,
        COPY.replace(
            "CloseHandle(in);",
            "long long size;GetFileSizeEx(in,&size);CloseHandle(in);",
        ),
    )
    assert not compare(image, extra, cases)["passed"]
    assert compare(image, extra, [{**c, "effect_policy": "observable"} for c in cases])[
        "passed"
    ]


# Every failure is inspected immediately, as required by Win32. The source itself
# checks the independent expected semantics as well as native/emulated agreement.
ORACLE = """int ha_main(void){
  unsigned short wide[]={105,110,112,117,116,46,98,105,110,0};
  char b[20];ha_dword n=0;long long pos=0,size=0;
  void *a=CreateFileW(wide,0xc0000000UL,3,0,3,128,0);
  if(a==(void*)-1)return 1;
  if(!ReadFile(a,b,2,&n,0)||n!=2||b[0]!='a'||b[1]!='b')return 2;
  if(!SetFilePointerEx(a,-1,&pos,1)||pos!=1)return 3;
  if(!WriteFile(a,"XY",2,&n,0)||n!=2)return 4;
  void *c=CreateFileA("INPUT.BIN",0x80000000UL,3,0,3,128,0);
  if(c==(void*)-1)return 5;
  if(!ReadFile(c,b,20,&n,0)||n!=4||b[1]!='X'||b[2]!='Y')return 6;
  ha_write(b,n);
  if(!GetFileSizeEx(a,&size)||size!=4)return 7;
  if(!SetFilePointerEx(a,2,&pos,2)||pos!=6)return 8;
  if(!WriteFile(a,"Z",1,&n,0)||n!=1)return 9;
  if(!SetFilePointerEx(c,0,0,0)||!ReadFile(c,b,20,&n,0)||n!=7||b[4]||b[5]||b[6]!='Z')return 10;
  if(!SetFilePointerEx(a,3,0,0)||!SetEndOfFile(a))return 11;
  if(!ReadFile(c,b,20,&n,0)||n)return 12;
  if(!CloseHandle(a)||!CloseHandle(c))return 13;
  a=CreateFileA("input.bin",0x80000000UL,0,0,1,128,0);
  if(a!=(void*)-1||GetLastError()!=80)return 14;
  a=CreateFileA("missing.bin",0x80000000UL,0,0,3,128,0);
  if(a!=(void*)-1||GetLastError()!=2)return 15;
  a=CreateFileA("input.bin",0x80000000UL,0,0,3,128,0);
  if(a==(void*)-1)return 16;
  n=99;if(WriteFile(a,"x",1,&n,0)||GetLastError()!=5||n)return 17;
  if(SetFilePointerEx(a,-1,0,0)||GetLastError()!=131)return 18;
  c=CreateFileA("input.bin",0x80000000UL,1,0,3,128,0);
  if(c!=(void*)-1||GetLastError()!=32)return 19;
  if(DeleteFileW(wide)||GetLastError()!=32)return 20;
  if(!CloseHandle(a))return 21;
  n=99;if(ReadFile(a,b,1,&n,0)||GetLastError()!=6||n)return 22;
  a=CreateFileA("output.bin",0xc0000000UL,3,0,4,128,0);
  if(a==(void*)-1||GetLastError()!=0)return 23;
  if(!WriteFile(a,"old",3,&n,0)||!CloseHandle(a))return 24;
  a=CreateFileA("output.bin",0xc0000000UL,3,0,2,128,0);
  if(a==(void*)-1||GetLastError()!=183)return 25;
  if(!GetFileSizeEx(a,&size)||size!=0)return 26;
  if(!SetFilePointerEx(a,5,0,0)||!WriteFile(a,"",0,&n,0)||!GetFileSizeEx(a,&size)||size!=0)return 27;
  if(!CloseHandle(a))return 28;
  a=CreateFileA("input.bin",0x40000000UL,0,0,5,128,0);
  if(a==(void*)-1||!GetFileSizeEx(a,&size)||size!=0||!CloseHandle(a))return 29;
  if(!DeleteFileA("input.bin"))return 30;
  if(DeleteFileA("input.bin")||GetLastError()!=2)return 31;
  SetLastError(123);if(GetLastError()!=123)return 32;
  return 0;
}"""


def test_file_api_state_and_error_oracle(tmp_path):
    image = compile_source(tmp_path, ORACLE)
    result = replay(image, files={"input.bin": b"abcd".hex()})
    assert result["status"] == "completed" and result["exit_code"] == 0, result
    assert result["stdout_hex"] == b"aXYd".hex()
    assert result["files"] == {"output.bin": ""}


@pytest.mark.skipif(os.name != "nt", reason="Independent native Windows OS oracle")
def test_native_windows_file_oracle(tmp_path):
    image = compile_source(tmp_path, ORACLE)
    exe = tmp_path / "oracle.exe"
    exe.write_bytes(image)
    (tmp_path / "input.bin").write_bytes(b"abcd")
    native = subprocess.run([str(exe)], cwd=tmp_path, capture_output=True, timeout=10)
    result = replay(image, files={"input.bin": b"abcd".hex()})
    assert result["status"] == "completed", result
    assert native.returncode == result["exit_code"] == 0, (native.returncode, result)
    assert native.stdout == bytes.fromhex(result["stdout_hex"]) == b"aXYd"
    assert native.stderr == bytes.fromhex(result["stderr_hex"]) == b""
    assert not (tmp_path / "input.bin").exists()
    assert (tmp_path / "output.bin").read_bytes() == b""
    assert result["files"] == {"output.bin": ""}


@pytest.mark.parametrize(
    "files",
    [
        [],
        {"x": "xx"},
        {"a": "", "A": ""},
        {"CON.txt": ""},
        {"../secret": ""},
        {"C:\\outside.txt": ""},
        {"x:y": ""},
        {"x.": ""},
        {"\\\\server\\share": ""},
        {"é.txt": ""},
        {"x": "00" * 1_000_001},
    ],
)
def test_invalid_declared_files_are_rejected_before_execution(files):
    from hivemind_assembly.domains.reverse_engineering.windows_program import (
        validate_case,
    )

    with pytest.raises(ContractError):
        validate_case({"files": files})


@pytest.mark.parametrize(
    "body,status",
    [
        ('CreateFileA("x",0,0,0,3,128,0);', "unsupported"),
        ('CreateFileA("x",0x80000000UL,0,0,2,128,0);', "unsupported"),
        ('CreateFileA("../outside",0x80000000UL,0,0,3,128,0);', "unsupported"),
        ('CreateFileA("x",0x80000000UL,0,0,3,0x40000080UL,0);', "unsupported"),
        ('CreateFileA("x",0x80000000UL,4,0,3,128,0);', "unsupported"),
        (
            'void *h=CreateFileA("x",0x40000000UL,0,0,2,128,0);SetFilePointerEx(h,1000001,0,0);',
            "budget_exhausted",
        ),
        (
            'void *h=CreateFileA("x",0x40000000UL,0,0,2,128,0);SetFilePointerEx(h,10,0,0);SetEndOfFile(h);',
            "unsupported",
        ),
        (
            'void *h=CreateFileA("x",0x40000000UL,0,0,2,128,0);CloseHandle(h);GetLastError();',
            "unsupported",
        ),
    ],
)
def test_unsupported_file_effects_never_pass(tmp_path, body, status):
    image = compile_source(tmp_path, "int ha_main(void){" + body + "return 0;}")
    result = compare(image, image, [{"effect_policy": "observable"}])
    assert not result["passed"]
    assert result["cases"][0]["original"]["status"] == status, result


def test_file_cases_are_pinned_and_hidden_from_worker(store):
    from hivemind_assembly.core.controller import Controller
    from hivemind_assembly.core.broker import Broker
    from hivemind_assembly.core.acceptance import Acceptance
    from hivemind_assembly.domains.reverse_engineering.domain import (
        ReverseEngineeringDomain,
    )

    task = store.create_project("File transform", "Recover file outputs", paused=True)
    root = store.root / "projects" / task["project_id"] / "workspace"
    image = compile_source(root, COPY)
    (root / "original.exe").write_bytes(image)
    (root / "build.json").write_text(json.dumps({"sources": ["main.c"]}))
    controller = Controller(store)
    broker = Broker(
        controller,
        {"foundations": {"c_compiler": compiler()}},
        ReverseEngineeringDomain(),
    )
    service = Acceptance(controller, broker)
    cases = [
        {"files": {"input.bin": value.hex()}} for value in (b"", b"sealed-file-content")
    ]
    service.configure(
        task["id"],
        {
            "scope": "windows_program",
            "original_path": "original.exe",
            "manifest_path": "build.json",
            "cases": cases,
        },
    )
    cases[1]["files"]["input.bin"] = "ff"
    (root / "input.bin").write_bytes(b"host content must not be read")
    contract = store.get("acceptance_contract", task["id"])
    result = broker.domain.acceptance.verify(
        root, contract, broker.artifacts, task["project_id"], broker.context(task["id"])
    )
    assert result["passed"] and "sealed-file-content".encode().hex() not in json.dumps(
        result
    )
    (root / "main.c").write_text(COPY.replace("+17", "+18"))
    assert not broker.domain.acceptance.verify(
        root, contract, broker.artifacts, task["project_id"], broker.context(task["id"])
    )["passed"]


@pytest.mark.parametrize(
    "body,files",
    [
        ('for(int i=0;i<129;i++)CreateFileA("x",0x80000000UL,3,0,3,128,0);', {"x": ""}),
        (
            'CreateFileA("new.bin",0x40000000UL,0,0,2,128,0);',
            {str(i): "" for i in range(64)},
        ),
        (
            'void *h=CreateFileA("x",0x40000000UL,0,0,2,128,0);ha_dword n;SetFilePointerEx(h,1000000,0,0);WriteFile(h,"x",1,&n,0);',
            {},
        ),
        (
            'static char b[1000000];ha_dword n;void *h=CreateFileA("x",0xc0000000UL,0,0,2,128,0);for(int i=0;i<5;i++){SetFilePointerEx(h,0,0,0);WriteFile(h,b,1000000,&n,0);}',
            {},
        ),
    ],
)
def test_file_resource_limits_cannot_pass_as_equivalence(tmp_path, body, files):
    image = compile_source(tmp_path, "int ha_main(void){" + body + "return 0;}")
    result = compare(image, image, [{"files": files, "effect_policy": "observable"}])
    assert not result["passed"]
    assert result["cases"][0]["original"]["status"] == "budget_exhausted", result


def test_declared_file_aliases_are_local_and_replays_are_fresh(tmp_path):
    image = compile_source(tmp_path, COPY)
    files = {"C:\\work\\INPUT.BIN": "616263", ".\\OUTPUT.BIN": "ffff"}
    for _ in range(2):
        result = replay(image, files=files)
        assert result["status"] == "completed" and result["exit_code"] == 0, result
        assert result["files"] == {"input.bin": "616263", "output.bin": "34373a"}
    assert files == {"C:\\work\\INPUT.BIN": "616263", ".\\OUTPUT.BIN": "ffff"}
    assert not (tmp_path / "output.bin").exists()
