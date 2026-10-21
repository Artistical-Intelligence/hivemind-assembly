"""Bounded Linux application replay using the complete upstream Qiling engine.

Qiling supplies ELF loading and Linux memory/filesystem semantics. This adapter
adds an explicit syscall contract, a fresh declared filesystem, deterministic
clock/random input, cancellation and evidence. It never forwards guest process
creation, networking or arbitrary host file access.
"""

from contextlib import ExitStack
import hashlib
import io
import struct
import tempfile
from pathlib import Path, PurePosixPath
from types import MethodType
from hivemind_assembly.core.common import Blocked, ContractError


# These handlers execute solely on the staged rootfs or guest memory. The
# dispatcher guard runs before upstream resolves or invokes any syscall.
ALLOWED = {
    0: "read",
    1: "write",
    2: "open",
    3: "close",
    4: "stat",
    5: "fstat",
    6: "lstat",
    8: "lseek",
    9: "mmap",
    10: "mprotect",
    11: "munmap",
    12: "brk",
    17: "pread64",
    18: "pwrite64",
    21: "access",
    60: "exit",
    79: "getcwd",
    82: "rename",
    83: "mkdir",
    84: "rmdir",
    87: "unlink",
    228: "clock_gettime",
    231: "exit_group",
    257: "openat",
    318: "getrandom",
    262: "newfstatat",
    158: "arch_prctl",
    218: "set_tid_address",
    273: "set_robust_list",
    334: "rseq",
    302: "prlimit64",
}
PATH_ARGS = {
    2: (0,),
    4: (0,),
    6: (0,),
    21: (0,),
    82: (0, 1),
    83: (0,),
    84: (0,),
    87: (0,),
    257: (1,),
    262: (1,),
}
MASK = (1 << 64) - 1


def files_spec(files):
    if not isinstance(files, dict) or len(files) > 128:
        raise ContractError("At most 128 declared guest files")
    result = {}
    for name, data in files.items():
        if (
            not isinstance(name, str)
            or not name.startswith("/")
            or "\\" in name
            or "\x00" in name
            or len(name) > 1024
        ):
            raise ContractError("Guest files require absolute POSIX paths")
        parts = PurePosixPath(name).parts
        if str(PurePosixPath(name)) != name or name == "/":
            raise ContractError("Guest file paths must be canonical")
        if ".." in parts or name.startswith("/.ha/") or name == "/.ha":
            raise Blocked("Guest file path is reserved or traverses its root")
        if not isinstance(data, str) or len(data) > 2_000_000:
            raise ContractError("Guest file exceeds bounds")
        result[name] = bytes.fromhex(data)
    if sum(map(len, result.values())) > 8_000_000:
        raise ContractError("Guest filesystem exceeds 8 MB")
    return result


class BoundedStream(io.BytesIO):
    def __init__(self, initial=b"", fd=0):
        super().__init__(initial)
        self.fd = fd

    def fileno(self):
        return self.fd

    def write(self, data):
        if self.tell() + len(data) > 1_000_000:
            raise Blocked("Guest stream exceeds 1 MB")
        return super().write(data)

    def close(self):
        # Keep evidence readable after guest close; descriptor ownership is Qiling's.
        pass


