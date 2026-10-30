# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
from __future__ import annotations
import contextlib
import functools
from pathlib import Path

@functools.lru_cache(maxsize=1)
def current_instantiation_epoch() -> str:
    """Identity of THIS container / VM instantiation ("<boot_id>:<pid1_start>").

    Stable for the life of PID 1 (a gateway-only respawn keeps honouring an
    in-flight drain) but changes when the machine is recreated: boot_id on a VM
    reboot, PID 1's start time on ``docker restart``.  ``""`` when neither is
    readable (non-Linux, no ``/proc``) disables the epoch check — never fail-closed.
    """
    boot_id = pid1_start = ''
    with contextlib.suppress(OSError):
        boot_id = Path('/proc/sys/kernel/random/boot_id').read_text(encoding='utf-8').strip()
    with contextlib.suppress(OSError, IndexError):
        pid1_start = Path('/proc/1/stat').read_text(encoding='utf-8').rsplit(')', 1)[1].split()[19]
    return f'{boot_id}:{pid1_start}' if boot_id or pid1_start else ''
