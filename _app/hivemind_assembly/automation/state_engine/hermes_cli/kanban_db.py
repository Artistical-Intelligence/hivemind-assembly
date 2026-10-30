# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
from __future__ import annotations
import contextlib
import json
import os
import re
import secrets
import sqlite3
import subprocess
import sys
import logging
import time
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional
from hivemind_assembly.automation.state_engine.hermes_cli.kanban_workflow import DEFAULT_STATUSES as VALID_STATUSES
from hivemind_assembly.automation.state_engine.toolsets import get_toolset_names
_log = logging.getLogger(__name__)

def _lossy_text(value: Any) -> Any:
    """``bytes`` -> ``str`` with U+FFFD for undecodable sequences; anything else passes through.

    Installed as every board connection's ``text_factory`` (a TEXT cell holding
    invalid UTF-8 otherwise aborts the whole ``fetchall`` with "Could not decode
    to UTF-8") and applied to BLOB-typed cells in the ``from_row`` constructors
    (task, comment, event, run), so one
    corrupt row degrades to replacement characters instead of taking the board
    listing down."""
    if isinstance(value, bytes):
        return value.decode('utf-8', errors='replace')
    return value

def _row_get(row: Any, col: str, default: Any=None) -> Any:
    """``row[col]`` tolerant of the column being absent from the SELECT / schema."""
    if row is None or col not in row.keys():
        return default
    return row[col]

def _json_or(value: Any, default: Any=None) -> Any:
    """Decode a JSON text column; any decode failure or empty value yields ``default``."""
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default

def _json_dict(value: Any) -> dict:
    """Decode a JSON text column that must be an object; anything else yields ``{}``."""
    parsed = _json_or(value, {})
    return parsed if isinstance(parsed, dict) else {}

def _env_int(name: str, default: int, *, minimum: int=0) -> int:
    """Integer env override: absent/empty/non-integer/below ``minimum`` falls back to ``default``."""
    raw = os.environ.get(name, '').strip()
    if raw:
        try:
            parsed = int(raw)
        except ValueError:
            return default
        if parsed >= minimum:
            return parsed
    return default

def _git_out(cwd: Path, *args: str, timeout: int=30) -> Optional[str]:
    """Run ``git -C cwd args`` and return stripped stdout, or ``None`` on any failure / empty output."""
    try:
        result = subprocess.run(['git', '-C', str(cwd), *args], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout, check=False)
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return (result.stdout or '').strip() or None
VALID_INITIAL_STATUSES = {'running', 'blocked'}
VALID_BLOCK_KINDS = {'dependency', 'needs_input', 'capability', 'transient'}
BLOCK_RECURRENCE_LIMIT = 2
VALID_WORKSPACE_KINDS = {'scratch', 'worktree', 'dir'}

def normalize_reasoning_effort(effort: Optional[str]) -> Optional[str]:
    """``VALID_REASONING_EFFORTS`` or ``"none"`` (thinking off), case-insensitive;
    empty/None = inherit the profile's own effort (NULL). Anything else raises —
    a typo'd level must not quietly hand the task back to the profile default."""
    from hivemind_assembly.automation.state_engine.hermes_constants import VALID_REASONING_EFFORTS
    value = str(effort or '').strip().lower()
    if not value:
        return None
    if value == 'none' or value in VALID_REASONING_EFFORTS:
        return value
    allowed = ', '.join(('none', *VALID_REASONING_EFFORTS))
    raise ValueError(f'reasoning_effort must be one of {allowed}, got {effort!r}')
KNOWN_TOOLSET_NAMES = frozenset((name.casefold() for name in get_toolset_names()))
_IS_WINDOWS = sys.platform == 'win32'
KANBAN_ATTACHMENT_MAX_BYTES = 25 * 1024 * 1024

def _assert_not_delegated_child_mutation(path: str | Path | None=None) -> None:
    """Reject Kanban mutations from ``delegate_task`` child contexts.

    The tool/CLI fast-fail guards are UX, not a trust boundary (a child can shell
    out or import this module); the invariant lives here so every ``write_txn``
    user and board-metadata mutator fails closed before touching durable state.
    *path* is the board DB / metadata root being mutated; ``None`` means the
    lineage's own board (``kanban_home()``).
    """
    from hivemind_assembly.automation.state_engine.agent.delegation_context import kanban_path_is_fenced
    if kanban_path_is_fenced(kanban_home() if path is None else path):
        raise PermissionError('delegate_task child contexts cannot mutate Kanban tasks or boards')

def _fire_kanban_lifecycle_hook(event: str, task_id: str, **fields: Any) -> None:
    """Best-effort lifecycle hook. Call AFTER the write txn commits (plugins never
    run under the SQLite write lock, always see durable state); failures are
    swallowed so an observer can never break a transition."""
    try:
        from hivemind_assembly.automation.state_engine.hermes_cli.lifecycle import invoke_hook
        invoke_hook(event, task_id=task_id, profile_name=_hook_profile_name(), **fields)
    except Exception as exc:
        _log.debug('kanban lifecycle hook %s failed: %s', event, exc)

def _fire_task_hook(event: str, task: Optional[Task], task_id: str, run_id: Optional[int], **fields: Any) -> None:
    """Lifecycle hook for a task transition; ``assignee`` from the (possibly missing) row."""
    _fire_kanban_lifecycle_hook(event, task_id, board=get_current_board(), assignee=task.assignee if task else None, run_id=run_id, **fields)

def _hook_profile_name() -> str:
    """Active profile for hook payloads; ``"default"`` when it cannot be resolved."""
    from hivemind_assembly.automation.state_engine.hermes_cli.profiles import get_active_profile_name
    try:
        return get_active_profile_name()
    except Exception:
        return 'default'
DEFAULT_CLAIM_TTL_SECONDS = 15 * 60

def _resolve_claim_ttl_seconds(ttl_seconds: Optional[int]=None) -> int:
    """Explicit ``ttl_seconds`` > ``HERMES_KANBAN_CLAIM_TTL_SECONDS`` > default."""
    if ttl_seconds is not None:
        return max(1, int(ttl_seconds))
    return _env_int('HERMES_KANBAN_CLAIM_TTL_SECONDS', DEFAULT_CLAIM_TTL_SECONDS, minimum=1)
DEFAULT_BOARD = 'default'
_CURRENT_BOARD_OVERRIDE: ContextVar[str | None] = ContextVar('hermes_kanban_current_board_override', default=None)
_PIN_FIRST_BOARD_RESOLUTION: ContextVar[bool] = ContextVar('hermes_kanban_pin_first_board_resolution', default=False)
_BOARD_SLUG_RE = re.compile('^[a-z0-9][a-z0-9\\-_]{0,63}$')

def _normalize_board_slug(slug: Optional[str]) -> Optional[str]:
    """Lowercase + strip a slug; validate; return ``None`` for empty."""
    s = str(slug).strip().lower() if slug is not None else ''
    if not s:
        return None
    if not _BOARD_SLUG_RE.match(s):
        raise ValueError(f"invalid board slug {slug!r}: must be 1-64 chars, lowercase alphanumerics / hyphens / underscores, not starting with '-' or '_'")
    return s

def _slug_or_default(board: Optional[str]) -> str:
    return _normalize_board_slug(board) or DEFAULT_BOARD

def kanban_home() -> Path:
    """``HERMES_KANBAN_HOME`` else ``get_default_hermes_root()``. Shared across
    profiles BY DESIGN: resolving through the active profile's HERMES_HOME would
    fork the board per profile and break the dispatcher/worker handoff."""
    override = os.environ.get('HERMES_KANBAN_HOME', '').strip()
    if override:
        return Path(override).expanduser()
    from hivemind_assembly.automation.state_engine.hermes_constants import get_default_hermes_root
    return get_default_hermes_root()

def boards_root() -> Path:
    """``<root>/kanban/boards`` — parent of the *additional* named boards.
    ``default`` is deliberately not here (its DB stays at ``<root>/kanban.db``)."""
    return kanban_home() / 'kanban' / 'boards'

def current_board_path() -> Path:
    """``<root>/kanban/current`` — one-line slug written by ``boards switch``; absent = ``default``."""
    return kanban_home() / 'kanban' / 'current'

def get_current_board() -> str:
    """Active slug: context override -> ``HERMES_KANBAN_BOARD`` -> ``<root>/kanban/current``
    (only while that board exists) -> ``DEFAULT_BOARD``. A malformed/stale slug
    falls through — the dispatcher must never crash on a hand-edited file."""

    def _existing(candidate: str) -> Optional[str]:
        if not candidate:
            return None
        try:
            normed = _normalize_board_slug(candidate)
        except ValueError:
            return None
        if not (normed and board_exists(normed)):
            return None
        if read_board_metadata(normed).get('archived'):
            return None
        return normed
    for candidate in ((_CURRENT_BOARD_OVERRIDE.get() or '').strip(), os.environ.get('HERMES_KANBAN_BOARD', '').strip()):
        found = _existing(candidate)
        if found:
            return found
    try:
        f = current_board_path()
        if f.exists():
            val = f.read_text(encoding='utf-8-sig').strip()
            if val:
                try:
                    normed = _normalize_board_slug(val)
                    if normed and board_exists(normed):
                        return normed
                except ValueError:
                    pass
    except OSError:
        pass
    return DEFAULT_BOARD

def board_dir(board: Optional[str]=None) -> Path:
    """``<root>/kanban/boards/<slug>/``. For ``default`` this holds metadata
    only (board.json, workspaces/, logs/) — its DB stays at ``<root>/kanban.db``
    for back-compat (:func:`kanban_db_path`).
    """
    return boards_root() / _slug_or_default(board)

def board_exists(board: Optional[str]=None) -> bool:
    """Board has a ``board.json`` on disk; ``default`` always exists."""
    slug = _slug_or_default(board)
    if slug == DEFAULT_BOARD:
        return True
    return _dir_holds_board(board_dir(slug))

def _explicit_board_slug(board: Optional[str]) -> Optional[str]:
    """Explicit caller intent: a direct ``board=`` argument, else the scoped
    ``--board`` context (CLI ``hermes kanban --board``, dashboard plugin_api);
    ``None`` when the caller expressed neither."""
    if board is not None:
        return _normalize_board_slug(board)
    ctx = (_CURRENT_BOARD_OVERRIDE.get() or '').strip()
    if ctx:
        try:
            return _normalize_board_slug(ctx)
        except ValueError:
            return None
    return None

def _explicit_board_intent_pinned() -> bool:
    """Whether an explicit ``board=`` (or scoped ``--board``) must still resolve
    through the ``HERMES_KANBAN_DB``-style env pins instead of its own board dir.

    True for machine flows wrapped in :func:`pin_first_board_resolution` and
    for every execution the dispatcher fences: its own workers (they carry
    ``HERMES_KANBAN_TASK``) and delegated children / descendants (the
    ``HERMES_DELEGATED_CHILD_CONTEXT`` marker). The pins ARE the "workers
    physically cannot see other boards" isolation (5ec6baa), and
    ``agent.delegation_context.kanban_path_is_fenced`` checks the pinned path /
    fenced root — an explicit board that resolved elsewhere would also escape
    that fence."""
    if _PIN_FIRST_BOARD_RESOLUTION.get():
        return True
    from hivemind_assembly.automation.state_engine.agent.delegation_context import explicit_board_intent_is_pinned
    return explicit_board_intent_is_pinned()

