"""Linked function replay: x86-64 and AArch64 ELF/PE, with bounded buffers.

Uses pefile/pyelftools for symbols and Unicorn for execution. No DLL loading,
initializers, OS imports, TLS, exceptions or host execution is implied. Each case
starts from the image's on-disk state. Every permitted external write is observed.
"""

import hashlib
import io
import re
import shutil
import tempfile
from pathlib import Path

from hivemind_assembly.core.common import Blocked, ContractError, file_hash, uid, digest
from .program import sources, load_image as load_elf
from .semantics import run_reference
from . import program_libc

ABIS = {
    "sysv": (
        ("RDI", "RSI", "RDX", "RCX", "R8", "R9"),
        ("RBX", "RBP", "R12", "R13", "R14", "R15"),
        0,
    ),
    "win64": (
        ("RCX", "RDX", "R8", "R9"),
        ("RBX", "RBP", "RDI", "RSI", "R12", "R13", "R14", "R15"),
        32,
    ),
    "aapcs64": (
        tuple("X" + str(i) for i in range(8)),
        tuple("X" + str(i) for i in range(19, 30)),
        0,
    ),
}
ABIS["winarm64"] = ABIS["aapcs64"]  # Non-variadic integer/pointer calls only.
ARM_ABIS = ("aapcs64", "winarm64")
PE_ABIS = ("win64", "winarm64")
STACK, STOP, BUFFERS = 0x70000000, 0x71000000, 0x60000000
MAX_IMAGE = 2_000_000


def function_name(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z_][A-Za-z_0-9]{0,99}", value
    ):
        raise ContractError("A C function symbol is required")
    return value


