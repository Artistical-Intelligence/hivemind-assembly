"""Guest-only failure locations; diagnostics never participate in acceptance."""


def stopped_context(se, data, instruction, api, access):
    import pefile
    from unicorn import UC_PROT_READ, UC_PROT_WRITE, UC_PROT_EXEC

    result = {"phase": "application" if instruction else "initialization"}
    if api is not None:
        result["api"] = api
    if access is not None:
        result["memory_access"] = access
    if instruction is None:
        return result
    pc, raw = instruction
    result.update(program_counter=pc, instruction_hex=raw.hex(), image="program")
    pe = pefile.PE(data=data)
    try:
        base = pe.OPTIONAL_HEADER.ImageBase
        rva = pc - base
        result.update(image_base=base, image_offset=rva)
        try:
            offset = pe.get_offset_from_rva(rva)
            if 0 <= offset and offset + len(raw) <= len(data):
                result["image_file_offset"] = offset
                result["image_instruction_hex"] = data[offset : offset + len(raw)].hex()
        except pefile.PEFormatError:
            pass
    finally:
        pe.close()
    try:
        result["current_program_counter"] = se.get_pc()
        for start, end, permissions in se.emu.get_mem_regions():
            if start <= pc <= end:
                result["mapping"] = {
                    "start": start,
                    "end": end + 1,
                    "permissions": "".join(
                        name
                        for bit, name in (
                            (UC_PROT_READ, "r"),
                            (UC_PROT_WRITE, "w"),
                            (UC_PROT_EXEC, "x"),
                        )
                        if permissions & bit
                    ),
                }
                break
    except Exception:
        # A partially initialized/stopped engine may not expose registers/maps.
        # Preserve the original failure and the instruction already observed.
        pass
    return result
