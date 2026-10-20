"""Bounded, credential-stripped native test processes; NOT a security sandbox."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time


@contextmanager
def process_directory():
    directory = tempfile.TemporaryDirectory(prefix="ha-process-")
    try:
        yield directory.name
    finally:
        # Windows may still release inherited stream handles after job accounting
        # reaches zero. Retry only transient sharing/lock violations, with a hard
        # deadline; never hide permissions failures or abandoned live processes.
        deadline = time.monotonic() + 2
        while True:
            try:
                directory.cleanup()
                break
            except PermissionError as error:
                if (
                    os.name != "nt"
                    or getattr(error, "winerror", None) not in (32, 33)
                    or time.monotonic() >= deadline
                ):
                    raise
                time.sleep(0.025)


class WindowsJob:
    """Own descendants before the cooperative launcher starts target code."""

    def __init__(self, process):
        import ctypes as c
        from ctypes import wintypes as w

        class Basic(c.Structure):
            _fields_ = [
                ("process_time", c.c_int64),
                ("job_time", c.c_int64),
                ("flags", w.DWORD),
                ("minimum", c.c_size_t),
                ("maximum", c.c_size_t),
                ("active", w.DWORD),
                ("affinity", c.c_size_t),
                ("priority", w.DWORD),
                ("scheduling", w.DWORD),
            ]

        class IO(c.Structure):
            _fields_ = [
                (name, c.c_uint64)
                for name in (
                    "read_ops",
                    "write_ops",
                    "other_ops",
                    "read_bytes",
                    "write_bytes",
                    "other_bytes",
                )
            ]

        class Extended(c.Structure):
            _fields_ = [
                ("basic", Basic),
                ("io", IO),
                ("process_memory", c.c_size_t),
                ("job_memory", c.c_size_t),
                ("peak_process", c.c_size_t),
                ("peak_job", c.c_size_t),
            ]

        class Accounting(c.Structure):
            _fields_ = [
                ("user_time", c.c_int64),
                ("kernel_time", c.c_int64),
                ("period_user_time", c.c_int64),
                ("period_kernel_time", c.c_int64),
                ("page_faults", w.DWORD),
                ("total_processes", w.DWORD),
                ("active_processes", w.DWORD),
                ("terminated_processes", w.DWORD),
            ]

        self.accounting_type = Accounting

        self.api = c.WinDLL("kernel32", use_last_error=True)
        for name, args, result in (
            ("CreateJobObjectW", [c.c_void_p, w.LPCWSTR], w.HANDLE),
            (
                "SetInformationJobObject",
                [w.HANDLE, c.c_int, c.c_void_p, w.DWORD],
                w.BOOL,
            ),
            ("AssignProcessToJobObject", [w.HANDLE, w.HANDLE], w.BOOL),
            ("CloseHandle", [w.HANDLE], w.BOOL),
            ("TerminateJobObject", [w.HANDLE, w.UINT], w.BOOL),
            (
                "QueryInformationJobObject",
                [w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.c_void_p],
                w.BOOL,
            ),
        ):
            fn = getattr(self.api, name)
            fn.argtypes, fn.restype = args, result
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise c.WinError(c.get_last_error())
        info = Extended()
        info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.api.SetInformationJobObject(
            self.handle, 9, c.byref(info), c.sizeof(info)
        ) or not self.api.AssignProcessToJobObject(self.handle, int(process._handle)):
            error = c.WinError(c.get_last_error())
            self.close()
            raise error

    def close(self):
        if self.handle:
            import ctypes as c

            try:
                # Kill-on-close is the crash fallback. Normal cleanup must also
                # wait for descendants to release inherited output-file handles.
                if not self.api.TerminateJobObject(self.handle, 1):
                    raise c.WinError(c.get_last_error())
                deadline = time.monotonic() + 5
                while True:
                    accounting = self.accounting_type()
                    if not self.api.QueryInformationJobObject(
                        self.handle, 1, c.byref(accounting), c.sizeof(accounting), None
                    ):
                        raise c.WinError(c.get_last_error())
                    if accounting.active_processes == 0:
                        break
                    if time.monotonic() >= deadline:
                        raise TimeoutError(
                            "Windows test process tree did not terminate"
                        )
                    time.sleep(0.01)
            finally:
                self.api.CloseHandle(self.handle)
                self.handle = None


def run(argv, cwd, *, stdin=b"", timeout=30, output_limit=1048576, cancel=None):
    """File-backed streams avoid descendant-held PIPE timeout deadlocks."""
    if cancel is not None and cancel.is_set():
        return {
            "status": "cancelled",
            "exit_code": None,
            "stdout_hex": "",
            "stderr_hex": "",
            "elapsed_seconds": 0.0,
        }
    started = time.monotonic()
    with process_directory() as temp:
        meta = Path(temp)
        home = meta / "home"
        home.mkdir()
        environment = {
            k: os.environ[k]
            for k in ("PATH", "SystemRoot", "WINDIR")
            if k in os.environ
        }
        if os.name == "nt":
            # Installed toolchains use Windows' shared installation roots (in
            # particular Visual Studio's Setup Configuration service). These are
            # system paths, not the user's profile or an inherited tool config.
            for name in (
                "SystemDrive",
                "ProgramData",
                "ALLUSERSPROFILE",
                "ProgramFiles",
                "ProgramFiles(x86)",
                "ProgramW6432",
            ):
                if name in os.environ:
                    environment[name] = os.environ[name]
        environment.update(
            HOME=str(home),
            USERPROFILE=str(home),
            TEMP=str(home),
            TMP=str(home),
            LANG="C.UTF-8",
            LC_ALL="C.UTF-8",
            TZ="UTC",
            PYTHONHASHSEED="0",
        )
        (meta / "stdin").write_bytes(stdin)
        (meta / "request.json").write_text(
            json.dumps({"argv": argv, "cwd": str(cwd), "parent_pid": os.getpid()}),
            encoding="utf-8",
        )
        command = [
            sys.executable,
            "-I",
            str(Path(__file__).with_name("_process_entry.py")),
            str(meta),
        ]
        job, proc = None, None
        status = "completed"
        with (meta / "stdin").open("rb") as inp, (meta / "stdout").open("wb") as out, (
            meta / "stderr"
        ).open("wb") as err:
            try:
                proc = subprocess.Popen(
                    command,
                    cwd=cwd,
                    env=environment,
                    stdin=inp,
                    stdout=out,
                    stderr=err,
                    **({"start_new_session": True} if os.name != "nt" else {})
                )
                if os.name == "nt":
                    job = WindowsJob(proc)
                (meta / "start").touch()
                while proc.poll() is None:
                    if cancel is not None and cancel.is_set():
                        status = "cancelled"
                        break
                    if time.monotonic() - started >= timeout:
                        status = "timeout"
                        break
                    if any(
                        (meta / name).stat().st_size > output_limit
                        for name in ("stdout", "stderr")
                    ):
                        status = "output_limit"
                        break
                    time.sleep(0.02)
            finally:
                if job:
                    job.close()
                if proc is not None:
                    if os.name != "nt":
                        # Also clean up descendants after a normally exiting parent.
                        try:
                            os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    elif proc.poll() is None:
                        proc.kill()
                    proc.wait(timeout=10)
        streams = {}
        for name in ("stdout", "stderr"):
            with (meta / name).open("rb") as f:
                data = f.read(output_limit + 1)
            if len(data) > output_limit:
                status = "output_limit"
            streams[name + "_hex"] = data[:output_limit].hex()
        code = proc.returncode
        if status == "completed":
            response = meta / "result.json"
            if code != 0 or not response.is_file():
                status = "launcher_error"
            else:
                code = json.loads(response.read_text(encoding="utf-8"))["exit_code"]
        return {
            "status": status,
            "exit_code": code,
            **streams,
            "elapsed_seconds": time.monotonic() - started,
        }
