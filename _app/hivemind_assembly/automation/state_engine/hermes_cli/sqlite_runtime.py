# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
from __future__ import annotations
from typing import Iterable

def _version_tuple(parts: Iterable[object]) -> tuple[int, int, int]:
    values = [int(part) for part in parts]
    values.extend([0] * (3 - len(values)))
    return tuple(values[:3])

def is_sqlite_wal_reset_vulnerable(version_info: tuple[int, ...]) -> bool:
    """Return whether *version_info* contains SQLite's WAL-reset bug."""
    info = _version_tuple(version_info)
    return not (info < (3, 7, 0) or info >= (3, 51, 3) or (3, 50, 7) <= info < (3, 51, 0) or ((3, 44, 6) <= info < (3, 45, 0)))
