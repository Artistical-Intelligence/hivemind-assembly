"""Cumulative static x86-64 ELF builds and deterministic whole-image replay.

The guest has no host filesystem or network. Linux read/write/exit and a fixed
clock are explicit boundaries. Unknown syscalls, dynamic linking, unsupported
instructions, faults and budget exhaustion cannot pass as successful execution.
"""

import hashlib
import re
import shutil
import struct
import tempfile
from pathlib import Path

from hivemind_assembly.core.common import (
    Blocked,
    ContractError,
    canonical,
    file_hash,
    scoped,
    uid,
)

HEADER = """typedef unsigned long ha_size;
long ha_argc(void);
const char *ha_argv(long index);
const char *ha_getenv(const char *name);
long ha_read(void *buffer, ha_size count);
long ha_write(const void *buffer, ha_size count);
void ha_exit(int code);
long ha_open(const char *path, long flags, long mode);
long ha_close(long fd);
long ha_seek(long fd, long offset, long origin);
long ha_file_read(long fd, void *buffer, ha_size count);
long ha_file_write(long fd, const void *buffer, ha_size count);
void *ha_map(ha_size count);
long ha_unmap(void *address, ha_size count);
long ha_mkdir(const char *path, long mode);
long ha_rmdir(const char *path);
long ha_remove(const char *path);
long ha_rename(const char *old_path, const char *new_path);
long ha_clock(long clock_id, long *seconds, long *nanoseconds);
long ha_random(void *buffer, ha_size count, long flags);
int ha_main(void);
"""
RUNTIME = (
    HEADER
    + r"""
static long ha_runtime_argc;
static char **ha_runtime_argv, **ha_runtime_env;
long ha_argc(void){return ha_runtime_argc;}
const char *ha_argv(long i){return i>=0 && i<ha_runtime_argc ? ha_runtime_argv[i] : (const char*)0;}
const char *ha_getenv(const char *name){if(!name || !*name)return (const char*)0;for(char **p=ha_runtime_env;*p;p++){long i=0;while(name[i] && name[i]!='=' && name[i]==(*p)[i])i++;if(!name[i] && (*p)[i]=='=')return *p+i+1;}return (const char*)0;}
int ha_boot(unsigned long *stack){ha_runtime_argc=(long)*stack;ha_runtime_argv=(char**)(stack+1);ha_runtime_env=ha_runtime_argv+ha_runtime_argc+1;return ha_main();}
long ha_read(void *p, ha_size n) { long r; __asm__ volatile("syscall":"=a"(r):"a"(0L),"D"(0L),"S"(p),"d"(n):"rcx","r11","memory"); return r; }
long ha_write(const void *p, ha_size n) { long r; __asm__ volatile("syscall":"=a"(r):"a"(1L),"D"(1L),"S"(p),"d"(n):"rcx","r11","memory"); return r; }
void ha_exit(int n) { __asm__ volatile("syscall"::"a"(60L),"D"((long)n):"rcx","r11","memory"); __builtin_unreachable(); }
static long ha_call3(long n,long a,long b,long c){long r;__asm__ volatile("syscall":"=a"(r):"a"(n),"D"(a),"S"(b),"d"(c):"rcx","r11","memory");return r;}
long ha_open(const char *p,long f,long m){return ha_call3(2,(long)p,f,m);}
long ha_mkdir(const char *p,long m){return ha_call3(83,(long)p,m,0);}
long ha_rmdir(const char *p){return ha_call3(84,(long)p,0,0);}
long ha_remove(const char *p){return ha_call3(87,(long)p,0,0);}
long ha_rename(const char *a,const char *b){return ha_call3(82,(long)a,(long)b,0);}
long ha_clock(long id,long *seconds,long *nanoseconds){long t[2];long r=ha_call3(228,id,(long)t,0);if(r==0){*seconds=t[0];*nanoseconds=t[1];}return r;}
long ha_random(void *p,ha_size n,long f){return ha_call3(318,(long)p,n,f);}
long ha_close(long f){return ha_call3(3,f,0,0);}
long ha_seek(long f,long o,long w){return ha_call3(8,f,o,w);}
long ha_file_read(long f,void *p,ha_size n){return ha_call3(0,f,(long)p,n);}
long ha_file_write(long f,const void *p,ha_size n){return ha_call3(1,f,(long)p,n);}
void *ha_map(ha_size n){long r;register long flags __asm__("r10")=34;register long fd __asm__("r8")=-1;register long off __asm__("r9")=0;__asm__ volatile("syscall":"=a"(r):"a"(9L),"D"(0L),"S"(n),"d"(3L),"r"(flags),"r"(fd),"r"(off):"rcx","r11","memory");return (void*)r;}
long ha_unmap(void *p,ha_size n){return ha_call3(11,(long)p,n,0);}
__attribute__((naked)) void _start(void) { __asm__ volatile("movq %rsp, %rdi; andq $-16, %rsp; call ha_boot; movl %eax, %edi; call ha_exit; ud2"); }
"""
)


