# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
import errno
import logging
import os
import threading
import time
import weakref
from pathlib import Path
from typing import TYPE_CHECKING, Iterator, Optional
if TYPE_CHECKING:
    from hivemind_assembly.automation.state_engine.hermes_state import SessionDB
logger = logging.getLogger('hermes_state')
_READ_POOL_MAX = 8
_READ_POOL_PROCESS_MAX = 24
_HANDLES_PER_PATH_WARN = 4
_FD_HEADROOM_RESERVE = 64
_FD_USAGE_CACHE_SECONDS = 0.25
_process_read_permits = threading.BoundedSemaphore(_READ_POOL_PROCESS_MAX)
_fd_usage_lock = threading.Lock()
_fd_usage_cache: tuple[float, Optional[int]] = (0.0, None)

def _proc_fd_targets(pid: int) -> Iterator[tuple[str, str]]:
    """Yield ``(readlink target, fd path)`` for every entry in /proc/<pid>/fd (unreadable
    links skipped). Raises OSError when the fd directory itself cannot be listed."""
    fd_dir = f'/proc/{pid}/fd'
    for fd in os.listdir(fd_dir):
        fd_path = f'{fd_dir}/{fd}'
        try:
            yield (os.readlink(fd_path), fd_path)
        except OSError:
            continue

def _open_fd_count() -> Optional[int]:
    """Open descriptors in THIS process; None when unmeasurable (Windows: no fd
    dir, correctly inert); -1 when the probe itself hit EMFILE/ENFILE (no headroom)."""
    for fd_dir in ('/proc/self/fd', '/dev/fd'):
        try:
            return len(os.listdir(fd_dir))
        except OSError as exc:
            if exc.errno in (errno.EMFILE, errno.ENFILE):
                return -1
    return None

def _fd_soft_limit() -> Optional[int]:
    """The process's soft RLIMIT_NOFILE, or None when there is no usable one."""
    try:
        import resource
    except ImportError:
        return None
    try:
        soft, _hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    except (AttributeError, OSError, ValueError):
        return None
    if soft in (resource.RLIM_INFINITY, -1):
        return None
    return int(soft)

def _fd_headroom_ok() -> bool:
    """Can the process spare a descriptor for a new read connection? Fails OPEN
    when unmeasurable (refusing every read would be a self-inflicted convoy);
    fails CLOSED only on evidence (measured shortfall or a starved probe)."""
    soft = _fd_soft_limit()
    if soft is None:
        return True
    global _fd_usage_cache
    now = time.monotonic()
    with _fd_usage_lock:
        stamp, cached = _fd_usage_cache
        fresh = cached is not None and now - stamp < _FD_USAGE_CACHE_SECONDS
    if not fresh:
        cached = _open_fd_count()
        with _fd_usage_lock:
            _fd_usage_cache = (now, cached)
    if cached is None:
        return True
    return cached >= 0 and soft - cached > _FD_HEADROOM_RESERVE

def _reclaim_idle_read_conn_anywhere() -> bool:
    """Close one idle read connection on ANY path: the process ceiling is shared
    across files, so a quiet profile must not hold descriptors a busy one needs."""
    with _read_budgets_lock:
        budgets = list(_read_budgets.values())
    return any((budget.reclaim_idle() for budget in budgets))

class _PathReadBudget:
    """Read-connection permits for ONE database file, shared process-wide
    (per-instance semaphores let N SessionDBs peak at N x (1 + MAX)). An idle
    pooled connection keeps its permit, so a permit miss first reclaims an IDLE
    connection from a peer on the same path.

    ``_READ_POOL_MAX`` used to be enforced by a ``BoundedSemaphore`` owned by each SessionDB, which bounded
    the wrong noun: the descriptors are spent on a *file*, so N SessionDB objects on one state.db each got
    their own allowance and peak scaled as ``N x (1 + _READ_POOL_MAX)``. A long-lived gateway holds at least
    two (``SessionStore`` and ``GatewayRunner`` open independent handles per profile path) and the count
    grows with the profile count, which is how a healthy process walked into EMFILE — #98573.
    """

    def __init__(self) -> None:
        self.permits = threading.BoundedSemaphore(_READ_POOL_MAX)
        self._lock = threading.Lock()
        self._members: weakref.WeakSet[SessionDB] = weakref.WeakSet()
        self._duplicate_handles_warned = False

    def register(self, db: 'SessionDB') -> None:
        with self._lock:
            self._members.add(db)
            handles = sum((1 for member in self._members if not member.read_only and member._conn is not None))
            warn = handles > _HANDLES_PER_PATH_WARN and (not self._duplicate_handles_warned)
            if warn:
                self._duplicate_handles_warned = True
                creation_sites = ', '.join(sorted((member._creation_site for member in self._members if not member.read_only)))
        if warn:
            logger.warning('%d live SessionDB handles on %s in this process; each holds its own writer connection (read connections are capped at %d for the file). A long-lived process should share one handle per path. Created at: %s', handles, db.db_path, _READ_POOL_MAX, creation_sites)

    def unregister(self, db: 'SessionDB') -> None:
        """Remove a closed writer from duplicate-handle diagnostics immediately."""
        with self._lock:
            self._members.discard(db)

    def acquire(self, requester: 'SessionDB') -> bool:
        """Take a permit for a new read connection, or refuse (caller degrades to the
        locked writer connection). Gates, broadest first: fd headroom, process
        ceiling, this file's ceiling."""
        if not _fd_headroom_ok():
            global _read_open_denied_fd_headroom
            with _read_budgets_lock:
                _read_open_denied_fd_headroom += 1
            return False
        if not self._acquire_process_permit():
            return False
        if self._acquire_path_permit(requester):
            return True
        _process_read_permits.release()
        return False

    def release(self) -> None:
        """Return one connection's permits. Pairs with a successful acquire()."""
        self.permits.release()
        _process_read_permits.release()

    def _acquire_process_permit(self) -> bool:
        return _process_read_permits.acquire(blocking=False) or (_reclaim_idle_read_conn_anywhere() and _process_read_permits.acquire(blocking=False))

    def _acquire_path_permit(self, requester: 'SessionDB') -> bool:
        return self.permits.acquire(blocking=False) or (self.reclaim_idle(exclude=requester) and self.permits.acquire(blocking=False))

    def reclaim_idle(self, exclude: 'Optional[SessionDB]'=None) -> bool:
        """Close one idle pooled connection held by a member; True if one went.
        Its release() returns both permits, so both ceilings reclaim through here."""
        with self._lock:
            members = [db for db in self._members if db is not exclude]
        return any((member._evict_one_idle_read_conn() for member in members))
_read_budgets: weakref.WeakValueDictionary[str, _PathReadBudget] = weakref.WeakValueDictionary()
_read_budgets_lock = threading.Lock()

def _read_budget_key(db_path) -> str:
    """Canonicalise a db path so two spellings share one budget."""
    try:
        return str(Path(db_path).resolve())
    except OSError:
        return str(db_path)

def _read_budget_for(db_path) -> _PathReadBudget:
    key = _read_budget_key(db_path)
    with _read_budgets_lock:
        budget = _read_budgets.get(key)
        if budget is None:
            budget = _PathReadBudget()
            _read_budgets[key] = budget
        return budget
