# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
from __future__ import annotations
from typing import Any

class SessionCompressionMixin:
    """Compression lineage, cooldown/streak counters, locks and turn leases."""

    def _session_turn_lease_key_on_conn(self, conn, session_id: str) -> str:
        """Walk compression parents on ``conn`` to the conversation lease key. Must share
        the connection of the lease INSERT/UPDATE/DELETE: a failed lookup must not yield a
        child id the write then persists. Markers bind to ``parent_session_id``. Lock
        errors propagate so ``_execute_write`` can retry."""
        if not session_id:
            return session_id

        def _row(sid: str):
            row = conn.execute('SELECT id, parent_session_id, source, model_config, end_reason FROM sessions WHERE id = ?', (sid,)).fetchone()
            return dict(row) if row else None
        current = _row(session_id)
        seen = {session_id}
        while current:
            parent_id = current.get('parent_session_id')
            if not parent_id or parent_id in seen or self._is_explicit_fork_child_row(current, include_reset=True):
                break
            parent = _row(parent_id)
            if not parent or parent.get('end_reason') != 'compression':
                break
            seen.add(parent_id)
            current = parent
        return str(current.get('id') or session_id) if current else session_id

    def _is_compression_child_row(self, child: dict[str, Any]) -> bool:
        parent_id = child.get('parent_session_id')
        if not parent_id or self._is_explicit_fork_child_row(child, include_reset=True):
            return False
        parent = self.get_session(parent_id)
        return bool(parent and parent.get('end_reason') == 'compression')