def load(data, symbol=None, address=None, *, _imports_resolved=False):
    """Load at linked addresses; never guess an ABI or relocate untrusted input."""
    if not isinstance(data, bytes) or not 1 <= len(data) <= MAX_IMAGE:
        raise ContractError("Image must contain 1–2000000 bytes")
    if (symbol is None) == (address is None):
        raise ContractError("Select exactly one function symbol or absolute address")
    if symbol is not None:
        function_name(symbol)
    if address is not None and (type(address) is not int or address < 0):
        raise ContractError("Function address must be an unsigned integer")
    segments, matches = [], []
    if data.startswith(b"\x7fELF"):
        from elftools.elf.elffile import ELFFile

        machine = int.from_bytes(data[18:20], "little")
        if machine not in (62, 183):
            raise Blocked("Linked ELF calls support x86-64 or little-endian AArch64")
        _, parts = load_elf(data, machine=machine)
        base = min(s["address"] for s in parts)
        elf = ELFFile(io.BytesIO(data))
        if any(s["p_type"] == "PT_TLS" for s in elf.iter_segments()):
            raise Blocked("TLS requires a separately modeled runtime")
        for s in parts:
            segments.append(
                {
                    "address": s["address"],
                    "size": s["size"],
                    "hex": s["data"].hex(),
                    "file_offset": s["file_offset"],
                    "permissions": "".join(
                        p
                        for bit, p in ((4, "r"), (2, "w"), (1, "x"))
                        if s["flags"] & bit
                    ),
                }
            )
        if symbol:
            for section in elf.iter_sections():
                if section["sh_type"] not in ("SHT_SYMTAB", "SHT_DYNSYM"):
                    continue
                for item in section.iter_symbols():
                    if (
                        item.name == symbol
                        and item["st_info"]["type"] == "STT_FUNC"
                        and item["st_shndx"] != "SHN_UNDEF"
                    ):
                        matches.append(item["st_value"])
        abi = "aapcs64" if machine == 183 else "sysv"
    elif data.startswith(b"MZ"):
        import pefile

        try:
            pe = pefile.PE(data=data, fast_load=False)
        except pefile.PEFormatError as e:
            raise ContractError("Invalid PE image") from e
        h = pe.OPTIONAL_HEADER
        if pe.FILE_HEADER.Machine not in (0x8664, 0xAA64) or h.Magic != 0x20B:
            raise Blocked(
                "Only standard PE32+ x86-64 or ARM64 images are supported; ARM64EC/ARM64X are not"
            )
        base = h.ImageBase
        if (
            base % 4096
            or base < 0x10000
            or base + h.SizeOfImage >= 2**47
            or not 1 <= h.SizeOfImage <= 32_000_000
            or not 1 <= len(pe.sections) <= 128
            or h.SectionAlignment < 4096
        ):
            raise ContractError("Invalid PE image layout or bounds")
        # These need loader/runtime semantics, not just executable memory.
        if (
            getattr(pe, "DIRECTORY_ENTRY_TLS", None)
            or (getattr(pe, "DIRECTORY_ENTRY_IMPORT", None) and not _imports_resolved)
            or getattr(pe, "DIRECTORY_ENTRY_DELAY_IMPORT", None)
        ):
            raise Blocked("PE imports or TLS require a separately modeled runtime")
        if h.SizeOfHeaders > len(data) or h.SizeOfHeaders > h.SizeOfImage:
            raise ContractError("Invalid PE headers")
        segments.append(
            {
                "address": base,
                "size": h.SizeOfHeaders,
                "hex": data[: h.SizeOfHeaders].hex(),
                "file_offset": 0,
                "permissions": "r",
            }
        )
        for s in pe.sections:
            size = max(s.Misc_VirtualSize, s.SizeOfRawData)
            if not size:
                continue
            if (
                s.VirtualAddress + size > h.SizeOfImage
                or s.PointerToRawData + s.SizeOfRawData > len(data)
            ):
                raise ContractError("PE section exceeds image or file")
            segments.append(
                {
                    "address": base + s.VirtualAddress,
                    "size": size,
                    "hex": data[
                        s.PointerToRawData : s.PointerToRawData + s.SizeOfRawData
                    ].hex(),
                    "file_offset": s.PointerToRawData,
                    "permissions": "".join(
                        p
                        for bit, p in (
                            (0x40000000, "r"),
                            (0x80000000, "w"),
                            (0x20000000, "x"),
                        )
                        if s.Characteristics & bit
                    ),
                }
            )
        if symbol:
            for item in getattr(
                getattr(pe, "DIRECTORY_ENTRY_EXPORT", None), "symbols", ()
            ):
                if item.name == symbol.encode():
                    if item.forwarder:
                        raise Blocked("Forwarded exports require a DLL runtime")
                    matches.append(base + item.address)
        abi = "winarm64" if pe.FILE_HEADER.Machine == 0xAA64 else "win64"
    else:
        raise ContractError("Expected a linked ELF or PE image")
    if symbol:
        if len(set(matches)) != 1:
            raise ContractError("Exactly one defined function symbol is required")
        address = matches[0]
    if abi in ARM_ABIS and address % 4:
        raise ContractError("AArch64 function entry must be four-byte aligned")
    if not any(
        s["address"] <= address < s["address"] + s["size"] and "x" in s["permissions"]
        for s in segments
    ):
        raise ContractError("Function address is not executable")
    pages = set()
    for s in segments:
        start, end = s["address"] & ~4095, (s["address"] + s["size"] + 4095) & ~4095
        if s["size"] <= 0 or end - start > 32_000_000:
            raise ContractError("Invalid image mapping")
        if start < STOP + 4096 and end > BUFFERS:
            raise ContractError("Image overlaps replay memory")
        for p in range(start, end, 4096):
            if p in pages:
                raise ContractError("Overlapping image pages")
            pages.add(p)
    if len(pages) * 4096 > 32_000_000:
        raise ContractError("Image memory exceeds bounds")
    fingerprint = hashlib.sha256(data).hexdigest()
    for segment in segments:
        segment.update(image="program", image_base=base, image_sha256=fingerprint)
    return {
        "abi": abi,
        "entry": address,
        "segments": segments,
        "sha256": fingerprint,
    }