def sources(root, manifest):
    if not isinstance(manifest, dict) or set(manifest) - {
        "sources",
        "declarations",
        "optimization",
    }:
        raise ContractError(
            "Build manifest allows sources, declarations and optimization"
        )
    paths = manifest.get("sources")
    if (
        not isinstance(paths, list)
        or not 1 <= len(paths) <= 64
        or len(paths) != len(set(paths))
    ):
        raise ContractError("Build requires 1–64 distinct C sources")
    result = {}
    for name in paths:
        if not isinstance(name, str) or not name.endswith(".c"):
            raise ContractError("Only C source files can be compiled")
        path = scoped(root, name)
        if path.stat().st_size > 256000:
            raise Blocked("C source exceeds 256 KB")
        result[name] = path.read_text("utf-8")
    declarations = manifest.get("declarations", "")
    if not isinstance(declarations, str) or len(declarations) > 64000:
        raise ContractError("Declarations exceed bounds")
    for source in [*result.values(), declarations]:
        # No preprocessor, assembler or host headers; fixed trusted runtime only.
        if "#" in source or re.search(r"\b(?:asm|__asm|__asm__)\b", source):
            raise Blocked(
                "Use declarations and separate C files; preprocessor and inline assembly are outside this build lane"
            )
    if manifest.get("optimization", "O2") not in ("O0", "O2"):
        raise ContractError("Optimization must be O0 or O2")
    return result


def build(root, manifest, jobs, compiler="", cancel=None):
    units = sources(root, manifest)
    executable = (
        shutil.which(compiler)
        if compiler
        else (shutil.which("clang") or shutil.which("gcc"))
    )
    if not executable:
        raise Blocked("Install Clang or GCC to build recovered programs")
    compiler_hash = file_hash(executable)
    with tempfile.TemporaryDirectory(prefix="ha-program-") as tmp:
        stage = Path(tmp)
        paths = []
        for i, source in enumerate(units.values()):
            name = f"unit_{i}.c"
            (stage / name).write_text(
                HEADER + "\n" + manifest.get("declarations", "") + "\n" + source,
                encoding="utf-8",
            )
            paths.append(name)
        (stage / "runtime.c").write_text(RUNTIME, encoding="utf-8")
        argv = [executable]
        if "clang" in Path(executable).name.lower():
            argv += ["--target=x86_64-unknown-linux-gnu"]
            import os

            if os.name == "nt":
                argv += ["-fuse-ld=lld"]
        argv += [
            "-m64",
            "-std=c11",
            "-" + manifest.get("optimization", "O2"),
            "-ffreestanding",
            "-fno-builtin",
            "-fno-stack-protector",
            "-fno-pie",
            "-no-pie",
            "-nostdlib",
            "-nostdinc",
            "-static",
            "-Wl,--build-id=none,-e,_start",
            *paths,
            "runtime.c",
            "-o",
            "program.elf",
        ]
        result = jobs.run(uid("program"), argv, stage, timeout=120, cancel=cancel)
        if result["status"] != "completed" or result["exit_code"] != 0:
            return {"passed": False, "stage": "build", "build": result}
        output = stage / "program.elf"
        if not output.exists() or output.stat().st_size > 2_000_000:
            raise Blocked("Linked image is missing or exceeds 2 MB")
        data = output.read_bytes()
        load_image(data)  # Reject wrong architecture/dynamic images before retaining.
        if file_hash(executable) != compiler_hash:
            raise Blocked("Compiler changed during the build")
        return {
            "passed": True,
            "stage": "linked",
            "elf_hex": data.hex(),
            "sha256": hashlib.sha256(data).hexdigest(),
            "sources": {
                n: hashlib.sha256(s.encode()).hexdigest() for n, s in units.items()
            },
            "manifest_sha256": hashlib.sha256(canonical(manifest).encode()).hexdigest(),
            "compiler_sha256": compiler_hash,
            "runtime_sha256": hashlib.sha256(RUNTIME.encode()).hexdigest(),
            "build": result,
        }


