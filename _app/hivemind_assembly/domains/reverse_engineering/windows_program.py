"""Freestanding Windows x64 console reconstruction with an explicit API boundary.

Speakeasy supplies the PE loader and Windows calling conventions. HA supplies
bounded stream/clock contracts and rejects every API outside that contract.
No Windows DLLs, host mounts, network, CRT, GUI, threads or native target execution.
"""

import hashlib
import shutil
import tempfile
from pathlib import Path

from hivemind_assembly.core.common import (
    Blocked,
    ContractError,
    canonical,
    file_hash,
    uid,
)
from .program import sources
from .guest_cpu import unsupported as unsupported_cpu

API_NAMES = (
    "GetStdHandle",
    "ReadFile",
    "WriteFile",
    "ExitProcess",
    "GetTickCount",
    "GetTickCount64",
)
HEADER = """typedef unsigned long ha_dword;
typedef unsigned long long ha_size;
__declspec(dllimport) void *GetStdHandle(ha_dword);
__declspec(dllimport) int ReadFile(void *, void *, ha_dword, ha_dword *, void *);
__declspec(dllimport) int WriteFile(void *, const void *, ha_dword, ha_dword *, void *);
__declspec(dllimport) void ExitProcess(ha_dword);
__declspec(dllimport) ha_dword GetTickCount(void);
__declspec(dllimport) unsigned long long GetTickCount64(void);
long long ha_read(void *, ha_size);
long long ha_write(const void *, ha_size);
long long ha_error(const void *, ha_size);
void ha_exit(int);
int ha_main(void);
"""
RUNTIME = (
    HEADER
    + """
long long ha_read(void *p, ha_size n){ha_dword k=0;if(n>0xffffffffULL)return -1;return ReadFile(GetStdHandle((ha_dword)-10),p,(ha_dword)n,&k,0)?k:-1;}
long long ha_write(const void *p, ha_size n){ha_dword k=0;if(n>0xffffffffULL)return -1;return WriteFile(GetStdHandle((ha_dword)-11),p,(ha_dword)n,&k,0)?k:-1;}
long long ha_error(const void *p, ha_size n){ha_dword k=0;if(n>0xffffffffULL)return -1;return WriteFile(GetStdHandle((ha_dword)-12),p,(ha_dword)n,&k,0)?k:-1;}
void ha_exit(int code){ExitProcess((ha_dword)code);}
void ha_start(void){ha_exit(ha_main());}
"""
)
LIMIT = 1_000_000


def image_info(data):
    import pefile
    from .call_images import load

    if not isinstance(data, bytes) or not 64 <= len(data) <= 2_000_000:
        raise ContractError("Expected a PE executable of at most 2 MB")
    try:
        pe = pefile.PE(data=data)
    except pefile.PEFormatError as exc:
        raise ContractError("Invalid Windows PE image") from exc
    try:
        h = pe.OPTIONAL_HEADER
        if (
            pe.FILE_HEADER.Machine != 0x8664
            or h.Magic != 0x20B
            or pe.is_dll()
            or h.Subsystem != 3
        ):
            raise Blocked(
                "Windows program replay requires an x64 PE32+ console executable"
            )
        image = load(
            data, address=h.ImageBase + h.AddressOfEntryPoint, _imports_resolved=True
        )
        imports = []
        for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", ()):
            dll = entry.dll.decode("ascii", errors="strict").lower()
            for imp in entry.imports:
                name = (
                    imp.name.decode("ascii", errors="strict")
                    if imp.name
                    else "ordinal:" + str(imp.ordinal)
                )
                if dll != "kernel32.dll" or name not in API_NAMES:
                    raise Blocked("Unsupported Windows API: " + dll + "." + name)
                imports.append(name)
        if (
            len(imports) > 128
            or h.SizeOfStackReserve > 8_000_000
            or h.SizeOfHeapReserve > 8_000_000
        ):
            raise Blocked("Windows image resources exceed replay bounds")
        return {"imports": sorted(set(imports)), "image": image}
    finally:
        pe.close()


