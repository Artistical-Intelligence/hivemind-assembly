"""Private virtual memory against independent bytes and the native Windows API."""

import os
import subprocess

import pytest

from hivemind_assembly.domains.reverse_engineering.windows_program import (
    compare,
    replay,
)
from test_windows_program import compile_source


ORACLE = """int ha_main(void){
  unsigned char *p=VirtualAlloc(0,12287,0x2000,4);ha_dword old=0;
  if(!p||((ha_size)p&65535))return 1;
  if(VirtualProtect(p,4096,2,&old))return 2;
  if(VirtualAlloc(p+4095,2,0x1000,4)!=p)return 3;
  for(int i=0;i<8192;i++)if(p[i])return 4;
  p[0]=17;p[4095]=33;p[4096]=65;p[8191]=129;
  if(VirtualAlloc(p+4096,1,0x1000,4)!=p+4096||p[4096]!=65)return 5;
  if(!VirtualProtect(p+4095,2,2,&old)||old!=4)return 6;
  ha_write(p,1);ha_write(p+4095,2);ha_write(p+8191,1);
  if(!VirtualProtect(p+4096,4096,4,&old)||old!=2)return 7;
  if(!VirtualProtect(p,8192,4,&old)||old!=2)return 8;
  if(!VirtualFree(p+4095,2,0x4000))return 9;
  if(!VirtualFree(p+4096,1,0x4000))return 10;
  if(VirtualAlloc(p,8192,0x1000,4)!=p)return 11;
  for(int i=0;i<8192;i++)if(p[i])return 12;
  if(!VirtualFree(p,0,0x4000))return 13;
  if(VirtualProtect(p,8192,4,&old))return 14;
  if(!VirtualFree(p,0,0x8000))return 15;
  p=VirtualAlloc(0,4097,0x3000,4);
  if(!p)return 16;
  for(int i=0;i<8192;i++)if(p[i])return 17;
  p[0]=7;p[8191]=9;ha_write(p,1);ha_write(p+8191,1);
  if(!VirtualProtect(p,8192,1,&old)||old!=4)return 18;
  if(!VirtualProtect(p,8192,4,&old)||old!=1||p[0]!=7||p[8191]!=9)return 19;
  if(!VirtualFree(p,0,0x8000))return 20;
  p=VirtualAlloc(0,1,0x1000,2);
  if(!p||p[0])return 21;
  if(!VirtualFree(p,0,0x8000))return 22;
  p=VirtualAlloc(0,12288,0x2000,4);
  if(!p||VirtualAlloc(p+4096,4096,0x1000,4)!=p+4096)return 23;
  p[4096]=65;
  if(VirtualAlloc(p,12288,0x1000,4)!=p||p[0]||p[4096]!=65||p[12287])return 24;
  if(!VirtualFree(p,0,0x8000))return 25;
  return 0;
}"""
EXPECTED = bytes([17, 33, 65, 129, 7, 9])


def test_virtual_memory_rounding_zeroing_protection_and_independent_output(tmp_path):
    image = compile_source(tmp_path, ORACLE)
    result = replay(image)
    assert result["status"] == "completed" and result["exit_code"] == 0, result
    assert bytes.fromhex(result["stdout_hex"]) == EXPECTED
    assert result["files"] == {} and result["stderr_hex"] == ""
    assert any(e.get("result") == 0 for e in result["events"])


@pytest.mark.skipif(
    os.name != "nt", reason="Independent native Windows virtual-memory oracle"
)
def test_native_windows_memory_oracle(tmp_path):
    image = compile_source(tmp_path, ORACLE)
    exe = tmp_path / "memory.exe"
    exe.write_bytes(image)
    native = subprocess.run([str(exe)], cwd=tmp_path, capture_output=True, timeout=10)
    result = replay(image)
    assert result["status"] == "completed", result
    assert native.returncode == result["exit_code"] == 0, (native.returncode, result)
    assert native.stdout == bytes.fromhex(result["stdout_hex"]) == EXPECTED
    assert native.stderr == bytes.fromhex(result["stderr_hex"]) == b""


