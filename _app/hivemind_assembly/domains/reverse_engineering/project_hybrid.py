"""Function-region replacement in a static Linux ELF: recovered C plus original code.

Selected functions are compiled from the candidate's C units, linked at a free
address above the original image and reached through a direct branch written at
each original entry. The remainder of a replaced function is filled with trap
instructions so stray control flow faults instead of running stale code. Every
other function, all global data and the original runtime stay in place: recovered
code calls unrecovered functions and uses shared globals at their original
addresses. Removing a function from the selection rolls that region back to the
original machine code.

Scope: static ET_EXEC x86-64/AArch64 images inside the replay contract, entry
patching through symbols (or owner-supplied address/size pairs for stripped
images). Copies the compiler inlined into other original functions are not
redirected; checks state that limit rather than hiding it.
"""

import hashlib
import io
import re
import shutil
import struct
import tempfile
from pathlib import Path

from hivemind_assembly.core.common import Blocked, ContractError, file_hash, uid
from . import program, program_libc

PAGE = 0x1000
PATCH_BYTES = {62: 5, 183: 4}
TRAP = {62: b"\xcc", 183: struct.pack("<I", 0xD4200000)}  # int3 / brk #0
MEMORY = ("memcpy", "memmove", "memset", "memcmp")
NAME = re.compile(r"[A-Za-z_][A-Za-z_0-9]{0,99}")
LIMIT = 0x10000000  # program.load_image upper bound


def _symbols(data):
    from elftools.elf.elffile import ELFFile

    elf = ELFFile(io.BytesIO(data))
    rows = []
    for section in elf.iter_sections():
        if section["sh_type"] != "SHT_SYMTAB":
            continue
        for item in section.iter_symbols():
            if not item.name or item["st_shndx"] == "SHN_UNDEF":
                continue
            rows.append(
                {
                    "name": item.name,
                    "value": item["st_value"],
                    "size": item["st_size"],
                    "type": item["st_info"]["type"],
                    "bind": item["st_info"]["bind"],
                    "section": item["st_shndx"],
                }
            )
    return elf, rows


def inventory(original, addresses=None):
    """Original functions and data symbols that recovered code may bind to."""
    machine = program.image_machine(original)
    entry, segments = program.load_image(original, machine=machine)
    _, rows = _symbols(original)
    functions, objects, ambiguous = {}, {}, set()
    globals_ = {r["name"] for r in rows if r["bind"] in ("STB_GLOBAL", "STB_WEAK")}
    seen = {}
    for row in rows:
        if row["type"] not in ("STT_FUNC", "STT_OBJECT", "STT_NOTYPE"):
            continue
        if not NAME.fullmatch(row["name"]) or row["section"] == "SHN_ABS":
            continue
        local = row["bind"] == "STB_LOCAL"
        if local and row["name"] in globals_:
            continue
        key = row["name"]
        if key in seen and seen[key] != row["value"]:
            ambiguous.add(key)
            continue
        seen[key] = row["value"]
        item = {"address": row["value"], "size": row["size"], "local": local}
        (functions if row["type"] == "STT_FUNC" else objects)[key] = item
    for key in ambiguous:
        functions.pop(key, None)
        objects.pop(key, None)
    for key, spec in (addresses or {}).items():
        if not NAME.fullmatch(key) or not isinstance(spec, dict):
            raise ContractError("Address entries map C names to {address, size}")
        address = spec.get("address")
        address = int(address, 16) if isinstance(address, str) else address
        size = spec.get("size", 0)
        if type(address) is not int or type(size) is not int or address < 0 or size < 0:
            raise ContractError("Supplied symbol addresses need integer address and size")
        target = functions if spec.get("kind", "function") == "function" else objects
        target[key] = {"address": address, "size": size, "local": False, "supplied": True}
        ambiguous.discard(key)
    return {
        "machine": machine,
        "entry": entry,
        "segments": segments,
        "functions": functions,
        "objects": objects,
        "ambiguous": sorted(ambiguous),
    }


