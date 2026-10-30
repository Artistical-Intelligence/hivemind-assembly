# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
from __future__ import annotations
import contextlib
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from hivemind_assembly.automation.state_engine.hermes_cli.sqlite_util import add_column_if_missing as _add_column_if_missing, open_db
from hivemind_assembly.automation.state_engine.hermes_constants import get_hermes_home

def projects_db_path() -> Path:
    """The per-profile projects DB path (``$HERMES_HOME/projects.db``)."""
    return get_hermes_home() / 'projects.db'
SCHEMA_SQL = '\nCREATE TABLE IF NOT EXISTS projects (\n    id            TEXT PRIMARY KEY,\n    slug          TEXT NOT NULL UNIQUE,\n    name          TEXT NOT NULL,\n    description   TEXT,\n    icon          TEXT,\n    color         TEXT,\n    board_slug    TEXT,\n    primary_path  TEXT,\n    created_at    INTEGER NOT NULL,\n    archived      INTEGER NOT NULL DEFAULT 0\n);\n\nCREATE TABLE IF NOT EXISTS project_folders (\n    project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,\n    path        TEXT NOT NULL,\n    label       TEXT,\n    is_primary  INTEGER NOT NULL DEFAULT 0,\n    added_at    INTEGER NOT NULL,\n    PRIMARY KEY (project_id, path)\n);\n\nCREATE INDEX IF NOT EXISTS idx_project_folders_path\n    ON project_folders(path);\n\nCREATE TABLE IF NOT EXISTS project_meta (\n    key    TEXT PRIMARY KEY,\n    value  TEXT\n);\n\n-- Git repos found by scanning the filesystem (desktop "repo-first" discovery).\n-- Cached here so the overview is instant after the first scan instead of\n-- re-walking the disk every time the Projects view opens.\nCREATE TABLE IF NOT EXISTS discovered_repos (\n    root          TEXT PRIMARY KEY,\n    label         TEXT,\n    last_seen     INTEGER NOT NULL\n);\n'
_SLUG_RE = re.compile('^[a-z0-9][a-z0-9\\-_]{0,63}$')
_BRANCH_SAFE_RE = re.compile('[^a-z0-9._-]+')
_INITIALIZED_PATHS: set[str] = set()
_OPTIONAL_PROJECT_COLUMNS = ('board_slug', 'primary_path', 'icon', 'color')
_OPTIONAL_ROW_FIELDS = ('description', 'icon', 'color', 'board_slug', 'primary_path')

def _slugify(name: str) -> str:
    """Derive a slug candidate from a human name (best-effort)."""
    s = re.sub('[^a-z0-9]+', '-', str(name or '').strip().lower()).strip('-_')
    return s[:64].strip('-_') or 'project'

def normalize_slug(slug: Optional[str]) -> Optional[str]:
    """Lowercase + strip a slug; validate; return ``None`` for empty."""
    s = str(slug).strip().lower() if slug is not None else ''
    if not s:
        return None
    if not _SLUG_RE.match(s):
        raise ValueError(f"invalid project slug {slug!r}: must be 1-64 chars, lowercase alphanumerics / hyphens / underscores, not starting with '-' or '_'")
    return s

def connect(db_path: Optional[Path]=None) -> sqlite3.Connection:
    """Open (and initialize if needed) the per-profile projects DB.

    WAL with DELETE fallback for network filesystems (``hermes_state`` helper). Schema init is
    idempotent (``CREATE TABLE IF NOT EXISTS`` + additive migrations) and cached per-path per-process.
    """
    path = db_path if db_path is not None else projects_db_path()
    resolved = str(path.resolve())

    def _initialize(conn: sqlite3.Connection) -> None:
        if resolved in _INITIALIZED_PATHS:
            return
        conn.executescript(SCHEMA_SQL)
        cols = {row['name'] for row in conn.execute('PRAGMA table_info(projects)')}
        for col in _OPTIONAL_PROJECT_COLUMNS:
            if col not in cols:
                _add_column_if_missing(conn, 'projects', col, f'{col} TEXT')
        _INITIALIZED_PATHS.add(resolved)
    return open_db(path, db_label='projects.db', foreign_keys=True, initialize=_initialize)

@contextlib.contextmanager
def connect_closing(db_path: Optional[Path]=None):
    """Open a projects DB connection and close it on exit (sqlite3's own context manager only
    commits/rollbacks, so long-lived gateway/dashboard processes would leak fds otherwise)."""
    conn = connect(db_path=db_path)
    try:
        yield conn
    finally:
        with contextlib.suppress(Exception):
            conn.close()

@dataclass
class ProjectFolder:
    path: str
    label: Optional[str] = None
    is_primary: bool = False
    added_at: int = 0

    def to_dict(self) -> dict:
        return {'path': self.path, 'label': self.label, 'is_primary': bool(self.is_primary), 'added_at': self.added_at}

@dataclass
class Project:
    id: str
    slug: str
    name: str
    created_at: int
    description: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    board_slug: Optional[str] = None
    primary_path: Optional[str] = None
    archived: bool = False
    folders: list[ProjectFolder] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {k: getattr(self, k) for k in ('id', 'slug', 'name', *_OPTIONAL_ROW_FIELDS)}
        return {**d, 'archived': bool(self.archived), 'created_at': self.created_at, 'folders': [f.to_dict() for f in self.folders]}

def _load_project(conn: sqlite3.Connection, row: sqlite3.Row) -> Project:
    """Materialize a ``projects`` row together with its folders."""
    keys = row.keys()
    folders = conn.execute('SELECT path, label, is_primary, added_at FROM project_folders WHERE project_id = ? ORDER BY is_primary DESC, added_at ASC', (row['id'],)).fetchall()
    return Project(id=row['id'], slug=row['slug'], name=row['name'], created_at=row['created_at'], archived=bool(row['archived']) if 'archived' in keys else False, folders=[ProjectFolder(r['path'], r['label'], bool(r['is_primary']), r['added_at']) for r in folders], **{f: row[f] for f in _OPTIONAL_ROW_FIELDS if f in keys})

def get_project(conn: sqlite3.Connection, id_or_slug: str) -> Optional[Project]:
    """Look up a project by id first, then by slug."""
    row = conn.execute('SELECT * FROM projects WHERE id = ?', (id_or_slug,)).fetchone() or conn.execute('SELECT * FROM projects WHERE slug = ?', (str(id_or_slug).lower(),)).fetchone()
    return None if row is None else _load_project(conn, row)

def branch_name_for(project: Project, task_id: str, *, title: str='') -> str:
    """Deterministic ``<project-slug>/<task-id>[-<title-slug>]`` branch name for a project-linked kanban
    task (stable and human-meaningful, replacing the random ``wt/<task-id>`` fallback)."""
    base = f'{project.slug or _slugify(project.name)}/{task_id}'
    tslug = _BRANCH_SAFE_RE.sub('-', str(title).strip().lower()).strip('-')[:40].strip('-') if title else ''
    return f'{base}-{tslug}' if tslug else base
