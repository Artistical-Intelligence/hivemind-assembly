"""Bounded AArch64 function execution using Unicorn's Cortex-A57 CPU.

Base AAPCS64 integer/pointer calls only. System registers, exceptions, authenticated
branches, process state, TLS, SVE/SME and host services have no implicit emulation.
This is a replay adapter, not an ARM operating-system runtime or an equivalence proof.
"""

from hivemind_assembly.core.common import ContractError

REGISTERS = tuple("X" + str(i) for i in range(31)) + ("SP", "PC")


def unsupported_instruction(code):
    """Reject system effects before execution, including counter/random reads.

    In A64's branch/exception/system encoding space, D4 is exception generation,
    D5 is system instructions, and D6 contains register branches. Only the ordinary
    BR/BLR/RET encodings and architectural NOP are admitted from those classes.
    """
    if len(code) != 4:
        return True
    word = int.from_bytes(code, "little")
    top = word >> 24
    if top == 0xD4:
        return True
    if top == 0xD5:
        return word != 0xD503201F
    if top in (0xD6, 0xD7):
        return word & 0xFFFFFC1F not in (0xD61F0000, 0xD63F0000, 0xD65F0000)
    return False


def replay(case):
    import unicorn as u
    from unicorn import arm64_const as ac

    machine = u.Uc(u.UC_ARCH_ARM64, u.UC_MODE_ARM)
    machine.ctl_set_cpu_model(ac.UC_CPU_ARM64_A57)
    # Enable deterministic local SIMD/FP execution, including integer vectorized
    # loops. No FP arguments/results are implied by the caller's integer contract.
    machine.reg_write(ac.UC_ARM64_REG_CPACR_EL1, 3 << 20)
    trace, fault, unsupported = [], None, None
    for region in case["memory"]:
        address, size = region["address"], region["size"]
        data = bytes.fromhex(region["hex"])
        if address % 4096 or size % 4096 or size <= 0 or len(data) > size:
            raise ContractError("AArch64 memory must be page aligned and bounded")
        permissions = region["permissions"]
        mode = sum(
            bit
            for char, bit in (
                ("r", u.UC_PROT_READ),
                ("w", u.UC_PROT_WRITE),
                ("x", u.UC_PROT_EXEC),
            )
            if char in permissions
        )
        machine.mem_map(address, size, mode)
        machine.mem_write(address, data)
    for name, value in case["registers"].items():
        machine.reg_write(getattr(ac, "UC_ARM64_REG_" + name), value)
    machine.reg_write(ac.UC_ARM64_REG_PC, case["start"])
    machine.reg_write(ac.UC_ARM64_REG_NZCV, 0)

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

    def on_code(m, address, size, data):
        nonlocal unsupported
        trace.append(address)
        reason = None
        if size != 4 or address % 4:
            reason = "Invalid AArch64 instruction alignment or length"
        elif not any(
            start <= address and address + size <= end
            for start, end in case["code_ranges"]
        ):
            reason = "Execution left the declared function bytes"
        elif m.reg_read(ac.UC_ARM64_REG_SP) % 16:
            reason = "AArch64 replay requires a 16-byte aligned stack"
        elif unsupported_instruction(bytes(m.mem_read(address, size))):
            reason = (
                "AArch64 system state, exceptions and extended branches are not modeled"
            )
        if reason:
            unsupported = {"reason": reason, "address": address}
            m.emu_stop()

    def on_system(m, *args):
        nonlocal unsupported
        unsupported = {
            "reason": "Operating-system effects and exceptions are not modeled"
        }
        m.emu_stop()

    machine.hook_add(u.UC_HOOK_MEM_READ | u.UC_HOOK_MEM_WRITE, on_access)
    machine.hook_add(u.UC_HOOK_MEM_INVALID, on_fault)
    machine.hook_add(u.UC_HOOK_CODE, on_code)
    machine.hook_add(u.UC_HOOK_INTR, on_system)
    try:
        machine.emu_start(
            case["start"],
            case["stop"],
            timeout=2_000_000,
            count=case.get("max_instructions", 100000),
        )
        status = (
            "completed"
            if machine.reg_read(ac.UC_ARM64_REG_PC) == case["stop"]
            else "budget_exhausted"
        )
    except u.UcError as error:
        status = "fault" if fault else "unsupported"
        if fault is None:
            fault = {"reason": str(error)}
    if unsupported is not None:
        status, fault = "unsupported", unsupported
    return {
        "status": status,
        "registers": {
            name: machine.reg_read(getattr(ac, "UC_ARM64_REG_" + name))
            for name in (*REGISTERS, *case.get("extra_registers", ()))
        },
        "memory": {
            item["name"]: bytes(machine.mem_read(item["address"], item["size"])).hex()
            for item in case.get("observe_memory", ())
        },
        "fault": fault,
        "trace": trace,
    }
