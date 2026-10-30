# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
from __future__ import annotations
import os
from contextvars import ContextVar
_DELEGATED_CHILD_CONTEXT: ContextVar[bool] = ContextVar('hermes_delegated_child_context', default=False)
DELEGATED_CHILD_ENV_MARKER = 'HERMES_DELEGATED_CHILD_CONTEXT'

def explicit_board_intent_is_pinned() -> bool:
    """Whether an explicit kanban ``board=`` argument must still resolve through
    the dispatcher-injected env pins (``HERMES_KANBAN_DB`` & friends) rather than
    its own board directory.

    True for in-process delegate children, descendants carrying
    :data:`DELEGATED_CHILD_ENV_MARKER`, and dispatched workers
    (``HERMES_KANBAN_TASK`` set). The pins are the "workers physically cannot
    see other boards" isolation, and :func:`kanban_path_is_fenced` checks the
    pinned path / fenced root — an explicit board that resolved elsewhere would
    also escape that fence. Outside these fences an explicit board is the
    caller's own intent and wins.
    """
    if _DELEGATED_CHILD_CONTEXT.get():
        return True
    if os.environ.get(DELEGATED_CHILD_ENV_MARKER):
        return True
    return bool((os.environ.get('HERMES_KANBAN_TASK') or '').strip())

def kanban_path_is_fenced(path: os.PathLike[str] | str) -> bool:
    """Whether Kanban mutations at *path* (a board DB or board-metadata root) are denied for this
    process: always for an in-process delegate child (the parent's own board); for a spawned
    descendant only when *path* is the dispatcher-pinned ``HERMES_KANBAN_DB`` or lies under the
    fenced root the marker carries. A legacy ``"1"`` marker fences everything."""
    if _DELEGATED_CHILD_CONTEXT.get():
        return True
    marker = os.environ.get(DELEGATED_CHILD_ENV_MARKER, '')
    if not marker:
        return False
    if marker == '1':
        return True
    from pathlib import Path
    target = Path(path).expanduser().resolve()
    pinned = os.environ.get('HERMES_KANBAN_DB', '').strip()
    if pinned and target == Path(pinned).expanduser().resolve():
        return True
    try:
        target.relative_to(Path(marker).expanduser().resolve())
    except ValueError:
        return False
    return True