def load_image(data):
    if len(data) < 64 or len(data) > 2_000_000 or data[:7] != b"\x7fELF\x02\x01\x01":
        raise ContractError("Expected a bounded little-endian ELF64 executable")
    h = struct.unpack_from("<16sHHIQQQIHHHHHH", data)
    if h[1:3] != (2, 62) or h[9] != 56 or not 1 <= h[10] <= 128:
        raise Blocked("Only static x86-64 ET_EXEC images are supported")
    segments = []
    total = 0
    for i in range(h[10]):
        offset = h[5] + 56 * i
        if offset + 56 > len(data):
            raise ContractError("Truncated ELF program headers")
        kind, flags, start, address, _, size, memory, alignment = struct.unpack_from(
            "<IIQQQQQQ", data, offset
        )
        if kind in (2, 3):
            raise Blocked("Dynamic linking is outside the replay contract")
        if kind != 1:
            continue
        if (
            memory < size
            or start + size > len(data)
            or address < 0x10000
            or address + memory >= 0x10000000
            or memory > 16_000_000
        ):
            raise ContractError("Invalid or oversized load segment")
        if alignment and alignment & (alignment - 1):
            raise ContractError("Invalid ELF alignment")
        total += memory
        segments.append(
            {
                "address": address,
                "size": memory,
                "flags": flags,
                "data": data[start : start + size],
            }
        )
    if (
        not segments
        or total > 32_000_000
        or not any(
            s["address"] <= h[4] < s["address"] + s["size"] and s["flags"] & 1
            for s in segments
        )
    ):
        raise ContractError("Entry point is not in an executable load segment")
    return h[4], segments


