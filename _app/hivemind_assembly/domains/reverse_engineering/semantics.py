"""Bounded x86-64 raw P-code interpreter and independent Unicorn oracle.

Supported scalar semantics only. Missing operations are explicit unsupported results.
No platform, OS, device, floating-point or whole-program equivalence is implied.
"""

from __future__ import annotations
import importlib.metadata
from hivemind_assembly.core.common import ContractError
from .guest_cpu import unsupported as unsupported_cpu


class Unsupported(ContractError):
    pass


class MemoryFault(Exception):
    def __init__(self, kind, address):
        self.kind = kind
        self.address = address


REGISTERS = (
    "RAX",
    "RBX",
    "RCX",
    "RDX",
    "RSI",
    "RDI",
    "RBP",
    "RSP",
    "R8",
    "R9",
    "R10",
    "R11",
    "R12",
    "R13",
    "R14",
    "R15",
    "RIP",
)
FLAGS = {"CF": 0, "PF": 2, "AF": 4, "ZF": 6, "SF": 7, "OF": 11}


def signed(x, bits):
    return x - (1 << bits) if x & (1 << (bits - 1)) else x


def arithmetic(op, v, bits, outbits):
    a = v[0]
    b = v[1] if len(v) > 1 else 0
    mask = (1 << outbits) - 1
    if op in ("COPY", "INT_ZEXT"):
        r = a
    elif op == "INT_SEXT":
        r = signed(a, bits)
    elif op == "INT_ADD":
        r = a + b
    elif op == "INT_SUB":
        r = a - b
    elif op == "INT_MULT":
        r = a * b
    elif op == "INT_AND":
        r = a & b
    elif op == "INT_OR":
        r = a | b
    elif op == "INT_XOR":
        r = a ^ b
    elif op == "INT_NEGATE":
        r = ~a
    elif op == "INT_2COMP":
        r = -a
    elif op == "INT_LEFT":
        r = 0 if b >= bits else a << b
    elif op == "INT_RIGHT":
        r = 0 if b >= bits else a >> b
    elif op == "INT_SRIGHT":
        r = signed(a, bits) >> min(b, bits)
    elif op == "INT_EQUAL":
        r = int(a == b)
    elif op == "INT_NOTEQUAL":
        r = int(a != b)
    elif op == "INT_LESS":
        r = int(a < b)
    elif op == "INT_LESSEQUAL":
        r = int(a <= b)
    elif op == "INT_SLESS":
        r = int(signed(a, bits) < signed(b, bits))
    elif op == "INT_SLESSEQUAL":
        r = int(signed(a, bits) <= signed(b, bits))
    elif op == "INT_CARRY":
        r = int(a + b >= (1 << bits))
    elif op == "INT_SCARRY":
        s = signed(a, bits) + signed(b, bits)
        r = int(not -(1 << (bits - 1)) <= s < (1 << (bits - 1)))
    elif op == "INT_SBORROW":
        s = signed(a, bits) - signed(b, bits)
        r = int(not -(1 << (bits - 1)) <= s < (1 << (bits - 1)))
    elif op in ("INT_DIV", "INT_REM", "INT_SDIV", "INT_SREM"):
        if not b:
            raise Unsupported(
                "Division faults require an architecture-specific contract"
            )
        if op in ("INT_DIV", "INT_REM"):
            r = a // b if op == "INT_DIV" else a % b
        else:
            aa, bb = signed(a, bits), signed(b, bits)
            q = (abs(aa) // abs(bb)) * (-1 if (aa < 0) != (bb < 0) else 1)
            r = q if op == "INT_SDIV" else aa - q * bb
    elif op == "BOOL_NEGATE":
        r = int(not a)
    elif op == "BOOL_AND":
        r = int(bool(a) and bool(b))
    elif op == "BOOL_OR":
        r = int(bool(a) or bool(b))
    elif op == "BOOL_XOR":
        r = int(bool(a) != bool(b))
    elif op == "POPCOUNT":
        r = a.bit_count()
    elif op == "LZCOUNT":
        r = bits - a.bit_length()
    elif op == "SUBPIECE":
        r = a >> (b * 8)
    else:
        raise Unsupported("Unmodeled P-code operation: " + op)
    return r & mask


class PcodeMachine:
    def __init__(self, case):
        import pypcode

        self.ctx = pypcode.Context("x86:LE:64:default")
        self.case = case
        self.reg = {}
        self.unique = {}
        self.memory = {}
        self.regions = []
        self.writes = {}
        self.trace = []
        for region in case["memory"]:
            addr = region["address"]
            data = bytes.fromhex(region["hex"])
            size = region.get("size", len(data))
            self.regions.append((addr, addr + size, region.get("permissions", "rw")))
            self.memory.update(
                {addr + i: (data[i] if i < len(data) else 0) for i in range(size)}
            )
        for name in REGISTERS:
            if name in self.ctx.registers:
                self.write(
                    self.ctx.registers[name], case.get("registers", {}).get(name, 0)
                )
        for name in FLAGS:
            self.write(self.ctx.registers[name], case.get("flags", {}).get(name, 0))
        self.pc = case["start"]
        self.write(self.ctx.registers["RIP"], self.pc)

    def access(self, address, size, kind):
        if not any(
            lo <= address and address + size <= hi and kind in perm
            for lo, hi, perm in self.regions
        ):
            raise MemoryFault(kind, address)

    def read(self, n):
        space = n.space.name
        if space == "const":
            return n.offset
        if space == "register":
            d = self.reg
        elif space == "unique":
            d = self.unique
        elif space == "ram":
            self.access(n.offset, n.size, "r")
            d = self.memory
        else:
            raise Unsupported("Address space " + space)
        return sum(d.get(n.offset + i, 0) << (8 * i) for i in range(n.size))

    def write(self, n, value):
        space = n.space.name
        if space == "register":
            d = self.reg
        elif space == "unique":
            d = self.unique
        elif space == "ram":
            self.access(n.offset, n.size, "w")
            d = self.memory
        else:
            raise Unsupported("Output address space " + space)
        for i in range(n.size):
            d[n.offset + i] = (value >> (8 * i)) & 255
            if space == "ram":
                self.writes[n.offset + i] = d[n.offset + i]

    def step(self):
        self.access(self.pc, 1, "x")
        code = bytes(self.memory.get(self.pc + i, 0) for i in range(16))
        try:
            translation = self.ctx.translate(code, self.pc, max_instructions=1)
        except Exception as e:
            raise Unsupported("Decode failed: " + str(e)) from e
        ops = translation.ops
        mark = ops[0].inputs[0]
        self.access(self.pc, mark.size, "x")
        next_pc = self.pc + mark.size
        self.unique = {}
        i = 1
        fuel = 10000
        while i < len(ops):
            fuel -= 1
            if fuel < 0:
                raise Unsupported("P-code internal branch budget exceeded")
            op = ops[i]
            name = op.opcode.name
            inputs = op.inputs
            if name in ("BRANCH", "CBRANCH", "CALL", "BRANCHIND", "CALLIND", "RETURN"):
                take = name != "CBRANCH" or self.read(inputs[1]) != 0
                if take:
                    target = inputs[0]
                    if target.space.name == "const" and name in ("BRANCH", "CBRANCH"):
                        i += signed(target.offset, target.size * 8)
                        continue
                    next_pc = (
                        target.offset
                        if target.space.name == "ram"
                        else self.read(target)
                    )
                    break
            elif name == "LOAD":
                if inputs[0].getSpaceFromConst().name != "ram":
                    raise Unsupported("Non-RAM LOAD")
                addr = self.read(inputs[1])
                self.access(addr, op.output.size, "r")
                self.write(
                    op.output,
                    sum(
                        self.memory[addr + j] << (8 * j) for j in range(op.output.size)
                    ),
                )
            elif name == "STORE":
                if inputs[0].getSpaceFromConst().name != "ram":
                    raise Unsupported("Non-RAM STORE")
                addr = self.read(inputs[1])
                value = self.read(inputs[2])
                self.access(addr, inputs[2].size, "w")
                for j in range(inputs[2].size):
                    self.memory[addr + j] = (value >> (8 * j)) & 255
                    self.writes[addr + j] = self.memory[addr + j]
            elif name == "PIECE":
                self.write(
                    op.output,
                    (self.read(inputs[0]) << (inputs[1].size * 8))
                    | self.read(inputs[1]),
                )
            else:
                if op.output is None:
                    raise Unsupported("Unmodeled effect: " + name)
                self.write(
                    op.output,
                    arithmetic(
                        name,
                        [self.read(n) for n in inputs],
                        inputs[0].size * 8,
                        op.output.size * 8,
                    ),
                )
            i += 1
        self.pc = next_pc
        self.write(self.ctx.registers["RIP"], next_pc)

    def result(self, status, fault=None):
        return {
            "status": status,
            "registers": {k: self.read(self.ctx.registers[k]) for k in REGISTERS},
            "flags": {k: self.read(self.ctx.registers[k]) for k in FLAGS},
            "writes": {str(k): v for k, v in self.writes.items()},
            "fault": fault,
            "trace": self.trace,
        }

    def run(self):
        try:
            for _ in range(self.case.get("max_instructions", 1000)):
                if self.pc == self.case["stop"]:
                    return self.result("completed")
                self.trace.append(self.pc)
                self.step()
            return self.result("budget_exhausted")
        except MemoryFault as e:
            return self.result("fault", {"kind": e.kind, "address": e.address})
        except Unsupported as e:
            return self.result("unsupported", {"reason": str(e)})


def run_reference(case):
    import unicorn as u
    from unicorn import x86_const as xc

    machine = u.Uc(u.UC_ARCH_X86, u.UC_MODE_64)
    writes = {}
    trace = []
    fault = None
    unsupported = None
    for region in case["memory"]:
        addr = region["address"]
        data = bytes.fromhex(region["hex"])
        size = region.get("size", len(data))
        perm = region.get("permissions", "rw")
        if addr % 4096 or size % 4096:
            raise ContractError("Unicorn regions must be page aligned")
        mode = (
            (u.UC_PROT_READ if "r" in perm else 0)
            | (u.UC_PROT_WRITE if "w" in perm else 0)
            | (u.UC_PROT_EXEC if "x" in perm else 0)
        )
        machine.mem_map(addr, size, mode)
        machine.mem_write(addr, data)
    for name, value in case.get("registers", {}).items():
        machine.reg_write(getattr(xc, "UC_X86_REG_" + name), value)
    machine.reg_write(xc.UC_X86_REG_RIP, case["start"])
    flags = 2 + sum(
        case.get("flags", {}).get(name, 0) << bit for name, bit in FLAGS.items()
    )
    machine.reg_write(xc.UC_X86_REG_EFLAGS, flags)

    def on_write(m, access, address, size, value, data):
        for i in range(size):
            writes[str(address + i)] = (value >> (8 * i)) & 255

    def on_access(m, access, address, size, value, data):
        nonlocal unsupported
        permission = "w" if access == u.UC_MEM_WRITE else "r"
        if not any(
            start <= address and address + size <= end and permission in perms
            for start, end, perms in case["access_ranges"]
        ):
            unsupported = {
                "reason": "Access left the declared memory bounds",
                "address": address,
                "size": size,
                "permission": permission,
            }
            m.emu_stop()

    def on_fault(m, access, address, size, value, data):
        nonlocal fault
        kinds = {
            u.UC_MEM_READ_UNMAPPED: "r",
            u.UC_MEM_WRITE_UNMAPPED: "w",
            u.UC_MEM_FETCH_UNMAPPED: "x",
            u.UC_MEM_READ_PROT: "r",
            u.UC_MEM_WRITE_PROT: "w",
            u.UC_MEM_FETCH_PROT: "x",
        }
        fault = {"kind": kinds.get(access, "unknown"), "address": address}
        return False

    machine.hook_add(u.UC_HOOK_MEM_WRITE, on_write)
    machine.hook_add(u.UC_HOOK_MEM_INVALID, on_fault)
    if "access_ranges" in case:
        machine.hook_add(u.UC_HOOK_MEM_READ | u.UC_HOOK_MEM_WRITE, on_access)

    def on_code(m, address, size, data):
        nonlocal unsupported
        trace.append(address)
        if not 1 <= size <= 15:
            unsupported = {
                "reason": "Invalid x86 instruction length",
                "address": address,
            }
            m.emu_stop()
            return
        nondeterministic = unsupported_cpu(bytes(m.mem_read(address, size)))
        if nondeterministic:
            unsupported = {
                "reason": "Host-dependent CPU state or port I/O is outside deterministic replay",
                "address": address,
            }
            m.emu_stop()
            return
        ranges = case.get("code_ranges")
        if ranges and not any(
            start <= address and address + size <= end for start, end in ranges
        ):
            unsupported = {
                "reason": "Execution left the declared function bytes",
                "address": address,
            }
            m.emu_stop()

    def on_system(m, *args):
        nonlocal unsupported
        unsupported = {"reason": "Operating-system effects are not modeled"}
        m.emu_stop()

    machine.hook_add(u.UC_HOOK_CODE, on_code)
    machine.hook_add(u.UC_HOOK_INTR, on_system)
    machine.hook_add(u.UC_HOOK_INSN, on_system, None, 1, 0, xc.UC_X86_INS_SYSCALL)
    machine.hook_add(u.UC_HOOK_INSN, on_system, None, 1, 0, xc.UC_X86_INS_SYSENTER)
    try:
        machine.emu_start(
            case["start"],
            case["stop"],
            timeout=2_000_000,
            count=case.get("max_instructions", 1000),
        )
        status = (
            "completed"
            if machine.reg_read(xc.UC_X86_REG_RIP) == case["stop"]
            else "budget_exhausted"
        )
    except u.UcError as e:
        status = "fault" if fault else "unsupported"
        if not fault:
            fault = {"reason": str(e)}
    if unsupported is not None:
        status, fault = "unsupported", unsupported
    ef = machine.reg_read(xc.UC_X86_REG_EFLAGS)
    # Invalid writes may invoke the write hook before faulting; only committed bytes count.
    committed = {}
    for k, v in writes.items():
        try:
            if machine.mem_read(int(k), 1)[0] == v:
                committed[k] = v
        except u.UcError:
            pass
    return {
        "status": status,
        "registers": {
            k: machine.reg_read(getattr(xc, "UC_X86_REG_" + k))
            for k in (*REGISTERS, *case.get("extra_registers", ()))
        },
        "memory": {
            item["name"]: bytes(machine.mem_read(item["address"], item["size"])).hex()
            for item in case.get("observe_memory", ())
        },
        "flags": {k: (ef >> b) & 1 for k, b in FLAGS.items()},
        "writes": committed,
        "fault": fault,
        "trace": trace,
    }


def compare_states(reference, candidate, registers=None, flags=None):
    differences = []
    for field in ("status", "fault", "writes"):
        if reference[field] != candidate[field]:
            differences.append(
                {
                    "field": field,
                    "reference": reference[field],
                    "candidate": candidate[field],
                }
            )
    for group, names in (
        ("registers", registers or REGISTERS),
        ("flags", flags if flags is not None else FLAGS),
    ):
        for name in names:
            if reference[group].get(name) != candidate[group].get(name):
                differences.append(
                    {
                        "field": group + "." + name,
                        "reference": reference[group].get(name),
                        "candidate": candidate[group].get(name),
                    }
                )
    supported = reference["status"] in ("completed", "fault") and candidate[
        "status"
    ] in ("completed", "fault")
    return {
        "passed": supported and not differences,
        "differences": differences,
        "status": (
            "differentially_tested"
            if supported and not differences
            else "mismatch" if supported else "unsupported"
        ),
        "scope": "Recorded inputs and explicitly compared effects only; no all-input equivalence claim",
    }


def differential(case):
    reference = run_reference(case)
    candidate = PcodeMachine(case).run()
    comparison = compare_states(
        reference, candidate, case.get("observe_registers"), case.get("observe_flags")
    )
    return {
        "case": case,
        "reference": reference,
        "candidate": candidate,
        "comparison": comparison,
        "versions": {p: importlib.metadata.version(p) for p in ("unicorn", "pypcode")},
    }


def fixture(name, code, registers=None, flags=None):
    return {
        "name": name,
        "start": 0x1000,
        "stop": 0x1000 + len(bytes.fromhex(code)),
        "registers": {"RSP": 0x3800, **(registers or {})},
        "memory": [
            {"address": 0x1000, "size": 4096, "permissions": "rx", "hex": code},
            {"address": 0x3000, "size": 4096, "permissions": "rw", "hex": ""},
        ],
        "observe_flags": ["CF", "OF", "SF", "ZF", "PF"] if flags is None else flags,
        "max_instructions": 100,
    }


def smoke_cases():
    return [
        fixture("arithmetic_flags", "89f801f0", {"RDI": 0x7FFFFFFF, "RSI": 1}),
        fixture("conditional_branch", "83ff057405b80100000083c002", {"RDI": 5}),
        fixture("memory", "89378b07", {"RDI": 0x3000, "RSI": 0xDEADBEEF}, []),
        fixture("fault", "8b07", {"RDI": 0x9000}, []),
        fixture("call_return", "e802000000eb06b82a000000c3", {}, []),
        fixture("return_contract", "89f84883c003", {"RDI": 7}),
    ]
