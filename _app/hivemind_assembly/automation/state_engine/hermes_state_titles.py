# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
from __future__ import annotations
import re
from typing import Optional
from hivemind_assembly.automation.state_engine.hermes_state_common import escape_like as _escape_like
_NUMBERED_TITLE_RE = re.compile('^(.*?) #(\\d+)$')

def next_title_in_lineage(conn, base_title: str) -> str:
    """Next title in a lineage ("my session" -> "my session #2") as seen by *conn*: strip any
    " #N" suffix, then increment the highest existing number."""
    match = _NUMBERED_TITLE_RE.match(base_title)
    base = match.group(1) if match else base_title
    rows = conn.execute("SELECT title FROM sessions WHERE title = ? OR title LIKE ? ESCAPE '\\'", (base, f'{_escape_like(base)} #%')).fetchall()
    if not rows:
        return base
    numbers = [int(m.group(2)) for m in (_NUMBERED_TITLE_RE.match(row[0]) for row in rows) if m]
    return f'{base} #{max([1, *numbers]) + 1}'

class SessionTitlesMixin:
    """Sanitizing, ranking auto/user titles, lineage-aware lookups."""

    @classmethod
    def _title_rank(cls, source: Optional[str]) -> int:
        """Rank a stored title_source. NULL (pre-provenance rows) is indistinguishable from a
        manual ``/title`` of that era, so it ranks as ``user``."""
        rank = cls._TITLE_SOURCE_RANK
        return rank[cls.TITLE_SOURCE_USER] if source is None else rank.get(str(source), 0)
