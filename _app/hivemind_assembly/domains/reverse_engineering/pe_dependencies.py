"""Explicit PE DLL graph linking with upstream pefile relocation/inspection.

No DLL discovery, downloads, OS API substitutes or host loader invocation.
Only supplied, bounded DLLs with no TLS/delay imports/initialization entry can
be dependencies. Calls still obey call_images' memory and execution contract.
"""

import hashlib
import re
import struct
import pefile
from . import call_images
from hivemind_assembly.core.common import Blocked, ContractError, scoped


def library_name(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z0-9_.-]{1,128}\.dll", value, re.I
    ):
        raise ContractError("Dependency names must be plain DLL filenames")
    return value.lower()


def parsed(raw):
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= call_images.MAX_IMAGE:
        raise ContractError("PE dependency exceeds file bounds")
    try:
        pe = pefile.PE(data=raw, fast_load=False)
    except pefile.PEFormatError as error:
        raise ContractError("Invalid PE dependency") from error
    if pe.FILE_HEADER.Machine != 0x8664 or pe.OPTIONAL_HEADER.Magic != 0x20B:
        raise Blocked("Dependencies must be PE32+ x86-64")
    if getattr(pe, "DIRECTORY_ENTRY_TLS", None) or getattr(
        pe, "DIRECTORY_ENTRY_DELAY_IMPORT", None
    ):
        raise Blocked("TLS and delayed imports need a Windows runtime")
    if len(pe.sections) > 128 or not 1 <= pe.OPTIONAL_HEADER.SizeOfImage <= 32_000_000:
        raise ContractError("PE dependency memory exceeds bounds")
    return pe


def read_dependencies(root, paths):
    if not isinstance(paths, dict) or len(paths) > 16:
        raise ContractError(
            "Dependencies must map at most 16 DLL names to project paths"
        )
    result = {}
    for name, path in paths.items():
        library_name(name)
        if not isinstance(path, str):
            raise ContractError("Dependency path must be a string")
        resolved = scoped(root, path)
        if resolved.stat().st_size > call_images.MAX_IMAGE:
            raise ContractError("Dependency file exceeds bounds")
        result[name] = resolved.read_bytes()
    if sum(map(len, result.values())) > 16_000_000:
        raise ContractError("Dependencies exceed 16 MB")
    return result


