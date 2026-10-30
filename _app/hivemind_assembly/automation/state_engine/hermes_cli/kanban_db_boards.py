# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
from __future__ import annotations
import json
from typing import Any
from typing import Optional
from pathlib import Path

def _dir_holds_board(d: Path) -> bool:
    return (d / 'board.json').exists()

def board_metadata_path(board: Optional[str]=None) -> Path:
    """``board.json`` path — display metadata only; the directory slug is the identity."""
    return _kb.board_dir(_kb._slug_or_default(board)) / 'board.json'

def _default_board_display_name(slug: str) -> str:
    """``atm10-server`` -> ``Atm10 Server``."""
    return ' '.join((part.capitalize() for part in slug.replace('_', '-').split('-') if part)) or slug

def read_board_metadata(board: Optional[str]=None) -> dict:
    """``board.json`` merged over defaults, plus ``slug`` and ``db_path``. Never
    raises — a missing/malformed file yields the synthesized entry."""
    slug = _kb._slug_or_default(board)
    meta: dict[str, Any] = {'slug': slug, 'name': _default_board_display_name(slug), 'description': '', 'icon': '', 'color': '', 'default_workdir': None, 'project_id': None, 'created_at': None, 'archived': False}
    try:
        p = board_metadata_path(slug)
        if p.exists():
            raw = json.loads(p.read_text(encoding='utf-8-sig'))
            if isinstance(raw, dict):
                raw['slug'] = slug
                meta.update(raw)
    except (OSError, json.JSONDecodeError):
        pass
    meta['db_path'] = str(_kb.kanban_db_path(slug))
    return meta
from hivemind_assembly.automation.state_engine.hermes_cli import kanban_db as _kb
