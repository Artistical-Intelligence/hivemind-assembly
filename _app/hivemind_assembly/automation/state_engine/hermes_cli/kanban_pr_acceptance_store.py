# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
from __future__ import annotations
from hivemind_assembly.automation.state_engine.hermes_cli.kanban_db_connect import write_txn
from hivemind_assembly.automation.state_engine.hermes_cli.kanban_pr_acceptance import _PR, collect_acceptance

def _snapshot(conn, task_id):
    row = conn.execute('SELECT current_run_id, status, completion_contract FROM tasks WHERE id=?', (task_id,)).fetchone()
    return tuple(row) if row else None

def prepare_acceptance(conn, task_id, expected_run_id, metadata):
    snapshot = _snapshot(conn, task_id)
    if snapshot is None:
        return False
    run_id, status, contract = snapshot
    if not contract or contract == 'local-only':
        return None
    if status not in {'running', 'ready', 'blocked', 'review'} or (expected_run_id is not None and run_id != expected_run_id):
        return False
    published_pr = metadata.get('published_pr') if isinstance(metadata, dict) else None
    match = _PR.fullmatch(published_pr) if isinstance(published_pr, str) else None
    if match and contract == match[1]:
        with write_txn(conn):
            if _snapshot(conn, task_id) != snapshot:
                return False
            conn.execute('UPDATE tasks SET completion_contract=? WHERE id=?', (published_pr, task_id))
        snapshot = (run_id, status, published_pr)
        contract = published_pr
    assignee = conn.execute('SELECT assignee FROM tasks WHERE id=?', (task_id,)).fetchone()['assignee']
    return (snapshot, collect_acceptance(contract, published_pr, assignee=assignee))

def record_acceptance(conn, task_id, acceptance):
    """Called under complete_task's write_txn, before its terminal UPDATE."""
    from hivemind_assembly.automation.state_engine.hermes_cli.kanban_db import _append_event
    snapshot, receipt = acceptance
    if _snapshot(conn, task_id) != snapshot:
        return False
    _append_event(conn, task_id, 'pr_acceptance', receipt, run_id=snapshot[0])
    if not receipt['ok']:
        detail = f'PR acceptance {receipt['classification']}: {receipt.get('detail', '')} {receipt['recovery']}'
        conn.execute('UPDATE tasks SET last_failure_error=? WHERE id=?', (detail, task_id))
    return receipt['ok']