def _board_path(env_var: Optional[str], board: Optional[str], default_parts: tuple[str, ...], leaf: str) -> Path:
    """Shared resolver. An explicit ``board=`` argument — or the scoped
    ``--board`` context (:func:`scoped_current_board`) — outranks the ``env_var``
    pin ONLY where no fence applies (see :func:`_explicit_board_intent_pinned`):
    user-facing cross-board intent (CLI ``--board``, a model tool's ``board=``)
    is honored, but machine flows that enumerate boards (gateway notifier /
    watcher / dispatcher ticks) and dispatched or delegated workers keep
    resolving through the pin. Without explicit intent the ``env_var`` override
    pins the file, else legacy ``<root>/<default_parts>`` for the ``default``
    board, else ``board_dir(slug)/leaf``."""
    pin = os.environ.get(env_var, '').strip() if env_var else ''
    slug = _explicit_board_slug(board)
    if pin and (slug is None or _explicit_board_intent_pinned()):
        return Path(pin).expanduser()
    if slug is None:
        slug = get_current_board()
    if slug == DEFAULT_BOARD:
        return kanban_home().joinpath(*default_parts)
    return board_dir(slug) / leaf

def kanban_db_path(board: Optional[str]=None) -> Path:
    """``kanban.db`` path: ``HERMES_KANBAN_DB`` pins it (injected into workers);
    ``default`` -> ``<root>/kanban.db`` (back-compat), else the board dir."""
    return _board_path('HERMES_KANBAN_DB', board, ('kanban.db',), 'kanban.db')

def attachments_root(board: Optional[str]=None) -> Path:
    """Per-board attachments root (``HERMES_KANBAN_ATTACHMENTS_ROOT`` wins). Workers
    read attachments by absolute path, so remote terminal backends must mount it."""
    return _board_path('HERMES_KANBAN_ATTACHMENTS_ROOT', board, ('kanban', 'attachments'), 'attachments')

def task_attachments_dir(task_id: str, board: Optional[str]=None) -> Path:
    """Return the per-task attachment directory ``<root>/<task_id>/``."""
    return attachments_root(board=board) / task_id

@dataclass
class Task:
    """In-memory view of a row from the ``tasks`` table."""
    id: str
    title: str
    body: Optional[str]
    assignee: Optional[str]
    status: str
    priority: int
    created_by: Optional[str]
    created_at: Optional[int]
    started_at: Optional[int]
    completed_at: Optional[int]
    workspace_kind: str
    workspace_path: Optional[str]
    claim_lock: Optional[str]
    claim_expires: Optional[int]
    tenant: Optional[str]
    branch_name: Optional[str] = None
    project_id: Optional[str] = None
    result: Optional[str] = None
    idempotency_key: Optional[str] = None
    consecutive_failures: int = 0
    worker_pid: Optional[int] = None
    last_failure_error: Optional[str] = None
    max_runtime_seconds: Optional[int] = None
    last_heartbeat_at: Optional[int] = None
    current_run_id: Optional[int] = None
    workflow_template_id: Optional[str] = None
    current_step_key: Optional[str] = None
    skills: Optional[list] = None
    model_override: Optional[str] = None
    provider_override: Optional[str] = None
    reasoning_effort: Optional[str] = None
    max_retries: Optional[int] = None
    goal_mode: bool = False
    goal_max_turns: Optional[int] = None
    session_id: Optional[str] = None
    block_kind: Optional[str] = None
    block_recurrences: int = 0
    completion_contract: Optional[str] = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Task:
        g = lambda col, default=None: _lossy_text(_row_get(row, col, default))
        parsed = _json_or(g('skills'))
        skills_value = [str(s) for s in parsed if s] if isinstance(parsed, list) else None
        return cls(**{col: _lossy_text(row[col]) for col in _TASK_REQUIRED_COLUMNS}, **{col: _to_epoch(g(col)) for col in _TASK_EPOCH_COLUMNS}, **{col: g(col) for col in _TASK_OPTIONAL_COLUMNS}, **{col: g(col) or None for col in _TASK_EMPTY_IS_NULL_COLUMNS}, consecutive_failures=g('consecutive_failures', g('spawn_failures', 0)), last_failure_error=g('last_failure_error', g('last_spawn_error')), skills=skills_value, goal_mode=bool(g('goal_mode')), block_recurrences=int(g('block_recurrences') or 0))
_TASK_REQUIRED_COLUMNS = ('id', 'title', 'body', 'assignee', 'status', 'priority', 'created_by', 'workspace_kind', 'workspace_path', 'claim_lock')
_TASK_EPOCH_COLUMNS = ('created_at', 'started_at', 'completed_at', 'claim_expires', 'last_heartbeat_at')
_TASK_OPTIONAL_COLUMNS = ('branch_name', 'project_id', 'tenant', 'result', 'idempotency_key', 'worker_pid', 'max_runtime_seconds', 'current_run_id', 'workflow_template_id', 'current_step_key', 'max_retries', 'session_id', 'completion_contract')
_TASK_EMPTY_IS_NULL_COLUMNS = ('model_override', 'provider_override', 'reasoning_effort', 'goal_max_turns', 'block_kind')
SCHEMA_SQL = '\nCREATE TABLE IF NOT EXISTS tasks (\n    id                   TEXT PRIMARY KEY,\n    title                TEXT NOT NULL,\n    body                 TEXT,\n    assignee             TEXT,\n    status               TEXT NOT NULL,\n    priority             INTEGER DEFAULT 0,\n    created_by           TEXT,\n    created_at           INTEGER NOT NULL,\n    started_at           INTEGER,\n    completed_at         INTEGER,\n    workspace_kind       TEXT NOT NULL DEFAULT \'scratch\',\n    workspace_path       TEXT,\n    branch_name          TEXT,\n    -- Optional link to a first-class Project (hermes_cli/projects_db). When set,\n    -- the task\'s worktree is anchored under the project\'s primary repo with a\n    -- deterministic branch name instead of a random wt/<task-id> fallback.\n    project_id           TEXT,\n    claim_lock           TEXT,\n    claim_expires        INTEGER,\n    tenant               TEXT,\n    result               TEXT,\n    idempotency_key      TEXT,\n    -- Unified consecutive-failure counter. Incremented on spawn\n    -- failure, timeout, or crash; reset only on successful completion.\n    -- The circuit breaker in _record_task_failure trips when this\n    -- exceeds DEFAULT_FAILURE_LIMIT consecutive non-successes.\n    consecutive_failures INTEGER NOT NULL DEFAULT 0,\n    worker_pid           INTEGER,\n    -- Restart-stable fingerprint of worker_pid ("<boot/instantiation epoch>|<start time>",\n    -- kanban_db_dispatch._process_fingerprint) recorded at spawn: liveness and kills require pid\n    -- AND fingerprint to agree, so a PID recycled after a reboot is never read as our worker or\n    -- signalled. NULL = legacy row (pre-fingerprint spawn); \'unverified\' = capture failed at\n    -- spawn (held while live, never signalled). Column keeps its INTEGER affinity for the\n    -- start-time-only integer values older rows carry.\n    worker_started_at    INTEGER,\n    -- Short excerpt of the most recent failure\'s error text.\n    last_failure_error   TEXT,\n    max_runtime_seconds  INTEGER,\n    last_heartbeat_at    INTEGER,\n    -- Pointer into task_runs for the currently-active run (NULL if no\n    -- run is in-flight). Denormalised for cheap reads.\n    current_run_id       INTEGER,\n    -- Forward-compat for v2 workflow routing. In v1 the kernel writes\n    -- these when the task is opted into a template but otherwise ignores\n    -- them; the dispatcher doesn\'t consult them for routing yet.\n    workflow_template_id TEXT,\n    current_step_key     TEXT,\n    -- Force-loaded skills for the worker on this task, stored as JSON.\n    -- Passed to the worker via `--skills`. NULL or empty array = no extras.\n    skills               TEXT,\n    -- Per-task model override. When set, the dispatcher passes -m <model>\n    -- to the worker, overriding the profile\'s default model. NULL = use\n    -- the profile default.\n    model_override       TEXT,\n    -- Provider the model override belongs to. When set (alongside\n    -- model_override), the dispatcher passes --provider <name> so the\n    -- worker resolves the model against the right backend instead of the\n    -- profile\'s configured provider. NULL = profile provider.\n    provider_override    TEXT,\n    -- Per-task reasoning effort for the worker (minimal|low|medium|high|\n    -- xhigh|max|ultra, or \'none\' for thinking off). When set, the dispatcher\n    -- passes --reasoning <level> so the worker runs at that depth regardless\n    -- of the profile\'s agent.reasoning_effort. NULL = profile setting.\n    reasoning_effort     TEXT,\n    -- Per-task override for the consecutive-failure circuit breaker.\n    -- The value is the failure count at which the breaker trips — e.g.\n    -- ``max_retries=1`` blocks on the first failure. NULL (the common\n    -- case) falls through to the dispatcher-level ``kanban.failure_limit``\n    -- config and then ``DEFAULT_FAILURE_LIMIT``.\n    max_retries          INTEGER,\n    -- When 1, the dispatched worker runs in a Ralph-style goal loop: an\n    -- auxiliary judge re-evaluates the worker\'s response against the\n    -- card title/body after each turn and feeds a continuation prompt\n    -- back into the SAME session until the judge agrees the work is done\n    -- or ``goal_max_turns`` is exhausted. NULL/0 = classic single-shot\n    -- worker (the default).\n    goal_mode            INTEGER NOT NULL DEFAULT 0,\n    -- Goal-loop turn budget for ``goal_mode`` workers. NULL = use the\n    -- goals-engine default.\n    goal_max_turns       INTEGER,\n    -- Originating chat/agent session id when the task was created from\n    -- inside an agent loop that propagated ``HERMES_SESSION_ID``. NULL\n    -- for tasks created from the CLI, dashboard, or any path that doesn\'t\n    -- set the env var, and for an id with no ``sessions`` row in this\n    -- profile\'s state.db (kanban_create verifies before stamping). Indexed\n    -- so per-session list queries stay cheap on larger boards.\n    session_id           TEXT,\n    -- Typed block reason set by ``block_task`` (one of VALID_BLOCK_KINDS, or\n    -- NULL for legacy/un-typed blocks). Drives routing: ``dependency`` never\n    -- sits in ``blocked`` (goes to ``todo`` for parent-gating); the others go\n    -- to ``blocked`` for a human. Preserved across unblock so a re-block for\n    -- the SAME kind can be recognised as a loop.\n    block_kind           TEXT,\n    -- Unblock-loop counter. Incremented each time a task is re-blocked for the\n    -- same truly-blocked reason after having been unblocked. When it reaches\n    -- BLOCK_RECURRENCE_LIMIT the task is routed to ``triage`` instead of\n    -- ``blocked`` so a cron can\'t spin it forever. Reset to 0 only on a\n    -- successful completion — NOT on unblock (resetting on unblock is exactly\n    -- the amnesia that let the loop run unbounded).\n    block_recurrences    INTEGER NOT NULL DEFAULT 0\n);\n\nCREATE TABLE IF NOT EXISTS task_links (\n    parent_id  TEXT NOT NULL,\n    child_id   TEXT NOT NULL,\n    PRIMARY KEY (parent_id, child_id)\n);\n\nCREATE TABLE IF NOT EXISTS task_comments (\n    id         INTEGER PRIMARY KEY AUTOINCREMENT,\n    task_id    TEXT NOT NULL,\n    author     TEXT NOT NULL,\n    body       TEXT NOT NULL,\n    created_at INTEGER NOT NULL\n);\n\nCREATE TABLE IF NOT EXISTS task_events (\n    id         INTEGER PRIMARY KEY AUTOINCREMENT,\n    task_id    TEXT NOT NULL,\n    run_id     INTEGER,\n    kind       TEXT NOT NULL,\n    payload    TEXT,\n    created_at INTEGER NOT NULL\n);\n\n-- Historical attempt record. Each time the dispatcher claims a task, a\n-- new row is created here; claim state, PID, heartbeat, runtime cap,\n-- and structured summary all live on the run, not the task. Multiple\n-- rows per task id when the task was retried after crash/timeout/block.\n-- v2 of the kanban schema will use ``step_key`` to drive per-stage\n-- workflow routing; in v1 the column is nullable and unused (kernel\n-- ignores it).\nCREATE TABLE IF NOT EXISTS task_runs (\n    id                  INTEGER PRIMARY KEY AUTOINCREMENT,\n    task_id             TEXT NOT NULL,\n    profile             TEXT,\n    step_key            TEXT,\n    status              TEXT NOT NULL,\n    -- status: running | done | blocked | crashed | timed_out | failed | released\n    claim_lock          TEXT,\n    claim_expires       INTEGER,\n    worker_pid          INTEGER,\n    -- Spawn-time start fingerprint of worker_pid (see tasks.worker_started_at). Retained with\n    -- worker_pid after the run ends so a worker that outlives its terminal transition can\n    -- still be found and reaped; NULL = legacy row, never signalled.\n    worker_started_at   INTEGER,\n    max_runtime_seconds INTEGER,\n    last_heartbeat_at   INTEGER,\n    started_at          INTEGER NOT NULL,\n    ended_at            INTEGER,\n    outcome             TEXT,\n    -- outcome: completed | blocked | crashed | timed_out | spawn_failed |\n    --          gave_up | reclaimed | (null while still running)\n    summary             TEXT,\n    metadata            TEXT,\n    error               TEXT\n);\n\n-- Files attached to a task (PDFs, images, source documents). The blob\n-- lives on disk under ``attachments_root(board)/<task_id>/<stored_name>``;\n-- this row carries metadata + the absolute ``stored_path`` so the\n-- dashboard can list/download and ``build_worker_context`` can surface\n-- the absolute path to the worker (which has full file-tool access). See\n-- #35338.\nCREATE TABLE IF NOT EXISTS task_attachments (\n    id           INTEGER PRIMARY KEY AUTOINCREMENT,\n    task_id      TEXT NOT NULL,\n    filename     TEXT NOT NULL,\n    stored_path  TEXT NOT NULL,\n    content_type TEXT,\n    size         INTEGER NOT NULL DEFAULT 0,\n    uploaded_by  TEXT,\n    created_at   INTEGER NOT NULL\n);\n\n-- Subscription from a gateway source (platform + chat + thread) to a\n-- task. The gateway\'s kanban-notifier watcher tails task_events and\n-- pushes ``completed`` / ``blocked`` / ``spawn_auto_blocked`` events to\n-- the original requester so human-in-the-loop workflows close the loop.\nCREATE TABLE IF NOT EXISTS kanban_notify_subs (\n    task_id       TEXT NOT NULL,\n    platform      TEXT NOT NULL,\n    chat_id       TEXT NOT NULL,\n    thread_id     TEXT NOT NULL DEFAULT \'\',\n    user_id       TEXT,\n    user_id_alt   TEXT,\n    chat_type     TEXT,\n    notifier_profile TEXT,\n    delivery_mode TEXT NOT NULL DEFAULT \'notify\',\n    delivery_metadata TEXT,\n    created_at    INTEGER NOT NULL,\n    last_event_id INTEGER NOT NULL DEFAULT 0,\n    last_ping_event_id INTEGER NOT NULL DEFAULT 0,\n    PRIMARY KEY (task_id, platform, chat_id, thread_id)\n);\n\nCREATE INDEX IF NOT EXISTS idx_tasks_status          ON tasks(status);\nCREATE INDEX IF NOT EXISTS idx_links_child           ON task_links(child_id);\nCREATE INDEX IF NOT EXISTS idx_links_parent          ON task_links(parent_id);\nCREATE INDEX IF NOT EXISTS idx_comments_task         ON task_comments(task_id, created_at);\nCREATE INDEX IF NOT EXISTS idx_events_task           ON task_events(task_id, created_at);\nCREATE INDEX IF NOT EXISTS idx_runs_task             ON task_runs(task_id, started_at);\nCREATE INDEX IF NOT EXISTS idx_runs_status           ON task_runs(status);\nCREATE INDEX IF NOT EXISTS idx_attachments_task      ON task_attachments(task_id, created_at);\nCREATE INDEX IF NOT EXISTS idx_notify_task           ON kanban_notify_subs(task_id);\n'