def _file_offset(segments, address, size):
    for s in segments:
        start = s["address"]
        if start <= address and address + size <= start + len(s["data"]):
            if not s["flags"] & 1:
                raise ContractError("Replaced region is not executable code")
            return s["file_offset"] + address - start
    raise ContractError("Replaced region is not file-backed code")


def _branch(machine, source, target):
    if machine == 62:
        delta = target - (source + 5)
        if not -(2**31) <= delta < 2**31:
            raise Blocked("Recovered code is out of rel32 range")
        return b"\xe9" + struct.pack("<i", delta)
    delta = target - source
    if delta % 4 or not -(2**27) <= delta < 2**27:
        raise Blocked("Recovered code is out of AArch64 branch range")
    return struct.pack("<I", 0x14000000 | ((delta >> 2) & 0x3FFFFFF))


def _object_symbols(data):
    _, rows = _symbols(data)
    from elftools.elf.elffile import ELFFile

    undefined = set()
    for section in ELFFile(io.BytesIO(data)).iter_sections():
        if section["sh_type"] != "SHT_SYMTAB":
            continue
        for item in section.iter_symbols():
            if item.name and item["st_shndx"] == "SHN_UNDEF":
                undefined.add(item.name)
    defined = {
        r["name"]: r["type"]
        for r in rows
        if r["bind"] in ("STB_GLOBAL", "STB_WEAK") and r["section"] != "SHN_ABS"
    }
    return defined, undefined


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
):
    """Build the original with `recovered` functions replaced. Returns image and map."""
    inv = inventory(original, addresses)
    machine = inv["machine"]
    arm = machine == 183
    if not recovered:
        return {
            "passed": True,
            "image": original,
            "regions": [],
            "recovered": [],
            "fallback": sorted(inv["functions"]),
            "claim": "No region selected; the original image is unchanged",
        }
    if len(set(recovered)) != len(recovered):
        raise ContractError("Recovered regions must be distinct")
    for name in recovered:
        item = inv["functions"].get(name)
        if not item:
            raise ContractError(
                "No unique original function for recovered region (supply its address and size): "
                + name
            )
        if item["size"] < PATCH_BYTES[machine]:
            raise Blocked("Original function is too small to redirect: " + name)
        if arm and (item["address"] % 4 or item["size"] % 4):
            raise ContractError("AArch64 regions must be four-byte aligned: " + name)
    executable = (
        shutil.which(compiler) if compiler else shutil.which("clang")
    )
    if not executable or "clang" not in Path(executable).name.lower():
        raise Blocked("Region replacement requires Clang and LLD")
    architecture = "aarch64" if arm else "x86_64"
    compiler_hash = file_hash(executable)
    end = max(s["address"] + s["size"] for s in inv["segments"])
    base = (end + 0xFFFF) & ~0xFFFF
    base += 0x10000
    flags = [
        executable,
        "--target=" + architecture + "-unknown-linux-gnu",
        *(["-march=armv8-a", "-ffixed-x18"] if arm else ["-m64"]),
        "-std=c11",
        "-" + optimization,
        "-ffreestanding",
        "-fno-builtin",
        "-fno-stack-protector",
        "-fno-pie",
        "-fno-pic",
        "-nostdinc",
        "-Imemory_include",
        "-ffunction-sections",
        "-fdata-sections",
        "-fno-asynchronous-unwind-tables",
        "-fno-unwind-tables",
        "-fno-jump-tables",
    ]
    known = set(inv["functions"]) | set(inv["objects"])
    with tempfile.TemporaryDirectory(prefix="ha-hybrid-") as tmp:
        stage = Path(tmp)
        memory_sources, memory_hash = program_libc.stage(stage)

        def compile_units(weak):
            objects = []
            for i, text in enumerate(units.values()):
                pragmas = "".join("#pragma weak " + n + "\n" for n in sorted(weak.get(i, ())))
                name = f"unit_{i}"
                (stage / (name + ".c")).write_text(
                    program.HEADER + "\n" + declarations + "\n" + pragmas + text,
                    encoding="utf-8",
                )
                result = jobs.run(
                    uid("hybrid"),
                    flags + ["-c", name + ".c", "-o", name + ".o"],
                    stage,
                    timeout=120,
                    cancel=cancel,
                )
                if result["status"] != "completed" or result["exit_code"] != 0:
                    return None, result
                objects.append((stage / (name + ".o")).read_bytes())
            return objects, None

        objects, failure = compile_units({})
        if failure:
            return {"passed": False, "stage": "compile", "build": failure}
        weak, definitions, undefined = {}, {}, set()
        for i, data in enumerate(objects):
            defined, missing = _object_symbols(data)
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
            objects, failure = compile_units(weak)
            if failure:
                return {"passed": False, "stage": "compile", "build": failure}
        names = []
        for i, data in enumerate(objects):
            (stage / f"unit_{i}.o").write_bytes(data)
            names.append(f"unit_{i}.o")
        missing_memory = [
            n for n in MEMORY if n in undefined and n not in known and n not in definitions
        ]
        extra = []
        if missing_memory:
            for source in memory_sources:
                result = jobs.run(
                    uid("hybrid"),
                    flags + ["-c", source, "-o", source + ".o"],
                    stage,
                    timeout=120,
                    cancel=cancel,
                )
                if result["status"] != "completed" or result["exit_code"] != 0:
                    return {"passed": False, "stage": "compile", "build": result}
                extra.append(source + ".o")
        bind = {}
        for name in sorted(known - set(recovered)):
            item = inv["functions"].get(name) or inv["objects"][name]
            bind[name] = item["address"]
        script = [
            "SECTIONS {",
            f"  . = {base:#x};",
            "  .ha.text : { *(.text .text.*) }",
            "  .ha.rodata : { *(.rodata .rodata.* .srodata .srodata.*) }",
            "  . = ALIGN(0x1000);",
            "  .ha.data : { *(.data .data.* .sdata .sdata.*) }",
            "  .ha.bss : { *(.bss .bss.* .sbss .sbss.* COMMON) }",
            "  /DISCARD/ : { *(.eh_frame*) *(.comment) *(.note*) }",
            "}",
            *(f"{n} = {a:#x};" for n, a in bind.items()),
        ]
        (stage / "hybrid.ld").write_text("\n".join(script) + "\n", encoding="utf-8")
        link = [
            executable,
            "--target=" + architecture + "-unknown-linux-gnu",
            "-fuse-ld=lld",
            "-nostdlib",
            "-static",
            *names,
            *extra,
            "-Wl,-T,hybrid.ld",
            "-Wl,--gc-sections",
            "-Wl,--build-id=none",
            "-Wl,-e," + recovered[0],
            *("-Wl,--undefined=" + n for n in recovered),
            *(["-Wl,--undefined=ha_memory_runtime_notice"] if extra else []),
            "-o",
            "regions.elf",
        ]
        result = jobs.run(uid("hybrid"), link, stage, timeout=120, cancel=cancel)
        if result["status"] != "completed" or result["exit_code"] != 0:
            return {"passed": False, "stage": "link", "build": result}
        part = (stage / "regions.elf").read_bytes()
        if file_hash(executable) != compiler_hash:
            raise Blocked("Compiler changed during the build")
    if extra:
        program_libc.verify_notice(part)
    image, regions = _assemble(original, inv, part, recovered)
    program.load_image(image, machine=machine)
    return {
        "passed": True,
        "stage": "composed",
        "architecture": architecture,
        "image": image,
        "sha256": hashlib.sha256(image).hexdigest(),
        "regions": regions,
        "recovered": list(recovered),
        "fallback": sorted(set(inv["functions"]) - set(recovered)),
        "memory_runtime_sha256": memory_hash if extra else None,
        "compiler_sha256": compiler_hash,
        "build": result,
        "claim": "Selected function entries redirect to recovered code; all other code and data are the original image's. Inlined copies inside other original functions are not redirected.",
    }


