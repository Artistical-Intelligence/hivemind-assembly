# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
from __future__ import annotations
from contextlib import contextmanager
import logging
import os
import subprocess
import sys
import time
from typing import Optional
logger = logging.getLogger(__name__)

@contextmanager
def _process_tree_snapshot(pid: int, *, hard_kill: bool):
    """Stop each hard-kill target before discovering its children: a running
    parent can fork after psutil builds its PID map and escape the final signal.
    Resume anything we stopped if signalling fails. Graceful signals never stop
    their recipients, since their handlers must remain able to run.
    """
    descendants = []
    stopped = []
    try:
        try:
            import psutil
            root = psutil.Process(pid)
            descendants = root.children(recursive=True)
            if hard_kill:
                pending = [root]
                seen = {os.getpid()}
                known = {process.pid: process for process in descendants}
                stop_deadline = time.monotonic() + 1.0
                while pending:
                    for process in pending:
                        if process.pid in seen:
                            continue
                        seen.add(process.pid)
                        if time.monotonic() >= stop_deadline:
                            raise TimeoutError('process tree did not stop before snapshot deadline')
                        try:
                            status = process.status()
                            if status in (psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD):
                                continue
                            if status != psutil.STATUS_STOPPED:
                                process.suspend()
                                stopped.append(process)
                            while process.status() != psutil.STATUS_STOPPED:
                                if time.monotonic() >= stop_deadline:
                                    raise TimeoutError('process did not stop before snapshot deadline')
                                time.sleep(0.001)
                        except psutil.NoSuchProcess:
                            continue
                    for process in root.children(recursive=True):
                        known.setdefault(process.pid, process)
                    descendants = list(known.values())
                    pending = [process for process in descendants if process.pid not in seen]
        except Exception:
            logger.debug('kill_process_tree: snapshot incomplete for pid %s', pid, exc_info=True)
        yield descendants
    finally:
        for process in stopped:
            try:
                process.resume()
            except Exception:
                logger.debug('kill_process_tree: target already gone or resume refused', exc_info=True)

def kill_process_tree(pid: int, *, sig: Optional[int]=None) -> bool:
    """Terminate ``pid`` and all its descendants, portably; True when anything was signalled.

    Windows: ``taskkill /F /T`` (``sig`` ignored). POSIX: snapshot descendants via
    psutil; for SIGKILL, stop and rescan the live tree so a concurrent fork cannot
    escape a stale snapshot. Signal identity-checked descendants before their
    parent, then its group when ``pid`` leads one. Stopping is best-effort with a
    bounded wait; unavailable psutil still leaves process-group cleanup. Other
    signals do not suspend recipients. ``sig`` defaults to ``SIGKILL``."""
    if sys.platform == 'win32':
        try:
            from hivemind_assembly.automation.state_engine.hermes_cli._subprocess_compat import windows_hide_flags
            creationflags = windows_hide_flags()
        except Exception:
            creationflags = 0
        try:
            proc = subprocess.run(['taskkill', '/F', '/T', '/PID', str(pid)], stdin=subprocess.DEVNULL, capture_output=True, timeout=15, check=False, creationflags=creationflags)
            return proc.returncode == 0
        except Exception:
            logger.debug('kill_process_tree: taskkill failed for pid %s', pid, exc_info=True)
            return False
    import signal as _signal
    if sig is None:
        sig = _signal.SIGKILL
    with _process_tree_snapshot(int(pid), hard_kill=sig == _signal.SIGKILL) as descendants:
        signalled = False
        for child in reversed(descendants):
            try:
                if child.is_running():
                    child.send_signal(sig)
                    signalled = True
            except Exception:
                continue
        try:
            pgid = os.getpgid(pid)
        except (ProcessLookupError, PermissionError, OSError):
            pgid = None
        try:
            if pgid is not None and pgid == pid:
                os.killpg(pgid, sig)
            else:
                os.kill(pid, sig)
            signalled = True
        except ProcessLookupError:
            pass
        except (PermissionError, OSError):
            logger.debug('kill_process_tree: signal failed for pid %s', pid, exc_info=True)
        return signalled
