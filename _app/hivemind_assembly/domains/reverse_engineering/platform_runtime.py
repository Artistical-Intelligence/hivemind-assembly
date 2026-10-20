"""Bounded Linux application replay using the complete upstream Qiling engine.

Qiling supplies ELF loading and Linux memory/filesystem semantics. This adapter
adds an explicit syscall contract, a fresh declared filesystem, deterministic
clock/random input, cancellation and evidence. It never forwards guest process
creation, networking or arbitrary host file access.
"""

import hashlib
import io
import struct
import tempfile
from pathlib import Path, PurePosixPath
from types import MethodType
from .program import load_image
from hivemind_assembly.core.common import Blocked, ContractError


# These handlers execute solely on the staged rootfs or guest memory. The
# dispatcher guard runs before upstream resolves or invokes any syscall.
ALLOWED = {
    0: "read",
    1: "write",
    2: "open",
    3: "close",
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
    from .guest_cpu import unsupported as unsupported_cpu

    argv, env = normalize(argv, env)
    load_image(data)
    declared = files_spec(files or {})
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
    events = []
    state = {
        "status": "budget_exhausted",
        "exit_code": None,
        "instructions": 0,
        "random_used": 0,
    }
    with tempfile.TemporaryDirectory(prefix="ha-qiling-") as directory:
        root = Path(directory).resolve()
        binary = root / ".ha/program"
        binary.parent.mkdir()
        binary.write_bytes(data)
        for name, content in declared.items():
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
        if ql.arch.bits != 64 or ql.os.type.name != "LINUX":
            raise Blocked("Platform lane requires Linux x86-64")
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

        def dispatch(os):
            number = os.get_syscall()
            args = [
                ql.arch.regs.read(r) for r in ("rdi", "rsi", "rdx", "r10", "r8", "r9")
            ]
            if len(events) >= 4096:
                stop("event_limit")
                return
            name = ALLOWED.get(number)
            if name is None:
                events.append({"call": "unsupported", "number": number})
                stop("unsupported_syscall")
                return
            event = {"call": name}
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
                host = Path(ql.os.path.virtual_to_host_path(text)).resolve()
                if (
                    not host.is_relative_to(root)
                    or host == binary
                    or binary.parent in host.parents
                ):
                    stop("filesystem_boundary")
                    return
                event.setdefault("paths", []).append(
                    "/" + host.relative_to(root).as_posix()
                )
            # openat/fstatat may only resolve from CWD here; directory-fd effects
            # require their own declared contract and cannot inherit host FDs.
            if number in (257, 262) and args[0] not in ((-100) & MASK,):
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
                    if p.is_file() and binary.parent not in p.parents
                ]
                if (
                    offset + args[2] > 2_000_000
                    or len(owned) > 128
                    or sum(p.stat().st_size for p in owned) + args[2] > 8_000_000
                ):
                    stop("filesystem_limit")
                    return
            if number == 9 and args[3] & 0x10:
                stop("unsupported_fixed_mapping")
                return
            if (
                number in (2, 257)
                and len(
                    [
                        p
                        for p in root.rglob("*")
                        if p.is_file() and binary.parent not in p.parents
                    ]
                )
                >= 128
            ):
                # Opening an existing file is allowed at the file-count limit.
                if not host.is_file():
                    stop("filesystem_limit")
                    return
            if number in (60, 231):
                state["exit_code"] = args[0] & 255
                event["code"] = state["exit_code"]
                events.append(event)
                stop("completed")
                return
            if number == 228:
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
                original()
                # Results that expose allocation addresses are implementation
                # details; actual memory/output observations still compare.
                if number not in (9, 12):
                    event["result"] = ql.arch.regs.rax
                if number in (0, 1, 3, 8, 17, 18):
                    event["fd"] = args[0]
            events.append(event)

        ql.os.load_syscall = MethodType(dispatch, ql.os)

        def instruction(engine, address, size):
            state["instructions"] += 1
            if not 1 <= size <= 15 or unsupported_cpu(
                bytes(ql.mem.read(address, size))
            ):
                stop("unsupported_cpu_state")
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
            ql.run(count=max_instructions, timeout=5_000_000)
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
            if path.is_file() and binary.parent not in path.parents:
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
            "memory": memory,
            "fault": fault,
            "files": outputs,
            "engine": "qiling-1.4.6",
            "image_sha256": hashlib.sha256(data).hexdigest(),
        }
