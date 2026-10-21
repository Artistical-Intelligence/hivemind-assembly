"""Explicit Windows command-line/environment inputs with no host inheritance."""

import re

from hivemind_assembly.core.common import ContractError

PROCESS_APIS = (
    "GetCommandLineA",
    "GetCommandLineW",
    "GetEnvironmentVariableA",
    "GetEnvironmentVariableW",
)


def ascii_string(value, label, maximum=8192):
    if (
        not isinstance(value, str)
        or len(value) > maximum
        or "\0" in value
        or not value.isascii()
    ):
        raise ContractError(label + " must be bounded, NUL-free ASCII")
    return value


def inputs(case):
    command = ascii_string(
        case.get("command_line", "program.exe"), "Windows command_line"
    )
    env = case.get("env", {})
    if not isinstance(env, dict) or len(env) > 128:
        raise ContractError("Windows env must map at most 128 names to values")
    values = {}
    for name, value in env.items():
        if not isinstance(name, str) or not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]{0,127}", name
        ):
            raise ContractError(
                "Windows environment names must use ASCII letters, digits and underscores"
            )
        name = name.upper()
        if name in values:
            raise ContractError("Windows environment names alias the same variable")
        values[name] = ascii_string(value, "Windows environment value")
    if sum(len(k) + len(v) + 2 for k, v in values.items()) > 65536:
        raise ContractError("Windows environment exceeds 64 KB")
    return command, values


class _Memory:
    """Keep host-side API writes subject to the guest's read-only input pages."""

    def __init__(self, emu, process):
        self.emu, self.process = emu, process

    def mem_read(self, address, size):
        return self.emu.mem_read(address, size)

    def mem_map(self, *args, **kwargs):
        return self.emu.mem_map(*args, **kwargs)

    def mem_write(self, address, data):
        for start, content in self.process.buffers.values():
            end = start + (len(content) + 4095) // 4096 * 4096
            if data and address < end and address + len(data) > start:
                self.process.state.unsupported(
                    "Writing a command-line page is unsupported"
                )
        return self.emu.mem_write(address, data)


class Process:
    def __init__(self, command, env, state):
        self.command = command
        self.env = env
        self.state = state
        self.buffers = {}

    def memory(self, emu):
        return _Memory(emu, self)

    def check(self, emu):
        # CPU writes fault on read-only pages. API host-side writes can bypass
        # Unicorn permissions, so check those at every API return as well.
        for address, data in self.buffers.values():
            if bytes(emu.mem_read(address, len(data))) != data:
                self.state.unsupported(
                    "Command-line buffer modification is unsupported"
                )

    def name(self, emu, address, wide):
        width = 2 if wide else 1
        raw = bytearray()
        for i in range(129):
            part = bytes(emu.mem_read(address + i * width, width))
            if part == b"\0" * width:
                try:
                    name = raw.decode("utf-16-le" if wide else "ascii")
                    return ascii_string(name, "Environment query", 128).upper()
                except (UnicodeError, ContractError) as exc:
                    self.state.unsupported(str(exc))
            raw.extend(part)
        self.state.unsupported("Oversized or unterminated environment variable name")

    def call(self, emu, name, args, initialize):
        from speakeasy.common import PERM_MEM_READ

        self.state.error = None
        wide = name.endswith("W")
        encoding = "utf-16-le" if wide else "ascii"
        if name.startswith("GetCommandLine"):
            self.state.events.append({"call": name})
            if wide not in self.buffers:
                data = (self.command + "\0").encode(encoding)
                # Whole pages avoid Speakeasy's small-block allocator, whose
                # backing pages have broader permissions than individual blocks.
                size = (len(data) + 4095) // 4096 * 4096
                address = emu.mem_map(size, perms=PERM_MEM_READ, tag="ha.command_line")
                # Trusted initialization of newly allocated OS-owned pages is
                # the only write that may bypass their read-only permissions.
                initialize(address, data)
                self.buffers[wide] = (address, data)
            return self.buffers[wide][0]
        address, output, size = args
        size &= 0xFFFFFFFF
        key = self.name(emu, address, wide)
        self.state.events.append({"call": name, "name": key, "capacity": size})
        if size > 32768:
            self.state.unsupported("Environment output buffer exceeds bounds")
        if key not in self.env:
            return self.state.fail(203)
        value = self.env[key]
        if size == 0:
            return len(value) + 1
        if not output or size <= len(value):
            self.state.unsupported(
                "Environment query has undefined output buffer contents"
            )
        emu.mem_write(output, (value + "\0").encode(encoding))
        return len(value)
