# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
from __future__ import annotations
from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterator, Mapping, Optional
ARCHIVED = 'archived'

@dataclass(frozen=True)
class Column:
    """One board column. ``key`` is stable (stored in ``tasks.status``); ``label`` is display-only."""
    key: str
    label: str
    icon: str = '?'
    drag_target: bool = True

@dataclass(frozen=True)
class Workflow:
    """Columns (board order) and the manual move allow-list."""
    columns: tuple[Column, ...]
    manual: Mapping[str, frozenset[str]]

    def __iter__(self) -> Iterator[Column]:
        return iter(self.columns)

    def keys(self) -> tuple[str, ...]:
        """Column keys in board order (never includes ``archived``)."""
        return tuple((c.key for c in self.columns))

    def column(self, key: str) -> Optional[Column]:
        return next((c for c in self.columns if c.key == key), None)

    def _require(self, key: str) -> Column:
        col = self.column(key)
        if col is None:
            raise ValueError(f'unknown kanban workflow column {key!r}')
        return col

    def can_move(self, src: str, dst: str) -> bool:
        """True when a human may request ``src -> dst``. Archiving is always allowed;
        ``archived`` is a valid source (restore). ``src == dst`` is not a move."""
        if src != ARCHIVED:
            self._require(src)
        if src == dst:
            return False
        if dst == ARCHIVED:
            return True
        self._require(dst)
        return dst in self.manual.get(src, frozenset())

    def to_dict(self) -> dict:
        """JSON shape served by the dashboard's ``GET /workflow``. ``manual`` keys are the
        column keys plus ``archived`` (restore source), which is never a column."""
        return {'columns': [{'key': c.key, 'label': c.label, 'icon': c.icon, 'drag_target': c.drag_target} for c in self.columns], 'manual': {src: sorted(dsts) for src, dsts in self.manual.items()}, 'archived': ARCHIVED}

    def validate(self) -> None:
        """Raise ``ValueError`` on an inconsistent workflow (duplicate or unknown keys)."""
        keys = self.keys()
        if len(set(keys)) != len(keys):
            raise ValueError(f'duplicate column keys: {keys}')
        if ARCHIVED in keys:
            raise ValueError(f'{ARCHIVED!r} is reserved and cannot be a column')
        known = set(keys)
        for src, dsts in self.manual.items():
            if src not in known | {ARCHIVED} or not set(dsts) <= known:
                raise ValueError(f'manual moves from {src!r} reference unknown columns')

def _frozen_manual(table: Mapping[str, tuple[str, ...]]) -> Mapping[str, frozenset[str]]:
    return MappingProxyType({src: frozenset(dsts) for src, dsts in table.items()})
DEFAULT_WORKFLOW = Workflow(columns=(Column('triage', 'Triage', '◇'), Column('todo', 'Todo', '◻'), Column('scheduled', 'Scheduled', '⏱', drag_target=False), Column('ready', 'Ready', '▶'), Column('running', 'Running', '●', drag_target=False), Column('blocked', 'Blocked', '⊘'), Column('review', 'Review', '◎', drag_target=False), Column('done', 'Done', '✓')), manual=_frozen_manual({'triage': ('todo', 'ready'), 'todo': ('triage', 'scheduled', 'ready'), 'scheduled': ('triage', 'todo', 'ready'), 'ready': ('triage', 'todo', 'scheduled', 'blocked', 'review', 'done'), 'running': ('triage', 'todo', 'scheduled', 'ready', 'blocked', 'review', 'done'), 'blocked': ('triage', 'todo', 'scheduled', 'ready', 'done'), 'review': ('triage', 'todo', 'ready', 'done'), 'done': ('triage', 'todo', 'ready'), ARCHIVED: ('triage', 'todo', 'ready')}))
DEFAULT_STATUSES = frozenset(DEFAULT_WORKFLOW.keys()) | {ARCHIVED}
