# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
from __future__ import annotations
import sqlite3
from typing import Optional

def inherit_creator_origin(conn: sqlite3.Connection, task_id: str, creator_task_id: Optional[str], *, created_at: int) -> None:
    """Copy durable origin inside creation's transaction, never adding dependencies."""
    if not creator_task_id:
        return
    from hivemind_assembly.automation.state_engine.hermes_cli.kanban_db import _inherit_notify_subs
    conn.execute('UPDATE tasks SET session_id = COALESCE(session_id, (SELECT session_id FROM tasks WHERE id = ?)) WHERE id = ?', (creator_task_id, task_id))
    _inherit_notify_subs(conn, task_id, (creator_task_id,), created_at=created_at)

def initial_task_state(conn: sqlite3.Connection, parents: tuple[str, ...], initial_status: str, triage: bool, tenant: Optional[str]) -> tuple[str, Optional[str]]:
    """Resolve state and tenant under the creator's write transaction.

    Parent order breaks ties in this soft namespace; explicit tenant wins.
    Validate parents even for parked tasks so links never dangle.
    """
    rows = {}
    if parents:
        rows = {row['id']: row for row in conn.execute('SELECT id, status, tenant FROM tasks WHERE id IN (' + ','.join('?' * len(parents)) + ')', parents)}
        missing = [pid for pid in parents if pid not in rows]
        if missing:
            raise ValueError(f'unknown parent task(s): {', '.join(missing)}')
        if tenant is None:
            tenant = next((rows[pid]['tenant'] for pid in parents if rows[pid]['tenant']), None)
    if initial_status == 'blocked':
        return ('blocked', tenant)
    if triage:
        return ('triage', tenant)
    if any((row['status'] != 'done' for row in rows.values())):
        return ('todo', tenant)
    return ('ready', tenant)
