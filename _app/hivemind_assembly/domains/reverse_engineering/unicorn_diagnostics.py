"""Bounded guest-only stop evidence shared by Unicorn replay adapters."""


def stopped_context(
    machine, arm, status, instruction, *, count, budget, access=None, syscall=None
):
    import unicorn as u
    from unicorn import arm64_const as ac, x86_const as xc

    result = {
        "phase": "application" if instruction else "initialization",
        "stop_reason": status,
    }
    if status == "budget_exhausted":
        # Query the engine: elapsed host time or the current PC is not proof
        # of which bound stopped execution, especially on busy hosted runners.
        result["stop_reason"] = (
            "wall_clock_limit"
            if machine.query(u.UC_QUERY_TIMEOUT)
            else "instruction_limit" if count >= budget else "execution_stopped"
        )
    if access is not None:
        result["memory_access"] = dict(access)
    if syscall is not None:
        result["syscall"] = syscall
    if instruction is None:
        return result
    pc, raw = instruction
    result.update(program_counter=pc, instruction_hex=raw.hex())
    register = ac.UC_ARM64_REG_PC if arm else xc.UC_X86_REG_RIP
    result["current_program_counter"] = machine.reg_read(register)
    for lo, hi, permissions in machine.mem_regions():
        if lo <= pc <= hi:
            result["mapping"] = {
                "start": lo,
                "end": hi + 1,
                "permissions": "".join(
                    name
                    for bit, name in (
                        (u.UC_PROT_READ, "r"),
                        (u.UC_PROT_WRITE, "w"),
                        (u.UC_PROT_EXEC, "x"),
                    )
                    if permissions & bit
                ),
            }
            break
    return result


def locate(context, segments, buffers=()):
    """Attach supplied image/buffer identities, never paths or arbitrary memory."""
    if context is None:
        return None
    result = dict(context)
    pc = result.get("program_counter")
    if pc is not None:
        for segment in segments:
            offset = pc - segment["address"]
            if not 0 <= offset < segment["size"]:
                continue
            result.update(
                image=segment.get("image", "program"),
                image_base=segment.get("image_base", segment["address"]),
                image_offset=pc - segment.get("image_base", segment["address"]),
            )
            if "image_sha256" in segment:
                result["image_sha256"] = segment["image_sha256"]
            for key in ("source_image_sha256", "original_image_base"):
                if key in segment:
                    result[key] = segment[key]
            raw = segment.get("data")
            if raw is None:
                raw = bytes.fromhex(segment.get("hex", ""))
            size = len(bytes.fromhex(result["instruction_hex"]))
            if size and "file_offset" in segment and offset + size <= len(raw):
                result.update(
                    image_file_offset=segment["file_offset"] + offset,
                    image_instruction_hex=raw[offset : offset + size].hex(),
                )
            break
    access = result.get("memory_access")
    if access is not None:
        access = dict(access)
        address, size = access["address"], access["size"]
        for buffer in buffers:
            lo, hi = buffer["address"], buffer["address"] + buffer["size"]
            if lo <= address <= hi or (address < lo < address + size):
                access.update(
                    buffer=buffer["name"],
                    buffer_offset=address - lo,
                    buffer_size=buffer["size"],
                    within_bounds=lo <= address and address + size <= hi,
                )
                break
        result["memory_access"] = access
    return result


def memory_access(access, address, size):
    import unicorn as u

    names = {
        u.UC_MEM_READ: "read",
        u.UC_MEM_WRITE: "write",
        u.UC_MEM_READ_UNMAPPED: "read",
        u.UC_MEM_READ_PROT: "read",
        u.UC_MEM_WRITE_UNMAPPED: "write",
        u.UC_MEM_WRITE_PROT: "write",
        u.UC_MEM_FETCH_UNMAPPED: "execute",
        u.UC_MEM_FETCH_PROT: "execute",
    }
    return {"access": names.get(access, "unknown"), "address": address, "size": size}
