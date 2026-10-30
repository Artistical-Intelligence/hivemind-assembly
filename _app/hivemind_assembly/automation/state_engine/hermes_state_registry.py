# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
from __future__ import annotations
import contextlib
import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Optional
if TYPE_CHECKING:
    from hivemind_assembly.automation.state_engine.hermes_state import SessionDB
logger = logging.getLogger(__name__)

class _TeardownBarrier:
    """Accounting for every admitted-but-unfinished physical close of one path.

    A path can own more than one close at a time: the current generation's final
    release and a retired generation's drain are admitted independently under
    ``_lock`` and only meet at the lifecycle mutex. One event per path is honest
    only if the LAST admitted teardown settles it. Signalling on the first lets
    ``close_all()`` return and ``acquire()`` publish a replacement while an older
    handle is still inside ``PRAGMA wal_checkpoint``/sidecar unlink -- the exact
    overlap (#102827) this registry exists to forbid.
    """
    __slots__ = ('event', 'pending')

    def __init__(self) -> None:
        self.event = threading.Event()
        self.pending = 0

class _Generation:
    """One shared SessionDB generation: instance, refcount, file identity."""
    __slots__ = ('db', 'identity', 'path', 'refcount', 'retired')

    def __init__(self, path: Path, db: SessionDB, identity: Optional[tuple[int, int]]) -> None:
        self.path = path
        self.db = db
        self.refcount = 1
        self.identity = identity
        self.retired = False
_lock = threading.Lock()
_generations: dict[Path, _Generation] = {}
_retired: dict[int, _Generation] = {}
_tearing_down: dict[Path, _TeardownBarrier] = {}
_path_lifecycle_locks: dict[Path, threading.Lock] = {}

def _teardown(db: SessionDB) -> None:
    """Close a shared instance, clearing its registry-owned flag first."""
    with contextlib.suppress(Exception):
        db._shared_registry_owned = False
    _close_quietly(db, 'Error closing shared SessionDB')

def _close_quietly(db: SessionDB, debug_message: str) -> None:
    """close() that never propagates. A lost WAL generation whose capture failed is data at risk,
    not teardown noise: the handle stays open and the operator has to act, so that one surfaces."""
    try:
        db.close()
    except Exception as exc:
        from hivemind_assembly.automation.state_engine.hermes_state_dbfile import RetiredGenerationCaptureError
        if isinstance(exc, RetiredGenerationCaptureError):
            logger.error('SessionDB for %s did not settle at close: %s', _db_path_of(db), exc)
        else:
            logger.debug(debug_message, exc_info=True)

def _path_lifecycle_lock_locked(path: Path) -> threading.Lock:
    """Return the lifecycle mutex for *path* (caller holds ``_lock``)."""
    lock = _path_lifecycle_locks.get(path)
    if lock is None:
        lock = threading.Lock()
        _path_lifecycle_locks[path] = lock
    return lock

def _admit_teardown_locked(path: Path) -> _TeardownBarrier:
    """Register one pending physical close for *path* (caller holds ``_lock``).

    Admission shares the lock section that removes the generation, so a peer
    release, ``acquire`` or ``close_all`` taking the lock next always sees this
    teardown accounted for.
    """
    barrier = _tearing_down.get(path)
    if barrier is None:
        barrier = _tearing_down[path] = _TeardownBarrier()
    barrier.pending += 1
    return barrier

def _finish_teardown(path: Path, barrier: _TeardownBarrier) -> None:
    """Settle one admitted teardown; only the last one lifts the path barrier."""
    with _lock:
        barrier.pending -= 1
        if barrier.pending > 0:
            return
        if _tearing_down.get(path) is barrier:
            _tearing_down.pop(path, None)
        barrier.event.set()

def _teardown_generation(path: Path, db: SessionDB, *, barrier: Optional[_TeardownBarrier]=None) -> None:
    """Close *db* under its path lifecycle mutex, then settle its barrier slot."""
    with _lock:
        lifecycle_lock = _path_lifecycle_lock_locked(path)
    try:
        with lifecycle_lock:
            _teardown(db)
    finally:
        if barrier is not None:
            _finish_teardown(path, barrier)

def _db_path_of(db: SessionDB) -> Optional[Path]:
    """``Path(db.db_path)`` or None when absent/unconvertible."""
    path = getattr(db, 'db_path', None)
    try:
        return None if path is None else Path(path)
    except (TypeError, ValueError):
        return None

def release(db: SessionDB) -> bool:
    """Decrement the refcount of a shared SessionDB. ``True`` if *db* was shared; ``False``
    if it is not registry-managed (caller owns close()). The final release tears the
    generation down OUTSIDE the registry lock. Lookup is object-keyed, so holders of an
    old generation release into its retired record, not into whatever the path names."""
    if db is None:
        return False
    key = id(db)
    teardown_barrier: Optional[_TeardownBarrier] = None
    with _lock:
        generation = _retired.get(key)
        if generation is None:
            path = _db_path_of(db)
            if path is None:
                return False
            generation = _generations.get(path)
            if generation is None or generation.db is not db:
                return False
        generation.refcount -= 1
        needs_teardown = generation.refcount <= 0
        if needs_teardown:
            if generation.retired:
                _retired.pop(key, None)
            elif _generations.get(generation.path) is generation:
                _generations.pop(generation.path, None)
            teardown_barrier = _admit_teardown_locked(generation.path)
    if needs_teardown:
        _teardown_generation(generation.path, db, barrier=teardown_barrier)
    return True
