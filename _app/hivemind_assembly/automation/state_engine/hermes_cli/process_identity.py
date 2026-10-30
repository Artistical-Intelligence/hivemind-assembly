# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
from __future__ import annotations

def process_birth(proc) -> float:
    """A managed worker's identity birth for the ``psutil.Process`` *proc*, the same in every process.

    On macOS psutil shifts ``create_time()`` by ``abs(INIT_BOOT_TIME - boot_time())``
    (``psutil._psosx.adjust_proc_create_time``), with a boot-time reference frozen when psutil
    was imported in the CALLING process. After a clock step (NTP, sleep/wake) a long-lived
    gateway owner and a freshly spawned worker read different births for the same process, and
    the exact identity match refused every managed worker (#140580). The kernel's own start
    (``monotonic=True``: the unadjusted ``kinfo_proc`` epoch start) is what every process sees.
    Other platforms keep ``create_time()``: Linux and Windows apply no per-process reference.
    Raises ``psutil.Error`` like ``create_time()``.
    """
    import psutil
    if getattr(psutil, 'MACOS', False):
        platform_proc = getattr(proc, '_proc', None)
        if platform_proc is not None:
            try:
                return float(platform_proc.create_time(monotonic=True))
            except TypeError:
                pass
    return float(proc.create_time())
