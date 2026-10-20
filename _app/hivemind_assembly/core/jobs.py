from __future__ import annotations
import os, signal, subprocess, threading, time
from pathlib import Path
from hivemind_assembly.core.common import ContractError


class Jobs:
    """Managed child processes; no shell strings and no ambient model credentials."""

    def __init__(self):
        self.running = {}
        self.lock = threading.Lock()

    def run(self, key, argv, cwd, timeout=300, cancel=None, environment=None):
        if not argv or not all(isinstance(x, str) for x in argv):
            raise ContractError("Expected an argv array")
        env = {
            k: v
            for k, v in os.environ.items()
            if k.upper()
            in (
                "PATH",
                "SYSTEMROOT",
                "WINDIR",
                "TEMP",
                "TMP",
                "HOME",
                "USERPROFILE",
                "JAVA_HOME",
                "LANG",
                "LOCALAPPDATA",
                "APPDATA",
            )
        }
        if environment:
            if set(environment) - {"GHIDRA_INSTALL_DIR", "JAVA_HOME"}:
                raise ContractError("Unrecognized native tool environment setting")
            if any(not isinstance(v, str) for v in environment.values()):
                raise ContractError("Native tool environment values must be paths")
            env.update(environment)
        flags = (
            {"start_new_session": True}
            if os.name != "nt"
            else {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        )
        log = Path(cwd) / (".job-" + key + ".log")
        log.parent.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        with log.open("wb") as f:
            proc = subprocess.Popen(
                argv,
                cwd=cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=f,
                stderr=subprocess.STDOUT,
                **flags,
            )
            with self.lock:
                self.running[key] = proc
            outcome = "completed"
            try:
                while proc.poll() is None:
                    if cancel and cancel.is_set():
                        outcome = "cancelled"
                        self.stop(key)
                        break
                    if time.monotonic() - started > timeout:
                        outcome = "timeout"
                        self.stop(key)
                        break
                    if log.stat().st_size > 32 * 1024 * 1024:
                        outcome = "output_limit"
                        self.stop(key)
                        break
                    time.sleep(0.05)
                proc.wait(timeout=10)
            finally:
                with self.lock:
                    self.running.pop(key, None)
        data = log.read_bytes()
        log.unlink(missing_ok=True)
        return {
            "status": outcome,
            "exit_code": proc.returncode,
            "elapsed": time.monotonic() - started,
            "output": data[-2_000_000:].decode("utf-8", errors="replace"),
            "output_truncated": len(data) > 2_000_000,
        }

    def stop(self, key):
        with self.lock:
            proc = self.running.get(key)
        if proc and proc.poll() is None:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True
                )
            else:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
