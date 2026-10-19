"""Compile freestanding C functions and compare them with original machine code.

Candidate machine code runs only inside Unicorn. This bounded SysV x86-64 lane
supports scalar arguments, branches, loops and private stack use, not OS calls,
external symbols or pointer arguments. Passing samples are not an all-input proof.
"""

import hashlib
import itertools
import random
import re
import shutil
import struct
import tempfile
from pathlib import Path

from hivemind_assembly.core.common import Blocked, ContractError, file_hash, uid
from .semantics import run_reference

ARGUMENTS = ("RDI", "RSI", "RDX", "RCX", "R8", "R9")
PRESERVED = ("RBX", "RBP", "R12", "R13", "R14", "R15")


def extract_function(data, name):
    """Extract a defined function from an ELF64 relocatable object, fail closed."""
    if len(data) < 64 or data[:7] != b"\x7fELF\x02\x01\x01":
        raise ContractError("Compiler must produce little-endian ELF64")
    header = struct.unpack_from("<16sHHIQQQIHHHHHH", data)
    if header[1:3] != (1, 62):
        raise ContractError("Expected a relocatable x86-64 object")
    offset, entry_size, count = header[6], header[11], header[12]
    if entry_size != 64 or not 1 <= count <= 4096:
        raise ContractError("Invalid object section table")

    def bounded(start, size):
        if start < 0 or size < 0 or start + size > len(data):
            raise ContractError("Object range exceeds file")
        return data[start : start + size]

    sections = [
        struct.unpack("<IIQQQQIIQQ", bounded(offset + i * 64, 64)) for i in range(count)
    ]
    found = []
    for section in sections:
        if section[1] != 2:  # SHT_SYMTAB
            continue
        if section[9] != 24 or section[5] % 24 or section[6] >= count:
            raise ContractError("Invalid symbol table")
        strings = sections[section[6]]
        names = bounded(strings[4], strings[5])
        symbols = bounded(section[4], section[5])
        for pos in range(0, len(symbols), 24):
            n, info, _, index, start, size = struct.unpack_from("<IBBHQQ", symbols, pos)
            if n >= len(names):
                raise ContractError("Invalid symbol name")
            if names[n:].split(b"\0", 1)[0] == name.encode() and info & 15 == 2:
                found.append((index, start, size))
    if len(found) != 1:
        raise ContractError(
            "Exactly one defined function with the requested name is required"
        )
    index, start, size = found[0]
    if not 0 < index < count or not 1 <= size <= 16384:
        raise ContractError("Function must contain 1–16384 bytes")
    section = sections[index]
    if not section[2] & 4 or start + size > section[5]:
        raise ContractError("Function must be contained in an executable section")
    for reloc in sections:
        if reloc[1] not in (4, 9) or reloc[7] != index:
            continue
        stride = 24 if reloc[1] == 4 else 16
        if reloc[9] != stride or reloc[5] % stride:
            raise ContractError("Invalid relocation table")
        entries = bounded(reloc[4], reloc[5])
        for pos in range(0, len(entries), stride):
            target = struct.unpack_from("<Q", entries, pos)[0]
            if start <= target < start + size:
                raise Blocked(
                    "Function requires relocation, external data or another function"
                )
    return bounded(section[4] + start, size)


def compile_function(source, function, jobs, compiler="", cancel=None):
    if not isinstance(function, str) or not re.fullmatch(
        r"[A-Za-z_][A-Za-z_0-9]{0,99}", function
    ):
        raise ContractError("Invalid C function name")
    if not isinstance(source, str) or not 1 <= len(source.encode()) <= 128000:
        raise ContractError("C source must contain 1–128000 bytes")
    # Keep this lane self-contained: no headers, file inclusion or inline assembly.
    if "#" in source or re.search(r"\b(?:asm|__asm|__asm__)\b", source):
        raise Blocked(
            "Freestanding function validation does not allow preprocessor directives or inline assembly"
        )
    executable = (
        shutil.which(compiler)
        if compiler
        else (shutil.which("clang") or shutil.which("gcc"))
    )
    if not executable:
        raise Blocked("Install Clang or GCC, or configure foundations.c_compiler")
    compiler_hash = file_hash(executable)
    with tempfile.TemporaryDirectory(prefix="hivemind-build-") as directory:
        root = Path(directory)
        (root / "candidate.c").write_text(source, encoding="utf-8")
        argv = [executable]
        if "clang" in Path(executable).name.lower():
            argv += ["--target=x86_64-unknown-linux-gnu"]
        argv += [
            "-m64",
            "-std=c11",
            "-O2",
            "-ffreestanding",
            "-fno-builtin",
            "-fno-stack-protector",
            "-fno-asynchronous-unwind-tables",
            "-fno-unwind-tables",
            "-fno-pic",
            "-fno-pie",
            "-nostdinc",
            "-c",
            "candidate.c",
            "-o",
            "candidate.o",
        ]
        built = jobs.run(uid("build"), argv, root, timeout=30, cancel=cancel)
        if built["status"] != "completed" or built["exit_code"] != 0:
            return {"passed": False, "stage": "compile", "build": built}
        obj = root / "candidate.o"
        if not obj.exists() or obj.stat().st_size > 2_000_000:
            raise Blocked("Compiler output missing or too large")
        data = obj.read_bytes()
        code = extract_function(data, function)
        if file_hash(executable) != compiler_hash:
            raise Blocked("Compiler changed during build")
        return {
            "passed": True,
            "stage": "compiled",
            "machine_hex": code.hex(),
            "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
            "object_sha256": hashlib.sha256(data).hexdigest(),
            "compiler_sha256": compiler_hash,
            "compiler": str(executable),
            "build": built,
        }


