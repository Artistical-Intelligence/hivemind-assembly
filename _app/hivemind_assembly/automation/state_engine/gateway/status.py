# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
import os
from pathlib import Path
from typing import Any, Optional
from hivemind_assembly.automation.state_engine.hermes_cli._subprocess_compat import pid_exists_stdlib

def _start_times_agree(current: Any, *recorded: Any) -> bool:
    """Same process object: all fingerprints > 0 and within 1ms of ``current``; raises on junk."""
    cur = float(current)
    return cur > 0 and all((r > 0 and abs(r - cur) <= 0.001 for r in map(float, recorded)))

def _get_process_start_time(pid: int) -> Optional[int]:
    """Return a stable per-process start-time fingerprint, or None.

    Used as a PID-reuse guard: a ``(pid, start_time)`` pair uniquely identifies
    a process, so a recycled PID (same number, different process) yields a
    different value and is never mistaken for the original.

    On Linux this is field 22 of ``/proc/<pid>/stat`` (start time in clock
    ticks since boot, an int).  On platforms without ``/proc`` (macOS, Windows)
    we fall back to ``psutil.Process(pid).create_time()`` — a float epoch
    timestamp — quantized to an int (centiseconds) for stable equality.

    The two sources are never mixed on a single platform: ``/proc`` always
    succeeds first on Linux, and always fails on macOS/Windows so psutil is
    always used there.  Because the guard only compares the value recorded at
    spawn against the live value *on the same host*, the differing units across
    platforms are irrelevant — only same-source equality matters.
    """
    stat_path = Path(f'/proc/{pid}/stat')
    try:
        return int(stat_path.read_text(encoding='utf-8').split()[21])
    except (FileNotFoundError, IndexError, PermissionError, ValueError, OSError):
        pass
    try:
        import psutil
        from hivemind_assembly.automation.state_engine.hermes_cli.process_identity import process_birth
        return round(process_birth(psutil.Process(pid)) * 100)
    except Exception:
        return None

def get_process_start_time(pid: int) -> Optional[int]:
    """Public wrapper for retrieving a process start time when available."""
    return _get_process_start_time(pid)

def _pid_exists(pid: int) -> bool:
    """Cross-platform "is this PID alive" check that does NOT kill the target. CRITICAL on Windows:
    ``os.kill(pid, 0)`` sends ``CTRL_C_EVENT`` to the whole console group (bpo-14484), so prefer
    psutil, then ctypes ``OpenProcess`` (Windows) / ``os.kill(pid, 0)`` (POSIX). Zombies report
    dead: treating one as alive makes --replace wait forever under systemd Restart=always."""
    pid = int(pid)
    try:
        import psutil
        probe_zombie = os.name != 'nt'
        try:
            if probe_zombie and psutil.Process(pid).status() == psutil.STATUS_ZOMBIE:
                return False
        except getattr(psutil, 'NoSuchProcess', ()):
            return False
        except Exception:
            pass
        return bool(psutil.pid_exists(pid))
    except ImportError:
        pass
    return pid_exists_stdlib(pid)