def build(root, manifest, function, abi, jobs, compiler="", cancel=None):
    function_name(function)
    if abi not in ABIS:
        raise ContractError("ABI must be sysv, win64, aapcs64 or winarm64")
    units = sources(root, manifest)
    if "architecture" in manifest and manifest["architecture"] != (
        "aarch64" if abi in ARM_ABIS else "x86_64"
    ):
        raise ContractError(
            "Manifest architecture conflicts with the selected calling convention"
        )
    executable = (
        shutil.which(compiler)
        if compiler
        else shutil.which("clang") or shutil.which("gcc")
    )
    if not executable:
        raise Blocked("Install a C compiler")
    clang = "clang" in Path(executable).name.lower()
    if abi != "sysv" and not clang:
        raise Blocked("Windows/AArch64 linked reconstruction requires Clang and LLD")
    fingerprint = file_hash(executable)
    hashes = {
        name: hashlib.sha256(text.encode()).hexdigest() for name, text in units.items()
    }
    with tempfile.TemporaryDirectory(prefix="ha-call-image-") as tmp:
        stage = Path(tmp)
        paths = []
        for index, text in enumerate(units.values()):
            name = f"unit_{index}.c"
            (stage / name).write_text(
                program_libc.HEADER.replace("ha_size", "__SIZE_TYPE__")
                + manifest.get("declarations", "")
                + "\n"
                + text,
                encoding="utf-8",
            )
            paths.append(name)
        memory_sources, memory_hash = program_libc.stage(stage)
        output = "candidate.dll" if abi in PE_ABIS else "candidate.elf"
        argv = [executable]
        if clang:
            argv += [
                "--target="
                + {
                    "win64": "x86_64-pc-windows-msvc",
                    "sysv": "x86_64-unknown-linux-gnu",
                    "aapcs64": "aarch64-unknown-linux-gnu",
                    "winarm64": "aarch64-pc-windows-msvc",
                }[abi],
                "-fuse-ld=lld",
            ]
        argv += ["-march=armv8-a", "-ffixed-x18"] if abi in ARM_ABIS else ["-m64"]
        if not clang:
            argv += ["-fno-tree-loop-distribute-patterns"]
        argv += [
            "-std=c11",
            "-" + manifest.get("optimization", "O2"),
            "-ffreestanding",
            "-fno-builtin",
            "-fno-stack-protector",
            "-nostdinc",
            "-Imemory_include",
            "-nostdlib",
            "-fno-asynchronous-unwind-tables",
            "-fno-unwind-tables",
        ]
        if abi in PE_ABIS:
            argv += [
                "-Wl,/dll,/noentry,/nodefaultlib,/fixed:no,/base:0x180000000,/timestamp:0",
                "-Wl,/export:" + function,
                "-Wl,/include:ha_memory_runtime_notice",
            ]
        else:
            argv += [
                "-static",
                "-fno-pic",
                "-fno-pie",
                "-Wl,--build-id=none,-e," + function,
                "-Wl,--undefined=ha_memory_runtime_notice",
            ]
            if not clang:
                argv += ["-no-pie"]
        argv += [*paths, *memory_sources, "-o", output]
        result = jobs.run(uid("linked-build"), argv, stage, timeout=60, cancel=cancel)
        if result["status"] != "completed" or result["exit_code"] != 0:
            return {"passed": False, "stage": "compile", "build": result}
        path = stage / output
        if not path.exists() or path.stat().st_size > MAX_IMAGE:
            raise Blocked("Missing or oversized linked image")
        data = path.read_bytes()
        program_libc.verify_notice(data)
        image = load(data, symbol=function)
        if image["abi"] != abi:
            raise Blocked("Compiler produced an image for a different ABI")
        if fingerprint != file_hash(executable):
            raise Blocked("Compiler changed during build")
        return {
            "passed": True,
            "stage": "linked",
            "abi": abi,
            "image_hex": data.hex(),
            "image_sha256": image["sha256"],
            "entry": image["entry"],
            "source_hashes": hashes,
            "manifest_sha256": digest(manifest),
            "compiler_sha256": fingerprint,
            "memory_runtime_sha256": memory_hash,
            "build": result,
        }


