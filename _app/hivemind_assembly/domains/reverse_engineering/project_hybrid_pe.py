"""Function-region replacement in an x64 Windows console PE.

The PE counterpart of `project_hybrid`. Recovered regions are compiled for the
Windows x64 ABI, linked by lld-link as a fixed image whose first section starts
exactly at the original SizeOfImage, and appended to the original as new
sections. Unrecovered functions and shared data bind to original addresses
through absolute COFF symbols; definitions of other original names in the
recovered units become weak and lose to those absolute symbols. Each replaced
entry receives a rel32 jump; the rest of the function is trap-filled.

PE executables rarely carry symbols, so region addresses and sizes come from the
project manifest's `addresses` (for example a Ghidra inventory) or from exports.
The composed image clears DYNAMIC_BASE so it is not relocated away from the
addresses the regions were linked against. Recovered regions carry no unwind
data; structured exception unwinding through them is outside this scope.
"""

import hashlib
import shutil
import struct
import tempfile
from pathlib import Path

from hivemind_assembly.core.common import Blocked, ContractError, file_hash, uid
from . import program_libc
from .project_hybrid import NAME

PATCH = 5
DYNAMIC_BASE = 0x40
MEMORY = ("memcpy", "memmove", "memset", "memcmp")


def inventory(original, addresses=None):
    import pefile

    from .windows_program import image_info

    info = image_info(original)
    base = info["image_base"]
    functions, objects = {}, {}
    pe = pefile.PE(data=original)
    try:
        export = getattr(pe, "DIRECTORY_ENTRY_EXPORT", None)
        for item in getattr(export, "symbols", ()):
            if item.name and NAME.fullmatch(item.name.decode("ascii", "replace")):
                functions[item.name.decode()] = {
                    "address": base + item.address,
                    "size": 0,
                    "local": False,
                }
    finally:
        pe.close()
    for key, spec in (addresses or {}).items():
        if not NAME.fullmatch(key) or not isinstance(spec, dict):
            raise ContractError("Address entries map C names to {address, size}")
        address = spec.get("address")
        address = int(address, 16) if isinstance(address, str) else address
        size = spec.get("size", 0)
        if type(address) is not int or type(size) is not int or address < 0 or size < 0:
            raise ContractError("Supplied symbol addresses need integer address and size")
        if address < base:  # Maps and some tools report RVAs.
            address += base
        target = functions if spec.get("kind", "function") == "function" else objects
        target[key] = {"address": address, "size": size, "local": False, "supplied": True}
    return {
        "machine": 0x8664,
        "image_base": base,
        "image_size": info["image_size"],
        "functions": functions,
        "objects": objects,
        "ambiguous": [],
    }


def coff_symbols(data):
    """Defined external names and undefined references in a COFF object."""
    if len(data) < 20 or struct.unpack_from("<H", data, 0)[0] != 0x8664:
        raise Blocked("Unexpected Windows object format")
    table, count = struct.unpack_from("<II", data, 8)
    strings = table + count * 18
    if strings > len(data):
        raise Blocked("Truncated Windows object symbol table")
    defined, undefined = set(), set()
    index = 0
    while index < count:
        offset = table + index * 18
        raw = data[offset : offset + 8]
        if raw[:4] == b"\0\0\0\0":
            start = strings + struct.unpack_from("<I", raw, 4)[0]
            end = data.index(b"\0", start)
            name = data[start:end].decode("utf-8", "replace")
        else:
            name = raw.rstrip(b"\0").decode("utf-8", "replace")
        value, section, _, storage, aux = struct.unpack_from("<IhHBB", data, offset + 8)
        if storage == 2 and section > 0:
            defined.add(name)
        elif storage == 2 and section == 0 and value == 0:
            undefined.add(name)
        elif storage == 105:  # Weak external: defined with a default.
            defined.add(name)
        index += 1 + aux
    return defined, undefined - defined


