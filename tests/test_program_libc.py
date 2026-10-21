"""Compiler-generated memory calls and reused musl code, with independent bytes."""

import os
import shutil
import struct
import subprocess

import pytest
from native_fixtures import LINUX_ORACLE, elf_compiler
from hivemind_assembly.core.common import Blocked
from hivemind_assembly.core.jobs import Jobs
from hivemind_assembly.domains.reverse_engineering import (
    program,
    windows_program,
    program_libc,
)
from test_windows_program import compiler

GCC = pytest.param(
    "gcc",
    marks=pytest.mark.skipif(
        os.name == "nt" or not shutil.which("gcc"), reason="Requires native Linux GCC"
    ),
)

# One instruction stream exercises short/word/unaligned sizes and both overlap
# directions; expected bytes come from Python snapshots, not the C algorithm.
SOURCE = """int ha_main(void) {
    unsigned char a[384], b[384], op[8];
    while (ha_read(op, 8) == 8) {
        for (int i=0;i<384;i++) { a[i]=(unsigned char)(i*3+129); b[i]=(unsigned char)(i*7+3); }
        unsigned n=op[1] | ((unsigned)op[2]<<8), d=op[3], s=op[4];
        if (d+n>384 || s+n>384) return 8;
        void *r=a+d;
        unsigned char sign=1;
        if (op[0]==0) r=memcpy(a+d,b+s,n);
        else if (op[0]==1) r=memset(a+d,op[5],n);
        else if (op[0]==2) r=memmove(a+d,a+s,n);
        else { int c=memcmp(a+d,b+s,n); sign=c<0?0:c>0?2:1; }
        if(r!=a+d) return 9;
        ha_write(&sign,1); ha_write(a,384);
    }
    return 0;
}"""


def corpus():
    data, expected = bytearray(), bytearray()
    sizes = [0, 1, 2, 3, 4, 7, 8, 15, 16, 17, 31, 32, 33, 64, 255, 256]
    for i, n in enumerate(sizes):
        for op in range(4):
            d, s = ((i * 7) % 32, (i * 11 + 1) % 32)
            data.extend(struct.pack("<B H B B B B B", op, n, d, s, 0xE1, 0, 0))
            a = bytearray((j * 3 + 129) % 256 for j in range(384))
            b = bytes((j * 7 + 3) % 256 for j in range(384))
            sign = 1
            if op == 0:
                a[d : d + n] = b[s : s + n]
            elif op == 1:
                a[d : d + n] = bytes([0xE1]) * n
            elif op == 2:
                a[d : d + n] = bytes(a[s : s + n])
            else:
                left, right = bytes(a[d : d + n]), b[s : s + n]
                sign = 0 if left < right else 2 if left > right else 1
            expected.extend(bytes([sign]) + a)
    return bytes(data), bytes(expected)


def compile_at(root, code, lane, optimization="O2"):
    root.mkdir(exist_ok=True)
    (root / "main.c").write_text(code)
    manifest = {"sources": ["main.c"], "optimization": optimization}
    if lane == "windows":
        result = windows_program.build(root, manifest, Jobs(), compiler())
        key = "pe_hex"
    else:
        manifest["architecture"] = "aarch64" if lane == "arm" else "x86_64"
        cc = elf_compiler() if lane == "gcc" else compiler()
        result = program.build(root, manifest, Jobs(), cc)
        key = "elf_hex"
    assert result["passed"], result
    image = bytes.fromhex(result[key])
    assert (program_libc.VENDOR / "COPYRIGHT").read_bytes() in image
    assert len(result["memory_runtime_sha256"]) == 64
    return image


