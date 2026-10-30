# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
from __future__ import annotations
import logging
import os
import struct
import sys
import threading
from typing import Optional
logger = logging.getLogger('hermes_state')
_PENDING_BYTE = 1073741824
_SHARED_FIRST = _PENDING_BYTE + 2
_SHARED_SIZE = 510
_SHM_DMS_BYTE = 128
if os.name == 'nt':
    fcntl = None
    _F_OFD_SETLK: Optional[int] = None
    _F_RDLCK = _F_UNLCK = _SEEK_SET = _F_SETLK = 0
else:
    try:
        import fcntl
        _F_OFD_SETLK = getattr(fcntl, 'F_OFD_SETLK', {'linux': 37, 'darwin': 90}.get(sys.platform.rstrip('0123456789')))
        _F_RDLCK, _F_UNLCK, _SEEK_SET = (fcntl.F_RDLCK, fcntl.F_UNLCK, os.SEEK_SET)
        _F_SETLK = fcntl.F_SETLK
        if not callable(getattr(fcntl, 'fcntl', None)):
            raise ImportError('fcntl module has no fcntl() callable')
    except (ImportError, AttributeError):
        fcntl = None
        _F_OFD_SETLK = None
        _F_RDLCK = _F_UNLCK = _SEEK_SET = _F_SETLK = 0
_FLOCK_FORMAT = '@qqihh' if sys.platform == 'darwin' or 'bsd' in sys.platform else '@hhqqi'
Identity = tuple[int, int]
Held = dict[Identity, tuple[int, int]]
_LOCK = threading.Lock()
_HANDLES: dict[Identity, int] = {}

def supported() -> bool:
    return _F_OFD_SETLK is not None

def _flock(lock_type: int, start: int, length: int) -> bytes:
    if _FLOCK_FORMAT == '@qqihh':
        return struct.pack(_FLOCK_FORMAT, start, length, 0, lock_type, _SEEK_SET)
    return struct.pack(_FLOCK_FORMAT, lock_type, _SEEK_SET, start, length, 0)

def _ofd_lock(fd: int, lock_type: int, start: int, length: int, *, cmd: Optional[int]=None) -> bool:
    """Apply a non-blocking OFD lock (a process-owned POSIX one with ``cmd=_F_SETLK``); False when
    the range is held EXCLUSIVE elsewhere."""
    assert fcntl is not None and _F_OFD_SETLK is not None
    try:
        fcntl.fcntl(fd, _F_OFD_SETLK if cmd is None else cmd, _flock(lock_type, start, length))
    except BlockingIOError:
        return False
    return True

def _identity(path: str) -> Optional[Identity]:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_dev, st.st_ino)

def _own_fds_for(identities: set[Identity]):
    """Yield ``(fd, identity)`` for every descriptor of this process on one of *identities*
    (SQLite's own connection descriptors; the cached header-probe fd too, harmless)."""
    for fd_dir in ('/proc/self/fd', '/dev/fd'):
        try:
            names = os.listdir(fd_dir)
        except OSError:
            continue
        for name in names:
            if not name.isdigit():
                continue
            fd = int(name)
            try:
                st = os.fstat(fd)
            except OSError:
                continue
            ident = (st.st_dev, st.st_ino)
            if ident in identities:
                yield (fd, ident)
        return

def _guard_ranges(db_path) -> Held:
    base = os.fspath(db_path)
    ranges: Held = {}
    for path, rng in ((base, (_SHARED_FIRST, _SHARED_SIZE)), (base + '-shm', (_SHM_DMS_BYTE, 1))):
        ident = _identity(path)
        if ident is not None:
            ranges[ident] = rng
    return ranges

def hold(db_path, held: Optional[Held]=None) -> Held:
    """Lock the guard ranges on every descriptor this process has open on ``state.db`` and its
    ``-shm``. Returns the record :func:`release` needs; pass it back to extend an existing one
    (a ``-shm`` minted after open, a reopened connection). Idempotent per handle: an inode already
    in *held* is re-locked (cheap, covers a new descriptor) without a second handle count."""
    held = {} if held is None else held
    if not supported():
        return held
    ranges = _guard_ranges(db_path)
    try:
        with _LOCK:
            for fd, ident in _own_fds_for(set(ranges)):
                start, length = ranges[ident]
                if _ofd_lock(fd, _F_RDLCK, start, length) and ident not in held:
                    held[ident] = ranges[ident]
                    _HANDLES[ident] = _HANDLES.get(ident, 0) + 1
    except OSError:
        logger.debug('WAL lock guard unavailable for %s', os.fspath(db_path), exc_info=True)
    return held

def release(held: Held) -> None:
    """Drop this handle's claim. The last handle on an inode unlocks the range on every descriptor
    still referencing it. Call BEFORE the handle's own close so SQLite's close-time reset sees only
    real holders: a sibling process's intact locks still refuse the unlink, and a true last close
    ends the generation, so a later ``state.db`` replace never pairs with a stale WAL.

    The OFD copy is swapped back for the POSIX lock SQLite believes it still holds (a stray close
    cancelled the real one): unlocked outright, the still-open connection would let a sibling's
    close take EXCLUSIVE and unlink ``-wal``/``-shm`` under it before its own close runs. SQLite's
    close upgrades or drops that process-owned lock itself, so a true last close is unaffected."""
    if not supported() or not held:
        return
    with _LOCK:
        to_unlock: Held = {}
        for ident, rng in held.items():
            remaining = _HANDLES.get(ident, 1) - 1
            if remaining > 0:
                _HANDLES[ident] = remaining
            else:
                _HANDLES.pop(ident, None)
                to_unlock[ident] = rng
        held.clear()
        if not to_unlock:
            return
        try:
            for fd, ident in _own_fds_for(set(to_unlock)):
                start, length = to_unlock[ident]
                _ofd_lock(fd, _F_RDLCK, start, length, cmd=_F_SETLK)
                _ofd_lock(fd, _F_UNLCK, start, length)
        except OSError:
            pass