def replay(
    data,
    input_bytes=b"",
    *,
    clock_ns=0,
    argv=None,
    env=None,
    max_instructions=1_000_000,
    observations=(),
    cancel=None,
):
    import unicorn as u
    from unicorn import x86_const as x

    if (
        len(input_bytes) > 1_000_000
        or type(clock_ns) is not int
        or not 0 <= clock_ns < 2**63
        or type(max_instructions) is not int
        or not 1 <= max_instructions <= 10_000_000
    ):
        raise ContractError("Replay input, clock or instruction bound invalid")
    from .process_inputs import normalize, entry_stack
    from .guest_cpu import unsupported as unsupported_cpu

    argv, env = normalize(argv, env)
    entry, segments = load_image(data)
    uc = u.Uc(u.UC_ARCH_X86, u.UC_MODE_64)
    pages = {}
    for s in segments:
        perms = (
            (u.UC_PROT_READ if s["flags"] & 4 else 0)
            | (u.UC_PROT_WRITE if s["flags"] & 2 else 0)
            | (u.UC_PROT_EXEC if s["flags"] & 1 else 0)
        )
        for address in range(
            s["address"] & ~4095, (s["address"] + s["size"] + 4095) & ~4095, 4096
        ):
            pages[address] = pages.get(address, 0) | perms
    for address in pages:
        uc.mem_map(address, 4096)
    for s in segments:
        uc.mem_write(s["address"], s["data"])
    for address, perms in pages.items():
        uc.mem_protect(address, 4096, perms)
    stack, stack_size = 0x70000000, 0x100000
    uc.mem_map(stack, stack_size, u.UC_PROT_READ | u.UC_PROT_WRITE)
    uc.reg_write(
        x.UC_X86_REG_RSP, entry_stack(uc.mem_write, stack + stack_size, argv, env)
    )
    events, output, stderr = [], bytearray(), bytearray()
    cursor, count, status, exit_code = 0, 0, "budget_exhausted", None
    fault = None

    def stop(reason):
        nonlocal status
        status = reason
        uc.emu_stop()

    def region(address, size, perm):
        if size > 1_000_000 or size < 0 or address + size > 2**64:
            return False
        return (
            all(
                (
                    pages.get(
                        p,
                        (
                            u.UC_PROT_READ | u.UC_PROT_WRITE
                            if stack <= p < stack + stack_size
                            else 0
                        ),
                    )
                    & perm
                )
                == perm
                for p in range(address & ~4095, (address + size + 4095) & ~4095, 4096)
            )
            if size
            else True
        )

    def syscall(engine, _):
        nonlocal cursor, exit_code
        number = engine.reg_read(x.UC_X86_REG_RAX)
        a, b, n = [
            engine.reg_read(r)
            for r in (x.UC_X86_REG_RDI, x.UC_X86_REG_RSI, x.UC_X86_REG_RDX)
        ]
        result = 0
        if len(events) >= 4096:
            stop("event_limit")
            return
        if number == 0 and a == 0:
            length = min(n, len(input_bytes) - cursor)
            if not region(b, length, u.UC_PROT_WRITE):
                result = -14
            else:
                engine.mem_write(b, input_bytes[cursor : cursor + length])
                cursor += length
                result = length
            events.append({"call": "read", "fd": a, "requested": n, "returned": result})
        elif number == 1 and a in (1, 2):
            if not region(b, n, u.UC_PROT_READ):
                result = -14
            elif len(output) + len(stderr) + n > 1_000_000:
                stop("output_limit")
                return
            else:
                payload = bytes(engine.mem_read(b, n))
                (output if a == 1 else stderr).extend(payload)
                result = n
            events.append({"call": "write", "fd": a, "returned": result})
        elif number in (60, 231):
            exit_code = a & 255
            events.append({"call": "exit", "code": exit_code})
            stop("completed")
        elif number == 228 and a in (0, 1):
            if not region(b, 16, u.UC_PROT_WRITE):
                result = -14
            else:
                engine.mem_write(
                    b,
                    struct.pack(
                        "<qq", clock_ns // 1_000_000_000, clock_ns % 1_000_000_000
                    ),
                )
            events.append({"call": "clock_gettime", "clock": a, "result": result})
        else:
            events.append({"call": "unsupported", "number": number})
            stop("unsupported_syscall")
        engine.reg_write(x.UC_X86_REG_RAX, result & ((1 << 64) - 1))
        engine.reg_write(x.UC_X86_REG_RCX, engine.reg_read(x.UC_X86_REG_RIP) + 2)
        engine.reg_write(x.UC_X86_REG_R11, engine.reg_read(x.UC_X86_REG_EFLAGS))

    def instruction(engine, address, size, _):
        nonlocal count
        count += 1
        if not 1 <= size <= 15 or unsupported_cpu(
            bytes(engine.mem_read(address, size))
        ):
            stop("unsupported_cpu_state")
            return
        if cancel is not None and count % 1024 == 0 and cancel.is_set():
            stop("cancelled")

    def invalid(engine, access, address, size, value, _):
        nonlocal fault
        fault = {"access": access, "address": address, "size": size}
        stop("fault")
        return False

    uc.hook_add(u.UC_HOOK_INSN, syscall, None, 1, 0, x.UC_X86_INS_SYSCALL)
    uc.hook_add(u.UC_HOOK_CODE, instruction)
    uc.hook_add(u.UC_HOOK_MEM_INVALID, invalid)
    try:
        uc.emu_start(entry, 0, count=max_instructions, timeout=5_000_000)
    except u.UcError as error:
        if status != "fault":
            status = "unsupported_instruction_or_fault"
            fault = {"error": str(error)}
    memory = []
    if not isinstance(observations, (list, tuple)) or len(observations) > 64:
        raise ContractError("At most 64 explicit memory observations")
    for item in observations:
        address, size = item["address"], item["size"]
        if (
            type(address) is not int
            or type(size) is not int
            or not 0 <= size <= 65536
            or not region(address, size, u.UC_PROT_READ)
        ):
            raise ContractError("Memory observation outside readable guest memory")
        memory.append(
            {"address": address, "bytes": bytes(uc.mem_read(address, size)).hex()}
        )
    return {
        "status": status,
        "exit_code": exit_code,
        "stdout_hex": output.hex(),
        "stderr_hex": stderr.hex(),
        "input_consumed": cursor,
        "events": events,
        "memory": memory,
        "fault": fault,
        "instructions": count,
    }


