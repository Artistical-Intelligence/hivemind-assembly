# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
from __future__ import annotations
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Optional
from hivemind_assembly.automation.state_engine.hermes_state_errors import classify_persistence_error, is_fts_scoped_corruption_error, is_malformed_schema_error
logger = logging.getLogger(__name__)
STORAGE_OK = 'ok'
STORAGE_CORRUPT = 'corrupt'
_lock = threading.Lock()
_corrupt: dict[str, str] = {}

def _key(db_path) -> str:
    return str(Path(db_path).expanduser().resolve(strict=False))

def is_structural_corruption_error(exc: BaseException) -> bool:
    """Canonical B-tree/schema/freelist damage: a corrupt/NOTADB error SQLite does not scope to
    the FTS index, and not the malformed-schema case the web open path repairs."""
    return isinstance(exc, sqlite3.DatabaseError) and (not is_fts_scoped_corruption_error(exc)) and (not is_malformed_schema_error(exc)) and (classify_persistence_error(exc) == 'corrupt')

def mark_storage_corrupt(db_path, reason: object) -> None:
    """Latch *db_path* as corrupt for the life of this process (idempotent)."""
    key = _key(db_path)
    with _lock:
        if key in _corrupt:
            return
        _corrupt[key] = str(reason)
    logger.error('state.db at %s is structurally corrupt (%s); session storage is reported as corrupt until Hermes restarts on a recovered or restored file. Stop Hermes, then run `hermes sessions recover --source %s --inspect-only` or restore a snapshot.', db_path, reason, db_path)

def note_storage_error(db_path, exc: BaseException) -> bool:
    """Latch *db_path* when *exc* is structural corruption; True when it was."""
    if not is_structural_corruption_error(exc):
        return False
    mark_storage_corrupt(db_path, exc)
    return True

def storage_state(db_path) -> str:
    """``"corrupt"`` once this process has seen structural corruption on *db_path*, else ``"ok"``."""
    with _lock:
        return STORAGE_CORRUPT if _key(db_path) in _corrupt else STORAGE_OK

def storage_corrupt_reason(db_path) -> Optional[str]:
    """The first error text latched for *db_path* (logs/diagnostics only), or None."""
    with _lock:
        return _corrupt.get(_key(db_path))
