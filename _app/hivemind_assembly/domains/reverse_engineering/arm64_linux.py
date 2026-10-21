"""Declared ARMv8-A process identity and single-thread runtime state for Qiling."""

from hivemind_assembly.core.common import Blocked


def configure_auxv(ql):
    # Qiling 1.4.6 uses x86 HWCAP/platform values for every 64-bit ELF. Advertise
    # only baseline FP/ASIMD supported by the verified Cortex-A72 guest. In
    # particular, never select SVE, LSE, PAC or MTE library implementations.
    found = set()
    for index in range(64):
        address = ql.loader.auxv + index * 16
        kind, value = ql.mem.read_ptr(address), ql.mem.read_ptr(address + 8)
        if kind == 0:
            break
        if kind in (16, 26):  # AT_HWCAP, AT_HWCAP2
            ql.mem.write_ptr(address + 8, 3 if kind == 16 else 0)
            found.add(kind)
        elif kind == 15:  # AT_PLATFORM: upstream reserves a pointer-aligned slot.
            if value % 8 or bytes(ql.mem.read(value, 5)) != b"i686\0":
                raise Blocked("Unexpected upstream ARM platform string layout")
            ql.mem.write(value, b"aarch64\0")
            found.add(kind)
    if found != {15, 16, 26}:
        raise Blocked("Missing ARM process capability metadata")
    ql.arch.regs.tpidr_el0 = 0


def runtime_instruction(ql, word, address, memory_allowed, record):
    """Handle only explicitly modeled runtime registers; unknown effects stay blocked."""
    register = word & 31
    instruction = word & ~31
    if instruction == 0xD53B00E0:  # MRS Xt, DCZID_EL0
        # DZP=1: cache-line zero is prohibited in this bounded guest. Libraries
        # must choose ordinary stores. DC ZVA itself remains unsupported.
        if register != 31:
            ql.arch.regs.write("x" + str(register), 0x10)
        record({"call": "cpu_query", "register": "dczid_el0", "value": 0x10})
    elif instruction == 0xD53BD040:  # MRS Xt, TPIDR_EL0
        if register != 31:
            ql.arch.regs.write("x" + str(register), ql.arch.regs.tpidr_el0)
    elif instruction == 0xD51BD040:  # MSR TPIDR_EL0, Xt
        value = ql.arch.regs.read("x" + str(register)) if register != 31 else 0
        if value and not memory_allowed(value, 1, "r"):
            raise Blocked("invalid_tls_memory")
        ql.arch.regs.tpidr_el0 = value
        record({"call": "thread_pointer"})
    elif word in (0xD503241F, 0xD503245F, 0xD503249F, 0xD50324DF):
        # BTI hints are architectural NOPs on the declared ARMv8.0 A72.
        # HWCAP2 does not advertise BTI and PROT_BTI mappings stay unsupported.
        pass
    elif word in (0xD5033BBF, 0xD5033B9F, 0xD5033FDF):  # DMB/DSB ISH, ISB SY
        # This guest is single-threaded, with synchronous memory operations and
        # no shared host mappings. The ordering constraint is already satisfied.
        pass
    else:
        return False
    ql.arch.regs.pc = address + 4
    return True