def compare(original, candidate, cases, cancel=None, dependencies=None):
    if not isinstance(cases, list) or not 1 <= len(cases) <= 256:
        raise ContractError("Program comparison requires 1–256 cases")
    results = []
    for case in cases:
        policy = case.get("effect_policy", "strict")
        if policy not in ("strict", "observable"):
            raise ContractError("Unknown program effect comparison policy")
        args = {
            "clock_ns": case.get("clock_ns", 0),
            "argv": case.get("argv"),
            "env": case.get("env"),
            "max_instructions": case.get("max_instructions", 1_000_000),
            "cancel": cancel,
        }
        runner = replay
        runtime = case.get("runtime", "unicorn_linux")
        if runtime == "qiling_linux":
            from .platform_runtime import replay as qiling_replay

            runner = qiling_replay
            args.update(
                files=case.get("files", {}),
                random_hex=case.get("random_hex", ""),
                dependencies=dependencies,
            )
        elif runtime != "unicorn_linux":
            raise ContractError("Unknown program runtime")
        before = runner(
            original,
            bytes.fromhex(case.get("input_hex", "")),
            observations=case.get("original_memory", ()),
            **args,
        )
        after = runner(
            candidate,
            bytes.fromhex(case.get("input_hex", "")),
            observations=case.get("candidate_memory", ()),
            **args,
        )
        fields = (
            "status",
            "exit_code",
            "stdout_hex",
            "stderr_hex",
            "input_consumed",
            "fault",
        )
        differences = [key for key in fields if before[key] != after[key]]
        if before.get("files") != after.get("files"):
            differences.append("files")
        if before.get("directories") != after.get("directories"):
            differences.append("directories")
        if policy == "strict" and before.get("random_used") != after.get("random_used"):
            differences.append("random_used")
        # Memory addresses may move between builds; compare explicitly paired regions.
        if [x["bytes"] for x in before["memory"]] != [
            x["bytes"] for x in after["memory"]
        ]:
            differences.append("memory")
        # Stream writes may be coalesced, but clocks and other effects stay ordered.
        effects = lambda r: [
            e for e in r["events"] if e["call"] not in ("read", "write")
        ]
        if policy == "strict" and effects(before) != effects(after):
            differences.append("external_effects")
        passed = before["status"] == after["status"] == "completed" and not differences
        results.append(
            {
                "id": case.get("id", len(results)),
                "effect_policy": policy,
                "passed": passed,
                "differences": differences,
                "original": before,
                "candidate": after,
            }
        )
    return {
        "passed": all(r["passed"] for r in results),
        "scope": "x86_64_linux_program",
        "cases": results,
        "claim": "Deterministic bounded corpus. Strict cases also match application effects and random consumption; observable cases compare streams, exit, input consumption, selected memory and final files/directories. Traces are retained. No all-input proof or arbitrary OS compatibility.",
    }