def build(root, manifest, jobs, compiler="", cancel=None):
    units = sources(root, manifest)
    if manifest.get("architecture", "x86_64") != "x86_64":
        raise ContractError("Windows whole-program builds currently require x86_64")
    executable = shutil.which(compiler or "clang")
    if not executable or "clang" not in Path(executable).name.lower():
        raise Blocked("Windows program reconstruction requires Clang and LLD")
    sibling = Path(executable).with_name(
        "lld-link.exe" if Path(executable).suffix == ".exe" else "lld-link"
    )
    linker = str(sibling) if sibling.is_file() else shutil.which("lld-link")
    if not linker:
        raise Blocked("Install lld-link alongside Clang")
    fingerprints = {
        "compiler_sha256": file_hash(executable),
        "linker_sha256": file_hash(linker),
    }
    with tempfile.TemporaryDirectory(prefix="ha-windows-build-") as tmp:
        stage = Path(tmp)
        (stage / "kernel32.def").write_text(
            "LIBRARY kernel32.dll\nEXPORTS\n" + "\n".join(API_NAMES) + "\n",
            encoding="ascii",
        )
        logs = []

        def run(argv):
            result = jobs.run(
                uid("windows-build"), argv, stage, timeout=120, cancel=cancel
            )
            logs.append(result)
            return result["status"] == "completed" and result["exit_code"] == 0

        if not run(
            [linker, "/lib", "/def:kernel32.def", "/machine:x64", "/out:kernel32.lib"]
        ):
            return {"passed": False, "stage": "import-library", "build": logs}
        paths = []
        for i, text in enumerate(units.values()):
            name = f"unit_{i}.c"
            (stage / name).write_text(
                HEADER + manifest.get("declarations", "") + "\n" + text,
                encoding="utf-8",
            )
            paths.append(name)
        (stage / "runtime.c").write_text(RUNTIME, encoding="utf-8")
        # Compile separately so the exact hashed linker is used on every host.
        if not run(
            [
                executable,
                "--target=x86_64-pc-windows-msvc",
                "-std=c11",
                "-" + manifest.get("optimization", "O2"),
                "-ffreestanding",
                "-fno-builtin",
                "-fno-stack-protector",
                "-nostdinc",
                "-fno-asynchronous-unwind-tables",
                "-fno-unwind-tables",
                "-c",
                *paths,
                "runtime.c",
            ]
        ):
            return {"passed": False, "stage": "compile", "build": logs}
        objects = []
        for source in [*paths, "runtime.c"]:
            matches = [
                Path(source).with_suffix(ext).name
                for ext in (".o", ".obj")
                if (stage / Path(source).with_suffix(ext)).is_file()
            ]
            if len(matches) != 1:
                raise Blocked("Compiler did not produce the expected object")
            objects.extend(matches)
        if not run(
            [
                linker,
                "/entry:ha_start",
                "/subsystem:console",
                "/nodefaultlib",
                "/timestamp:0",
                "/out:program.exe",
                *objects,
                "kernel32.lib",
            ]
        ):
            return {"passed": False, "stage": "link", "build": logs}
        path = stage / "program.exe"
        if not path.is_file() or path.stat().st_size > 2_000_000:
            raise Blocked("Linked Windows image is missing or oversized")
        data = path.read_bytes()
        image_info(data)
        if fingerprints != {
            "compiler_sha256": file_hash(executable),
            "linker_sha256": file_hash(linker),
        }:
            raise Blocked("Windows toolchain changed during build")
        return {
            "passed": True,
            "stage": "linked",
            "architecture": "x86_64",
            "pe_hex": data.hex(),
            "sha256": hashlib.sha256(data).hexdigest(),
            "sources": {
                n: hashlib.sha256(s.encode()).hexdigest() for n, s in units.items()
            },
            "manifest_sha256": hashlib.sha256(canonical(manifest).encode()).hexdigest(),
            "runtime_sha256": hashlib.sha256(RUNTIME.encode()).hexdigest(),
            **fingerprints,
            "build": logs,
        }


