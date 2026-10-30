# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
from __future__ import annotations
import logging
import time
from typing import Any, Optional
logger = logging.getLogger('hermes_state')
_TOKEN_COUNTERS = ('input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_write_tokens', 'reasoning_tokens')

def _token_update_sql(delta: bool) -> str:
    """``UPDATE sessions`` for one usage report: *delta* adds to the stored counters (CLI
    per-call path), otherwise sets them (gateway cumulative path). Cost/route columns
    COALESCE-fill either way (statement text is pinned by the SQL trace harness)."""

    def add(col: str) -> str:
        return f'{col} + ?' if delta else '?'

    def add0(col: str) -> str:
        return f'COALESCE({col}, 0) + ?' if delta else '?'
    counters = ''.join((f'                   {c} = {add(c)},\n' for c in _TOKEN_COUNTERS))
    estimated = 'COALESCE(estimated_cost_usd, 0) + COALESCE(?, 0)' if delta else 'COALESCE(?, 0)'
    return 'UPDATE sessions SET\n' + counters + f'                   estimated_cost_usd = {estimated},\n                   actual_cost_usd = CASE\n                       WHEN ? IS NULL THEN actual_cost_usd\n                       ELSE {add0('actual_cost_usd')}\n                   END,\n                   cost_status = COALESCE(?, cost_status),\n                   cost_source = COALESCE(?, cost_source),\n                   pricing_version = COALESCE(?, pricing_version),\n                   billing_provider = COALESCE(billing_provider, ?),\n                   billing_base_url = COALESCE(billing_base_url, ?),\n                   billing_mode = COALESCE(billing_mode, ?),\n                   model = COALESCE(model, ?),\n                   api_call_count = {add0('api_call_count')}\n                   WHERE id = ?'
_TOKEN_UPDATE_ABSOLUTE_SQL = _token_update_sql(delta=False)
_TOKEN_UPDATE_DELTA_SQL = _token_update_sql(delta=True)
_MODEL_USAGE_UPSERT_SQL = 'INSERT INTO session_model_usage (\n                   session_id, model, billing_provider, billing_base_url, billing_mode,\n                   task, api_call_count, input_tokens, output_tokens,\n                   cache_read_tokens, cache_write_tokens, reasoning_tokens,\n                   estimated_cost_usd, actual_cost_usd, cost_status, cost_source,\n                   first_seen, last_seen\n               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)\n               ON CONFLICT(session_id, model, billing_provider, billing_base_url, billing_mode, task)\n               DO UPDATE SET\n                   api_call_count = api_call_count + excluded.api_call_count,\n                   input_tokens = input_tokens + excluded.input_tokens,\n                   output_tokens = output_tokens + excluded.output_tokens,\n                   cache_read_tokens = cache_read_tokens + excluded.cache_read_tokens,\n                   cache_write_tokens = cache_write_tokens + excluded.cache_write_tokens,\n                   reasoning_tokens = reasoning_tokens + excluded.reasoning_tokens,\n                   estimated_cost_usd = estimated_cost_usd + excluded.estimated_cost_usd,\n                   actual_cost_usd = actual_cost_usd + excluded.actual_cost_usd,\n                   cost_status = COALESCE(excluded.cost_status, cost_status),\n                   cost_source = COALESCE(excluded.cost_source, cost_source),\n                   last_seen = excluded.last_seen'
_MODEL_USAGE_FIELDS = frozenset(('model', 'billing_provider', 'billing_base_url', 'billing_mode', 'input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_write_tokens', 'reasoning_tokens', 'estimated_cost_usd', 'actual_cost_usd', 'cost_status', 'cost_source', 'api_call_count'))

