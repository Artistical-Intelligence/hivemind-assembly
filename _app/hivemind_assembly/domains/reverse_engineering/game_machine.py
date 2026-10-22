"""Deterministic game engines over HA's bounded replay lanes.

`GameMachine` steps a static x86-64 or AArch64 ELF built for HA's freestanding runtime
under Unicorn. It pauses whenever the game blocks on standard input, so a caller can
feed one input record at a time, inspect streams and memory, and take snapshots.
Reads block until the requested byte count is available or input has ended, so a
stepped session produces exactly the streams, exit status and input consumption of
`program.replay` for the same input log. The same instruction policy applies: clock,
random, port and system instructions stop the machine, as do faults, unsupported
syscalls and budgets. Nothing reaches the host.

`ReplayEngine` adapts a batch replay (static Linux ELF or Windows x64 console PE) to
the same protocol by replaying the whole input log with end of input. It has no live
pause or memory reads; its snapshots are input logs. Instruction counts recorded at
each input read give it per-tick costs, so an instruction budget that runs out inside
one tick is a freeze and otherwise an inconclusive limit. Capabilities say which
applies. Output and event bounds derive from the game contract, so a session that
stays within its declared ticks never meets them. Instruction budgets bound every
call; wall-clock limits apply only inside the batch replays.
"""

import functools
import io
import struct
import zlib
from array import array

from hivemind_assembly.core.common import Blocked, ContractError

TERMINAL = (
    "completed",
    "fault",
    "unsupported_syscall",
    "unsupported_cpu_state",
    "unsupported_instruction_or_fault",
    "freeze",
    "instruction_limit",
    "wall_clock_limit",
    "output_limit",
    "event_limit",
    "cancelled",
)
# Defaults for direct use; open_engine derives both from the game contract.
OUTPUT_LIMIT = 1_000_000
EVENT_LIMIT = 4096
# HA's freestanding runtime and bundled memory routines are not game code.
RUNTIME_NAMES = {
    "_start",
    "ha_boot",
    "ha_argc",
    "ha_argv",
    "ha_getenv",
    "ha_read",
    "ha_write",
    "ha_exit",
    "ha_open",
    "ha_close",
    "ha_seek",
    "ha_file_read",
    "ha_file_write",
    "ha_map",
    "ha_unmap",
    "ha_mkdir",
    "ha_rmdir",
    "ha_remove",
    "ha_rename",
    "ha_clock",
    "ha_random",
    "ha_call3",
    "ha_error",
    "ha_memory_runtime_notice",
    "memcpy",
    "memmove",
    "memset",
    "memcmp",
}


class Stream:
    """Append-only output whose snapshots share immutable chunks."""

    __slots__ = ("chunks", "size")

    def __init__(self, chunks=(), size=0):
        self.chunks, self.size = list(chunks), size

    def append(self, data):
        if data:
            self.chunks.append(bytes(data))
            self.size += len(data)

    def tail(self, start):
        parts, position = [], self.size
        for chunk in reversed(self.chunks):
            if position <= start:
                break
            position -= len(chunk)
            parts.append(chunk[max(0, start - position) :])
        return b"".join(reversed(parts))

    def freeze(self):
        return tuple(self.chunks), self.size


@functools.lru_cache(maxsize=16)
def elf_symbols(data):
    """Defined ELF symbols: {name: {address, size, kind}} (empty when stripped).

    Cached per image; callers must treat the returned mapping as read-only.
    """
    from elftools.elf.elffile import ELFFile
    from elftools.common.exceptions import ELFError

    try:
        elf = ELFFile(io.BytesIO(data))
        result = {}
        for section in elf.iter_sections():
            if section["sh_type"] != "SHT_SYMTAB":
                continue
            for item in section.iter_symbols():
                kind = item["st_info"]["type"]
                if (
                    not item.name
                    or item["st_shndx"] == "SHN_UNDEF"
                    or kind not in ("STT_FUNC", "STT_OBJECT")
                ):
                    continue
                result.setdefault(
                    item.name,
                    {
                        "address": item["st_value"],
                        "size": item["st_size"],
                        "kind": "function" if kind == "STT_FUNC" else "object",
                    },
                )
        return result
    except (ELFError, ValueError, struct.error) as error:
        raise ContractError("Unreadable ELF symbol table") from error


