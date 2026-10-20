"""Instructions whose external state is outside deterministic replay."""


def unsupported(instruction):
    if not 1 <= len(instruction) <= 15:
        return True
    while instruction and (
        instruction[0]
        in (0x66, 0x67, 0xF0, 0xF2, 0xF3, 0x2E, 0x36, 0x3E, 0x26, 0x64, 0x65)
        or 0x40 <= instruction[0] <= 0x4F
    ):
        instruction = instruction[1:]
    return (
        instruction[:2] in (b"\x0f\x31", b"\x0f\x33", b"\x0f\xa2")
        or instruction[:3] in (b"\x0f\x01\xf9", b"\x0f\x01\xd0")
        or (
            instruction[:2] == b"\x0f\xc7"
            and len(instruction) >= 3
            and (instruction[2] >> 3) & 7 in (6, 7)
        )
        or bool(
            instruction
            and instruction[0]
            in (0xE4, 0xE5, 0xE6, 0xE7, 0xEC, 0xED, 0xEE, 0xEF, 0x6C, 0x6D, 0x6E, 0x6F)
        )
    )