def _assemble(original, inv, part, recovered):
    machine = inv["machine"]
    from elftools.elf.elffile import ELFFile

    elf = ELFFile(io.BytesIO(part))
    if elf["e_machine"] != ("EM_AARCH64" if machine == 183 else "EM_X86_64"):
        raise Blocked("Recovered regions were linked for another architecture")
    loads = [s for s in elf.iter_segments() if s["p_type"] == "PT_LOAD"]
    if not loads:
        raise Blocked("Recovered regions produced no loadable code")
    original_pages = set()
    for s in inv["segments"]:
        for p in range(s["address"] & ~(PAGE - 1), s["address"] + s["size"], PAGE):
            original_pages.add(p)
    for s in loads:
        if s["p_vaddr"] + s["p_memsz"] >= LIMIT:
            raise Blocked("Recovered regions exceed the replay address range")
        for p in range(s["p_vaddr"] & ~(PAGE - 1), s["p_vaddr"] + s["p_memsz"], PAGE):
            if p in original_pages:
                raise Blocked("Recovered regions overlap the original image")
    _, rows = _symbols(part)
    linked = {
        r["name"]: r["value"]
        for r in rows
        if r["type"] == "STT_FUNC" and r["bind"] in ("STB_GLOBAL", "STB_WEAK")
    }
    out = bytearray(original)
    regions = []
    for name in recovered:
        if name not in linked:
            raise Blocked("Linked regions do not define " + name)
        item = inv["functions"][name]
        offset = _file_offset(inv["segments"], item["address"], item["size"])
        jump = _branch(machine, item["address"], linked[name])
        fill = TRAP[machine] * ((item["size"] - len(jump)) // len(TRAP[machine]))
        out[offset : offset + item["size"]] = (jump + fill).ljust(
            item["size"], TRAP[machine][:1]
        )
        regions.append(
            {
                "function": name,
                "original_address": item["address"],
                "original_size": item["size"],
                "recovered_address": linked[name],
            }
        )
    header = struct.unpack_from("<16sHHIQQQIHHHHHH", original)
    phoff, phnum = header[5], header[10]
    kept = []
    for i in range(phnum):
        entry = original[phoff + 56 * i : phoff + 56 * (i + 1)]
        if struct.unpack_from("<I", entry)[0] != 6:  # PT_PHDR is re-created below
            kept.append(entry)
    added = []
    for s in loads:
        out.extend(b"\0" * ((s["p_vaddr"] - len(out)) % PAGE))
        offset = len(out)
        out.extend(s.data()[: s["p_filesz"]])
        added.append(
            struct.pack(
                "<IIQQQQQQ",
                1,
                s["p_flags"],
                offset,
                s["p_vaddr"],
                s["p_vaddr"],
                s["p_filesz"],
                s["p_memsz"],
                PAGE,
            )
        )
    table_vaddr = (max(s["p_vaddr"] + s["p_memsz"] for s in loads) + PAGE - 1) & ~(PAGE - 1)
    out.extend(b"\0" * ((-len(out)) % PAGE))
    table_offset = len(out)
    count = len(kept) + len(added) + 2
    size = 56 * count
    phdr = struct.pack("<IIQQQQQQ", 6, 4, table_offset, table_vaddr, table_vaddr, size, size, 8)
    table_load = struct.pack(
        "<IIQQQQQQ", 1, 4, table_offset, table_vaddr, table_vaddr, size, size, PAGE
    )
    out.extend(phdr + b"".join(kept) + b"".join(added) + table_load)
    struct.pack_into("<Q", out, 32, table_offset)
    struct.pack_into("<H", out, 56, count)
    if len(out) > 2_000_000:
        raise Blocked("Composed image exceeds 2 MB")
    return bytes(out), regions
