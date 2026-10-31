from __future__ import annotations
import math, os, re, signal, subprocess, threading, time
from pathlib import Path
from hivemind_assembly.core.common import ContractError


class Jobs:
    """Managed child processes; no shell strings and no ambient model credentials."""

    def __init__(self, runtime=None):
        self.running = {}
        self.lock = threading.Lock()
        self.runtime = runtime
        self.reservations = {}

    def run(self, key, argv, cwd, timeout=300, cancel=None, environment=None):
        if (not isinstance(key, str) or re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", key) is None
                or not isinstance(argv, (list, tuple)) or not argv or len(argv) > 200
                or not all(isinstance(x, str) and "\x00" not in x and len(x) <= 65536 for x in argv)
                or not argv[0]):
            raise ContractError("Expected a bounded argv array and operation identifier")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
            raise ContractError("Execution timeout must be between zero and one hour")
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
        owned_stop = threading.Event()
        with self.lock:
            if key in self.reservations:
                raise ContractError("This process operation is already running")
            self.reservations[key] = owned_stop

        class Cancellation:
            def is_set(self):
                return owned_stop.is_set() or (cancel is not None and cancel.is_set())

        cancelled = Cancellation()
        try:
            if cancelled.is_set():
                return {"status": "cancelled", "exit_code": -1, "elapsed": 0.0,
                        "output": "", "output_truncated": False}
            # The application supplies an authenticated component resolver. A
            # configured helper's failure never falls back or repeats the command.
            engine = self.runtime() if self.runtime is not None else None
            if engine is not None:
                return engine.run(key, argv, cwd, timeout, cancelled, env)
            return self._run_native(key, argv, cwd, timeout, cancelled, env)
        finally:
            with self.lock:
                self.reservations.pop(key, None)

    def _run_native(self, key, argv, cwd, timeout, cancel, env):
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
            owned_stop = self.reservations.get(key)
            proc = self.running.get(key)
        if owned_stop is not None:
            owned_stop.set()
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