@pytest.mark.parametrize(
    "body",
    [
        "VirtualFree(p,0,0x8000);return p[0];",
        "volatile char *r=VirtualAlloc(0,4096,0x2000,4);return r[0];",
        "VirtualFree(p,0,0x4000);return p[0];",
        "VirtualProtect(p,4096,1,&old);return p[0];",
        "VirtualProtect(p,4096,2,&old);p[0]=5;",
        "VirtualFree(p,0,0x8000);ha_write(p,1);",
        "VirtualFree(p,0,0x4000);ha_read(p,1);",
        "VirtualProtect(p,4096,2,&old);ha_read(p,1);",
        'VirtualProtect(p,4096,2,&old);GetEnvironmentVariableA("X",(char*)p,8);',
        "VirtualProtect(p,4096,1,&old);ha_write(p,1);",
        "VirtualProtect(p+4096,4096,1,&old);ha_write(p+4095,2);",
        "VirtualProtect(p+4096,4096,2,&old);ha_read(p+4095,2);",
        "VirtualProtect(p,4096,2,&old);WriteFile(GetStdHandle((ha_dword)-11),p+4096,0,(ha_dword*)p,0);",
        'VirtualProtect(p,4096,2,&old);void *f=CreateFileA("input.bin",0x80000000,0,0,3,128,0);ReadFile(f,p,1,&old,0);',
        'VirtualProtect(p,4096,1,&old);void *f=CreateFileA("out.bin",0x40000000,0,0,2,128,0);WriteFile(f,p,1,&old,0);',
        "((void(*)(void))p)();",
    ],
)
def test_inaccessible_cpu_and_api_buffers_never_pass_even_against_self(tmp_path, body):
    source = (
        "int ha_main(void){volatile unsigned char *p=VirtualAlloc(0,8192,0x3000,4);ha_dword old=0;"
        + body
        + "return 0;}"
    )
    image = compile_source(tmp_path, source)
    result = compare(
        image,
        image,
        [
            {
                "input_hex": "0102",
                "env": {"X": "value"},
                "files": {"input.bin": "ff"},
                "effect_policy": "observable",
            }
        ],
    )
    assert not result["passed"], result
    assert result["cases"][0]["original"]["status"] == "fault", result


@pytest.mark.parametrize(
    "body",
    [
        "VirtualAlloc((void*)65536,4096,0x3000,4);",
        "VirtualAlloc(0,4096,0x3000,64);",
        "VirtualAlloc(0,4096,0x103000,4);",
        "VirtualAlloc(0,0,0x3000,4);",
        "VirtualAlloc(0,16777217,0x3000,4);",
        "VirtualProtect(p,1,0x104,&old);",
        "VirtualProtect(p,1,2,(ha_dword*)p);",
        "VirtualFree(p,4096,0x8000);",
        "VirtualFree(p+1,0,0x8000);",
        "VirtualFree(p+1,0,0x4000);",
        "VirtualFree(p,0,0xC000);",
        "VirtualProtect((void*)GetCommandLineA(),1,4,&old);",
        "VirtualAlloc(p+8192,4096,0x1000,4);",
        "VirtualProtect(p,1,2,&old);VirtualAlloc(p,1,0x1000,4);",
    ],
)
def test_unmodeled_virtual_memory_does_not_fall_back_to_upstream(tmp_path, body):
    image = compile_source(
        tmp_path,
        "int ha_main(void){char *p=VirtualAlloc(0,8192,0x3000,4);ha_dword old=0;"
        + body
        + "return 0;}",
    )
    result = replay(image)
    assert result["status"] == "unsupported", result


def test_reservation_budget_is_not_reset_by_release(tmp_path):
    image = compile_source(
        tmp_path,
        "int ha_main(void){for(int i=0;i<17;i++){void *p=VirtualAlloc(0,1048576,0x2000,4);VirtualFree(p,0,0x8000);}return 0;}",
    )
    assert replay(image)["status"] == "budget_exhausted"


def test_observable_policy_allows_different_allocation_strategies(tmp_path):
    image = compile_source(
        tmp_path,
        "int ha_main(void){char *p=VirtualAlloc(0,64,0x3000,4);p[0]=7;ha_write(p,1);VirtualFree(p,0,0x8000);return 0;}",
    )
    other = compile_source(
        tmp_path, "int ha_main(void){char c=7;ha_write(&c,1);return 0;}"
    )
    assert not compare(image, other, [{}])["passed"]
    assert compare(image, other, [{"effect_policy": "observable"}])["passed"]


@pytest.mark.parametrize(
    "operation",
    [
        "ha_read((void*)value,1);",
        'GetEnvironmentVariableA("X",(char*)value,4);',
        'WriteFile(GetStdHandle((ha_dword)-11),"",0,(ha_dword*)value,0);',
        "void *p=VirtualAlloc(0,4096,0x3000,4);VirtualProtect(p,4096,2,(ha_dword*)value);",
    ],
)
def test_api_buffer_cannot_modify_readonly_image_section(tmp_path, operation):
    image = compile_source(
        tmp_path,
        'const char value[4]="abc";int ha_main(void){'
        + operation
        + "ha_write(value,3);return 0;}",
    )
    result = replay(image, b"X", env={"X": "xy"})
    assert result["status"] == "fault", result