@pytest.mark.parametrize("lane", ["windows", "clang", GCC, "arm"])
@pytest.mark.parametrize("optimization", ["O0", "O2"])
def test_memory_routines_match_independent_snapshot_oracle(
    tmp_path, lane, optimization
):
    image = compile_at(tmp_path, SOURCE, lane, optimization)
    data, expected = corpus()
    replay = windows_program.replay if lane == "windows" else program.replay
    # Each replay retains the product's wall/instruction limits. An O0 ARM
    # build can exceed the wall limit on a hosted runner if all 64 independent
    # commands share one replay. Bound each batch without dropping any cases.
    for first in range(0, len(data) // 8, 8):
        batch = data[first * 8 : (first + 8) * 8]
        result = replay(image, batch, max_instructions=5_000_000)
        assert result["status"] == "completed", result
        assert result["exit_code"] == 0
        assert bytes.fromhex(result["stdout_hex"]) == expected[
            first * 385 : (first + 8) * 385
        ]
        assert result["input_consumed"] == len(batch)


IMPLICIT = """struct Block {unsigned char bytes[768];};
struct Block stored;
int ha_main(void) {
    struct Block initial={{0}};
    ha_read(initial.bytes,768);
    stored=initial;
    struct Block output=stored;
    ha_write(output.bytes,768);
    return 0;
}"""


@pytest.mark.parametrize("lane", ["windows", "clang", GCC, "arm"])
@pytest.mark.parametrize("optimization", ["O0", "O2"])
def test_compiler_generated_zero_initialization_and_struct_copy(
    tmp_path, lane, optimization
):
    image = compile_at(tmp_path, IMPLICIT, lane, optimization)
    replay = windows_program.replay if lane == "windows" else program.replay
    result = replay(image, b"implicit calls\xff")
    assert result["status"] == "completed", result
    assert bytes.fromhex(result["stdout_hex"]) == b"implicit calls\xff" + bytes(753)


@pytest.mark.parametrize("lane", ["windows", "clang", GCC, "arm"])
def test_candidate_memory_definition_takes_precedence(tmp_path, lane):
    code = """void *memset(void *d,int c,ha_size n) {
        volatile unsigned char *p=d;
        for(ha_size i=0;i<n;i++)p[i]=(unsigned char)(c^85);
        return d;
    }
    int ha_main(void){unsigned char a[32];memset(a,3,32);ha_write(a,32);return 0;}"""
    image = compile_at(tmp_path, code, lane)
    replay = windows_program.replay if lane == "windows" else program.replay
    result = replay(image)
    assert result["status"] == "completed", result
    assert result["stdout_hex"] == bytes([3 ^ 85] * 32).hex()
    # A strong memcpy must also win when musl memmove calls it for disjoint data.
    code = """void *memcpy(void *d,const void *s,ha_size n) {
        volatile unsigned char *p=d;
        for(ha_size i=0;i<n;i++)p[i]=77;
        return d;
    }
    int ha_main(void){unsigned char a[32],b[32];memmove(a,b,32);ha_write(a,32);return 0;}"""
    image = compile_at(tmp_path, code, lane)
    result = replay(image)
    assert result["status"] == "completed", result
    assert result["stdout_hex"] == bytes([77] * 32).hex()


@pytest.mark.parametrize("lane", ["windows", "clang", "arm"])
@pytest.mark.parametrize("operation", ["memcpy", "memmove", "memset", "memcmp"])
def test_guard_page_boundary_and_invalid_access(tmp_path, operation, lane):
    call = {
        "memcpy": "memcpy(b,p+4096-n,n)",
        "memmove": "memmove(p+4096-n,p+4096-n-1,n)",
        "memset": "memset(p+4096-n,129,n)",
        "memcmp": "memcmp(p+4096-n,b,n)",
    }[operation]
    code = """int ha_main(void){unsigned char b[256];
        unsigned char *p=VirtualAlloc(0,8192,0x3000,4);ha_dword old;
        if(!p || !VirtualProtect(p+4096,4096,1,&old))return 5;
        for(int i=0;i<256;i++)b[i]=0;
        unsigned char sizes[8]={1,3,7,15,17,31,33,255};
        for(int i=0;i<8;i++){ha_size n=sizes[i];CALL;}
        return 0;}""".replace(
        "CALL", call
    )
    if lane != "windows":
        code = code.replace(
            "unsigned char *p=VirtualAlloc(0,8192,0x3000,4);ha_dword old;\n        if(!p || !VirtualProtect(p+4096,4096,1,&old))return 5;",
            "unsigned char *p=ha_map(8192); if(ha_unmap(p+4096,4096))return 5;",
        )
        from hivemind_assembly.domains.reverse_engineering.platform_runtime import (
            replay,
        )
    else:
        replay = windows_program.replay
    image = compile_at(tmp_path, code, lane)
    result = replay(image)
    assert result["status"] == "completed", result
    # Explicitly cross the protected page. The routine may not bypass guest permissions.
    bad_call = {
        "memcpy": "memcpy(b,p+4095,2)",
        "memmove": "memmove(p+4095,p,2)",
        "memset": "memset(p+4095,129,2)",
        "memcmp": "memcmp(p+4095,p+4094,2)",
    }[operation]
    bad = compile_at(tmp_path, code.replace(call, bad_call), lane)
    assert replay(bad)["status"] == "fault"


@LINUX_ORACLE
def test_native_linux_memory_execution(tmp_path):
    data, expected = corpus()
    image = compile_at(tmp_path, SOURCE, "gcc")
    path = tmp_path / "native"
    path.write_bytes(image)
    path.chmod(0o700)
    result = subprocess.run([str(path)], input=data, capture_output=True, timeout=10)
    assert result.returncode == 0 and result.stdout == expected


@pytest.mark.skipif(os.name != "nt", reason="Native Windows memory execution")
def test_native_windows_memory_execution(tmp_path):
    data, expected = corpus()
    image = compile_at(tmp_path, SOURCE, "windows")
    path = tmp_path / "native.exe"
    path.write_bytes(image)
    incoming = tmp_path / "in"
    incoming.write_bytes(data)
    with incoming.open("rb") as source, (tmp_path / "out").open("wb") as out:
        result = subprocess.run(
            [str(path)], stdin=source, stdout=out, capture_output=False, timeout=10
        )
    assert result.returncode == 0 and (tmp_path / "out").read_bytes() == expected


def test_memory_runtime_integrity_fails_closed(tmp_path, monkeypatch):
    vendor = tmp_path / "vendor"
    shutil.copytree(program_libc.VENDOR, vendor)
    monkeypatch.setattr(program_libc, "VENDOR", vendor)
    (vendor / "memcpy.c").write_text("bad source")
    with pytest.raises(Blocked, match="integrity"):
        program_libc.stage(tmp_path)
