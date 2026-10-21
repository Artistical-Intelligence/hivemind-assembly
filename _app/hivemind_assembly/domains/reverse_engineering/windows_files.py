"""Declared, in-memory Win32 regular files; never resolve paths on the host.

Speakeasy owns PE loading/ABI dispatch. This adapter owns the deliberately narrow
file contract, including independent cursors over shared bytes and access checks.
"""

import hashlib
import re

from hivemind_assembly.core.common import ContractError

LIMIT = 1_000_000
READ, WRITE = 0x80000000, 0x40000000
INVALID = 0xFFFFFFFFFFFFFFFF
FILE_APIS = (
    "CreateFileA",
    "CreateFileW",
    "CloseHandle",
    "SetFilePointerEx",
    "GetFileSizeEx",
    "SetEndOfFile",
    "DeleteFileA",
    "DeleteFileW",
    "GetLastError",
    "SetLastError",
)


def filename(value):
    """ASCII regular-file names in the fixed C:\\work directory only."""
    if not isinstance(value, str):
        raise ContractError("Windows file name must be a string")
    value = value.replace("/", "\\").lower()
    if value.startswith("c:\\work\\"):
        value = value[8:]
    elif value.startswith(".\\"):
        value = value[2:]
    if (
        not re.fullmatch(r"[a-z0-9_][a-z0-9_. -]{0,119}", value)
        or value.endswith((".", " "))
        or value.split(".")[0].rstrip()
        in {
            "con",
            "prn",
            "aux",
            "nul",
            "conin$",
            "conout$",
            *("com" + str(i) for i in range(1, 10)),
            *("lpt" + str(i) for i in range(1, 10)),
        }
    ):
        raise ContractError("Only ordinary ASCII file names in C:\\work are supported")
    return value


def declared_files(files):
    if not isinstance(files, dict) or len(files) > 64:
        raise ContractError(
            "Windows files must map at most 64 names to hexadecimal bytes"
        )
    result = {}
    total = 0
    for path, value in files.items():
        path = filename(path)
        if path in result:
            raise ContractError("Windows file names alias the same file")
        if not isinstance(value, str) or len(value) > LIMIT * 2:
            raise ContractError("Windows file input exceeds bounds")
        try:
            data = bytearray.fromhex(value)
        except ValueError as exc:
            raise ContractError("Windows files must contain hexadecimal bytes") from exc
        total += len(data)
        if total > LIMIT:
            raise ContractError("Windows file inputs exceed 1 MB total")
        result[path] = data
    return result