def _tools(compiler):
    executable = shutil.which(compiler or "clang")
    if not executable or "clang" not in Path(executable).name.lower():
        raise Blocked("Windows region replacement requires Clang and LLD")
    sibling = Path(executable).with_name(
        "lld-link.exe" if Path(executable).suffix == ".exe" else "lld-link"
    )
    linker = str(sibling) if sibling.is_file() else shutil.which("lld-link")
    if not linker:
        raise Blocked("Install lld-link alongside Clang")
    return executable, linker


def compose(
    root,
    units,
    declarations,
    optimization,
    original,
    recovered,
    jobs,
    compiler="",
    cancel=None,
    addresses=None,
    cache=None,
):
    from .windows_program import HEADER, image_info

    inv = inventory(original, addresses)
    if not recovered:
        return {
            "passed": True,
            "image": original,
            "regions": [],
            "recovered": [],
            "fallback": sorted(inv["functions"]),
        }
    if len(set(recovered)) != len(recovered):
        raise ContractError("Recovered regions must be distinct")
    for name in recovered:
        item = inv["functions"].get(name)
        if not item:
            raise ContractError(
                "No original function address for recovered region (supply its address and size): "
                + name
            )
        if item["size"] < PATCH:
            raise Blocked(
                "Original function size is unknown or too small to redirect: " + name
            )
    executable, linker = _tools(compiler)
    fingerprint = file_hash(executable) + file_hash(linker)
    base = inv["image_base"] + inv["image_size"] - 0x1000
    flags = [
        executable,
        "--target=x86_64-pc-windows-msvc",
        "-std=c11",
        "-" + optimization,
        "-ffreestanding",
        "-fno-builtin",
        "-fno-stack-protector",
        "-nostdinc",
        "-Imemory_include",
        "-fno-asynchronous-unwind-tables",
        "-fno-unwind-tables",
        "-ffunction-sections",
        "-fdata-sections",
        "-fno-jump-tables",
    ]
    known = set(inv["functions"]) | set(inv["objects"])
    with tempfile.TemporaryDirectory(prefix="ha-hybrid-pe-") as tmp:
        stage = Path(tmp)
        memory_sources, memory_hash = program_libc.stage(stage)

        def compile_unit(name, source):
            key = hashlib.sha256(
                "\0".join([fingerprint, *flags[1:], source]).encode()
            ).hexdigest()
            if cache is not None and key in cache:
                return cache[key], None
            (stage / (name + ".c")).write_text(source, encoding="utf-8")
            result = jobs.run(
                uid("hybrid-pe"),
                flags + ["-c", name + ".c", "-o", name + ".obj"],
                stage,
                timeout=120,
                cancel=cancel,
            )
            if result["status"] != "completed" or result["exit_code"] != 0:
                return None, result
            data = (stage / (name + ".obj")).read_bytes()
            if b".drectve" in data[20 : 20 + 40 * struct.unpack_from("<H", data, 2)[0]]:
                raise Blocked("Candidate object contains linker directives")
            if cache is not None:
                cache[key] = data
            return data, None

        def compile_all(weak):
            objects = []
            for i, text in enumerate(units.values()):
                pragmas = "".join(
                    "#pragma weak " + n + "\n" for n in sorted(weak.get(i, ()))
                )
                data, failure = compile_unit(
                    f"unit_{i}", HEADER + declarations + "\n" + pragmas + text
                )
                if failure:
                    return None, failure
                objects.append(data)
            return objects, None

        objects, failure = compile_all({})
        if failure:
            return {"passed": False, "stage": "compile", "build": failure}
        weak, definitions, undefined = {}, {}, set()
        for i, data in enumerate(objects):
            defined, missing = coff_symbols(data)
            undefined |= missing
            for name in defined:
                definitions.setdefault(name, []).append(i)
                if name in known and name not in recovered:
                    weak.setdefault(i, set()).add(name)
        for name in recovered:
            if len(definitions.get(name, ())) != 1:
                raise ContractError(
                    "Recovered region must be defined once by its sources: " + name
                )
        if weak:
            objects, failure = compile_all(weak)
            if failure:
                return {"passed": False, "stage": "compile", "build": failure}
        names = []
        for i, data in enumerate(objects):
            (stage / f"unit_{i}.obj").write_bytes(data)
            names.append(f"unit_{i}.obj")
        extra = []
        if any(n in undefined and n not in known and n not in definitions for n in MEMORY):
            for i, source in enumerate(memory_sources):
                data, failure = compile_unit(
                    f"memory_{i}", (stage / source).read_text(encoding="utf-8")
                )
                if failure:
                    return {"passed": False, "stage": "compile", "build": failure}
                (stage / f"memory_{i}.obj").write_bytes(data)
                extra.append(f"memory_{i}.obj")
        absolute = [
            f".globl {n}\n.set {n}, {(inv['functions'].get(n) or inv['objects'][n])['address']:#x}\n"
            for n in sorted((known & (undefined | {m for names in weak.values() for m in names})) - set(recovered))
        ]
        if absolute:
            (stage / "original.s").write_text("".join(absolute), encoding="ascii")
            result = jobs.run(
                uid("hybrid-pe"),
                [executable, "--target=x86_64-pc-windows-msvc", "-c", "original.s", "-o", "original.obj"],
                stage,
                timeout=120,
                cancel=cancel,
            )
            if result["status"] != "completed" or result["exit_code"] != 0:
                return {"passed": False, "stage": "compile", "build": result}
            names.append("original.obj")
        link = [
            linker,
            f"/base:{base:#x}",
            "/fixed",
            "/entry:" + recovered[0],
            *("/include:" + n for n in recovered),
            *(["/include:ha_memory_runtime_notice"] if extra else []),
            "/subsystem:console",
            "/nodefaultlib",
            "/opt:ref",
            "/timestamp:0",
            "/out:regions.exe",
            "/map:regions.map",
            *names,
            *extra,
        ]
        result = jobs.run(uid("hybrid-pe"), link, stage, timeout=120, cancel=cancel)
        if result["status"] != "completed" or result["exit_code"] != 0:
            return {"passed": False, "stage": "link", "build": result}
        part = (stage / "regions.exe").read_bytes()
        symbols = _map_symbols((stage / "regions.map").read_text("utf-8", "replace"), recovered)
        if fingerprint != file_hash(executable) + file_hash(linker):
            raise Blocked("Windows toolchain changed during the build")
    if extra:
        program_libc.verify_notice(part)
    image, regions = _assemble(original, inv, part, base, symbols, recovered)
    image_info(image)
    return {
        "passed": True,
        "stage": "composed",
        "architecture": "x86_64",
        "image": image,
        "sha256": hashlib.sha256(image).hexdigest(),
        "regions": regions,
        "recovered": list(recovered),
        "fallback": sorted(set(inv["functions"]) - set(recovered)),
        "memory_runtime_sha256": memory_hash if extra else None,
        "build": result,
        "claim": "Selected function entries redirect to recovered code appended as new PE sections; all other code, data and imports are the original image's. No unwind data is provided for recovered regions.",
    }