def load(data, symbol=None, address=None, dependencies=None):
    if not dependencies:
        return call_images.load(data, symbol, address)
    if not isinstance(dependencies, dict) or len(dependencies) > 16:
        raise ContractError("At most 16 explicit DLL dependencies are supported")
    if any(not isinstance(v, bytes) for v in dependencies.values()):
        raise ContractError("DLL contents must be bytes")
    if sum(len(v) for v in dependencies.values()) > 16_000_000:
        raise ContractError("DLL bundle exceeds 16 MB")
    supplied = {}
    for name, raw in dependencies.items():
        normalized = library_name(name)
        if normalized in supplied:
            raise ContractError("Duplicate dependency filename")
        supplied[normalized] = raw
    root = parsed(data)
    if (symbol is None) == (address is None):
        raise ContractError("Select exactly one original symbol or address")
    if symbol is not None:
        call_images.function_name(symbol)
    if address is not None and (type(address) is not int or address < 0):
        raise ContractError("Original address must be an unsigned integer")
    modules = {
        "<root>": {
            "pe": root,
            "raw": data,
            "original_base": root.OPTIONAL_HEADER.ImageBase,
        }
    }
    imports = []

    def ensure(name):
        name = library_name(name)
        if name in modules:
            return modules[name]
        if name not in supplied:
            raise Blocked("DLL dependency was not supplied: " + name)
        raw = supplied[name]
        pe = parsed(raw)
        if pe.OPTIONAL_HEADER.AddressOfEntryPoint:
            raise Blocked("Dependency requires loader initialization: " + name)
        base = 0x200000000 + len(modules) * 0x4000000
        while any(
            base
            < m["pe"].OPTIONAL_HEADER.ImageBase + m["pe"].OPTIONAL_HEADER.SizeOfImage
            and base + pe.OPTIONAL_HEADER.SizeOfImage
            > m["pe"].OPTIONAL_HEADER.ImageBase
            for m in modules.values()
        ):
            base += 0x4000000
        if pe.FILE_HEADER.Characteristics & 1:
            raise Blocked("Dependency relocation information was stripped: " + name)
        original = pe.OPTIONAL_HEADER.ImageBase
        # Reject relocation types outside PE32+ absolute/64-bit fixups.
        for block in getattr(pe, "DIRECTORY_ENTRY_BASERELOC", ()):
            for entry in block.entries:
                if entry.type not in (0, 10):
                    raise Blocked("Unsupported PE relocation type")
                if entry.type == 10 and entry.rva + 8 > pe.OPTIONAL_HEADER.SizeOfImage:
                    raise ContractError("PE relocation exceeds image")
        pe.relocate_image(base)
        modules[name] = {"pe": pe, "raw": raw, "original_base": original}
        return modules[name]

    def exported(module, selector, trail=()):
        if len(trail) > 16 or (module, selector) in trail:
            raise Blocked("Forwarded export cycle or depth exceeded")
        record = modules[module] if module == "<root>" else ensure(module)
        pe = record["pe"]
        choices = [
            x
            for x in getattr(getattr(pe, "DIRECTORY_ENTRY_EXPORT", None), "symbols", ())
            if (
                x.name == selector.encode()
                if isinstance(selector, str)
                else x.ordinal == selector
            )
        ]
        if len(choices) != 1:
            raise Blocked("Imported export is missing or ambiguous")
        item = choices[0]
        if item.forwarder:
            previous = (module, selector)
            try:
                dll, name = item.forwarder.decode("ascii").rsplit(".", 1)
                selector = int(name[1:]) if name.startswith("#") else name
            except (UnicodeError, ValueError) as error:
                raise ContractError("Invalid forwarded export") from error
            return exported(library_name(dll + ".dll"), selector, (*trail, previous))
        if not 0 <= item.address < pe.OPTIONAL_HEADER.SizeOfImage:
            raise ContractError("Export exceeds image")
        return pe.OPTIONAL_HEADER.ImageBase + item.address

    entry = exported("<root>", symbol) if symbol is not None else address
    pending = ["<root>"]
    done = set()
    while pending:
        name = pending.pop(0)
        if name in done:
            continue
        done.add(name)
        record = modules[name]
        pe = record["pe"]
        for directory in getattr(pe, "DIRECTORY_ENTRY_IMPORT", ()):
            try:
                dll = library_name(directory.dll.decode("ascii"))
            except UnicodeError as error:
                raise ContractError("Invalid import DLL name") from error
            ensure(dll)
            for item in directory.imports:
                if len(imports) >= 4096:
                    raise ContractError("Import graph exceeds bounds")
                try:
                    selector = item.name.decode("ascii") if item.name else item.ordinal
                except UnicodeError as error:
                    raise ContractError("Invalid import name") from error
                target = exported(dll, selector)
                # pefile updates import addresses during relocation; compute against
                # the current image base, and require an actual file-backed IAT slot.
                rva = item.address - pe.OPTIONAL_HEADER.ImageBase
                if not 0 <= rva <= pe.OPTIONAL_HEADER.SizeOfImage - 8:
                    raise ContractError("Invalid import address table slot")
                offset = pe.get_offset_from_rva(rva)
                if offset + 8 > len(pe.__data__):
                    raise ContractError("IAT exceeds file")
                record.setdefault("iat_patches", []).append((offset, target))
                imports.append(
                    {
                        "module": name,
                        "library": dll,
                        "symbol": selector,
                        "address": target,
                    }
                )
        pending.extend(k for k in modules if k not in done and k not in pending)
    segments = []
    total = 0
    for name, record in modules.items():
        pe = record["pe"]
        # Validate each module with the ordinary bounded loader, using any executable
        # section as a parsing entry; the actual root call entry is checked below.
        choices = [
            s
            for s in pe.sections
            if s.Characteristics & 0x20000000 and s.Misc_VirtualSize
        ]
        if not choices:
            raise ContractError("DLL contains no executable section")
        mapped = bytearray(pe.write())
        for offset, target in record.get("iat_patches", ()):
            struct.pack_into("<Q", mapped, offset, target)
        image = call_images.load(
            bytes(mapped),
            address=pe.OPTIONAL_HEADER.ImageBase + choices[0].VirtualAddress,
            _imports_resolved=True,
        )
        segments.extend(image["segments"])
        total += sum(s["size"] for s in image["segments"])
    if total > 64_000_000:
        raise ContractError("Linked DLL memory exceeds 64 MB")
    ranges = sorted(
        (s["address"] & ~4095, (s["address"] + s["size"] + 4095) & ~4095)
        for s in segments
    )
    if any(b[0] < a[1] for a, b in zip(ranges, ranges[1:])):
        raise ContractError("DLL mappings overlap")
    if not any(
        s["address"] <= entry < s["address"] + s["size"] and "x" in s["permissions"]
        for s in segments
    ):
        raise ContractError("Linked entry is not executable")
    return {
        "abi": "win64",
        "entry": entry,
        "segments": segments,
        "sha256": hashlib.sha256(data).hexdigest(),
        "dependencies": {
            name: hashlib.sha256(record["raw"]).hexdigest()
            for name, record in modules.items()
            if name != "<root>"
        },
        "imports": imports,
    }