def validate_case(case):
    if not isinstance(case, dict) or set(case) - {
        "id",
        "arguments",
        "buffers",
        "output_bits",
        "max_instructions",
    }:
        raise ContractError("Unknown linked-call case field")
    args, buffers = case.get("arguments", []), case.get("buffers", [])
    if (
        not isinstance(args, list)
        or len(args) > 16
        or not isinstance(buffers, list)
        or len(buffers) > 16
    ):
        raise ContractError("At most 16 arguments and buffers are supported")
    ids = set()
    for buf in buffers:
        if not isinstance(buf, dict) or set(buf) - {"id", "hex", "permissions"}:
            raise ContractError("Unknown buffer field")
        name = buf.get("id")
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name)
            or name in ids
        ):
            raise ContractError("Unique buffer IDs are required")
        ids.add(name)
        value = buf.get("hex")
        if not isinstance(value, str) or len(value) > 131072:
            raise ContractError("Buffer exceeds 64 KiB")
        try:
            data = bytes.fromhex(value)
        except ValueError as e:
            raise ContractError("Buffer must be hexadecimal") from e
        if not data or buf.get("permissions", "rw") not in ("r", "rw"):
            raise ContractError("Buffer requires 1–65536 bytes and r or rw permission")
    for arg in args:
        if type(arg) is int and 0 <= arg < 2**64:
            continue
        if (
            not isinstance(arg, dict)
            or set(arg) - {"buffer", "offset"}
            or arg.get("buffer") not in ids
        ):
            raise ContractError(
                "Arguments must be unsigned integers or buffer references"
            )
        offset = arg.get("offset", 0)
        length = len(
            bytes.fromhex(next(b["hex"] for b in buffers if b["id"] == arg["buffer"]))
        )
        if type(offset) is not int or not 0 <= offset <= length:
            raise ContractError("Pointer offset is outside its buffer")
    if type(case.get("output_bits", 64)) is not int or case.get(
        "output_bits", 64
    ) not in (32, 64):
        raise ContractError("Return width must be 32 or 64 bits")
    budget = case.get("max_instructions", 100000)
    if type(budget) is not int or not 1 <= budget <= 1_000_000:
        raise ContractError("Instruction budget must be 1–1000000")
    return case