def map_functions(text):
    """Public symbols from an lld-link map with sizes bounded by the next symbol.

    Sizes include any alignment padding before the next symbol; the last symbol
    of a section has no bound and reports size 0 rather than a guess.
    """
    import re

    rows = []
    for line in text.splitlines():
        parts = line.split()
        if (
            len(parts) >= 4
            and re.fullmatch(r"[0-9a-fA-F]{4}:[0-9a-fA-F]{8}", parts[0])
            and parts[0][:4] != "0000"
            and NAME.fullmatch(parts[1])
        ):
            rows.append((parts[0][:4], int(parts[2], 16), parts[1]))
    rows.sort()
    # Every public keeps its address; size is 0 when the next symbol does not bound it.
    result = {name: {"address": address, "size": 0} for _, address, name in rows}
    for (section, address, name), following in zip(rows, rows[1:]):
        if following[0] == section and following[1] > address:
            result[name]["size"] = following[1] - address
    return result


def _map_symbols(text, recovered):
    """Read recovered-function addresses from the lld-link map."""
    import re

    found = {}
    for line in text.splitlines():
        # " 0001:00000010       recovered      0000000140006010     unit_0.obj"
        parts = line.split()
        if (
            len(parts) >= 4
            and re.fullmatch(r"[0-9a-fA-F]{4}:[0-9a-fA-F]{8}", parts[0])
            and parts[0][:4] != "0000"
            and parts[1] in recovered
        ):
            found[parts[1]] = int(parts[2], 16)
    missing = set(recovered) - set(found)
    if missing:
        raise Blocked("Linked regions do not define " + ", ".join(sorted(missing)))
    return found


