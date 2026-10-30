# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
from __future__ import annotations
import sys
import time

class SessionGatewayMixin:
    """Routing index, session peers/orphans, hygiene streaks, heartbeats, handoffs."""

    def _reap_inactive_orphan_desktop_holders(self, holders: list[tuple[int, str]], *, min_age_seconds: float) -> list[int]:
        """Terminate old PPID-1 Desktop ephemeral backends with no client.

        Fails closed: anything whose parent, age, argv, or network connections
        cannot be proved safe remains a repair-blocking holder."""
        from hivemind_assembly.automation.state_engine.hermes_state import psutil
        from hivemind_assembly.automation.state_engine.hermes_state_dbfile import _concrete_state_db_holder_pids, _is_inactive_orphan_desktop_holder
        if not sys.platform.startswith('linux') or psutil is None:
            return []
        try:
            from hivemind_assembly.automation.state_engine.hermes_cli.dashboard_procs import _is_ephemeral_port_zero_backend
        except Exception:
            return []
        now = time.time()
        candidates = []
        for pid in _concrete_state_db_holder_pids(self.db_path, holders):
            try:
                process = psutil.Process(pid)
                statuses = [conn.status for conn in process.net_connections(kind='inet')]
                if not _is_inactive_orphan_desktop_holder(ppid=process.ppid(), age_seconds=now - process.create_time(), min_age_seconds=min_age_seconds, ephemeral_backend=_is_ephemeral_port_zero_backend(process.cmdline()), connection_statuses=statuses):
                    continue
            except Exception:
                continue
            candidates.append(process)
        signalled: list[int] = []
        for process in candidates:
            try:
                process.terminate()
                signalled.append(process.pid)
            except (psutil.Error, OSError):
                continue
        if not signalled:
            return []
        try:
            _gone, alive = psutil.wait_procs(candidates, timeout=1.5)
        except Exception:
            alive = []
        for process in alive:
            try:
                process.kill()
            except (psutil.Error, OSError):
                continue
        if alive:
            try:
                psutil.wait_procs(alive, timeout=1.5)
            except Exception:
                pass
        return signalled
