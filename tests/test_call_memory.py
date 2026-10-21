"""Memory helpers in linked reconstruction, checked against Python snapshots."""

import copy
import os
import shutil

import pytest

from hivemind_assembly.core.jobs import Jobs
from hivemind_assembly.domains.reverse_engineering import call_images as calls
from hivemind_assembly.domains.reverse_engineering import program_libc

CLANG = os.environ.get("HA_TEST_CLANG") or shutil.which("clang")
pytestmark = pytest.mark.skipif(not CLANG, reason="Clang required; set HA_TEST_CLANG")
LANES = [(abi, "clang") for abi in calls.ABIS] + [
    pytest.param(
        "sysv",
        "gcc",
        marks=pytest.mark.skipif(
            os.name == "nt" or not shutil.which("gcc"),
            reason="Native Linux GCC required",
        ),
    )
]


def build(root, code, abi, compiler, optimization="O2"):
    (root / "f.c").write_text(code)
    built = calls.build(
        root,
        {"sources": ["f.c"], "optimization": optimization},
        "f",
        abi,
        Jobs(),
        CLANG if compiler == "clang" else shutil.which("gcc"),
    )
    assert built["passed"], built
    raw = bytes.fromhex(built["image_hex"])
    assert (program_libc.VENDOR / "COPYRIGHT").read_bytes() in raw
    assert len(built["memory_runtime_sha256"]) == 64
    return calls.load(raw, symbol="f")


@pytest.mark.parametrize("abi,compiler", LANES)
@pytest.mark.parametrize("optimization", ["O0", "O2"])
def test_linked_implicit_copies_overlap_and_bounds(
    tmp_path, abi, compiler, optimization
):
    image = build(
        tmp_path,
        """
struct Block {unsigned char bytes[768];};
unsigned f(struct Block *out, const unsigned char *input, unsigned n) {
    struct Block initial={{0}};
    if (n>512) return 99;
    memcpy(initial.bytes,input,n);
    memmove(initial.bytes+3,initial.bytes,n);
    memset(initial.bytes+n+3,0xe1,5);
    *out=initial;
    return memcmp(out->bytes+3,input,n);
}
""",
        abi,
        compiler,
        optimization,
    )
    for n in [0, 1, 3, 7, 15, 17, 31, 33, 255, 512]:
        data = bytes((i * 7 + 129) % 256 for i in range(max(n, 1)))
        expected = bytearray(768)
        expected[:n] = data[:n]
        expected[3 : 3 + n] = bytes(expected[:n])
        expected[n + 3 : n + 8] = bytes([0xE1]) * 5
        case = {
            "arguments": [{"buffer": "out"}, {"buffer": "in"}, n],
            "buffers": [
                {"id": "out", "hex": bytes([0xCC] * 768).hex()},
                {"id": "in", "hex": data.hex(), "permissions": "r"},
            ],
            "output_bits": 32,
        }
        result = calls.execute(image, case)
        assert result["status"] == "completed" and result["abi_ok"], result
        assert result["value"] == 0
        assert result["buffers"]["out"] == expected.hex()
        assert result["buffers"]["in"] == data.hex()
    # A mapped page must not grant permission outside the declared buffer.
    for invalid in [
        dict(case["buffers"][0], permissions="r"),
        {"id": "out", "hex": "00"},
    ]:
        bad = copy.deepcopy(case)
        bad["buffers"][0] = invalid
        assert calls.execute(image, bad)["status"] != "completed"


@pytest.mark.parametrize("abi,compiler", LANES)
def test_linked_candidate_helpers_take_precedence(tmp_path, abi, compiler):
    image = build(
        tmp_path,
        """
void *memcpy(void *d, const void *s, __SIZE_TYPE__ n) {
    volatile unsigned char *p=d;
    for(__SIZE_TYPE__ i=0;i<n;i++)p[i]=77;
    return d;
}
void *memset(void *d, int c, __SIZE_TYPE__ n) {
    volatile unsigned char *p=d;
    for(__SIZE_TYPE__ i=0;i<n;i++)p[i]=(unsigned char)(c^85);
    return d;
}
unsigned f(unsigned char *out, const unsigned char *input) {
    memset(out,3,64);
    memmove(out+16,input,32);
    return 0;
}
""",
        abi,
        compiler,
    )
    result = calls.execute(
        image,
        {
            "arguments": [{"buffer": "out"}, {"buffer": "in"}],
            "buffers": [
                {"id": "out", "hex": bytes(64).hex()},
                {"id": "in", "hex": bytes(range(32)).hex(), "permissions": "r"},
            ],
        },
    )
    assert result["status"] == "completed" and result["abi_ok"], result
    assert (
        result["buffers"]["out"]
        == (bytes([3 ^ 85]) * 16 + bytes([77]) * 32 + bytes([3 ^ 85]) * 16).hex()
    )