def validate_case(case):
    if not isinstance(case, dict) or set(case) - {
        "id",
        "input_hex",
        "clock_ms",
        "max_instructions",
        "effect_policy",
    }:
        raise ContractError(
            "Windows cases allow id, input_hex, clock_ms, max_instructions and effect_policy"
        )
    value = case.get("input_hex", "")
    if not isinstance(value, str) or len(value) > LIMIT * 2:
        raise ContractError("Windows input exceeds bounds")
    try:
        data = bytes.fromhex(value)
    except ValueError as exc:
        raise ContractError("Windows input must be hexadecimal") from exc
    if case.get("effect_policy", "strict") not in ("strict", "observable"):
        raise ContractError("Unknown Windows effect policy")
    for key, default, low, high in (
        ("clock_ms", 0, 0, 2**64 - 1),
        ("max_instructions", LIMIT, 1, 5_000_000),
    ):
        value = case.get(key, default)
        if type(value) is not int or not low <= value <= high:
            raise ContractError("Invalid Windows " + key)
    return data


def replay(data, stdin=b"", *, clock_ms=0, max_instructions=LIMIT, cancel=None):
    import time
    import speakeasy
    from capstone import Cs, CS_ARCH_X86, CS_MODE_64
    from speakeasy.config import get_default_config_dict

    validate_case(
        {
            "input_hex": stdin.hex(),
            "clock_ms": clock_ms,
            "max_instructions": max_instructions,
        }
    )
    image_info(data)
    result = {
        "status": "incomplete",
        "exit_code": None,
        "stdout_hex": "",
        "stderr_hex": "",
        "input_consumed": 0,
        "events": [],
        "fault": None,
        "instructions": 0,
        "runtime": "speakeasy_windows",
    }
    streams = {0xFFFFFFF5: bytearray(), 0xFFFFFFF4: bytearray()}
    config = get_default_config_dict()
    config.update(
        timeout=10,
        max_total_time=10,
        max_instructions=max_instructions + 1,
        max_api_count=10001,
        command_line="program.exe",
        env={},
        current_dir="C:\\work",
        stack_size=0x100000,
    )
    config["filesystem"] = {"files": []}
    config["registry"] = {"keys": []}
    config["exceptions"] = {"dispatch_handlers": False}
    config["analysis"] = {"strings": False, "memory_tracing": False, "coverage": False}
    se = speakeasy.Speakeasy(config=config)
    decoder, cache = Cs(CS_ARCH_X86, CS_MODE_64), {}
    started = time.monotonic()
    calls = 0

    class ReplayStop(Exception):
        pass

    def stop(status, reason):
        result.update(status=status, fault=reason)
        se.stop()
        raise ReplayStop(reason)

    def check():
        if cancel is not None and cancel.is_set():
            stop("cancelled", "Cancelled")
        if time.monotonic() - started > 10:
            stop("budget_exhausted", "Wall-clock limit")

    def guarded_instruction(emu, address, size):
        check()
        result["instructions"] += 1
        if result["instructions"] > max_instructions:
            stop("budget_exhausted", "Instruction limit")
        raw = bytes(emu.mem_read(address, min(size, 15)))
        key = (address, raw)
        if key not in cache:
            ins = next(decoder.disasm(raw, address), None)
            if ins is None:
                stop("unsupported", "Undecodable instruction")
            # Never treat CPU/environment/time/privileged effects as deterministic.
            if (
                unsupported_cpu(raw)
                or ins.mnemonic
                in {
                    "rdtsc",
                    "rdtscp",
                    "rdrand",
                    "rdseed",
                    "cpuid",
                    "syscall",
                    "sysenter",
                    "int",
                    "int1",
                    "int3",
                    "into",
                    "hlt",
                    "in",
                    "out",
                    "insb",
                    "insd",
                    "insw",
                    "outsb",
                    "outsd",
                    "outsw",
                    "rdmsr",
                    "wrmsr",
                    "xgetbv",
                }
                or "fs:" in ins.op_str
                or "gs:" in ins.op_str
            ):
                stop("unsupported", "Unmodeled instruction: " + ins.mnemonic)
            cache[key] = True

    def instruction(emu, address, size):
        # ctypes callbacks must never let Python exceptions escape into Unicorn.
        try:
            guarded_instruction(emu, address, size)
        except ReplayStop:
            return False
        except Exception as exc:
            result.update(status="fault", fault=str(exc)[:2000])
            se.stop()
            return False
        return True

    def api(emu, name, original, args):
        nonlocal calls
        check()
        calls += 1
        if calls > 10000:
            stop("budget_exhausted", "API call limit")
        if name not in {"kernel32." + n for n in API_NAMES} or original is None:
            stop("unsupported", "Unsupported Windows API: " + name)
        function = name.split(".")[-1]
        if function == "GetStdHandle":
            handle = args[0] & 0xFFFFFFFF
            if handle not in (0xFFFFFFF6, *streams):
                stop("unsupported", "Unsupported standard handle")
            return handle
        if function in ("ReadFile", "WriteFile"):
            handle, address, count, count_ptr, overlapped = args
            count &= 0xffffffff  # DWORD; upper argument-register bits are not part of the API.
            if count > LIMIT or not count_ptr or overlapped:
                stop("unsupported", "Only bounded synchronous stream I/O is supported")
            if function == "ReadFile":
                if handle != 0xFFFFFFF6:
                    stop("unsupported", "ReadFile requires standard input")
                offset = result["input_consumed"]
                chunk = stdin[offset : offset + count]
                if chunk:
                    emu.mem_write(address, chunk)
                result["input_consumed"] += len(chunk)
            else:
                if handle not in streams:
                    stop("unsupported", "WriteFile requires standard output or error")
                if sum(map(len, streams.values())) + count > LIMIT:
                    stop("budget_exhausted", "Output limit")
                chunk = bytes(emu.mem_read(address, count)) if count else b""
                streams[handle].extend(chunk)
            emu.mem_write(count_ptr, len(chunk).to_bytes(4, "little"))
            return 1
        if function.startswith("GetTickCount"):
            value = clock_ms if function.endswith("64") else clock_ms & 0xFFFFFFFF
            result["events"].append({"call": function, "value": value})
            return value
        result["exit_code"] = args[0] & 0xFFFFFFFF
        result["status"] = "completed"
        return original(args)

    try:
        if cancel is not None and cancel.is_set():
            result.update(status="cancelled", fault="Cancelled")
            return result
        se.add_api_hook(api, module="*", api_name="*")
        se.add_code_hook(instruction)
        module = se.load_module(data=data, filename="program.exe")
        se.run_module(module, all_entrypoints=False, emulate_children=False)
        report = se.get_report().model_dump()
        errors = [
            e.get("error") for e in report.get("entry_points", []) if e.get("error")
        ]
        if errors:
            if result["status"] in ("completed", "incomplete"):
                result.update(status="fault", fault=str(errors[0])[:2000])
        elif result["status"] == "incomplete":
            result["fault"] = "Program did not call ExitProcess"
    except Exception as exc:
        if result["status"] in ("completed", "incomplete"):
            result.update(status="fault", fault=str(exc)[:2000])
    finally:
        se.shutdown()
        result["stdout_hex"] = streams[0xFFFFFFF5].hex()
        result["stderr_hex"] = streams[0xFFFFFFF4].hex()
    return result


