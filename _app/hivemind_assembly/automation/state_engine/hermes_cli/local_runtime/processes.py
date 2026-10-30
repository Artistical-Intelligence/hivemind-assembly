# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
from __future__ import annotations
import ctypes
from ctypes import wintypes
import subprocess
import sys
import threading
import psutil

class _BasicLimits(ctypes.Structure):
    _fields_ = [('PerProcessUserTimeLimit', ctypes.c_longlong), ('PerJobUserTimeLimit', ctypes.c_longlong), ('LimitFlags', wintypes.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t), ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', wintypes.DWORD), ('Affinity', ctypes.c_size_t), ('PriorityClass', wintypes.DWORD), ('SchedulingClass', wintypes.DWORD)]

class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in ('ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount', 'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]

class _ExtendedLimits(ctypes.Structure):
    _fields_ = [('BasicLimitInformation', _BasicLimits), ('IoInfo', _IoCounters), ('ProcessMemoryLimit', ctypes.c_size_t), ('JobMemoryLimit', ctypes.c_size_t), ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]

class _WindowsJob:

    def __init__(self):
        self._lock = threading.Lock()
        self._api = ctypes.WinDLL('kernel32', use_last_error=True)
        for name, args, result in (('CreateJobObjectW', [ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE), ('SetInformationJobObject', [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL), ('AssignProcessToJobObject', [wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL), ('CloseHandle', [wintypes.HANDLE], wintypes.BOOL)):
            fn = getattr(self._api, name)
            fn.argtypes = args
            fn.restype = result
        self._handle = self._api.CreateJobObjectW(None, None)
        if not self._handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            limits = _ExtendedLimits()
            limits.BasicLimitInformation.LimitFlags = 8192
            if not self._api.SetInformationJobObject(self._handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                raise ctypes.WinError(ctypes.get_last_error())
        except BaseException:
            self.close()
            raise

    def assign(self, proc: subprocess.Popen) -> None:
        if not self._api.AssignProcessToJobObject(self._handle, int(proc._handle)):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self) -> None:
        """Terminate the contained tree; repeated closes are harmless."""
        with self._lock:
            if self._handle is not None:
                if not self._api.CloseHandle(self._handle):
                    raise ctypes.WinError(ctypes.get_last_error())
                self._handle = None

def spawn_server(cmd, **kwargs) -> tuple[subprocess.Popen, _WindowsJob | None]:
    """Start a router, returning its process and an owner-held containment handle.

    Keep the job until shutdown and call close() to terminate the entire tree.
    Windows closes it automatically if the owner dies. Other hosts retain Popen's
    ordinary behavior. Assignment happens before the child's first instruction.
    """
    if sys.platform != 'win32':
        return (subprocess.Popen(cmd, **kwargs), None)
    job = _WindowsJob()
    proc = None
    try:
        kwargs['creationflags'] = kwargs.get('creationflags', 0) | 4
        proc = subprocess.Popen(cmd, **kwargs)
        job.assign(proc)
        psutil.Process(proc.pid).resume()
        return (proc, job)
    except BaseException:
        try:
            if proc is not None:
                proc.kill()
                proc.wait(timeout=10)
        finally:
            try:
                job.close()
            finally:
                if proc is not None:
                    for stream in (proc.stdin, proc.stdout, proc.stderr):
                        if stream is not None:
                            stream.close()
                    proc._handle.Close()
        raise
