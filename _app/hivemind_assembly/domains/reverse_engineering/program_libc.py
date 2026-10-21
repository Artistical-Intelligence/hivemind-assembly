"""Pinned musl memory routines for freestanding generated program images.

Only pure memory operations are linked. They execute as guest instructions and
inherit the existing CPU/memory bounds; no host libc or additional OS API is used.
Weak vendor definitions let supplied candidate definitions retain precedence.
"""

import hashlib
import json
from pathlib import Path

from hivemind_assembly.core.common import Blocked, canonical

HEADER = """
void *memcpy(void *restrict, const void *restrict, ha_size);
void *memmove(void *, const void *, ha_size);
void *memset(void *, int, ha_size);
int memcmp(const void *, const void *, ha_size);
"""
VENDOR = Path(__file__).resolve().parents[2] / "vendor" / "musl"
DIGESTS = {
    "COPYRIGHT": "b870108ec5e7790e9f9919064f1b9421d62d5f9b0e6c230c6adf7ea2da62e97b",
    "memcpy.c": "1664d565f968b053ac33c5ac615c057a255a5821c8fa510fba61d4f63dee08e9",
    "memmove.c": "1304f9ddfc18594f5d9a84691892b9fdaf3be8ecc6d7f365c691abb138eaf74e",
    "memset.c": "2a74d9e7f988945e0d691d480b78d77a228da0d2be401c1000637cc879b2c0be",
    "memcmp.c": "826b1b5e84d3c0fb68be827c051f6dc0d67da17ee3a444e94be0e5360586916f",
}
# These private headers supply compiler-defined ABI types, not host headers.
# Only vendor translation units include them. Candidate declarations stay strong.
INCLUDES = {
    "string.h": """typedef __SIZE_TYPE__ size_t;
void *memcpy(void *restrict, const void *restrict, size_t);
void *memmove(void *, const void *, size_t);
void *memset(void *, int, size_t);
int memcmp(const void *, const void *, size_t);
""",
    "stdint.h": """typedef __UINT32_TYPE__ uint32_t;
typedef __UINT64_TYPE__ uint64_t;
typedef __UINTPTR_TYPE__ uintptr_t;
""",
    "endian.h": """#define __BYTE_ORDER __BYTE_ORDER__
#define __LITTLE_ENDIAN __ORDER_LITTLE_ENDIAN__
""",
}


def stage(root):
    """Verify upstream bytes and stage deterministic sources; return names/hash."""
    files = {}
    for name, expected in DIGESTS.items():
        value = (VENDOR / name).read_bytes()
        if hashlib.sha256(value).hexdigest() != expected:
            raise Blocked("Bundled memory runtime integrity failure: " + name)
        files[name] = value
    include = root / "memory_include"
    include.mkdir()
    for name, value in INCLUDES.items():
        (include / name).write_bytes(value.encode("utf-8"))
    paths = []
    for name, value in files.items():
        if name.endswith(".c"):
            local = "ha_" + name
            # Mark only this definition weak. Marking references weak as well
            # creates duplicate COFF weak aliases when memmove calls memcpy.
            declaration = next(
                line for line in HEADER.splitlines() if name[:-2] + "(" in line
            )
            prefix = declaration.removesuffix(";").replace("ha_size", "__SIZE_TYPE__")
            prefix += " __attribute__((weak));\n"
            (root / local).write_bytes(prefix.encode() + value)
            paths.append(local)
    notice = "const char ha_memory_runtime_notice[] = "
    notice += json.dumps(files["COPYRIGHT"].decode("utf-8")) + ";\n"
    (root / "ha_memory_notice.c").write_bytes(notice.encode("ascii"))
    paths.append("ha_memory_notice.c")
    digest = hashlib.sha256(
        canonical(
            {
                "public_header": HEADER,
                "includes": INCLUDES,
                "staged_sources": {
                    name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                    for name in paths
                },
            }
        ).encode()
    ).hexdigest()
    return paths, digest


def verify_notice(image):
    notice = (VENDOR / "COPYRIGHT").read_bytes()
    if (
        hashlib.sha256(notice).hexdigest() != DIGESTS["COPYRIGHT"]
        or notice not in image
    ):
        raise Blocked("Generated image is missing its pinned memory-runtime notice")
