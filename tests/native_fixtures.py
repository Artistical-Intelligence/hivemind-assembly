"""Select the compiler for the guest format, separately from the host oracle."""

import os
import platform
import shutil
import pytest


def elf_compiler():
    # MinGW GCC produces PE, even with the freestanding Linux recipe's flags.
    compiler = (
        (os.environ.get("HA_TEST_CLANG") or shutil.which("clang"))
        if os.name == "nt"
        else (shutil.which("gcc") or shutil.which("clang"))
    )
    if not compiler:
        pytest.skip("A Linux ELF cross compiler is required")
    return compiler


LINUX_ORACLE = pytest.mark.skipif(
    platform.system() != "Linux"
    or platform.machine().lower() not in ("x86_64", "amd64"),
    reason="Native Linux ELF oracle requires a Linux x86-64 host",
)
