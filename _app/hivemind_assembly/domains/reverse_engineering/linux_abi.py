"""Deterministic metadata and single-thread Linux setup around Qiling handlers."""

from collections import defaultdict
import hashlib
import struct
from pathlib import Path
from hivemind_assembly.core.common import Blocked


class LinuxABI:
    def __init__(self, ql, root, clock_ns, memory_allowed):
        self.ql, self.root, self.clock_ns = ql, root, clock_ns
        self.memory_allowed = memory_allowed
        self.clear_tid = 0
        self.robust_list = 0

    def fd_path(self, descriptor):
        if (
            not 0 <= descriptor < len(self.ql.os.fd)
            or self.ql.os.fd[descriptor] is None
        ):
            return None
        name = getattr(self.ql.os.fd[descriptor], "name", None)
        if name is None:
            return None
        path = Path(name).resolve()
        if not path.is_relative_to(self.root):
            raise Blocked("filesystem_boundary")
        return path

    def stat(self, number, args, path, empty_path=False):
        from qiling.os.posix.syscall.stat import pack_stat_struct

        pointer = args[2] if number == 262 else args[1]
        descriptor = args[0] & 0xFFFFFFFF
        by_fd = number == 5 or (
            number == 262
            and empty_path
            and args[3] & 0x1000
            and descriptor != 0xFFFFFF9C
        )
        if number == 262 and args[3] & ~(0x100 | 0x1000):
            raise Blocked("unsupported_stat_flags")
        if number == 262 and empty_path and not args[3] & 0x1000:
            self.ql.os.set_syscall_return(-2)
            return
        if by_fd:
            path = self.fd_path(descriptor)
        info = defaultdict(int)
        info.update(st_nlink=1, st_blksize=4096)
        if by_fd and descriptor in (0, 1, 2) and self.ql.os.fd[descriptor] is not None:
            info.update(st_ino=descriptor + 1, st_mode=0o10600)
        elif path is not None and path.exists():
            name = "/" + path.relative_to(self.root).as_posix()
            info.update(
                st_ino=int.from_bytes(
                    hashlib.sha256(name.encode()).digest()[:8], "little"
                ),
                st_mode=0o40755 if path.is_dir() else 0o100644,
                st_size=path.stat().st_size if path.is_file() else 0,
            )
            info["st_blocks"] = (info["st_size"] + 511) // 512
        else:
            self.ql.os.set_syscall_return(-9 if by_fd else -2)
            return
        for field in ("atime", "mtime", "ctime"):
            info["st_" + field] = self.clock_ns // 1_000_000_000
            info["st_" + field + "_ns"] = self.clock_ns % 1_000_000_000
        packed = pack_stat_struct(self.ql, info)
        if not self.memory_allowed(pointer, len(packed), "w"):
            raise Blocked("invalid_buffer_memory")
        self.ql.mem.write(pointer, packed)
        self.ql.os.set_syscall_return(0)

    def setup(self, number, args):
        if number == 302:
            if args[0] != 0 or args[2] != 0:
                raise Blocked("unsupported_resource_change")
            limits = {
                1: 2_000_000,
                7: len(self.ql.os.fd),
                9: 128_000_000,
                3: sum(
                    end - start
                    for start, end, _, label, *_ in self.ql.mem.get_mapinfo()
                    if label == "[stack]"
                ),
            }
            if args[1] not in limits:
                raise Blocked("unsupported_resource_limit")
            if args[3]:
                if not self.memory_allowed(args[3], 16, "w"):
                    raise Blocked("invalid_buffer_memory")
                value = limits[args[1]]
                self.ql.mem.write(args[3], struct.pack("<QQ", value, value))
            self.ql.os.set_syscall_return(0)
            return True
        if number == 158:
            if args[0] not in (0x1001, 0x1002, 0x1003, 0x1004):
                raise Blocked("unsupported_arch_control")
            setting = args[0] in (0x1001, 0x1002)
            if not self.memory_allowed(
                args[1], 1 if setting else 8, "r" if setting else "w"
            ):
                raise Blocked("invalid_tls_memory")
            return False  # Validated MSR effects use upstream arch_prctl.
        if number == 218:
            if args[0] and not self.memory_allowed(args[0], 4, "w"):
                raise Blocked("invalid_tid_memory")
            self.clear_tid = args[0]
            self.ql.os.set_syscall_return(1)  # The declared guest has one thread.
        elif number == 273:
            if args[1] != 24 or not self.memory_allowed(args[0], 24, "r"):
                raise Blocked("invalid_robust_list")
            self.robust_list = args[0]
            self.ql.os.set_syscall_return(0)
        elif number == 334:
            self.ql.os.set_syscall_return(-38)  # This guest kernel has no rseq support.
        else:
            return False
        return True

    def exit(self):
        if (
            self.robust_list
            and self.ql.mem.read_ptr(self.robust_list) != self.robust_list
        ):
            raise Blocked("unsupported_thread_cleanup")
        if self.clear_tid:
            if not self.memory_allowed(self.clear_tid, 4, "w"):
                raise Blocked("invalid_tid_memory")
            self.ql.mem.write(self.clear_tid, b"\0" * 4)