class Files:
    def __init__(self, files, stop, events):
        self.data = declared_files(files)
        self.handles = {}
        self.serial = 0x10000
        self.error = None
        self.transferred = 0
        self.stop = stop
        self.events = events

    def unsupported(self, reason):
        self.stop("unsupported", reason)

    def fail(self, code, value=0):
        self.error = code
        return value

    def transfer(self, size):
        self.transferred += size
        if self.transferred > 4 * LIMIT:
            self.stop("budget_exhausted", "File transfer limit")

    def record_io(self, call, handle, position, chunk):
        self.events.append(
            {
                "call": call,
                "file": self.handles[handle]["path"],
                "handle": handle,
                "offset": position,
                "size": len(chunk),
                "sha256": hashlib.sha256(chunk).hexdigest(),
            }
        )

    def path(self, emu, address, wide):
        raw = bytearray()
        width = 2 if wide else 1
        for i in range(260):
            part = bytes(emu.mem_read(address + i * width, width))
            if part == b"\0" * width:
                try:
                    return filename(raw.decode("utf-16-le" if wide else "ascii"))
                except (UnicodeError, ContractError) as exc:
                    self.unsupported(str(exc))
            raw.extend(part)
        self.unsupported("Unterminated or oversized Windows file name")

    def call(self, emu, name, args):
        if name == "GetLastError":
            if self.error is None:
                self.unsupported(
                    "GetLastError after a call without a defined error result"
                )
            return self.error
        if name == "SetLastError":
            self.error = args[0] & 0xFFFFFFFF
            return 0
        # Successful APIs generally do not specify last-error contents. Do not
        # let implementation-specific emulator state become equivalence evidence.
        self.error = None
        if name.startswith("CreateFile"):
            address, access, share, security, disposition, flags, template = args
            access, share, disposition, flags = (
                v & 0xFFFFFFFF for v in (access, share, disposition, flags)
            )
            if (
                not access
                or access & ~(READ | WRITE)
                or disposition == 2
                and not access & WRITE
                or share & ~3
                or security
                or template
                or flags not in (0, 128)
                or disposition not in range(1, 6)
            ):
                self.unsupported(
                    "Unsupported CreateFile access, sharing, attributes or disposition"
                )
            path = self.path(emu, address, name.endswith("W"))
            self.events.append(
                {
                    "call": name,
                    "file": path,
                    "access": access,
                    "share": share,
                    "disposition": disposition,
                }
            )
            exists = path in self.data
            if exists and disposition == 1:
                return self.fail(80, INVALID)
            if not exists and disposition in (3, 5):
                return self.fail(2, INVALID)
            if disposition == 5 and not access & WRITE:
                return self.fail(5, INVALID)
            for h in self.handles.values():
                if h["path"] == path and (
                    (access & READ and not h["share"] & 1)
                    or (access & WRITE and not h["share"] & 2)
                    or (h["access"] & READ and not share & 1)
                    or (h["access"] & WRITE and not share & 2)
                ):
                    return self.fail(32, INVALID)
            if len(self.handles) >= 128 or not exists and len(self.data) >= 64:
                self.stop("budget_exhausted", "File or handle count limit")
            if not exists:
                self.data[path] = bytearray()
            elif disposition in (2, 5):
                self.data[path].clear()
            if disposition in (2, 4):
                self.error = 183 if exists else 0
            self.serial += 1
            self.handles[self.serial] = {
                "path": path,
                "access": access,
                "share": share,
                "position": 0,
            }
            return self.serial
        if name.startswith("DeleteFile"):
            path = self.path(emu, args[0], name.endswith("W"))
            self.events.append({"call": name, "file": path})
            if path not in self.data:
                return self.fail(2)
            # Delete sharing and delete-on-close are not admitted by CreateFile.
            if any(h["path"] == path for h in self.handles.values()):
                return self.fail(32)
            del self.data[path]
            return 1
        handle = args[0]
        h = self.handles.get(handle)
        self.events.append({"call": name, "handle": handle})
        if h is None:
            return self.fail(6)
        if name == "CloseHandle":
            del self.handles[handle]
        elif name == "GetFileSizeEx":
            emu.mem_write(args[1], len(self.data[h["path"]]).to_bytes(8, "little"))
        elif name == "SetFilePointerEx":
            distance, output, method = args[
                1:4
            ]  # x64 LARGE_INTEGER occupies one argument
            method &= 0xFFFFFFFF
            if method not in (0, 1, 2):
                return self.fail(87)
            if not h["access"] & (READ | WRITE):
                return self.fail(5)
            distance = distance & ((1 << 64) - 1)
            if distance >= 1 << 63:
                distance -= 1 << 64
            position = distance + (0, h["position"], len(self.data[h["path"]]))[method]
            self.events[-1].update(distance=distance, method=method)
            if position < 0:
                return self.fail(131)
            if position > LIMIT:
                self.stop("budget_exhausted", "File offset limit")
            h["position"] = position
            if output:
                emu.mem_write(output, position.to_bytes(8, "little"))
        elif name == "SetEndOfFile":
            if not h["access"] & WRITE:
                return self.fail(5)
            if h["position"] > len(self.data[h["path"]]):
                self.unsupported("SetEndOfFile extension has undefined byte contents")
            del self.data[h["path"]][h["position"] :]
        else:
            self.unsupported("Unsupported file API: " + name)
        return 1

    def io(self, emu, name, handle, address, count, count_ptr):
        self.error = None
        h = self.handles.get(handle)
        if h is None:
            self.events.append({"call": name, "handle": handle, "error": 6})
            return self.fail(6)
        reading = name == "ReadFile"
        if not h["access"] & (READ if reading else WRITE):
            self.events.append({"call": name, "handle": handle, "error": 5})
            return self.fail(5)
        data, position = self.data[h["path"]], h["position"]
        if reading:
            chunk = bytes(data[position : position + count])
            self.transfer(len(chunk))
            if chunk:
                emu.mem_write(address, chunk)
        else:
            self.transfer(count)
            end = position + count
            if count and (
                end > LIMIT
                or sum(map(len, self.data.values())) + max(0, end - len(data)) > LIMIT
            ):
                self.stop("budget_exhausted", "File output limit")
            chunk = bytes(emu.mem_read(address, count)) if count else b""
            if chunk:
                if end > len(data):
                    data.extend(b"\0" * (end - len(data)))
                data[position:end] = chunk
        self.record_io(name, handle, position, chunk)
        h["position"] += len(chunk)
        emu.mem_write(count_ptr, len(chunk).to_bytes(4, "little"))
        return 1
