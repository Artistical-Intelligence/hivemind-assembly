"""Guest-only failure location; diagnostic metadata never changes acceptance."""

from pathlib import Path


def stopped_context(ql, root, binary, dependencies, instruction, phase, syscall):
    pc, raw = instruction
    result = {
        "phase": phase,
        "program_counter": pc,
        "instruction_hex": raw.hex(),
        "current_program_counter": ql.arch.regs.arch_pc,
    }
    if syscall is not None:
        result["syscall_number"] = syscall
    # Qiling's image labels contain staging paths. Only expose declared guest
    # identities, never temporary host directories or arbitrary engine labels.
    image = ql.loader.find_containing_image(pc)
    if image:
        path = Path(image.path)
        if path == binary:
            result["image"] = "program"
            result["image_virtual_address"] = pc - ql.loader.load_address
        else:
            names = {root / name.lstrip("/"): name for name in dependencies}
            if path in names:
                result["image"] = names[path]
        result["image_base"] = image.base
        result["image_offset"] = pc - image.base
    for start, end, permissions, *_ in ql.mem.get_mapinfo():
        if start <= pc < end:
            result["mapping"] = {"start": start, "end": end, "permissions": permissions}
            break
    return result