def execute(image, case, cancel=None):
    validate_case(case)
    abi = image["abi"]
    if abi not in ABIS:
        raise ContractError("Unknown linked-call ABI")
    arm = abi in ARM_ABIS
    arg_registers, preserved, shadow = ABIS[abi]
    xmm = tuple("XMM" + str(i) for i in range(6, 16)) if abi == "win64" else ()
    registers = {name: 0xA55A12340000 + i for i, name in enumerate(preserved)}
    registers.update(
        {name: 0x112233445566778899AABBCCDDEEFF00 + i for i, name in enumerate(xmm)}
    )
    vectors = tuple("Q" + str(i) for i in range(8, 16)) if arm else ()
    registers.update(
        {name: 0x112233445566778899AABBCCDDEEFF00 + i for i, name in enumerate(vectors)}
    )
    # Room above return address for shadow space and all stack arguments.
    rsp = STACK + (0xFEF0 if arm else 0xFEF8)
    stack = bytearray(65536)
    if not arm:
        stack[rsp - STACK : rsp - STACK + 8] = STOP.to_bytes(8, "little")
    memory, ranges, access, observe = [], [], [], []
    for s in image["segments"]:
        start = s["address"] & ~4095
        size = (s["address"] + s["size"] + 4095 & ~4095) - start
        memory.append(
            {
                "address": start,
                "size": size,
                "hex": ("00" * (s["address"] - start)) + s["hex"],
                "permissions": s["permissions"],
            }
        )
        # Writes to image globals are not silently ignored. This lane only permits
        # stack and explicit caller-owned outputs; mutable image state needs a runtime.
        access.append(
            [s["address"], s["address"] + s["size"], s["permissions"].replace("w", "")]
        )
        if "x" in s["permissions"]:
            ranges.append([s["address"], s["address"] + s["size"]])
    addresses = {}
    for index, buf in enumerate(case.get("buffers", [])):
        address = BUFFERS + index * 0x20000
        data = bytes.fromhex(buf["hex"])
        perm = buf.get("permissions", "rw")
        addresses[buf["id"]] = address
        memory.append(
            {
                "address": address,
                "size": (len(data) + 4095) & ~4095,
                "hex": data.hex(),
                "permissions": perm,
            }
        )
        access.append([address, address + len(data), perm])
        observe.append({"name": buf["id"], "address": address, "size": len(data)})
    args = [
        arg if type(arg) is int else addresses[arg["buffer"]] + arg.get("offset", 0)
        for arg in case.get("arguments", [])
    ]
    registers.update(dict(zip(arg_registers, args)))
    for index, value in enumerate(args[len(arg_registers) :]):
        offset = rsp - STACK + (0 if arm else 8) + shadow + index * 8
        stack[offset : offset + 8] = value.to_bytes(8, "little")
    if arm:
        registers.update(SP=rsp, X30=STOP, X18=0xA55A180000, FPCR=0, FPSR=0)
    else:
        registers.update(RSP=rsp, MXCSR=0x1F80, FPCW=0x37F)
    memory += [
        {"address": STACK, "size": 65536, "hex": stack.hex(), "permissions": "rw"},
        {
            "address": STOP,
            "size": 4096,
            "hex": "1f2003d5" if arm else "90",
            "permissions": "rx",
        },
    ]
    access.append([STACK, STACK + 65536, "rw"])
    replay = run_reference
    if arm:
        from .arm64 import replay
    result = replay(
        {
            "start": image["entry"],
            "stop": STOP,
            "memory": memory,
            "registers": registers,
            "extra_registers": (
                (*vectors, "FPCR", "FPSR") if arm else (*xmm, "MXCSR", "FPCW")
            ),
            "access_ranges": access,
            "code_ranges": ranges,
            "observe_memory": observe,
            "max_instructions": case.get("max_instructions", 100000),
        },
        cancel=cancel,
        diagnose_completion=True,
    )
    checks = [("SP" if arm else "RSP", rsp + (0 if arm else 8), None)]
    checks += [(name, registers[name], None) for name in (*preserved, *xmm)]
    if arm:
        # AAPCS64 preserves only the low 64 bits of v8-v15. Reserve x18 because
        # its use is platform-specific; the freestanding compiler does likewise.
        checks += [("X18", registers["X18"], None), ("FPCR", 0, None)]
        checks += [(name, registers[name], (1 << 64) - 1) for name in vectors]
    else:
        checks += [("FPCW", 0x37F, None), ("MXCSR", 0x1F80, 0xFFC0)]
    violations = []
    for name, expected, mask in checks:
        actual = result["registers"][name]
        if mask is not None:
            expected, actual = expected & mask, actual & mask
        if actual != expected:
            violations.append(
                {"register": name, "expected": expected, "actual": actual}
            )
    abi_ok = not violations
    context = None
    if result["status"] != "completed" or not abi_ok:
        from .unicorn_diagnostics import locate

        context = locate(result["stop_context"], image["segments"], observe)
        if result["status"] == "completed" and violations:
            context.update(stop_reason="abi_violation", abi_violations=violations)
    return {
        "status": result["status"],
        "abi_ok": abi_ok,
        "value": result["registers"]["X0" if arm else "RAX"]
        & ((1 << case.get("output_bits", 64)) - 1),
        "buffers": result["memory"],
        "instructions": len(result["trace"]),
        "fault": result["fault"],
        "stop_context": context,
    }


def compare(original, candidate, cases, cancel=None):
    if not isinstance(cases, list) or not 1 <= len(cases) <= 256:
        raise ContractError("Use 1–256 linked-call cases")
    failures = []
    for index, case in enumerate(cases):
        if cancel is not None and cancel.is_set():
            raise Blocked("Linked-call verification cancelled")
        reference, result = execute(original, case, cancel), execute(
            candidate, case, cancel
        )
        if not (
            reference["status"] == result["status"] == "completed"
            and reference["abi_ok"]
            and result["abi_ok"]
            and reference["value"] == result["value"]
            and reference["buffers"] == result["buffers"]
        ):
            failures.append(
                {"index": index, "original": reference, "candidate": result}
            )
            if len(failures) >= 8:
                break
    return {
        "passed": not failures,
        "tested": index + 1,
        "total": len(cases),
        "failures": failures,
        "claim": "Declared integer/pointer calls and all caller buffers from fresh on-disk image state; no OS, initialization, floating-point ABI or whole-program equivalence claim",
    }
