# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
from __future__ import annotations
import sqlite3
import time
from pathlib import Path
from typing import Callable

def open_db(path: Path | str, *, db_label: str, busy_timeout_ms: int=5000, wal: bool=True, foreign_keys: bool=False, synchronous_full: bool=False, row_factory=sqlite3.Row, check_same_thread: bool=True, wal_lock_retries: int=1, initialize: Callable[[sqlite3.Connection], None] | None=None) -> sqlite3.Connection:
    """Open ``path`` (parent created), apply the PRAGMA set, run ``initialize``; closed if anything raises.

    ``busy_timeout_ms`` is the single busy knob: it is passed as ``connect(timeout=)`` AND set as the
    explicit PRAGMA so it is observable. ``wal=True`` goes through ``apply_wal_with_fallback`` — the
    only journal-mode setter that carries the WAL-reset-bug gate, the network-FS silent-refusal
    fallback and the never-live-downgrade invariant; a raw ``PRAGMA journal_mode=WAL`` bypasses all
    three. Only the transient ``database is locked`` from that pragma is retried (``wal_lock_retries``):
    a first opener initializing a shared DB can make it ignore the busy timeout, notably on Windows.
    """
    from hivemind_assembly.automation.state_engine.hermes_state_wal import apply_wal_with_fallback
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=busy_timeout_ms / 1000, check_same_thread=check_same_thread)
    try:
        conn.row_factory = row_factory
        conn.execute(f'PRAGMA busy_timeout={int(busy_timeout_ms)}')
        if wal:
            for attempt in range(wal_lock_retries):
                try:
                    apply_wal_with_fallback(conn, db_label=db_label)
                    break
                except sqlite3.OperationalError as exc:
                    if str(exc).lower() != 'database is locked' or attempt + 1 == wal_lock_retries:
                        raise
                    time.sleep(0.01 * 2 ** attempt)
        if foreign_keys:
            conn.execute('PRAGMA foreign_keys=ON')
        if synchronous_full:
            conn.execute('PRAGMA synchronous=FULL')
        if initialize is not None:
            initialize(conn)
    except BaseException:
        conn.close()
        raise
    return conn

def add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> bool:
    """``ALTER TABLE <table> ADD COLUMN <ddl>``, idempotent across races: True when this call added
    it, False on the ``duplicate column name`` a concurrent migrator caused.

    ``column`` is the human-readable name for the call site; ``ddl`` carries the actual definition. See
    #21708.
    """
    try:
        conn.execute(f'ALTER TABLE {table} ADD COLUMN {ddl}')
        return True
    except sqlite3.OperationalError as exc:
        if 'duplicate column name' in str(exc).lower():
            return False
        raise