def compare(original, candidate, cases, cancel=None, dependencies=None):
    if dependencies:
        raise ContractError("Windows console replay does not accept external DLLs")
    if not isinstance(cases, list) or not 1 <= len(cases) <= 256:
        raise ContractError("Windows comparison requires 1–256 cases")
    inputs = [validate_case(c) for c in cases]
    results = []
    for case, data in zip(cases, inputs):
        args = {
            "clock_ms": case.get("clock_ms", 0),
            "max_instructions": case.get("max_instructions", LIMIT),
            "cancel": cancel,
        }
        before, after = replay(original, data, **args), replay(candidate, data, **args)
        fields = ["status", "exit_code", "stdout_hex", "stderr_hex", "input_consumed"]
        if case.get("effect_policy", "strict") == "strict":
            fields.append("events")
        differences = [f for f in fields if before[f] != after[f]]
        passed = before["status"] == after["status"] == "completed" and not differences
        results.append(
            {
                "id": case.get("id", len(results)),
                "passed": passed,
                "differences": differences,
                "effect_policy": case.get("effect_policy", "strict"),
                "original": before,
                "candidate": after,
            }
        )
        if cancel is not None and cancel.is_set():
            break
    return {
        "scope": "windows_program",
        "passed": len(results) == len(cases) and all(r["passed"] for r in results),
        "cases": results,
        "claim": "Windows x64 console PE replay on the retained corpus: exact standard streams, input consumption and process exit; strict cases also match fixed-clock observations. No all-input proof, arbitrary Windows compatibility or native model acceptance.",
    }