def _new_task_id() -> str:
    """``t_`` + 4 hex bytes (collision ~1e-3 at 100k tasks; 2 bytes would hit 50%
    by 10k). Idempotency belongs to ``idempotency_key``, not id uniqueness."""
    return 't_' + secrets.token_hex(4)

def _claimer_id() -> str:
    """Return a ``host:pid`` string that identifies this claimer."""
    import socket
    try:
        host = socket.gethostname() or 'unknown'
    except Exception:
        host = 'unknown'
    return f'{host}:{os.getpid()}'

def _validate_model_override(model: Optional[str], provider: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Strip both; a provider without a model is rejected (a bare ``--provider``
    would re-resolve the profile's model against another backend — exactly
    the mismatch the override exists to kill)."""
    model = (model or '').strip() or None
    provider = (provider or '').strip() or None
    if provider and (not model):
        raise ValueError('provider_override requires a model_override')
    return (model, provider)

def _canonical_assignee(assignee: Optional[str]) -> Optional[str]:
    """Lowercase-assignee normalization for Kanban rows (dashboard/CLI parity)."""
    if assignee is None:
        return None
    from hivemind_assembly.automation.state_engine.hermes_cli.profiles import normalize_profile_name
    return normalize_profile_name(assignee)

def _resolve_project_link(conn: sqlite3.Connection, project_id: Optional[str], project_source_task_id: Optional[str], workspace_kind: str, workspace_path: Optional[str]) -> tuple[Optional[str], Any, Optional[str], str]:
    """``(project_id, project_obj, project_repo, workspace_kind)`` for ``create_task``.

    A project-linked task is anchored to the project's primary repo as a
    worktree with a deterministic branch (slug + task id). Projects live in the
    creator's per-profile projects.db, but the stored repo path is absolute so
    the cross-profile dispatcher needs no projects.db access. ``project_repo``
    is set when the worktree path must still be derived from the new task id.
    """
    project_id = str(project_id).strip() or None if project_id is not None else None
    if not project_id:
        return (None, None, None, workspace_kind)
    from hivemind_assembly.automation.state_engine.hermes_cli import projects_db as _pdb
    project_repo: Optional[str] = None
    try:
        with _pdb.connect_closing() as _pconn:
            project_obj = _pdb.get_project(_pconn, project_id)
    except Exception:
        project_obj = None
    if project_obj is None and project_source_task_id:
        project_obj, project_repo = _project_from_source_task(conn, _pdb, project_id, str(project_source_task_id))
        if project_obj is not None and workspace_kind == 'scratch':
            workspace_kind = 'worktree'
    if project_obj is None:
        return (None, None, None, workspace_kind)
    if workspace_kind == 'scratch' and project_obj.primary_path:
        workspace_kind = 'worktree'
    if workspace_kind == 'worktree' and workspace_path is None and project_obj.primary_path:
        project_repo = str(project_obj.primary_path)
    return (project_obj.id, project_obj, project_repo, workspace_kind)

def _project_from_source_task(conn: sqlite3.Connection, _pdb: Any, project_id: str, source_task_id: str) -> tuple[Any, Optional[str]]:
    """Recover a Project (and its repo) from a canonical project-linked
    worktree task on this board. Worker profiles have their own projects.db
    while the Kanban DB is shared, so this carries the repo + branch
    convention forward without opening the creator's store and without
    reusing the source task's literal worktree path. ``(None, None)`` when
    the source task is not a ``<repo>/.worktrees/<id>`` project worktree."""
    source_task = get_task(conn, source_task_id)
    if not (source_task is not None and source_task.project_id == project_id and (source_task.workspace_kind == 'worktree') and source_task.workspace_path):
        return (None, None)
    source_path = Path(source_task.workspace_path)
    if not (source_path.is_absolute() and source_path.name == source_task.id and (source_path.parent.name == '.worktrees')):
        return (None, None)
    project_slug = None
    if source_task.branch_name:
        prefix, separator, leaf = source_task.branch_name.partition('/')
        if separator and (leaf == source_task.id or leaf.startswith(f'{source_task.id}-')):
            with contextlib.suppress(ValueError):
                project_slug = _pdb.normalize_slug(prefix)
    if project_slug is None:
        with contextlib.suppress(ValueError):
            project_slug = _pdb.normalize_slug(project_id)
    if not project_slug:
        return (None, None)
    project_repo = str(source_path.parent.parent)
    project_obj = _pdb.Project(id=project_id, slug=project_slug, name=project_slug, created_at=0, primary_path=project_repo)
    return (project_obj, project_repo)

def _normalize_task_skills(skills: Optional[Iterable[str]]) -> Optional[list[str]]:
    """Strip/dedupe a skills list. Commas are refused (a comma-joined string must
    not land in one argv slot); toolset names are rejected all at once because
    agents that confuse the two usually pass several."""
    if skills is None:
        return None
    cleaned: list[str] = []
    seen: set[str] = set()
    toolset_typos: list[str] = []
    for s in skills:
        if not s:
            continue
        name = str(s).strip()
        if not name:
            continue
        if ',' in name:
            raise ValueError(f'skill name cannot contain comma: {name!r} (pass a list of separate names instead of a comma-joined string)')
        if name.casefold() in KNOWN_TOOLSET_NAMES:
            toolset_typos.append(name)
            continue
        if name in seen:
            continue
        seen.add(name)
        cleaned.append(name)
    if toolset_typos:
        quoted = ', '.join((repr(n) for n in toolset_typos))
        noun = 'is a toolset name' if len(toolset_typos) == 1 else 'are toolset names'
        raise ValueError(f"{quoted} {noun}, not skill name(s). Put toolsets in the assignee profile's `toolsets:` config instead of per-task skills. Skills are named skill bundles (e.g. `blogwatcher`, `github-code-review`); toolsets are runtime capabilities (e.g. `web`, `browser`, `terminal`).")
    return cleaned

def create_task(conn: sqlite3.Connection, *, title: str, body: Optional[str]=None, assignee: Optional[str]=None, created_by: Optional[str]=None, workspace_kind: Optional[str]=None, workspace_path: Optional[str]=None, branch_name: Optional[str]=None, tenant: Optional[str]=None, priority: int=0, parents: Iterable[str]=(), triage: bool=False, idempotency_key: Optional[str]=None, max_runtime_seconds: Optional[int]=None, skills: Optional[Iterable[str]]=None, max_retries: Optional[int]=None, model_override: Optional[str]=None, provider_override: Optional[str]=None, reasoning_effort: Optional[str]=None, goal_mode: bool=False, goal_max_turns: Optional[int]=None, initial_status: str='running', session_id: Optional[str]=None, board: Optional[str]=None, project_id: Optional[str]=None, project_source_task_id: Optional[str]=None, creator_task_id: Optional[str]=None, completion_contract: Optional[str]=None) -> str:
    """Create a task (optionally under ``parents``); returns its id.

    Status: ``ready`` unless a parent is not ``done`` (``todo``); ``triage=True``
    forces ``triage``; ``initial_status="blocked"`` parks it for human ops.
    ``idempotency_key``: an existing non-archived task with the key is returned
    instead of a duplicate. ``max_runtime_seconds``: cap before the dispatcher
    SIGTERMs and re-queues. ``model_override``/``provider_override`` pin the
    worker model (provider requires model); ``reasoning_effort`` is independent.
    ``creator_task_id``: inherit durable session/subscriptions independently of
    dependency edges; an explicit ``session_id`` still wins.
    ``project_source_task_id``: cross-profile fallback when ``project_id`` is not
    in the active profile's projects.db — see ``_resolve_project_link``.
    ``workspace_kind=None`` (omitted) inherits a project-scoped board's project;
    an explicit ``"scratch"`` or ``project_id=""`` is a request for no project.
    """
    from hivemind_assembly.automation.state_engine.hermes_cli.kanban_db_graph import initial_task_state, inherit_creator_origin
    from hivemind_assembly.automation.state_engine.hermes_cli.kanban_pr_acceptance import validate_contract
    completion_contract = validate_contract(completion_contract)
    model_override, provider_override = _validate_model_override(model_override, provider_override)
    reasoning_effort = normalize_reasoning_effort(reasoning_effort)
    assignee = _canonical_assignee(assignee)
    if not title or not title.strip():
        raise ValueError('title is required')
    if initial_status not in VALID_INITIAL_STATUSES:
        raise ValueError(f'initial_status must be one of {sorted(VALID_INITIAL_STATUSES)}')
    if project_id is None and workspace_kind != 'scratch':
        try:
            project_id = (_board_meta_for(board).get('project_id') or '').strip() or None
        except Exception:
            pass
    if workspace_kind is None:
        workspace_kind = 'scratch'
    if workspace_kind not in VALID_WORKSPACE_KINDS:
        raise ValueError(f'workspace_kind must be one of {sorted(VALID_WORKSPACE_KINDS)}, got {workspace_kind!r}')
    if branch_name is not None:
        branch_name = str(branch_name).strip() or None
    if branch_name and workspace_kind != 'worktree':
        raise ValueError('branch_name is only valid for worktree workspaces')
    project_id, project_obj, project_repo, workspace_kind = _resolve_project_link(conn, project_id, project_source_task_id, workspace_kind, workspace_path)
    parents = tuple((p for p in parents if p))
    skills_list = _normalize_task_skills(skills)
    if idempotency_key:
        row = conn.execute("SELECT id FROM tasks WHERE idempotency_key = ? AND status != 'archived' ORDER BY created_at DESC LIMIT 1", (idempotency_key,)).fetchone()
        if row:
            return row['id']
    now = int(time.time())
    if workspace_path is None and project_repo is None and (workspace_kind in {'dir', 'worktree'}):
        board_default = _board_meta_for(board).get('default_workdir')
        if board_default:
            workspace_path = str(board_default)
    for attempt in range(2):
        task_id = _new_task_id()
        try:
            with write_txn(conn, allow_nested=True):
                task_status, tenant = initial_task_state(conn, parents, initial_status, triage, tenant)
                if project_obj is not None and workspace_kind == 'worktree':
                    if project_repo and (not workspace_path):
                        workspace_path = os.path.join(project_repo, '.worktrees', task_id)
                    if not branch_name:
                        branch_name = _project_branch_name(project_obj, task_id, title)
                conn.execute('\n                    INSERT INTO tasks (\n                        id, title, body, assignee, status, priority,\n                        created_by, created_at, workspace_kind, workspace_path,\n                        branch_name, project_id, tenant, idempotency_key,\n                        max_runtime_seconds,\n                        skills, max_retries, model_override, provider_override,\n                        reasoning_effort,\n                        goal_mode, goal_max_turns, session_id, completion_contract\n                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)\n                    ', (task_id, title.strip(), body, assignee, task_status, priority, created_by, now, workspace_kind, workspace_path, branch_name, project_id, tenant, idempotency_key, _opt_int(max_runtime_seconds), json.dumps(skills_list) if skills_list is not None else None, _opt_int(max_retries), model_override, provider_override, reasoning_effort, 1 if goal_mode else 0, _opt_int(goal_max_turns), session_id, completion_contract))
                for pid in parents:
                    _link(conn, pid, task_id)
                _append_event(conn, task_id, 'created', {'assignee': assignee, 'status': task_status, 'parents': list(parents), 'creator_task_id': creator_task_id, 'tenant': tenant, 'workspace_kind': workspace_kind, 'workspace_path': workspace_path, 'branch_name': branch_name, 'project_id': project_id, 'skills': list(skills_list) if skills_list else None, 'goal_mode': bool(goal_mode) or None, 'model_override': model_override, 'provider_override': provider_override})
                if task_status == 'blocked':
                    _append_event(conn, task_id, 'blocked', {'reason': 'initial_status', 'status': 'blocked', 'actor': created_by or 'user'})
                if task_status == 'todo':
                    gating = [p for p in parents if _task_status(conn, p) not in ('done', 'archived')]
                    if gating:
                        _append_event(conn, task_id, 'dependency_wait', {'reason': 'parent_not_done', 'parent': gating[0]})
                inherit_creator_origin(conn, task_id, creator_task_id, created_at=now)
                _inherit_notify_subs(conn, task_id, parents, created_at=now)
            return task_id
        except sqlite3.IntegrityError:
            if attempt == 1:
                raise
    raise RuntimeError('unreachable')

def _board_meta_for(board: Optional[str]) -> dict:
    return read_board_metadata(board if board else get_current_board())

def _project_branch_name(project_obj: Any, task_id: str, title: Optional[str]) -> Optional[str]:
    from hivemind_assembly.automation.state_engine.hermes_cli import projects_db as _pdb
    try:
        return _pdb.branch_name_for(project_obj, task_id, title=title or '')
    except Exception:
        return None

def _link(conn: sqlite3.Connection, parent_id: str, child_id: str) -> None:
    conn.execute('INSERT OR IGNORE INTO task_links (parent_id, child_id) VALUES (?, ?)', (parent_id, child_id))

def _missing_task_ids(conn: sqlite3.Connection, ids: Iterable[str]) -> list[str]:
    """Subset of ``ids`` (order kept) with no ``tasks`` row."""
    ids = list(ids)
    if not ids:
        return []
    placeholders = ','.join('?' * len(ids))
    rows = conn.execute(f'SELECT id FROM tasks WHERE id IN ({placeholders})', ids).fetchall()
    present = {r['id'] for r in rows}
    return [p for p in ids if p not in present]

def _inherit_notify_subs(conn: sqlite3.Connection, child_id: str, parents: Iterable[str], *, created_at: Optional[int]=None) -> None:
    """Copy parents' notify subscriptions to a child, cursor caught up to the
    child's current event so a late ``link_tasks`` never replays history.

    Single owner of inheritance (create_task, link_tasks, decompose). It must
    copy EVERY routing/delivery column: dropping ``chat_type`` made DM-originated
    completions wake a fresh group session instead of the originating DM.

    Omitting columns here silently degrades routing: a DM-originated child completion falls back to
    chat_type='group' and wakes a fresh group-scoped session instead of the originating DM (issue #73030).
    """
    parent_ids = tuple(dict.fromkeys((p for p in parents if p)))
    if not parent_ids:
        return
    row = conn.execute('SELECT COALESCE(MAX(id), 0) AS cursor FROM task_events WHERE task_id = ?', (child_id,)).fetchone()
    cursor = int(row['cursor'] if row is not None else 0)
    placeholders = ','.join('?' * len(parent_ids))
    conn.execute(f"\n        INSERT OR IGNORE INTO kanban_notify_subs\n            (task_id, platform, chat_id, thread_id, user_id, user_id_alt,\n             chat_type, notifier_profile, delivery_mode, delivery_metadata,\n             created_at, last_event_id)\n        SELECT ?, platform, chat_id, thread_id, user_id, user_id_alt,\n               COALESCE(chat_type, 'dm'), notifier_profile,\n               COALESCE(delivery_mode, 'notify'), delivery_metadata, ?, ?\n          FROM kanban_notify_subs\n         WHERE task_id IN ({placeholders})\n        ", (child_id, int(created_at if created_at is not None else time.time()), cursor, *parent_ids))

def get_task(conn: sqlite3.Connection, task_id: str) -> Optional[Task]:
    row = conn.execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone()
    return Task.from_row(row) if row else None
VALID_SORT_ORDERS: dict[str, str] = {'created': 'created_at ASC, id ASC', 'created-desc': 'created_at DESC, id DESC', 'priority': 'priority DESC, created_at ASC', 'priority-desc': 'priority ASC, created_at ASC', 'status': 'status ASC, created_at ASC', 'assignee': 'assignee ASC, created_at ASC', 'title': 'title ASC, id ASC', 'updated': 'started_at DESC NULLS LAST, created_at DESC', 'completed-desc': 'completed_at DESC NULLS LAST, id DESC'}

def list_tasks(conn: sqlite3.Connection, *, assignee: Optional[str]=None, status: Optional[str]=None, tenant: Optional[str]=None, session_id: Optional[str]=None, include_archived: bool=False, limit: Optional[int]=None, order_by: Optional[str]=None, workflow_template_id: Optional[str]=None, current_step_key: Optional[str]=None) -> list[Task]:
    if status is not None and status not in VALID_STATUSES:
        raise ValueError(f'status must be one of {sorted(VALID_STATUSES)}')
    query = 'SELECT * FROM tasks WHERE 1=1'
    params: list[Any] = []
    for col, val in (('assignee', _canonical_assignee(assignee)), ('status', status), ('tenant', tenant), ('session_id', session_id), ('workflow_template_id', workflow_template_id), ('current_step_key', current_step_key)):
        if val is not None:
            query += f' AND {col} = ?'
            params.append(val)
    if not include_archived and status != 'archived':
        query += " AND status != 'archived'"
    if order_by is not None:
        order_by = order_by.strip().lower()
        if order_by not in VALID_SORT_ORDERS:
            raise ValueError(f'order_by must be one of {sorted(VALID_SORT_ORDERS.keys())}')
        query += f' ORDER BY {VALID_SORT_ORDERS[order_by]}'
    else:
        query += ' ORDER BY priority DESC, created_at ASC'
    if limit:
        query += f' LIMIT {int(limit)}'
    rows = conn.execute(query, params).fetchall()
    return [Task.from_row(r) for r in rows]

def link_tasks(conn: sqlite3.Connection, parent_id: str, child_id: str, *, expected_child_run_id: Optional[int]=None) -> bool:
    """Link ``parent_id -> child_id``. Returns True when the link gated a
    ``ready`` child back to ``todo`` (the new parent is not yet terminal), so
    callers can surface the demotion instead of a silent status flip.

    A running child cannot normally be gated retroactively, so reject the edge
    rather than record a dependency that did not constrain the active run. The
    owning worker may link its own active run for a subsequent dependency-block
    handoff by supplying its trusted ``expected_child_run_id``.
    """
    if parent_id == child_id:
        raise ValueError('a task cannot depend on itself')
    gated = False
    with write_txn(conn):
        missing = _missing_task_ids(conn, [parent_id, child_id])
        if missing:
            raise ValueError(f'unknown task(s): {', '.join(missing)}')
        child = conn.execute('SELECT status, current_run_id FROM tasks WHERE id = ?', (child_id,)).fetchone()
        if child['status'] == 'running' and (expected_child_run_id is None or child['current_run_id'] != expected_child_run_id):
            raise ValueError(f'cannot link {parent_id} -> {child_id}: child is already running')
        if _would_cycle(conn, parent_id, child_id):
            raise ValueError(f'linking {parent_id} -> {child_id} would create a cycle')
        _link(conn, parent_id, child_id)
        if _task_status(conn, parent_id) not in ('done', 'archived'):
            cur = conn.execute("UPDATE tasks SET status = 'todo' WHERE id = ? AND status = 'ready'", (child_id,))
            gated = cur.rowcount == 1
            if gated:
                _append_event(conn, child_id, 'dependency_wait', {'reason': 'parent_not_done', 'demoted': True, 'parent': parent_id})
        _append_event(conn, child_id, 'linked', {'parent': parent_id, 'child': child_id})
        _inherit_notify_subs(conn, child_id, (parent_id,))
    return gated

def _would_cycle(conn: sqlite3.Connection, parent_id: str, child_id: str) -> bool:
    """True iff ``parent_id`` is already a descendant of ``child_id``."""
    seen = set()
    stack = [child_id]
    while stack:
        node = stack.pop()
        if node == parent_id:
            return True
        if node in seen:
            continue
        seen.add(node)
        rows = conn.execute('SELECT child_id FROM task_links WHERE parent_id = ?', (node,)).fetchall()
        stack.extend((r['child_id'] for r in rows))
    return False

def _linked_ids(conn: sqlite3.Connection, want: str, where: str, task_id: str) -> list[str]:
    rows = conn.execute(f'SELECT {want} FROM task_links WHERE {where} = ? ORDER BY {want}', (task_id,)).fetchall()
    return [r[want] for r in rows]

def parent_ids(conn: sqlite3.Connection, task_id: str) -> list[str]:
    return _linked_ids(conn, 'parent_id', 'child_id', task_id)

def child_ids(conn: sqlite3.Connection, task_id: str) -> list[str]:
    return _linked_ids(conn, 'child_id', 'parent_id', task_id)

def _append_event(conn: sqlite3.Connection, task_id: str, kind: str, payload: Optional[dict]=None, *, run_id: Optional[int]=None) -> None:
    """Insert an event row inside the caller's txn; ``run_id`` groups it by attempt (NULL = task-scoped)."""
    conn.execute('INSERT INTO task_events (task_id, run_id, kind, payload, created_at) VALUES (?, ?, ?, ?, ?)', (task_id, run_id, kind, _json_or_null(payload), int(time.time())))

def _end_run(conn: sqlite3.Connection, task_id: str, *, outcome: str, summary: Optional[str]=None, error: Optional[str]=None, metadata: Optional[dict]=None, status: Optional[str]=None) -> Optional[int]:
    """Close the active run (``status`` defaults to ``outcome``) and clear
    ``current_run_id``; None when no run was active (never-claimed task).

    ``worker_pid`` / ``worker_started_at`` / ``claim_lock`` stay on the closed
    row: they are the only evidence left of the OS process once the task row
    is wiped, and :func:`kanban_db_dispatch.reap_terminal_workers` needs them
    to end a worker that survived its own terminal transition."""
    now = int(time.time())
    run_id = _current_run_id(conn, task_id)
    if run_id is None:
        return None
    conn.execute('\n        UPDATE task_runs\n           SET status        = ?,\n               outcome       = ?,\n               summary       = ?,\n               error         = ?,\n               metadata      = ?,\n               ended_at      = ?,\n               claim_expires = NULL\n         WHERE id = ?\n           AND ended_at IS NULL\n        ', (status or outcome, outcome, summary, error, _json_or_null(metadata), now, run_id))
    conn.execute('UPDATE tasks SET current_run_id = NULL WHERE id = ?', (task_id,))
    return run_id

def _first_line(text: Optional[str], limit: int) -> str:
    """First non-blank-stripped line of ``text`` capped at ``limit`` chars; "" when empty."""
    lines = (text or '').strip().splitlines()
    return lines[0][:limit] if lines else ''

def _opt_int(value: Any) -> Optional[int]:
    """``int(value)`` or ``None`` when ``value`` is ``None`` (NULL column passthrough)."""
    return int(value) if value is not None else None

def _json_or_null(obj: Any) -> Optional[str]:
    """JSON text for a payload/metadata column; falsy -> NULL."""
    return json.dumps(obj, ensure_ascii=False) if obj else None

def _task_status(conn: sqlite3.Connection, task_id: str) -> Optional[str]:
    """Current ``tasks.status`` for ``task_id``, or ``None`` when no such row."""
    row = conn.execute('SELECT status FROM tasks WHERE id = ?', (task_id,)).fetchone()
    return row['status'] if row else None

def _current_run_id(conn: sqlite3.Connection, task_id: str) -> Optional[int]:
    row = conn.execute('SELECT current_run_id FROM tasks WHERE id = ?', (task_id,)).fetchone()
    return int(row['current_run_id']) if row and row['current_run_id'] else None
_UNSET: Any = object()

def _end_or_synthesize_run(conn: sqlite3.Connection, task_id: str, *, outcome: str, status: str, summary: Optional[str]=None, metadata: Optional[dict]=None, synthesize: bool, profile: Any=_UNSET) -> Optional[int]:
    """:func:`_end_run`; when no run was active and ``synthesize`` holds, record a
    zero-duration run instead so the handoff fields survive in attempt history.
    ``profile`` overrides the profile read off the task row for the synthesized
    run — transitions that reassign the task (e.g. review handoff) pass the
    acting profile captured before the rewrite."""
    run_id = _end_run(conn, task_id, outcome=outcome, status=status, summary=summary, metadata=metadata)
    if run_id is None and synthesize:
        run_id = _synthesize_ended_run(conn, task_id, outcome=outcome, summary=summary, metadata=metadata, profile=profile)
    return run_id

def _synthesize_ended_run(conn: sqlite3.Connection, task_id: str, *, outcome: str, summary: Optional[str]=None, error: Optional[str]=None, metadata: Optional[dict]=None, profile: Any=_UNSET) -> int:
    """Zero-duration closed run for a terminal transition on a never-claimed
    task, so the handoff fields aren't silently dropped (``_end_run`` is a
    no-op then). ``started_at == ended_at`` keeps elapsed stats honest. Does
    NOT touch the tasks row.

    ``profile`` overrides the profile read off the task row: transitions that
    reassign the task (e.g. review handoff) pass the acting profile captured
    before the rewrite, so the run names the actor, not the new assignee."""
    now = int(time.time())
    trow = conn.execute('SELECT assignee, current_step_key FROM tasks WHERE id = ?', (task_id,)).fetchone()
    if profile is _UNSET:
        profile = trow['assignee'] if trow else None
    step_key = trow['current_step_key'] if trow else None
    cur = conn.execute('\n        INSERT INTO task_runs (\n            task_id, profile, step_key,\n            status, outcome,\n            summary, error, metadata,\n            started_at, ended_at\n        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)\n        ', (task_id, profile, step_key, outcome, outcome, summary, error, _json_or_null(metadata), now, now))
    return int(cur.lastrowid or 0)

def _has_sticky_block(conn: sqlite3.Connection, task_id: str) -> bool:
    """True when the newest ``blocked``/``unblocked``/``gave_up`` event says the
    block must wait for an operator: an explicit ``kanban_block`` (#28712), or a
    breaker trip ``_record_task_failure`` stamped ``sticky`` — the clean-exit
    protocol-violation budget or a systemic same-error wave. Those trip on a
    policy independent of ``consecutive_failures``, so ``recompute_ready``'s
    counter check cannot see them — without this the trip is promoted back to
    ``ready`` in the same tick and the card respawns forever. A plain
    (unified-budget) ``gave_up`` carries no marker and is judged by the counter,
    so raising ``failure_limit`` or ``assign_task`` to a fresh profile still
    releases it; a task with no such event at all (direct DB edit) auto-recovers.
    """
    row = conn.execute("SELECT kind FROM task_events WHERE task_id = ? AND kind IN ('blocked', 'unblocked') ORDER BY id DESC LIMIT 1", (task_id,)).fetchone()
    if row and row['kind'] == 'blocked':
        return True
    trip = conn.execute("SELECT payload FROM task_events WHERE task_id = ? AND kind = 'gave_up' AND id > COALESCE(  (SELECT MAX(id) FROM task_events WHERE task_id = ? AND kind = 'unblocked'), 0) ORDER BY id DESC LIMIT 1", (task_id, task_id)).fetchone()
    return bool(trip) and bool(_json_dict(trip['payload']).get('sticky'))

def _latest_event(conn: sqlite3.Connection, task_id: str, kind: str, run_id: Optional[int]=None) -> Optional[sqlite3.Row]:
    """Newest ``task_events`` row of ``kind`` (optionally scoped to one run)."""
    sql = 'SELECT payload FROM task_events WHERE task_id = ? AND kind = ?'
    params: tuple[Any, ...] = (task_id, kind)
    if run_id is not None:
        sql += ' AND run_id = ?'
        params = (*params, int(run_id))
    return conn.execute(sql + ' ORDER BY id DESC LIMIT 1', params).fetchone()

def _resume_status_from_events(conn: sqlite3.Connection, task_id: str) -> str:
    """``review`` when the newest lifecycle event carries a review
    ``resume_status``/``retry_status``/``source_status``, else ``ready`` (legacy)."""
    row = conn.execute("SELECT payload FROM task_events WHERE task_id = ? AND kind IN ('blocked', 'block_loop_detected', 'dependency_wait', 'gave_up', 'unblocked', 'changes_requested', 'review_reopened', 'status', 'reclaimed', 'stale', 'timed_out', 'crashed', 'spawn_failed', 'rate_limited') ORDER BY id DESC LIMIT 1", (task_id,)).fetchone()
    payload = _json_dict(_row_get(row, 'payload'))
    for key in ('resume_status', 'retry_status', 'source_status'):
        if payload.get(key) == 'review':
            return 'review'
    return 'ready'

def recompute_ready(conn: sqlite3.Connection, failure_limit: int | None=None) -> int:
    """Promote ``todo``/``blocked`` tasks whose parents are all done/archived;
    returns the count. Opens its own IMMEDIATE txn — call OUTSIDE any write txn.

    ``blocked`` is skipped when sticky (explicit ``kanban_block``) or when
    ``consecutive_failures`` reached the limit (else the breaker could never
    trip). Limit order matches ``_record_task_failure``: ``max_retries`` >
    ``failure_limit`` > ``DEFAULT_FAILURE_LIMIT``.

    1. The most recent block event was a worker-initiated ``kanban_block`` — those stay blocked until an
    explicit ``kanban_unblock`` (#28712).
    """
    if failure_limit is None:
        failure_limit = DEFAULT_FAILURE_LIMIT
    promoted = 0
    with write_txn(conn):
        todo_rows = conn.execute("SELECT id, status, consecutive_failures, max_retries FROM tasks WHERE status IN ('todo', 'blocked')").fetchall()
        for row in todo_rows:
            task_id = row['id']
            cur_status = row['status']
            if cur_status == 'blocked' and _has_sticky_block(conn, task_id):
                continue
            parents = conn.execute('SELECT t.status FROM tasks t JOIN task_links l ON l.parent_id = t.id WHERE l.child_id = ?', (task_id,)).fetchall()
            if all((p['status'] in ('done', 'archived') for p in parents)):
                resume_status = _resume_status_from_events(conn, task_id)
                if cur_status == 'blocked':
                    failures = int(row['consecutive_failures'] or 0)
                    task_limit = row['max_retries']
                    effective_limit = int(task_limit) if task_limit is not None else int(failure_limit)
                    if failures >= effective_limit:
                        continue
                    conn.execute("UPDATE tasks SET status = ? WHERE id = ? AND status = 'blocked'", (resume_status, task_id))
                else:
                    conn.execute("UPDATE tasks SET status = ? WHERE id = ? AND status = 'todo'", (resume_status, task_id))
                _append_event(conn, task_id, 'promoted', {'status': resume_status} if resume_status != 'ready' else None)
                promoted += 1
    return promoted

def _parents_satisfied(conn: sqlite3.Connection, task_id: str) -> bool:
    """Return whether every direct parent is terminal for dependency gating."""
    return conn.execute("SELECT 1 FROM task_links l JOIN tasks p ON p.id = l.parent_id WHERE l.child_id = ? AND p.status NOT IN ('done', 'archived') LIMIT 1", (task_id,)).fetchone() is None

def _claim_and_open_run(conn: sqlite3.Connection, task_id: str, source_status: str, lock: str, expires: int, now: int, *, event_extra: Optional[dict]=None) -> Optional[int]:
    """CAS ``source_status -> running``, open a run row, emit ``claimed``; None
    when the CAS lost. Caller holds the txn."""
    cur = conn.execute(f"\n        UPDATE tasks\n           SET status        = 'running',\n               claim_lock    = ?,\n               claim_expires = ?,\n               started_at    = COALESCE(started_at, ?)\n         WHERE id = ?\n           AND status = '{source_status}'\n           AND claim_lock IS NULL\n        ", (lock, expires, now, task_id))
    if cur.rowcount != 1:
        return None
    trow = conn.execute('SELECT assignee, max_runtime_seconds, current_step_key FROM tasks WHERE id = ?', (task_id,)).fetchone()
    run_cur = conn.execute("\n        INSERT INTO task_runs (\n            task_id, profile, step_key, status,\n            claim_lock, claim_expires, max_runtime_seconds,\n            started_at\n        ) VALUES (?, ?, ?, 'running', ?, ?, ?, ?)\n        ", (task_id, trow['assignee'] if trow else None, trow['current_step_key'] if trow else None, lock, expires, trow['max_runtime_seconds'] if trow else None, now))
    run_id = run_cur.lastrowid
    conn.execute('UPDATE tasks SET current_run_id = ? WHERE id = ?', (run_id, task_id))
    _append_event(conn, task_id, 'claimed', {'lock': lock, 'expires': expires, 'run_id': run_id, **(event_extra or {})}, run_id=run_id)
    return run_id

def claim_task(conn: sqlite3.Connection, task_id: str, *, ttl_seconds: Optional[int]=None, claimer: Optional[str]=None) -> Optional[Task]:
    """Atomically transition ``ready -> running``.

    Returns the claimed ``Task`` on success, ``None`` if the task was
    already claimed (or is not in ``ready`` status).
    """
    now = int(time.time())
    lock = claimer or _claimer_id()
    expires = now + _resolve_claim_ttl_seconds(ttl_seconds)
    with write_txn(conn):
        if not _parents_satisfied(conn, task_id):
            conn.execute("UPDATE tasks SET status = 'todo' WHERE id = ? AND status = 'ready'", (task_id,))
            _append_event(conn, task_id, 'claim_rejected', {'reason': 'parents_not_done'})
            return None
        _reclaim_dangling_run(conn, task_id, statuses=('ready',), now=now, note='invariant recovery on re-claim')
        run_id = _claim_and_open_run(conn, task_id, 'ready', lock, expires, now)
        if run_id is None:
            return None
        claimed = get_task(conn, task_id)
    _fire_task_hook('kanban_task_claimed', claimed, task_id, run_id)
    return claimed

def _retry_status_for_run(conn: sqlite3.Connection, task_id: str, run_id: Optional[int]=None) -> str:
    """``review`` when the run's ``claimed`` event says ``source_status=review``,
    else ``ready`` — one place, so crash/timeout/reclaim can't silently turn a
    reviewer run into an implementation run."""
    if run_id is None:
        run_id = _current_run_id(conn, task_id)
    if run_id is None:
        return 'ready'
    event = _latest_event(conn, task_id, 'claimed', run_id)
    payload = _json_dict(_row_get(event, 'payload'))
    return 'review' if payload.get('source_status') == 'review' else 'ready'

def heartbeat_claim(conn: sqlite3.Connection, task_id: str, *, ttl_seconds: Optional[int]=None, claimer: Optional[str]=None) -> bool:
    """Extend a running claim; True if we still own it."""
    expires = int(time.time()) + _resolve_claim_ttl_seconds(ttl_seconds)
    lock = claimer or _claimer_id()
    with write_txn(conn):
        cur = conn.execute("UPDATE tasks SET claim_expires = ? WHERE id = ? AND status = 'running' AND claim_lock = ?", (expires, task_id, lock))
        if cur.rowcount != 1:
            return False
        _extend_run_claim(conn, task_id, expires)
        return True

def _extend_run_claim(conn: sqlite3.Connection, task_id: str, expires: int) -> Optional[int]:
    """Mirror a task claim extension onto its active run row; returns that run id."""
    run_id = _current_run_id(conn, task_id)
    if run_id is not None:
        conn.execute('UPDATE task_runs SET claim_expires = ? WHERE id = ?', (expires, run_id))
    return run_id

def _verify_created_cards(conn: sqlite3.Connection, completing_task_id: str, claimed_ids: Iterable[str]) -> tuple[list[str], list[str]]:
    """Partition ``claimed_ids`` into (verified, phantom). Verified = the row
    exists AND ``created_by`` is the completing task's assignee or id, OR the
    card is linked as its child (created elsewhere, attached by the worker).
    Never mutates."""
    ordered = list(dict.fromkeys((str(x).strip() for x in claimed_ids or [] if str(x).strip())))
    if not ordered:
        return ([], [])
    row = conn.execute('SELECT assignee FROM tasks WHERE id = ?', (completing_task_id,)).fetchone()
    if row is None:
        return ([], ordered)
    completing_assignee = row['assignee']
    placeholders = ','.join(['?'] * len(ordered))
    rows = conn.execute(f'SELECT id, created_by FROM tasks WHERE id IN ({placeholders})', tuple(ordered)).fetchall()
    found = {r['id']: r['created_by'] for r in rows}
    linked_children: set[str] = set(child_ids(conn, completing_task_id))
    verified: list[str] = []
    phantom: list[str] = []
    for cid in ordered:
        created_by = found.get(cid)
        trusted = created_by is not None and (completing_assignee and created_by == completing_assignee or created_by == completing_task_id or cid in linked_children)
        (verified if trusted else phantom).append(cid)
    return (verified, phantom)
_TASK_ID_PROSE_RE = re.compile('\\bt_[a-f0-9]{8,}\\b')

def _scan_prose_for_phantom_ids(conn: sqlite3.Connection, text: str) -> list[str]:
    """``t_<hex>`` references in ``text`` that don't resolve to a task (deduped; advisory)."""
    if not text:
        return []
    return _missing_task_ids(conn, dict.fromkeys(_TASK_ID_PROSE_RE.findall(text)))

class HallucinatedCardsError(ValueError):
    """``complete_task`` refused: ``created_cards`` has ids that don't exist or
    weren't created by this worker (``.phantom``). A ``ValueError`` so tool
    error handlers treat it as recoverable."""

    def __init__(self, phantom: list[str], completing_task_id: str):
        self.phantom = list(phantom)
        self.completing_task_id = completing_task_id
        super().__init__(f'completion blocked: claimed created_cards that do not exist or were not created by this worker: {', '.join(phantom)}')

class EmptyCompletionError(ValueError):
    """``complete_task`` refused: no substantive ``result``, ``summary``, or
    stored result. A ``ValueError`` so tool error handlers treat it as
    recoverable. Review approvals are exempt (the human is the record)."""

    def __init__(self, task_id: str):
        self.task_id = task_id
        super().__init__(f'completion blocked: {task_id} has no result or summary evidence')

class ArtifactPreservationError(RuntimeError):
    """Raised when a declared scratch deliverable cannot be preserved."""

class LiveClaimError(ValueError):
    """``complete_task`` refused: the task is ``running`` under a live claim and
    the caller neither owns its run (``expected_run_id``) nor passed ``force``.
    Completing anyway would close the worker's run row underneath a process
    that is still executing. A ``ValueError`` so tool error handlers treat it
    as recoverable."""

    def __init__(self, task_id: str):
        super().__init__(f'{task_id} is running under a live worker claim; pass expected_run_id (worker ownership) or force=True (explicit operator override) instead of closing the live run')

def _claim_is_live(trow) -> bool:
    """True when a ``running`` task's claim still protects a run: the worker process
    it spawned exists (PID + start-time fingerprint). A claim whose worker is gone,
    or a library/CLI claim that never spawned one, has no run to protect. TTL expiry
    is deliberately not consulted: ``reclaim_stale_tasks`` extends, not reclaims, the
    claim of a live worker, so the process is the liveness authority here too."""
    return bool(trow['status'] == 'running' and trow['claim_lock'] is not None and trow['worker_pid'] and _worker_alive(trow['worker_pid'], trow['worker_started_at']))

def complete_task(conn: sqlite3.Connection, task_id: str, *, result: Optional[str]=None, summary: Optional[str]=None, metadata: Optional[dict]=None, created_cards: Optional[Iterable[str]]=None, expected_run_id: Optional[int]=None, fire_lifecycle_hook: bool=True, force: bool=False) -> bool:
    """``running|ready|blocked|review -> done``; records ``result``.

    ``ready`` is accepted for manual CLI completion, ``review`` for human
    approval. A ``running`` task under a live claim is only completed with
    proof of ownership (``expected_run_id``) or ``force=True`` (explicit
    operator override) — otherwise :class:`LiveClaimError`, the same fence
    :func:`request_review` applies. With no active run the handoff fields survive via
    :func:`_synthesize_ended_run`. ``summary`` (defaults to ``result``) and
    ``metadata`` land on the closing run for :func:`build_worker_context`.
    ``created_cards`` are verified first — a phantom id raises
    :class:`HallucinatedCardsError` after an auditable event; afterwards the
    prose is scanned for unresolvable ``t_<hex>`` refs (advisory event only).
    Completions from non-review statuses need evidence: a stripped ``result``
    or ``summary``, or a stripped result already stored on the card. Empty or
    whitespace-only evidence raises :class:`EmptyCompletionError` after an
    auditable event. Approving a card out of ``review`` stays exempt.
    """
    now = int(time.time())
    if not _parents_satisfied(conn, task_id):
        return False
    from hivemind_assembly.automation.state_engine.hermes_cli.kanban_pr_acceptance_store import prepare_acceptance, record_acceptance
    verified_cards = _gate_created_cards(conn, task_id, created_cards, summary or result)
    _gate_empty_completion(conn, task_id, result=result, summary=summary)
    metadata = _merge_completion_prose_artifacts(conn, task_id, metadata, summary=summary, result=result)
    handoff_summary = summary if summary is not None else result
    acceptance = prepare_acceptance(conn, task_id, expected_run_id, metadata)
    if acceptance is False:
        return False
    with write_txn(conn):
        if not _parents_satisfied(conn, task_id):
            return False
        if acceptance is not None and (not record_acceptance(conn, task_id, acceptance)):
            return False
        trow = conn.execute('SELECT status, claim_lock, worker_pid, worker_started_at FROM tasks WHERE id = ?', (task_id,)).fetchone()
        prior_status = trow['status'] if trow else None
        if expected_run_id is None and (not force) and trow and _claim_is_live(trow):
            raise LiveClaimError(task_id)
        sql = "\n                UPDATE tasks\n                   SET status       = 'done',\n                       result       = ?,\n                       completed_at = ?,\n                       claim_lock   = NULL,\n                       claim_expires= NULL,\n                       worker_pid   = NULL,\n                       block_kind   = NULL,\n                       block_recurrences = 0\n                 WHERE id = ?\n                   AND status IN ('running', 'ready', 'blocked', 'review')\n                "
        params: tuple = (result, now, task_id)
        if expected_run_id is not None:
            sql += ' AND current_run_id = ?'
            params = (*params, int(expected_run_id))
        if conn.execute(sql, params).rowcount != 1:
            return False
        if isinstance(metadata, dict):
            _stage_completion_artifacts(conn, task_id, metadata, now)
        run_id = _end_run(conn, task_id, outcome='completed', status='done', summary=handoff_summary, metadata=metadata)
        if run_id is None and (summary or metadata or result or (prior_status == 'review')):
            synth_summary, synth_metadata = (handoff_summary, metadata)
            if prior_status == 'review' and (not synth_summary) and (not synth_metadata):
                synth_summary = _REVIEW_APPROVED_NOTE
                synth_metadata = {'source_status': 'review', 'approval': 'manual'}
            run_id = _synthesize_ended_run(conn, task_id, outcome='completed', summary=synth_summary, metadata=synth_metadata)
        event_summary = handoff_summary
        if prior_status == 'review' and (not event_summary):
            event_summary = _REVIEW_APPROVED_NOTE
        _append_event(conn, task_id, 'completed', _completed_event_payload(result, event_summary, verified_cards, metadata), run_id=run_id)
    _flag_phantom_prose_refs(conn, task_id, run_id, summary, result, verified_cards)
    _clear_failure_counter(conn, task_id)
    recompute_ready(conn)
    _cleanup_workspace(conn, task_id)
    _done_task = get_task(conn, task_id)
    if fire_lifecycle_hook:
        _fire_task_hook('kanban_task_completed', _done_task, task_id, run_id, summary=handoff_summary)
    return True
_REVIEW_APPROVED_NOTE = 'Review approved without additional evidence.'

def _gate_created_cards(conn: sqlite3.Connection, task_id: str, created_cards: Optional[Iterable[str]], preview_text: Optional[str]) -> list[str]:
    """Verify ``created_cards`` BEFORE the main write txn; returns the verified
    ids. A phantom id is recorded in its own tiny txn (auditable) then raised
    as :class:`HallucinatedCardsError` without touching task state."""
    if not created_cards:
        return []
    verified_cards, phantom_cards = _verify_created_cards(conn, task_id, created_cards)
    if phantom_cards:
        with write_txn(conn):
            _append_event(conn, task_id, 'completion_blocked_hallucination', {'phantom_cards': phantom_cards, 'verified_cards': verified_cards, 'summary_preview': _first_line(preview_text, 200) or None})
        raise HallucinatedCardsError(phantom_cards, task_id)
    return verified_cards

def _substantive_text(value: Optional[str]) -> bool:
    return bool(value is not None and str(value).strip())

def _gate_empty_completion(conn: sqlite3.Connection, task_id: str, *, result: Optional[str], summary: Optional[str]) -> None:
    """Refuse a completion that would leave the card with no evidence.

    Review approvals are exempt: a human vouches for the card and
    ``_REVIEW_APPROVED_NOTE`` is the documented record.
    """
    row = conn.execute('SELECT status, result FROM tasks WHERE id = ?', (task_id,)).fetchone()
    if row is None:
        return
    if row['status'] == 'review':
        return
    stored = row['result']
    if _substantive_text(result) or _substantive_text(summary) or _substantive_text(stored):
        return
    with write_txn(conn):
        _append_event(conn, task_id, 'completion_blocked_empty_result', {'result_preview': _first_line(result, 200) or None, 'summary_preview': _first_line(summary, 200) or None})
    raise EmptyCompletionError(task_id)

def _stage_completion_artifacts(conn: sqlite3.Connection, task_id: str, metadata: dict, now: int, *, uploaded_by: str='kanban_complete') -> list[Path]:
    """Copy scratch artifacts to the attachments dir and record each as an
    attachment row; returns the copies so the caller can discard them if its
    transaction rolls back."""
    _persist_scratch_completion_artifacts(conn, task_id, metadata)
    staged = [Path(stored_path) for stored_path in metadata.pop('_staged_artifacts', [])]
    for path in staged:
        _insert_completion_attachment(conn, task_id, filename=path.name, stored_path=str(path), size=path.stat().st_size, created_at=now, uploaded_by=uploaded_by)
    return staged

def _cleaned_artifact_paths(metadata: Any) -> list[str]:
    """Non-blank string paths declared in ``metadata["artifacts"]``."""
    if not isinstance(metadata, dict):
        return []
    raw = metadata.get('artifacts')
    if not isinstance(raw, (list, tuple)):
        return []
    return [str(p).strip() for p in raw if isinstance(p, str) and str(p).strip()]

def _completed_event_payload(result: Optional[str], event_summary: Optional[str], verified_cards: list[str], metadata: Any) -> dict:
    """``completed`` event payload: first summary line (400 chars) so gateway
    notifiers / dashboard WS render without a second round-trip; verified
    cards; and ``metadata["artifacts"]`` promoted so the notifier can upload
    them as native attachments without fetching the run row."""
    payload: dict = {'result_len': len(result) if result else 0, 'summary': _first_line(event_summary, 400) or None}
    if verified_cards:
        payload['verified_cards'] = verified_cards
    if isinstance(metadata, dict):
        cleaned = _cleaned_artifact_paths(metadata)
        if cleaned:
            payload['artifacts'] = cleaned
    return payload

def _flag_phantom_prose_refs(conn: sqlite3.Connection, task_id: str, run_id: Optional[int], summary: Optional[str], result: Optional[str], verified_cards: list[str]) -> None:
    """Advisory post-commit scan of summary+result for unresolvable ``t_<hex>``
    references; emits ``suspected_hallucinated_references`` in its own txn so
    the completion is already durable. Never blocks."""
    scan_text = ' '.join(filter(None, [summary, result]))
    if not scan_text:
        return
    phantom_refs = [p for p in _scan_prose_for_phantom_ids(conn, scan_text) if p not in set(verified_cards)]
    if phantom_refs:
        with write_txn(conn):
            _append_event(conn, task_id, 'suspected_hallucinated_references', {'phantom_refs': phantom_refs, 'source': 'completion_summary'}, run_id=run_id)

def _merge_completion_prose_artifacts(conn: sqlite3.Connection, task_id: str, metadata: Optional[dict], *, summary: Optional[str], result: Optional[str]) -> Optional[dict]:
    """Legacy workers named deliverables only by absolute path in prose; add
    those that exist under the scratch workspace to ``metadata["artifacts"]``
    before cleanup can erase them."""
    workspace = _scratch_workspace(conn, task_id)
    if workspace is None:
        return metadata
    if not _is_managed_scratch_path(workspace):
        return metadata
    text = '\n'.join((part for part in (summary, result) if part))
    if not text:
        return metadata
    prefix = re.escape(str(workspace))
    discovered: list[str] = []
    for match in re.finditer(prefix + '(?:[/\\\\][^\\s`\\"\'<>]+)', text):
        raw = match.group(0).rstrip('.,;:!?)]}')
        candidate = Path(raw)
        if candidate.is_file():
            discovered.append(str(candidate))
    if not discovered:
        return metadata
    updated = dict(metadata) if isinstance(metadata, dict) else {}
    existing = updated.get('artifacts')
    merged = list(existing) if isinstance(existing, (list, tuple)) else []
    seen = {str(path) for path in merged}
    for path in discovered:
        if path not in seen:
            merged.append(path)
            seen.add(path)
    updated['artifacts'] = merged
    return updated

def _persist_scratch_completion_artifacts(conn: sqlite3.Connection, task_id: str, metadata: dict) -> None:
    """Copy scratch-workspace completion artifacts before cleanup removes them."""
    raw_artifacts = metadata.get('artifacts')
    if not isinstance(raw_artifacts, (list, tuple)):
        return
    workspace = _scratch_workspace(conn, task_id)
    if workspace is None:
        return
    is_managed, board = _managed_scratch_path_info(workspace)
    if not is_managed:
        return
    try:
        workspace_root = workspace.resolve()
    except OSError:
        return
    attachment_dir = task_attachments_dir(task_id, board=board)
    persisted: list[str] = []
    used_destinations: set[Path] = set()
    changed = False

    def _discard_copies() -> None:
        _discard_staged_copies(used_destinations, attachment_dir)
    for item in raw_artifacts:
        artifact = str(item).strip() if isinstance(item, str) else ''
        if not artifact:
            continue
        src = Path(artifact).expanduser()
        try:
            resolved_src = src.resolve()
        except OSError:
            persisted.append(artifact)
            continue
        if not resolved_src.is_relative_to(workspace_root):
            persisted.append(artifact)
            continue
        problem = None
        if not src.is_file():
            problem = f'declared scratch artifact is unavailable or not a regular file: {artifact}'
        elif resolved_src.stat().st_size > KANBAN_ATTACHMENT_MAX_BYTES:
            problem = f'declared scratch artifact exceeds the {KANBAN_ATTACHMENT_MAX_BYTES}-byte limit: {artifact}'
        if problem:
            _discard_copies()
            raise ArtifactPreservationError(problem)
        dest: Optional[Path] = None
        try:
            attachment_dir.mkdir(parents=True, exist_ok=True)
            dest = _unique_attachment_path(attachment_dir, resolved_src.name, used_destinations)
            _copy_capped(resolved_src, dest, artifact)
        except Exception as exc:
            if dest is not None:
                with contextlib.suppress(OSError):
                    dest.unlink(missing_ok=True)
            _discard_copies()
            if isinstance(exc, ArtifactPreservationError):
                raise
            raise ArtifactPreservationError(f'could not preserve declared scratch artifact {artifact}: {exc}') from exc
        used_destinations.add(dest)
        persisted.append(str(dest.resolve()))
        changed = True
    if changed:
        metadata['artifacts'] = persisted
        metadata['_staged_artifacts'] = [path for path in persisted if path.startswith(str(attachment_dir.resolve()))]

def _discard_staged_copies(copies: Iterable[Path], attachment_dir: Path) -> None:
    """Remove staged attachment copies whose DB rows never committed; a leaked
    copy would make the retry stage ``name_1.ext`` next to an orphan."""
    for copied in copies:
        with contextlib.suppress(OSError):
            Path(copied).unlink(missing_ok=True)
    with contextlib.suppress(OSError):
        attachment_dir.rmdir()

def _copy_capped(src: Path, dest: Path, artifact: str) -> None:
    """Chunked copy that aborts if the file grows past the attachment cap mid-copy."""
    with src.open('rb') as source_file, dest.open('xb') as destination_file:
        copied = 0
        while (chunk := source_file.read(1024 * 1024)):
            copied += len(chunk)
            if copied > KANBAN_ATTACHMENT_MAX_BYTES:
                raise ArtifactPreservationError(f'declared scratch artifact grew beyond the size limit: {artifact}')
            destination_file.write(chunk)

def _insert_completion_attachment(conn: sqlite3.Connection, task_id: str, *, filename: str, stored_path: str, size: int, created_at: int, uploaded_by: str='kanban_complete') -> None:
    """Record a worker-produced artifact in the existing attachment table."""
    conn.execute('INSERT INTO task_attachments (task_id, filename, stored_path, content_type, size, uploaded_by, created_at) VALUES (?, ?, ?, NULL, ?, ?, ?)', (task_id, filename, stored_path, size, uploaded_by, created_at))
    _append_event(conn, task_id, 'attached', {'filename': filename, 'size': size, 'by': uploaded_by})

def _unique_attachment_path(directory: Path, filename: str, used: set[Path]) -> Path:
    """Return a non-conflicting path under ``directory`` for ``filename``."""
    safe_name = Path(filename).name or 'artifact'
    stem, suffix = (Path(safe_name).stem or 'artifact', Path(safe_name).suffix)
    candidate = directory / safe_name
    idx = 1
    while candidate in used or candidate.exists():
        candidate = directory / f'{stem}_{idx}{suffix}'
        idx += 1
    return candidate

def block_task(conn: sqlite3.Connection, task_id: str, *, reason: Optional[str]=None, kind: Optional[str]=None, expected_run_id: Optional[int]=None) -> bool:
    """``running``/``ready`` -> ``blocked`` (or ``todo`` / ``triage``, see
    :func:`_route_block`). ``kind='dependency'`` with no incomplete parent is
    re-kinded to ``needs_input`` (sticky) so ``recompute_ready`` cannot
    promote it into a context-free respawn. ``transient`` still counts
    toward the loop breaker so a forever-flaky task escalates. True on any
    transition.

    An already-``blocked`` card that the failure breaker parked UNTYPED
    (``block_kind IS NULL``, no live run) is classified in place when *kind*
    is supplied: ``block_kind``/``block_recurrences`` are set and a ``blocked``
    audit event is appended, while status, failure evidence and the terminal
    runs stay exactly as the breaker left them. A typed block, a card with a
    live run, or a kind-less call on a blocked card are still refused.
    """
    if kind is not None and kind not in VALID_BLOCK_KINDS:
        raise ValueError(f'block kind must be one of {sorted(VALID_BLOCK_KINDS)} or None')
    with write_txn(conn):
        cur_row = conn.execute('SELECT status, block_kind, block_recurrences FROM tasks WHERE id = ?', (task_id,)).fetchone()
        if cur_row is None:
            return False
        if cur_row['status'] == 'blocked':
            if kind is None or expected_run_id is not None or _row_get(cur_row, 'block_kind') is not None:
                return False
            classified = conn.execute("UPDATE tasks SET block_kind = ?, block_recurrences = 1 WHERE id = ? AND status = 'blocked' AND block_kind IS NULL AND current_run_id IS NULL", (kind, task_id)).rowcount
            if classified != 1:
                return False
            _append_event(conn, task_id, 'blocked', {'kind': kind, 'reason': reason, 'classified_in_place': True})
            return True
        source_status = _retry_status_for_run(conn, task_id) if cur_row['status'] == 'running' else 'ready'
        requested_kind = kind
        rekind_reason = None
        if kind == 'dependency' and _parents_satisfied(conn, task_id):
            kind = 'needs_input'
            rekind_reason = 'no_open_parent'
        new_status, event_kind, set_sql, params, payload = _route_block(kind, reason, source_status, prev_kind=_row_get(cur_row, 'block_kind'), prev_recurrences=int(_row_get(cur_row, 'block_recurrences') or 0))
        if rekind_reason:
            payload['requested_kind'] = requested_kind
            payload['rekind_reason'] = rekind_reason
        sql = f"\n                UPDATE tasks\n                   SET status        = '{new_status}',\n                       claim_lock    = NULL,\n                       claim_expires = NULL,\n                       worker_pid    = NULL,\n                       {set_sql}\n                 WHERE id = ?\n                   AND status IN ('running', 'ready')\n                "
        params = (*params, task_id)
        if expected_run_id is not None:
            sql += ' AND current_run_id = ?'
            params = (*params, int(expected_run_id))
        if conn.execute(sql, params).rowcount != 1:
            return False
        run_id = _end_or_synthesize_run(conn, task_id, outcome='blocked', status='blocked', summary=reason, synthesize=bool(reason))
        _append_event(conn, task_id, event_kind, payload, run_id=run_id)
        blocked_task = get_task(conn, task_id)
        if kind == 'dependency':
            _fire_task_hook('kanban_task_blocked', blocked_task, task_id, run_id, reason=reason)
            return True
    _fire_task_hook('kanban_task_blocked', blocked_task, task_id, run_id, reason=reason)
    return True

def _route_block(kind: Optional[str], reason: Optional[str], source_status: str, *, prev_kind: Optional[str], prev_recurrences: int) -> tuple[str, str, str, tuple, dict]:
    """``(new_status, event_kind, set_sql, params, payload)`` for :func:`block_task`.

    ``dependency`` never enters the human ``blocked`` bucket: it waits in
    ``todo`` for ``recompute_ready``, so a cron never sees a dependency-wait
    as something to "unblock". Callers that pass ``dependency`` with no
    incomplete parent are re-kinded to ``needs_input`` before this runs
    (see :func:`block_task`). Every other kind counts unblock-loop
    recurrences: block_task only fires from running/ready (AFTER an unblock
    returned the task to the pool), so a stored ``block_kind`` equal to the
    incoming one means blocked -> unblocked -> re-block for the same cause
    (un-typed None compares equal to a prior un-typed block). At
    ``BLOCK_RECURRENCE_LIMIT`` the task routes to ``triage`` for a human.
    """
    payload = {'reason': reason, 'kind': kind, 'source_status': source_status}
    if kind == 'dependency':
        return ('todo', 'dependency_wait', 'block_kind    = ?', (kind,), payload)
    recurrences = prev_recurrences + 1 if prev_kind == kind else 1
    set_sql = 'block_kind    = ?,\n                       block_recurrences = ?'
    payload = {'reason': reason, 'kind': kind, 'recurrences': recurrences, 'source_status': source_status}
    if recurrences >= BLOCK_RECURRENCE_LIMIT:
        payload['limit'] = BLOCK_RECURRENCE_LIMIT
        return ('triage', 'block_loop_detected', set_sql, (kind, recurrences), payload)
    return ('blocked', 'blocked', set_sql, (kind, recurrences), payload)

def _reclaim_dangling_run(conn: sqlite3.Connection, task_id: str, *, statuses, now: int, note: str) -> None:
    """Close a leaked open run before a status flip so the invariant
    ``current_run_id IS NULL <=> run row terminal`` holds; no-op normally."""
    placeholders = ', '.join(('?' for _ in statuses))
    stale = conn.execute(f'SELECT current_run_id FROM tasks WHERE id = ? AND status IN ({placeholders})', (task_id, *statuses)).fetchone()
    if stale and stale['current_run_id']:
        conn.execute("\n            UPDATE task_runs\n               SET status = 'reclaimed', outcome = 'reclaimed',\n                   summary = COALESCE(summary, ?),\n                   ended_at = ?,\n                   claim_lock = NULL, claim_expires = NULL, worker_pid = NULL\n             WHERE id = ? AND ended_at IS NULL\n            ", (note, now, int(stale['current_run_id'])))

def _to_epoch(val) -> Optional[int]:
    """Epoch seconds from int/float/numeric string/ISO-8601; None for empty/invalid."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return int(val)
    s = str(val).strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        pass
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(s)
        return int(dt.timestamp())
    except (ValueError, OSError):
        return None
from hivemind_assembly.automation.state_engine.hermes_cli.kanban_db_boards import _dir_holds_board, board_metadata_path, read_board_metadata
from hivemind_assembly.automation.state_engine.hermes_cli.kanban_db_connect import write_txn
from hivemind_assembly.automation.state_engine.hermes_cli.kanban_db_workspace import _cleanup_workspace, _is_managed_scratch_path, _managed_scratch_path_info, _scratch_workspace
from hivemind_assembly.automation.state_engine.hermes_cli.kanban_db_dispatch import DEFAULT_FAILURE_LIMIT, _clear_failure_counter, _pid_alive, _worker_alive