def vectors(widths, seed, count=64):
    if (
        not isinstance(widths, list)
        or not 0 <= len(widths) <= 6
        or any(type(w) is not int or w not in (32, 64) for w in widths)
    ):
        raise ContractError("Use 0–6 unsigned scalar arguments of 32 or 64 bits")
    if not widths:
        return [[]]
    values = [[0, 1, (1 << (w - 1)) - 1, 1 << (w - 1), (1 << w) - 1] for w in widths]
    cases = [list(v) for v in itertools.islice(itertools.product(*values), 25)]
    # Exercise each argument's boundaries even for larger signatures.
    for i, choices in enumerate(values):
        for value in choices:
            row = [0] * len(widths)
            row[i] = value
            cases.append(row)
    rng = random.Random(seed)
    cases += [[rng.getrandbits(w) for w in widths] for _ in range(count)]
    return list(dict.fromkeys(tuple(c) for c in cases))


def execute_function(code, arguments, output_bits):
    if not 1 <= len(code) <= 16384:
        raise ContractError("Function code must contain 1–16384 bytes")
    if output_bits not in (32, 64) or type(output_bits) is not int:
        raise ContractError("Return width must be 32 or 64 bits")
    stack, stop = 0x200000, 0x400000
    rsp = stack + 0xFFF8
    stack_data = bytearray(65536)
    stack_data[-8:] = stop.to_bytes(8, "little")
    registers = {k: 0x55AA0000 + i for i, k in enumerate(PRESERVED)}
    registers.update(dict(zip(ARGUMENTS, arguments)))
    registers["RSP"] = rsp
    case = {
        "start": 0x1000,
        "stop": stop,
        "max_instructions": 10000,
        "code_ranges": [[0x1000, 0x1000 + len(code)]],
        "registers": registers,
        "memory": [
            {"address": 0x1000, "size": 16384, "hex": code.hex(), "permissions": "rx"},
            {
                "address": stack,
                "size": 65536,
                "hex": stack_data.hex(),
                "permissions": "rw",
            },
            {"address": stop, "size": 4096, "hex": "90", "permissions": "rx"},
        ],
    }
    result = run_reference(case)
    abi_ok = result["registers"]["RSP"] == rsp + 8 and all(
        result["registers"][k] == registers[k] for k in PRESERVED
    )
    return {
        "status": result["status"],
        "value": result["registers"]["RAX"] & ((1 << output_bits) - 1),
        "abi_ok": abi_ok,
        "fault": result["fault"],
        "instructions": len(result["trace"]),
    }


def compare_functions(original, candidate, cases, output_bits, cancel=None):
    failures = []
    for index, arguments in enumerate(cases):
        if cancel is not None and cancel.is_set():
            raise Blocked("Function validation cancelled")
        reference = execute_function(original, arguments, output_bits)
        result = execute_function(candidate, arguments, output_bits)
        passed = (
            reference["status"] == result["status"] == "completed"
            and reference["abi_ok"]
            and result["abi_ok"]
            and reference["value"] == result["value"]
        )
        if not passed:
            failures.append(
                {
                    "index": index,
                    "arguments": list(arguments),
                    "original": reference,
                    "candidate": result,
                }
            )
            if len(failures) >= 8:
                return {
                    "passed": False,
                    "tested": index + 1,
                    "total": len(cases),
                    "failures": failures,
                }
    return {
        "passed": not failures,
        "tested": len(cases),
        "total": len(cases),
        "failures": failures,
    }