class SessionUsageMixin:
    """Coalesced token writer, per-model usage rows, billing route."""

    def _apply_claimed_batch(self, batch) -> None:
        """Apply a batch whose ``busy`` flag the caller already claimed, then release."""
        try:
            self._apply_token_batch(batch)
        finally:
            with self._token_queue_cond:
                self._token_writer_busy = False
                self._token_queue_cond.notify_all()

    def flush_token_counts(self, timeout: float=5.0) -> bool:
        """Block until every queued token delta has been applied. False on timeout (callers
        then read totals stale by the queued deltas). Never raises."""
        if not self._token_queue and (not self._token_writer_busy):
            return True
        batch = None
        with self._token_queue_cond:
            deadline = time.monotonic() + timeout
            while self._token_queue or self._token_writer_busy:
                thread = self._token_writer_thread
                if (thread is None or not thread.is_alive()) and (not self._token_writer_busy):
                    self._token_writer_busy = True
                    batch = list(self._token_queue)
                    self._token_queue.clear()
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._token_queue_cond.wait(remaining)
        if batch:
            self._apply_claimed_batch(batch)
        return True

    def _apply_token_batch(self, batch: list[tuple[str, dict[str, Any]]]) -> None:
        """Apply queued deltas in order, coalescing where safe. Never raises."""
        try:
            coalesced = self._coalesce_token_deltas(batch)
        except Exception as exc:
            logger.warning('async token accounting: coalesce failed, applying raw batch: %s', exc)
            coalesced = batch
        for session_id, kwargs in coalesced:
            try:
                self.update_token_counts(session_id, **kwargs)
            except Exception as exc:
                logger.warning('async token accounting: apply failed (session=%s): %s', session_id, exc)

    def _coalesce_token_deltas(self, batch: list[tuple[str, dict[str, Any]]]) -> list[tuple[str, dict[str, Any]]]:
        """Merge adjacent incremental deltas with an identical route, so ordering across
        sessions and /model switches is preserved exactly. absolute=True never merges."""
        groups: list[tuple[Optional[tuple], str, dict[str, Any]]] = []
        for session_id, kwargs in batch:
            key = None
            if not kwargs.get('absolute'):
                key = (session_id, *(kwargs.get(f) for f in self._TOKEN_DELTA_ROUTE_FIELDS))
            if groups and key is not None and (groups[-1][0] == key):
                merged = groups[-1][2]
                for f in self._TOKEN_DELTA_SUM_FIELDS:
                    merged[f] = merged.get(f, 0) + kwargs.get(f, 0)
                for f in self._TOKEN_DELTA_COST_FIELDS:
                    value = kwargs.get(f)
                    if value is not None:
                        merged[f] = (merged.get(f) or 0.0) + value
            else:
                groups.append((key, session_id, dict(kwargs)))
        return [(sid, kw) for _, sid, kw in groups]

    def _stop_token_writer(self, join_timeout: float=10.0) -> None:
        """Stop the writer thread and drain remaining deltas. Never raises."""
        with self._token_queue_cond:
            self._token_writer_stop = True
            self._token_queue_cond.notify_all()
            thread = self._token_writer_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=join_timeout)
            if thread.is_alive():
                logger.warning('async token accounting: writer did not stop within %.0fs; %d queued delta(s) not persisted', join_timeout, len(self._token_queue))
                return
        with self._token_queue_cond:
            deadline = time.monotonic() + join_timeout
            while self._token_writer_busy:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    logger.warning('async token accounting: concurrent drain did not finish within %.0fs; %d queued delta(s) not persisted', join_timeout, len(self._token_queue))
                    return
                self._token_queue_cond.wait(remaining)
            batch = list(self._token_queue)
            if batch:
                self._token_writer_busy = True
                self._token_queue.clear()
        if batch:
            self._apply_claimed_batch(batch)

    def update_token_counts(self, session_id: str, input_tokens: int=0, output_tokens: int=0, model: str | None=None, cache_read_tokens: int=0, cache_write_tokens: int=0, reasoning_tokens: int=0, estimated_cost_usd: Optional[float]=None, actual_cost_usd: Optional[float]=None, cost_status: Optional[str]=None, cost_source: Optional[str]=None, pricing_version: Optional[str]=None, billing_provider: Optional[str]=None, billing_base_url: Optional[str]=None, billing_mode: Optional[str]=None, api_call_count: int=0, absolute: bool=False, source: Optional[str]=None, task: str='') -> None:
        """Update totals and route attribution, ensuring the legacy missing-row backfill.
        *absolute*=False increments (per-API-call deltas, CLI path); *absolute*=True sets directly
        (gateway path, where the cached agent holds cumulative totals). ``source`` is the session's
        real surface for the row-existence guard; callers that don't know it leave the placeholder.
        ``task`` names a per-turn route (``voice_chat``): its calls count in the session totals and
        land in ``session_model_usage`` under that task, but never become the session's recorded route."""
        values = dict(locals())
        values.pop('self')
        values.pop('session_id')
        values.pop('source')
        self._insert_session_row(session_id, source or 'unknown', model=model)
        self._execute_write(lambda conn: self._update_token_counts_in_transaction(conn, session_id, **values))

    def _update_token_counts_in_transaction(self, conn, session_id: str, input_tokens: int=0, output_tokens: int=0, model: str | None=None, cache_read_tokens: int=0, cache_write_tokens: int=0, reasoning_tokens: int=0, estimated_cost_usd: Optional[float]=None, actual_cost_usd: Optional[float]=None, cost_status: Optional[str]=None, cost_source: Optional[str]=None, pricing_version: Optional[str]=None, billing_provider: Optional[str]=None, billing_base_url: Optional[str]=None, billing_mode: Optional[str]=None, api_call_count: int=0, absolute: bool=False, task: str='') -> None:
        usage = {k: v for k, v in locals().items() if k in _MODEL_USAGE_FIELDS}
        sql = _TOKEN_UPDATE_ABSOLUTE_SQL if absolute else _TOKEN_UPDATE_DELTA_SQL
        has_usage = bool(input_tokens or output_tokens or cache_read_tokens or cache_write_tokens or reasoning_tokens or api_call_count or estimated_cost_usd)
        has_accounted_usage = bool(has_usage or actual_cost_usd)
        params = (input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, reasoning_tokens, estimated_cost_usd, actual_cost_usd, actual_cost_usd, cost_status, cost_source, pricing_version, billing_provider if has_accounted_usage else None, billing_base_url if has_accounted_usage else None, billing_mode if has_accounted_usage else None, model if has_accounted_usage else None, api_call_count, session_id)
        record_model_usage = not absolute and has_usage
        row = conn.execute('SELECT model, billing_provider, api_call_count FROM sessions WHERE id = ?', (session_id,)).fetchone()
        existing = dict(row) if row is not None else {}
        first_accounted_route = not task and int(existing.get('api_call_count') or 0) == 0 and has_accounted_usage and bool(model) and bool(billing_provider) and (existing.get('model') != model or existing.get('billing_provider') != billing_provider)
        if first_accounted_route:
            conn.execute('UPDATE sessions\n                   SET model = ?, billing_provider = ?,\n                   billing_base_url = ?, billing_mode = ?\n                   WHERE id = ?', (model, billing_provider, billing_base_url, billing_mode, session_id))
        conn.execute(sql, params)
        if record_model_usage:
            self._record_model_usage(conn, session_id, task=task, **usage)

    def _record_model_usage(self, conn, session_id: str, *, model: Optional[str]=None, billing_provider: Optional[str]=None, billing_base_url: Optional[str]=None, billing_mode: Optional[str]=None, input_tokens: int=0, output_tokens: int=0, cache_read_tokens: int=0, cache_write_tokens: int=0, reasoning_tokens: int=0, estimated_cost_usd: Optional[float]=None, actual_cost_usd: Optional[float]=None, cost_status: Optional[str]=None, cost_source: Optional[str]=None, api_call_count: int=0, task: str='') -> None:
        """Accumulate a per-API-call usage delta into session_model_usage, inside the caller's
        write txn after the ``sessions`` UPDATE. A missing model/provider falls back to
        the session row — except for aux rows (``task`` set), which must NOT inherit the
        main-loop route (vision on gemini while the main loop runs anthropic): missing
        info stays 'unknown'/empty.

        ``task`` distinguishes what kind of work consumed the tokens: ``''`` (empty) is the main agent loop;
        auxiliary calls record their task name (``vision``, ``compression``, ``title_generation``, ...) via
        :meth:`record_auxiliary_usage` (issue #23270).
        """
        row = conn.execute('SELECT model, billing_provider, billing_base_url, billing_mode FROM sessions WHERE id = ?', (session_id,)).fetchone()
        sess = dict(row) if row is not None and (not task) else {}
        counts = [v or 0 for v in (input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, reasoning_tokens)]
        now = time.time()
        conn.execute(_MODEL_USAGE_UPSERT_SQL, (session_id, model or sess.get('model') or 'unknown', billing_provider or sess.get('billing_provider') or '', billing_base_url or sess.get('billing_base_url') or '', billing_mode or sess.get('billing_mode') or '', task or '', api_call_count or 0, *counts, float(estimated_cost_usd or 0.0), float(actual_cost_usd or 0.0), cost_status, cost_source, now, now))
