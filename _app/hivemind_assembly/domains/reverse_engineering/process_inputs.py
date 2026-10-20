"""Explicit Linux process inputs; never inherit the host environment."""

import struct
from hivemind_assembly.core.common import ContractError


def normalize(argv=None, env=None):
    argv = ["program"] if argv is None else argv
    env = {} if env is None else env
    if not isinstance(argv, list) or not 1 <= len(argv) <= 128:
        raise ContractError("argv requires 1–128 strings including the program name")
    if not isinstance(env, dict) or len(env) > 128:
        raise ContractError("env requires at most 128 named string values")
    strings = list(argv)
    for key, value in env.items():
        if (
            not isinstance(key, str)
            or not key
            or "=" in key
            or not isinstance(value, str)
        ):
            raise ContractError(
                "Environment names must be nonempty and contain no equals sign"
            )
        strings.extend((key, value))
    total = 0
    for value in strings:
        if not isinstance(value, str) or "\0" in value:
            raise ContractError("Process inputs must be strings without NUL bytes")
        try:
            size = len(value.encode("utf-8"))
        except UnicodeEncodeError as error:
            raise ContractError("Process inputs must encode as UTF-8") from error
        if size > 4096:
            raise ContractError("Each process input is limited to 4096 UTF-8 bytes")
        total += size + 1
    if total > 65536:
        raise ContractError("Process inputs exceed 64 KiB")
    return list(argv), dict(sorted(env.items()))


def entry_stack(write, top, argv, env):
    """Build the bounded initial stack for the low-level Unicorn ELF lane."""
    cursor = top

    def push(value):
        nonlocal cursor
        raw = value.encode("utf-8") + b"\0"
        cursor -= len(raw)
        write(cursor, raw)
        return cursor

    args = [push(value) for value in argv]
    variables = [push(key + "=" + value) for key, value in env.items()]
    words = [len(argv), *args, 0, *variables, 0, 0, 0]
    cursor = (cursor - len(words) * 8) & ~15
    write(cursor, struct.pack("<" + "Q" * len(words), *words))
    return cursor