def game_functions(symbols, declared=None, limit=1024):
    """Function entry addresses for coverage, excluding HA's runtime."""
    entries = {
        item["address"]: name
        for name, item in sorted(symbols.items())
        if item["kind"] == "function" and item["size"] and name not in RUNTIME_NAMES
    }
    for name, address in (declared or {}).items():
        entries[address] = name
    ordered = sorted(entries.items())
    return dict(ordered[:limit]), len(ordered) > limit


class GameMachine:
    capabilities = {
        "runtime": "unicorn_linux",
        "stepping": "live",
        "snapshots": "state",
        "memory": True,
        "coverage": "function_entries",
        "deterministic": True,
        "frame_exact_input": True,
        "observations": "while_waiting_for_input",
    }

    def __init__(
        self,
        image,
        *,
        argv=None,
        env=None,
        clock_ns=0,
        max_instructions=10_000_000,
        freeze_tick_instructions=2_000_000,
        functions=None,
        cancel=None,
        output_limit=OUTPUT_LIMIT,
        event_limit=EVENT_LIMIT,
    ):
        import unicorn as u
        from unicorn import arm64_const as ac
        from unicorn import x86_const as x

        from .process_inputs import entry_stack, normalize
        from .program import image_machine, load_image

        if (
            type(clock_ns) is not int
            or not 0 <= clock_ns < 2**63
            or type(max_instructions) is not int
            or not 1 <= max_instructions <= 10_000_000
            or type(freeze_tick_instructions) is not int
            or not 1 <= freeze_tick_instructions <= max_instructions
            or type(output_limit) is not int
            or not 1 <= output_limit <= 128 * 2**20
            or type(event_limit) is not int
            or not 1 <= event_limit <= 2_000_000
        ):
            raise ContractError("Game clock, instruction, output or event bounds are invalid")
        argv, env = normalize(argv, env)
        self.u, self.image = u, image
        machine = image_machine(image)
        self.arm = machine == 183
        entry, segments = load_image(image, machine=machine)
        self.segments = segments
        uc = u.Uc(u.UC_ARCH_ARM64, u.UC_MODE_ARM) if self.arm else u.Uc(u.UC_ARCH_X86, u.UC_MODE_64)
        if self.arm:
            uc.ctl_set_cpu_model(ac.UC_CPU_ARM64_A57)
            uc.reg_write(ac.UC_ARM64_REG_CPACR_EL1, 3 << 20)
        self.uc = uc
        self.pc_register = ac.UC_ARM64_REG_PC if self.arm else x.UC_X86_REG_RIP
        self.stack_register = ac.UC_ARM64_REG_SP if self.arm else x.UC_X86_REG_RSP
        self.result_register = ac.UC_ARM64_REG_X0 if self.arm else x.UC_X86_REG_RAX
        self.number_register = ac.UC_ARM64_REG_X8 if self.arm else x.UC_X86_REG_RAX
        self.argument_registers = (
            (ac.UC_ARM64_REG_X0, ac.UC_ARM64_REG_X1, ac.UC_ARM64_REG_X2)
            if self.arm
            else (x.UC_X86_REG_RDI, x.UC_X86_REG_RSI, x.UC_X86_REG_RDX)
        )
        self.syscall_names = (
            {63: "read", 64: "write", 93: "exit", 94: "exit", 113: "clock"}
            if self.arm
            else {0: "read", 1: "write", 60: "exit", 231: "exit", 228: "clock"}
        )
        pages = {}
        for s in segments:
            perms = (
                (u.UC_PROT_READ if s["flags"] & 4 else 0)
                | (u.UC_PROT_WRITE if s["flags"] & 2 else 0)
                | (u.UC_PROT_EXEC if s["flags"] & 1 else 0)
            )
            for address in range(s["address"] & ~4095, (s["address"] + s["size"] + 4095) & ~4095, 4096):
                pages[address] = pages.get(address, 0) | perms
        for address in pages:
            uc.mem_map(address, 4096)
        for s in segments:
            uc.mem_write(s["address"], s["data"])
        for address, perms in pages.items():
            uc.mem_protect(address, 4096, perms)
        self.pages = pages
        self.stack, self.stack_size = 0x70000000, 0x100000
        uc.mem_map(self.stack, self.stack_size, u.UC_PROT_READ | u.UC_PROT_WRITE)
        uc.reg_write(
            self.stack_register,
            entry_stack(uc.mem_write, self.stack + self.stack_size, argv, env),
        )
        writable = sorted(a for a, p in pages.items() if p & u.UC_PROT_WRITE)
        self.writable = [(a, 4096) for a in writable] + [(self.stack, self.stack_size)]
        # Snapshots store pages that differ from this initial writable memory.
        self.initial = b"".join(bytes(uc.mem_read(a, size)) for a, size in self.writable)
        # Without writable code pages, validated blocks cannot change.
        self.mutable_code = any(
            p & u.UC_PROT_WRITE and p & u.UC_PROT_EXEC for p in pages.values()
        )
        self.symbols = elf_symbols(image)
        self.entries, self.coverage_truncated = game_functions(self.symbols, functions)
        self.hits = {name: 0 for name in self.entries.values()}
        self.clock_ns = clock_ns
        self.max_instructions = max_instructions
        self.freeze_tick = freeze_tick_instructions
        self.output_limit, self.event_limit = output_limit, event_limit
        self.cancel = cancel
        self.pc = entry
        self.inputs = bytearray()
        self.cursor = 0
        self.ended = False
        self.pending = None
        self.status = "ready"
        self.exit_code = None
        self.events = 0
        self.effects = []
        self.instructions = 0
        self.tick_instructions = 0
        self.costs = []
        self.stdout, self.stderr = Stream(), Stream()
        self.fault = None
        self.stop_context = None
        self.blocks = {}
        self.counted = 0
        self.seen = 0
        self.last_block = None
        self.access = None
        self.active_syscall = None
        if self.arm:
            self.uc.hook_add(u.UC_HOOK_INTR, self._interrupt)
        else:
            self.uc.hook_add(u.UC_HOOK_INSN, self._syscall_hook, None, 1, 0, x.UC_X86_INS_SYSCALL)
        self.uc.hook_add(u.UC_HOOK_BLOCK, self._block)
        self.uc.hook_add(u.UC_HOOK_MEM_INVALID, self._invalid)
        self._resume()

    # Instruction policy, coverage and cancellation, once per translated block.
    def _validate(self, address, size):
        from .guest_cpu import unsupported

        code = bytes(self.uc.mem_read(address, size))
        if self.arm:
            from .arm64 import unsupported_instruction

            if size % 4 or address % 4:
                return None, code
            for offset in range(0, size, 4):
                word = code[offset : offset + 4]
                if word != b"\x01\x00\x00\xd4" and unsupported_instruction(word):
                    return None, code
            return size // 4, code
        from capstone import CS_ARCH_X86, CS_MODE_64, Cs

        decoder = getattr(self, "_decoder", None) or Cs(CS_ARCH_X86, CS_MODE_64)
        self._decoder = decoder
        count = consumed = 0
        for _, length, _, _ in decoder.disasm_lite(code, address):
            if not 1 <= length <= 15 or unsupported(code[consumed : consumed + length]):
                return None, code
            consumed += length
            count += 1
        return (count if consumed == size and count else None), code

    def _block(self, engine, address, size, _):
        # Hot path: a block validated before runs with counting and coverage only.
        cached = self.blocks.get(address)
        if cached is not None and cached[0] == size and not self.mutable_code:
            self.counted += cached[1]
            if cached[3] is not None:
                self.hits[cached[3]] += 1
            self.seen += 1
            if not self.seen & 1023 and self.cancel is not None and self.cancel.is_set():
                self._stop("cancelled")
            return
        self._first_block(engine, address, size, cached)

    def _first_block(self, engine, address, size, cached):
        if cached is None or cached[0] != size or bytes(engine.mem_read(address, size)) != cached[2]:
            count, code = self._validate(address, size)
            if count is None:
                self.last_block = (address, code[:15])
                self._stop("unsupported_cpu_state")
                return
            cached = self.blocks[address] = (size, count, code, self.entries.get(address))
        self.last_block = (address, cached[2][: 4 if self.arm else 15])
        # AArch64 requires an aligned stack pointer; checked when a block is
        # first translated and at every system call.
        if self.arm and engine.reg_read(self.stack_register) % 16:
            self._stop("unsupported_cpu_state")
            return
        self.counted += cached[1]
        if cached[3] is not None:
            self.hits[cached[3]] += 1

    def _invalid(self, engine, access, address, size, value, _):
        from .unicorn_diagnostics import memory_access

        self.fault = {"access": access, "address": address, "size": size}
        self.access = memory_access(access, address, size)
        self._stop("fault")
        return False

    def _interrupt(self, engine, number, _):
        pc = engine.reg_read(self.pc_register)
        # SVC #0 is the only admitted exception; PC already points past it.
        if (
            number != 2
            or bytes(engine.mem_read(pc - 4, 4)) != b"\x01\x00\x00\xd4"
            or engine.reg_read(self.stack_register) % 16
        ):
            self._stop("unsupported_cpu_state")
            return
        self._syscall(engine)

    def _syscall_hook(self, engine, _):
        from unicorn import x86_const as x

        self._syscall(engine)
        engine.reg_write(x.UC_X86_REG_RCX, engine.reg_read(x.UC_X86_REG_RIP) + 2)
        engine.reg_write(x.UC_X86_REG_R11, engine.reg_read(x.UC_X86_REG_EFLAGS))

    def _stop(self, status):
        self.status = status
        self.uc.emu_stop()

    def rebind(self, cancel):
        """Observe a new request's cancellation (cached sessions outlive requests)."""
        self.cancel = cancel

    def _writable(self, address, size, perm):
        if size > self.output_limit or size < 0 or address + size > 2**64:
            return False
        if not size:
            return True
        stack = self.u.UC_PROT_READ | self.u.UC_PROT_WRITE
        return all(
            (
                self.pages.get(
                    page,
                    stack if self.stack <= page < self.stack + self.stack_size else 0,
                )
                & perm
            )
            == perm
            for page in range(address & ~4095, (address + size + 4095) & ~4095, 4096)
        )

    def _syscall(self, engine):
        u = self.u
        number = engine.reg_read(self.number_register)
        operation = self.syscall_names.get(number)
        a, b, n = [engine.reg_read(r) for r in self.argument_registers]
        self.active_syscall = {"number": number, "name": operation or "unsupported", "arguments": [a, b, n]}
        if self.events >= self.event_limit:
            self._stop("event_limit")
            return
        result = 0
        if operation == "read" and a == 0:
            # Every read ends the current tick interval. The guest blocks here
            # until the requested bytes or end of input arrive; _resume completes it.
            self.pending = (b, n)
            self.status = "reading"
            engine.emu_stop()
            return
        elif operation == "write" and a in (1, 2):
            if not self._writable(b, n, u.UC_PROT_READ):
                result = -14
            elif self.stdout.size + self.stderr.size + n > self.output_limit:
                self._stop("output_limit")
                return
            else:
                (self.stdout if a == 1 else self.stderr).append(engine.mem_read(b, n))
                result = n
            self.events += 1
        elif operation == "exit":
            self.exit_code = a & 255
            self.events += 1
            self._stop("completed")
            return
        elif operation == "clock" and a in (0, 1):
            if not self._writable(b, 16, u.UC_PROT_WRITE):
                result = -14
            else:
                engine.mem_write(b, struct.pack("<qq", self.clock_ns // 1_000_000_000, self.clock_ns % 1_000_000_000))
            self.events += 1
            self.effects.append({"call": "clock_gettime", "clock": a, "result": result})
        else:
            self._stop("unsupported_syscall")
            return
        engine.reg_write(self.result_register, result & ((1 << 64) - 1))
        self.active_syscall = None

    def _ready(self):
        address, count = self.pending
        return self.ended or len(self.inputs) - self.cursor >= count

    def _complete(self):
        address, count = self.pending
        self.pending = None
        length = min(count, len(self.inputs) - self.cursor)
        self.events += 1
        if not self._writable(address, length, self.u.UC_PROT_WRITE):
            result = -14
        else:
            self.uc.mem_write(address, bytes(self.inputs[self.cursor : self.cursor + length]))
            self.cursor += length
            result = length
        return result

    def _resume(self):
        from .unicorn_diagnostics import locate, stopped_context

        while self.status not in TERMINAL:
            if self.pending is not None:
                if not self._ready():
                    self.status = "awaiting_input"
                    return
                self.uc.reg_write(self.result_register, self._complete() & ((1 << 64) - 1))
                self.active_syscall = None
            if self.cancel is not None and self.cancel.is_set():
                self.status = "cancelled"
                break
            total = self.max_instructions - self.instructions
            tick = self.freeze_tick - self.tick_instructions
            budget = min(total, tick)
            if budget <= 0:
                self.status = "instruction_limit" if total <= 0 else "freeze"
                break
            self.status = "running"
            self.counted = 0
            try:
                # The instruction budget bounds each tick (and so its host time); a
                # per-call timer thread would cost more than the tick itself.
                self.uc.emu_start(self.pc, 0, count=budget)
            except self.u.UcError as error:
                if self.status == "running":
                    self.status = "unsupported_instruction_or_fault"
                    self.fault = {"error": str(error)}
            self.pc = self.uc.reg_read(self.pc_register)
            if self.status == "running":
                # Neither a syscall nor a policy hook stopped the guest: a bound did.
                self.counted = budget
                self.status = "instruction_limit" if total <= budget else "freeze"
            self.instructions += self.counted
            self.tick_instructions += self.counted
            self.counted = 0
            if self.status == "reading":
                # A tick interval ends when the game asks for its next input; the
                # cost of the interval is known before the game has to wait.
                self.costs.append(self.tick_instructions)
                self.tick_instructions = 0
                self.status = "ready"
        if self.status not in ("completed", "awaiting_input") and self.stop_context is None:
            reported = {
                "freeze": "budget_exhausted",
                "instruction_limit": "budget_exhausted",
            }.get(self.status, self.status)
            instruction = None
            pc = self.uc.reg_read(self.pc_register)
            if self.last_block is not None:
                try:
                    instruction = (pc, bytes(self.uc.mem_read(pc, 4 if self.arm else 15)))
                except self.u.UcError:
                    instruction = self.last_block
            context = stopped_context(
                self.uc,
                self.arm,
                reported,
                instruction,
                count=self.instructions,
                budget=self.max_instructions,
                access=self.access,
                syscall=self.active_syscall,
            )
            if self.status == "freeze":
                context["stop_reason"] = "tick_instruction_limit"
            base = min(s["address"] for s in self.segments)
            self.stop_context = locate(context, [dict(s, image_base=base) for s in self.segments])
            self.stop_context["function"] = self.function_at(pc)

    def function_at(self, address):
        best = None
        for name, item in self.symbols.items():
            if item["kind"] == "function" and item["address"] <= address < item["address"] + max(item["size"], 1):
                if best is None or item["address"] > self.symbols[best]["address"]:
                    best = name
        return best

    # Harness protocol.
    def feed(self, data):
        if self.ended:
            raise ContractError("Input has already ended for this game session")
        if len(self.inputs) + len(data) > 1_000_000:
            raise ContractError("Game input exceeds 1 MB")
        self.inputs += data
        if self.status == "awaiting_input":
            self._resume()

    def end(self):
        self.ended = True
        if self.status == "awaiting_input":
            self._resume()

    def output_size(self, stream):
        return (self.stdout if stream == "stdout" else self.stderr).size

    def output_tail(self, stream, start):
        return (self.stdout if stream == "stdout" else self.stderr).tail(start)

    @property
    def input_consumed(self):
        return self.cursor

    def coverage(self):
        return dict(self.hits)

    def symbol(self, name):
        item = self.symbols.get(name)
        return None if item is None else item["address"]

    def read_memory(self, address, size):
        if (
            type(address) is not int
            or type(size) is not int
            or not 0 < size <= 4096
            or not self._writable(address, size, self.u.UC_PROT_READ)
        ):
            raise ContractError("Memory read outside readable guest memory")
        return bytes(self.uc.mem_read(address, size))

    def diagnostics(self):
        return {"fault": self.fault, "stop_context": self.stop_context}

    def snapshot(self):
        if self.status == "running":
            raise ContractError("A running machine cannot be snapshotted")
        memory = b"".join(bytes(self.uc.mem_read(a, size)) for a, size in self.writable)
        # Keep only pages that differ from the loaded image and the empty stack.
        pages = [
            offset
            for offset in range(0, len(memory), 4096)
            if memory[offset : offset + 4096] != self.initial[offset : offset + 4096]
        ]
        return {
            "context": self.uc.context_save(),
            "pages": pages,
            "memory": zlib.compress(b"".join(memory[o : o + 4096] for o in pages), 1),
            "pc": self.pc,
            "inputs": bytes(self.inputs),
            "streams": (self.stdout.freeze(), self.stderr.freeze()),
            "fields": {
                key: getattr(self, key)
                for key in (
                    "cursor",
                    "ended",
                    "pending",
                    "status",
                    "exit_code",
                    "events",
                    "instructions",
                    "tick_instructions",
                    "fault",
                    "stop_context",
                    "access",
                    "active_syscall",
                )
            },
            # Snapshots can be restored in any order, so keep contents, not lengths;
            # packed counts keep a large exploration archive small.
            "costs": array("Q", self.costs).tobytes(),
            "effects": tuple(self.effects),
            "hits": dict(self.hits),
        }

    def restore(self, snapshot):
        self.uc.context_restore(snapshot["context"])
        memory = bytearray(self.initial)
        dirty = zlib.decompress(snapshot["memory"])
        for index, offset in enumerate(snapshot["pages"]):
            memory[offset : offset + 4096] = dirty[index * 4096 : (index + 1) * 4096]
        offset = 0
        for address, size in self.writable:
            self.uc.mem_write(address, bytes(memory[offset : offset + size]))
            offset += size
        self.pc = snapshot["pc"]
        self.inputs = bytearray(snapshot["inputs"])
        (out_chunks, out_size), (err_chunks, err_size) = snapshot["streams"]
        self.stdout, self.stderr = Stream(out_chunks, out_size), Stream(err_chunks, err_size)
        for key, value in snapshot["fields"].items():
            setattr(self, key, value)
        costs = array("Q")
        costs.frombytes(snapshot["costs"])
        self.costs = costs.tolist()
        self.effects = list(snapshot["effects"])
        self.hits = dict(snapshot["hits"])
        self.counted = 0

    @staticmethod
    def snapshot_bytes(snapshot):
        # Stream chunks are shared between snapshots and not counted here.
        return (
            len(snapshot["memory"])
            + len(snapshot["inputs"])
            + len(snapshot["costs"])
            + 64 * len(snapshot["effects"])
            + 8 * len(snapshot["hits"])
            + 4096
        )


class ReplayEngine:
    """Batch replay behind the harness protocol; observations follow end of input."""

    def __init__(self, image, runner, runtime, options, functions=None, symbols=None, freeze_tick=None):
        self.image, self.runner, self.options = image, runner, dict(options)
        self.freeze_tick = freeze_tick
        self.capabilities = {
            "runtime": runtime,
            "stepping": "replay",
            "snapshots": "input_log",
            "memory": False,
            "coverage": "function_entries" if functions else "none",
            "deterministic": True,
            "frame_exact_input": True,
            "observations": "after_end_of_input",
        }
        self.entries = dict(functions or {})
        self.symbols = symbols or {}
        self.inputs = bytearray()
        self.ended = False
        self.result = None
        self.streams = {"stdout": b"", "stderr": b""}
        self._replay()

    def _replay(self):
        options = dict(self.options)
        if self.entries:
            options["coverage"] = self.entries
        self.result = self.runner(self.image, bytes(self.inputs), tick_marks=True, **options)
        self.streams = {
            "stdout": bytes.fromhex(self.result.get("stdout_hex", "")),
            "stderr": bytes.fromhex(self.result.get("stderr_hex", "")),
        }

    @property
    def status(self):
        result = self.result
        status = result["status"]
        if status == "budget_exhausted":
            # Linux replay names the bound in its stop context; Windows replay in
            # its fault text. Only an instruction budget spent inside one tick is a
            # freeze; every other bound is an inconclusive harness limit.
            reason = (result.get("stop_context") or {}).get("stop_reason") or ""
            fault = str(result.get("fault") or "")
            if reason == "wall_clock_limit" or fault == "Wall-clock limit":
                return "wall_clock_limit"
            if fault == "API call limit":
                return "event_limit"
            if fault == "Output limit":
                return "output_limit"
            if self.freeze_tick is not None and self.open_tick_instructions >= self.freeze_tick:
                return "freeze"
            return "instruction_limit"
        return {"unsupported": "unsupported_syscall", "incomplete": "fault"}.get(status, status)

    @property
    def marks(self):
        return self.result.get("read_instructions") or []

    @property
    def open_tick_instructions(self):
        """Instructions since the last input read (the tick that was running)."""
        marks = self.marks
        return self.instructions - (marks[-1] if marks else 0)

    @property
    def costs(self):
        marks = self.marks
        return [b - a for a, b in zip([0] + marks[:-1], marks)]

    def rebind(self, cancel):
        self.options["cancel"] = cancel

    @property
    def exit_code(self):
        return self.result.get("exit_code")

    @property
    def input_consumed(self):
        return self.result.get("input_consumed", 0)

    @property
    def instructions(self):
        return self.result.get("instructions", 0)

    def feed(self, data):
        if self.ended:
            raise ContractError("Input has already ended for this game session")
        self.inputs += data
        self._replay()

    def end(self):
        self.ended = True

    def output_size(self, stream):
        return len(self.streams[stream])

    def output_tail(self, stream, start):
        return self.streams[stream][start:]

    def coverage(self):
        return dict(self.result.get("coverage") or {})

    def symbol(self, name):
        item = self.symbols.get(name)
        return None if item is None else item["address"]

    def read_memory(self, address, size):
        raise Blocked("This game engine replays whole input logs and cannot read live memory")

    def diagnostics(self):
        return {"fault": self.result.get("fault"), "stop_context": self.result.get("stop_context")}

    def snapshot(self):
        return {"inputs": bytes(self.inputs), "ended": self.ended}

    def restore(self, snapshot):
        self.inputs = bytearray(snapshot["inputs"])
        self.ended = snapshot["ended"]
        self._replay()

    @staticmethod
    def snapshot_bytes(snapshot):
        return len(snapshot["inputs"]) + 64


def image_kind(image):
    if image[:4] == b"\x7fELF":
        return "elf"
    if image[:2] == b"MZ":
        return "pe"
    raise ContractError("Game images must be ELF or PE executables")


def open_engine(image, spec, *, live=True, cancel=None):
    """Choose the engine for an image under a validated game spec."""
    from hivemind_assembly.core import game_spec as gs

    limits, process = spec["limits"], spec["process"]
    declared = dict(spec.get("functions") or {})
    kind = image_kind(image)
    if kind == "elf":
        from .program import load_image, image_machine, replay

        try:
            load_image(image, machine=image_machine(image))
        except Blocked as error:
            raise Blocked(
                "The game harness steps static ELF images; dynamic games are not supported yet: " + str(error)
            ) from error
        if live:
            return GameMachine(
                image,
                argv=process.get("argv"),
                env=process.get("env"),
                clock_ns=process.get("clock_ns", 0),
                max_instructions=limits["max_instructions"],
                freeze_tick_instructions=limits["freeze_tick_instructions"],
                functions=declared,
                cancel=cancel,
                output_limit=gs.output_bound(spec),
                event_limit=gs.event_bound(spec),
            )
        symbols = elf_symbols(image)
        entries, _ = game_functions(symbols, declared, limit=256)
        return ReplayEngine(
            image,
            replay,
            "unicorn_linux",
            {
                "argv": process.get("argv"),
                "env": process.get("env"),
                "clock_ns": process.get("clock_ns", 0),
                "max_instructions": limits["max_instructions"],
                "cancel": cancel,
            },
            functions=entries,
            symbols=symbols,
            freeze_tick=limits["freeze_tick_instructions"],
        )
    from .windows_program import replay as windows_replay

    # PE images rarely carry symbols; coverage uses explicitly declared entries.
    entries = {address: name for name, address in declared.items()}
    return ReplayEngine(
        image,
        windows_replay,
        "speakeasy_windows",
        {
            "command_line": process.get("command_line", "program.exe"),
            "env": process.get("env", {}),
            "clock_ms": process.get("clock_ms", 0),
            "max_instructions": min(limits["max_instructions"], 5_000_000),
            "cancel": cancel,
        },
        functions=dict(sorted(entries.items())[:256]),
        freeze_tick=limits["freeze_tick_instructions"],
    )