def replay(
    data,
    input_bytes=b"",
    *,
    files=None,
    dependencies=None,
    clock_ns=0,
    argv=None,
    env=None,
    random_hex="",
    max_instructions=1_000_000,
    observations=(),
    cancel=None,
):
    from qiling import Qiling
    from qiling.const import QL_VERBOSE

    from .process_inputs import normalize
    from .guest_cpu import opcode, unsupported as unsupported_cpu

    argv, env = normalize(argv, env)
    from .linux_dependencies import validate
    from .linux_abi import LinuxABI
    from .program import image_machine

    dependencies = {} if dependencies is None else dependencies
    arm = image_machine(data) == 183
    info = validate(data, dependencies)
    declared = files_spec(files or {})
    if set(declared) & set(dependencies):
        raise ContractError("Guest files cannot replace executable dependencies")
    if (
        len(input_bytes) > 1_000_000
        or type(max_instructions) is not int
        or not 1 <= max_instructions <= 10_000_000
    ):
        raise ContractError("Invalid platform replay bounds")
    if (
        type(clock_ns) is not int
        or not 0 <= clock_ns < 2**63
        or not isinstance(random_hex, str)
        or len(random_hex) > 2_000_000
    ):
        raise ContractError("Invalid deterministic clock/random inputs")
    random_bytes = bytes.fromhex(random_hex)
    events, loader_events = [], []
    phase = {"loading": bool(info["interpreter"])}
    state = {
        "status": "budget_exhausted",
        "exit_code": None,
        "instructions": 0,
        "random_used": 0,
    }
    with tempfile.TemporaryDirectory(
        prefix="ha-qiling-"
    ) as directory, ExitStack() as cleanup:
        root = Path(directory).resolve()
        binary = root / ".ha/program"
        binary.parent.mkdir()
        binary.write_bytes(data)
        for name, content in {**declared, **dependencies}.items():
            path = root / name.lstrip("/")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

        # Qiling's ELF loader encodes strings as Latin-1. Preserve the declared
        # UTF-8 bytes and separate the guest program name from the staged host path.
        class DeclaredProcess(Qiling):
            @property
            def path(self):
                return str(binary)

            @property
            def argv(self):
                return [value.encode("utf-8").decode("latin-1") for value in argv]

        ql = DeclaredProcess(
            [str(binary)],
            str(root),
            env={
                key.encode("utf-8")
                .decode("latin-1"): value.encode("utf-8")
                .decode("latin-1")
                for key, value in env.items()
            },
            verbose=QL_VERBOSE.OFF,
            console=False,
            multithread=False,
        )

        def close_guest_files():
            for descriptor in range(3, len(ql.os.fd)):
                value = ql.os.fd[descriptor]
                if value is not None:
                    value.close()
                    ql.os.fd[descriptor] = None

        cleanup.callback(close_guest_files)
        from unicorn.x86_const import UC_CPU_X86_HASWELL
        from unicorn.arm64_const import UC_CPU_ARM64_A72

        if ql.uc.ctl_get_cpu_model() != (UC_CPU_ARM64_A72 if arm else UC_CPU_X86_HASWELL):
            raise Blocked("Unsupported guest CPU model; revalidate the runtime")
        if arm:
            from .arm64_linux import configure_auxv

            configure_auxv(ql)
        dependency_paths = {root / name.lstrip("/") for name in dependencies}
        application_entry = ql.loader.elf_entry

        def entered_application(engine):
            phase["loading"] = False

        if phase["loading"]:
            ql.hook_address(entered_application, application_entry)
        if ql.arch.bits != 64 or ql.os.type.name != "LINUX" or ql.arch.type.name != ("ARM64" if arm else "X8664"):
            raise Blocked("Platform lane requires the selected Linux x86-64/AArch64 architecture")
        result_register = "x0" if arm else "rax"
        stdin, stdout, stderr = (
            BoundedStream(input_bytes, 0),
            BoundedStream(fd=1),
            BoundedStream(fd=2),
        )
        ql.os.stdin, ql.os.stdout, ql.os.stderr = stdin, stdout, stderr
        original = ql.os.load_syscall
        initial_brk = ql.loader.brk_address

        def stop(reason):
            state["status"] = reason
            ql.stop()

        def memory_allowed(address, size, permission):
            if size == 0:
                return True
            if address < 0 or size < 0 or address + size > 2**64:
                return False
            end = address + size
            for begin, limit, permissions, *_ in sorted(ql.mem.get_mapinfo()):
                if begin <= address < limit and permission in permissions:
                    address = min(end, limit)
                    if address == end:
                        return True
            return False

        abi = LinuxABI(ql, root, clock_ns, memory_allowed)

        def record(event):
            if len(events) + len(loader_events) >= 4096:
                stop("event_limit")
                return
            (loader_events if phase["loading"] else events).append(event)

        def replaceable_mapping(address, size):
            end = address + size
            for begin, limit, _, label, *_ in sorted(ql.mem.get_mapinfo()):
                if begin <= address < limit and label.startswith("[mmap"):
                    address = min(end, limit)
                    if address == end:
                        return True
            return False

        def dispatch(os):
            original_number = number = os.get_syscall()
            args = [
                ql.arch.regs.read(r) for r in (("x0", "x1", "x2", "x3", "x4", "x5") if arm else ("rdi", "rsi", "rdx", "r10", "r8", "r9"))
            ]
            adapted_handler = None
            if arm:
                from .program_arm64 import qiling_operation

                number, args, adapted_handler = qiling_operation(number, args)
            if len(events) + len(loader_events) >= 4096:
                stop("event_limit")
                return
            name = ALLOWED.get(number)
            if name is None:
                record({"call": "unsupported", "number": original_number})
                stop("unsupported_syscall")
                return
            if phase["loading"] and (
                number
                not in (
                    0,
                    2,
                    3,
                    4,
                    5,
                    6,
                    8,
                    9,
                    10,
                    11,
                    12,
                    17,
                    21,
                    158,
                    218,
                    257,
                    262,
                    273,
                    302,
                    334,
                )
                or (number in (0, 17) and args[0] < 3)
            ):
                stop("unsupported_loader_effect")
                return
            event = {"call": name}
            host, empty_path = None, False
            for index in PATH_ARGS.get(number, ()):
                raw = bytearray()
                for offset in range(4096):
                    if not memory_allowed(args[index] + offset, 1, "r"):
                        stop("invalid_path_memory")
                        return
                    byte = bytes(ql.mem.read(args[index] + offset, 1))
                    if byte == b"\x00":
                        break
                    raw.extend(byte)
                else:
                    stop("path_limit")
                    return
                text = raw.decode("utf-8", errors="strict")
                empty_path = not text
                host = Path(ql.os.path.virtual_to_host_path(text)).resolve()
                if (
                    not host.is_relative_to(root)
                    or host == binary
                    or binary.parent in host.parents
                    or text == "/proc"
                    or text.startswith("/proc/")
                ):
                    stop("filesystem_boundary")
                    return
                flags = args[1] if number == 2 else args[2] if number == 257 else 0
                writing = number in (82, 83, 84, 87) or (
                    number in (2, 257) and flags & (3 | 0x40 | 0x200 | 0x400)
                )
                affects_dependency = any(
                    dep == host or host in dep.parents for dep in dependency_paths
                )
                if writing and (phase["loading"] or affects_dependency):
                    stop(
                        "readonly_dependency"
                        if affects_dependency
                        else "unsupported_loader_effect"
                    )
                    return
                event.setdefault("paths", []).append(
                    "/" + host.relative_to(root).as_posix()
                )
            # openat/fstatat may only resolve from CWD here; directory-fd effects
            # require their own declared contract and cannot inherit host FDs.
            if (
                number in (257, 262)
                and (args[0] & 0xFFFFFFFF) != 0xFFFFFF9C
                and not (number == 262 and empty_path and args[3] & 0x1000)
            ):
                stop("unsupported_directory_fd")
                return
            if number in (0, 1, 17, 18) and args[2] > 1_000_000:
                stop("io_limit")
                return
            buffers = {
                0: (1, 2, "w"),
                1: (1, 2, "r"),
                17: (1, 2, "w"),
                18: (1, 2, "r"),
                79: (0, 1, "w"),
                318: (0, 1, "w"),
            }
            if number in buffers:
                pointer, length, permission = buffers[number]
                if args[length] > 1_000_000 or not memory_allowed(
                    args[pointer], args[length], permission
                ):
                    stop("invalid_buffer_memory")
                    return
            if number == 228 and not memory_allowed(args[1], 16, "w"):
                stop("invalid_buffer_memory")
                return
            if number in (9, 10, 11) and args[1] > 16_000_000:
                stop("memory_limit")
                return
            if number == 12 and args[0] and abs(args[0] - initial_brk) > 16_000_000:
                stop("memory_limit")
                return
            mapped = sum(end - start for start, end, *_ in ql.mem.get_mapinfo())
            if number == 9 and mapped + args[1] > 128_000_000:
                stop("memory_limit")
                return
            if number in (1, 18):
                f = ql.os.fd[args[0]] if args[0] < len(ql.os.fd) else None
                offset = (
                    args[3]
                    if number == 18
                    else (f.lseek(0, 1) if f is not None and hasattr(f, "lseek") else 0)
                )
                owned = [
                    p
                    for p in root.rglob("*")
                    if p.is_file()
                    and binary.parent not in p.parents
                    and p not in dependency_paths
                ]
                if (
                    offset + args[2] > 2_000_000
                    or len(owned) > 128
                    or sum(p.stat().st_size for p in owned) + args[2] > 8_000_000
                ):
                    stop("filesystem_limit")
                    return
            if number == 9:
                if args[2] & 4 and (
                    args[3] & 0x20
                    or abi.fd_path(args[4] & 0xFFFFFFFF) not in dependency_paths
                ):
                    stop("undeclared_executable_mapping")
                    return
                if args[3] & 1:
                    stop("unsupported_shared_mapping")
                    return
                if args[3] & 0x10 and not replaceable_mapping(args[0], args[1]):
                    stop("unsupported_fixed_mapping")
                    return
            if (
                number in (2, 257)
                and len(
                    [
                        p
                        for p in root.rglob("*")
                        if p.is_file()
                        and binary.parent not in p.parents
                        and p not in dependency_paths
                    ]
                )
                >= 128
            ):
                # Opening an existing file is allowed at the file-count limit.
                if not host.is_file():
                    stop("filesystem_limit")
                    return
            if number in (60, 231):
                abi.exit()
                state["exit_code"] = args[0] & 255
                event["code"] = state["exit_code"]
                record(event)
                stop("completed")
                return
            if number in (4, 5, 6, 262):
                abi.stat(number, args, host, empty_path)
                event["result"] = ql.arch.regs.read(result_register)
            elif abi.setup(number, args):
                event["result"] = ql.arch.regs.read(result_register)
            elif number == 228:
                if args[0] not in (0, 1):
                    stop("unsupported_clock")
                    return
                ql.mem.write(
                    args[1],
                    struct.pack(
                        "<qq", clock_ns // 1_000_000_000, clock_ns % 1_000_000_000
                    ),
                )
                os.set_syscall_return(0)
                event["clock"] = args[0]
            elif number == 318:
                size = args[1]
                if (
                    args[2] not in (0, 1, 2, 3)
                    or size > len(random_bytes) - state["random_used"]
                ):
                    stop("random_input_exhausted")
                    return
                begin = state["random_used"]
                ql.mem.write(args[0], random_bytes[begin : begin + size])
                state["random_used"] += size
                os.set_syscall_return(size)
                event["count"] = size
            else:
                if adapted_handler:
                    handler, count = adapted_handler
                    os.set_syscall_return(handler(ql, *args[:count]))
                else:
                    original()
                # Results that expose allocation addresses are implementation
                # details; actual memory/output observations still compare.
                if number not in (9, 12):
                    event["result"] = ql.arch.regs.read(result_register)
                if number in (0, 1, 3, 8, 17, 18):
                    event["fd"] = args[0]
            record(event)

        ql.os.load_syscall = MethodType(dispatch, ql.os)

        def instruction(engine, address, size):
            state["instructions"] += 1
            raw = bytes(ql.mem.read(address, size)) if 1 <= size <= 15 else b""
            op = opcode(raw) if not arm else None
            if arm:
                from .arm64 import unsupported_instruction
                from .arm64_linux import runtime_instruction

                valid_state = size == 4 and address % 4 == 0 and ql.arch.regs.sp % 16 == 0
                handled = valid_state and bool(info["interpreter"]) and runtime_instruction(
                    ql, int.from_bytes(raw, "little"), address, memory_allowed, record
                )
                if not valid_state or (
                    not handled and raw != b"\x01\x00\x00\xd4" and unsupported_instruction(raw)
                ):
                    record({"call": "unsupported_cpu", "instruction": raw.hex()})
                    stop("unsupported_cpu_state")
                    return
            elif dependencies and op in (b"\x0f\x31", b"\x0f\x01\xf9"):
                # A fixed 1 GHz guest timestamp counter shares the declared clock.
                ql.arch.regs.rax = clock_ns & 0xFFFFFFFF
                ql.arch.regs.rdx = clock_ns >> 32
                if op == b"\x0f\x01\xf9":
                    ql.arch.regs.rcx = 0
                record({"call": "cpu_clock", "value": clock_ns})
                ql.arch.regs.rip = address + size
            elif unsupported_cpu(raw, allow_queries=bool(dependencies)):
                record({"call": "unsupported_cpu", "instruction": raw.hex()})
                stop("unsupported_cpu_state")
                return
            if state["instructions"] >= max_instructions:
                stop("budget_exhausted")
                return
            if state["instructions"] % 1024 == 0:
                if cancel is not None and cancel.is_set():
                    stop("cancelled")
                # Enforce total mapped-memory bound in addition to each allocation.
                if (
                    sum(end - start for start, end, *_ in ql.mem.get_mapinfo())
                    > 128_000_000
                ):
                    stop("memory_limit")

        ql.hook_code(instruction)
        fault = None
        try:
            # One bounded run spans interpreter and application. Qiling's default
            # two-stage Linux run would restart at the application after a stopped
            # interpreter, so explicitly begin at the loader's first entry.
            ql.run(
                begin=ql.loader.entry_point, count=max_instructions, timeout=5_000_000
            )
        except Blocked as error:
            state["status"] = str(error)
            fault = {"kind": type(error).__name__}
        except Exception as error:
            if state["status"] == "budget_exhausted":
                state["status"] = "fault"
            fault = {"kind": type(error).__name__}
        memory = []
        if len(observations) > 64:
            raise ContractError("At most 64 memory observations")
        for item in observations:
            address, size = item["address"], item["size"]
            if (
                type(address) is not int
                or type(size) is not int
                or not 0 <= size <= 65536
            ):
                raise ContractError("Invalid memory observation")
            if not memory_allowed(address, size, "r"):
                raise Blocked("Memory observation is outside readable guest memory")
            memory.append(
                {"address": address, "bytes": bytes(ql.mem.read(address, size)).hex()}
            )
        outputs = {}
        for path in sorted(root.rglob("*")):
            if (
                path.is_file()
                and binary.parent not in path.parents
                and path not in dependency_paths
            ):
                if path.stat().st_size > 2_000_000:
                    stop("filesystem_limit")
                    break
                outputs["/" + path.relative_to(root).as_posix()] = (
                    path.read_bytes().hex()
                )
        if len(outputs) > 128 or sum(len(v) // 2 for v in outputs.values()) > 8_000_000:
            state["status"] = "filesystem_limit"
        return {
            **state,
            "stdout_hex": stdout.getvalue().hex(),
            "stderr_hex": stderr.getvalue().hex(),
            "input_consumed": stdin.tell(),
            "events": events,
            "loader_events": loader_events,
            "loader_completed": not phase["loading"],
            "dependencies": {
                name: hashlib.sha256(value).hexdigest()
                for name, value in dependencies.items()
            },
            "cpu_model": "cortex-a72" if arm else "haswell",
            "memory": memory,
            "fault": fault,
            "files": outputs,
            "directories": sorted(
                "/" + p.relative_to(root).as_posix()
                for p in root.rglob("*")
                if p.is_dir() and p != binary.parent and binary.parent not in p.parents
            ),
            "engine": "qiling-1.4.6",
            "image_sha256": hashlib.sha256(data).hexdigest(),
        }