def _assemble(original, inv, part, base, symbols, recovered):
    import pefile

    pe = pefile.PE(data=original)
    regions_pe = pefile.PE(data=part)
    try:
        out = bytearray(original)
        opt = pe.OPTIONAL_HEADER
        if opt.SectionAlignment != 0x1000:
            raise Blocked("Region replacement expects 4 KiB section alignment")
        if pe.OPTIONAL_HEADER.DATA_DIRECTORY[4].Size:
            raise Blocked("Signed images cannot be composed; remove the certificate first")
        file_align = opt.FileAlignment
        new = [s for s in regions_pe.sections if s.Misc_VirtualSize]
        table = pe.sections[0].get_file_offset()
        end = table + 40 * (len(pe.sections) + len(new))
        first_raw = min(s.PointerToRawData for s in pe.sections if s.PointerToRawData)
        if end > min(opt.SizeOfHeaders, first_raw):
            raise Blocked("No room in the PE headers for new section entries")
        image_size = opt.SizeOfImage
        for name in recovered:
            item = inv["functions"][name]
            rva = item["address"] - inv["image_base"]
            section = next(
                (s for s in pe.sections
                 if s.VirtualAddress <= rva and rva + item["size"] <= s.VirtualAddress + s.SizeOfRawData),
                None,
            )
            if section is None or not section.Characteristics & 0x20000000:
                raise ContractError("Replaced region is not file-backed executable code: " + name)
            offset = section.PointerToRawData + rva - section.VirtualAddress
            delta = symbols[name] - (item["address"] + PATCH)
            if not -(2**31) <= delta < 2**31:
                raise Blocked("Recovered code is out of rel32 range")
            out[offset : offset + item["size"]] = (
                b"\xe9" + struct.pack("<i", delta) + b"\xcc" * (item["size"] - PATCH)
            )
        headers = []
        last_end = image_size
        for s in new:
            rva = base - inv["image_base"] + s.VirtualAddress
            if rva < image_size:
                raise Blocked("Recovered sections overlap the original image")
            out.extend(b"\0" * ((-len(out)) % file_align))
            raw = s.get_data()[: s.SizeOfRawData]
            raw += b"\0" * ((-len(raw)) % file_align)
            pointer = len(out) if raw else 0
            out.extend(raw)
            headers.append(
                struct.pack(
                    "<8sIIIIIIHHI",
                    s.Name,
                    s.Misc_VirtualSize,
                    rva,
                    len(raw),
                    pointer,
                    0,
                    0,
                    0,
                    0,
                    s.Characteristics,
                )
            )
            last_end = max(last_end, rva + ((s.Misc_VirtualSize + 0xFFF) & ~0xFFF))
        start = table + 40 * len(pe.sections)
        out[start : start + 40 * len(headers)] = b"".join(headers)
        file_header = pe.FILE_HEADER.get_file_offset()
        struct.pack_into("<H", out, file_header + 2, len(pe.sections) + len(new))
        optional = opt.get_file_offset()
        struct.pack_into("<I", out, optional + 56, last_end)  # SizeOfImage
        struct.pack_into("<I", out, optional + 64, 0)  # CheckSum
        characteristics = struct.unpack_from("<H", out, optional + 70)[0]
        struct.pack_into("<H", out, optional + 70, characteristics & ~DYNAMIC_BASE)
    finally:
        pe.close()
        regions_pe.close()
    if len(out) > 2_000_000:
        raise Blocked("Composed image exceeds 2 MB")
    regions = [
        {
            "function": name,
            "original_address": inv["functions"][name]["address"],
            "original_size": inv["functions"][name]["size"],
            "recovered_address": symbols[name],
        }
        for name in recovered
    ]
    return bytes(out), regions
