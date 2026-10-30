# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
from __future__ import annotations
import hashlib
import json
import logging
import re
import time
from typing import Any, Optional
from hivemind_assembly.automation.state_engine.agent.context_compressor import MODEL_ONLY_DISPLAY_METADATA_KEY, split_user_originated_turn
from hivemind_assembly.automation.state_engine.agent.message_metadata import DB_ROW_SNAPSHOT, TOOL_CALL_UID, TOOL_CALL_UIDS, index_tool_call_uids, message_uid_or_none, resolve_tool_call_uid, mint_uid, stamp_message_uid
from hivemind_assembly.automation.state_engine.agent.message_sanitization import _sanitize_surrogates, coalesce_tool_call_id
from hivemind_assembly.automation.state_engine.hermes_cli.timefmt import coerce_epoch
from hivemind_assembly.automation.state_engine.hermes_state_common import _COMPRESSION_LOCK_ROW_SQL, _ENDED_ROW_SQL, _ended_by_compression, _json_or, _placeholders, _sql_json_extract
from hivemind_assembly.automation.state_engine.hermes_state_detached_results import SessionDetachedResultsMixin
from hivemind_assembly.automation.state_engine.hermes_state_todo import SessionTodoResultMixin
from hivemind_assembly.automation.state_engine.hermes_state_identity import _absorbed_uids_json, _stable_tool_key, _tool_call_uid_map, _tool_call_uid_or_none, _tool_call_uids_json, _uid_list
logger = logging.getLogger('hermes_state')
_INSERT_MESSAGE_SQL = 'INSERT INTO messages (session_id, role, content, tool_call_id,\n                   tool_calls, tool_name, effect_disposition, timestamp, token_count, finish_reason,\n                   reasoning, reasoning_content, reasoning_details, codex_reasoning_items,\n                   codex_message_items, platform_message_id, observed, _compressed_summary, active, api_content, display_kind,\n                   display_metadata, display_identity, message_uid, absorbed_message_uids, tool_call_uids,\n                   tool_call_uid)\n                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)'
_MESSAGE_WRITE_COLUMNS = tuple(re.findall('\\w+', _INSERT_MESSAGE_SQL.split('(', 1)[1].split(')', 1)[0]))
_MESSAGE_SCHEMA_KEYS = frozenset(_MESSAGE_WRITE_COLUMNS) | {'id', 'compacted', 'display_order'}
_TURN_LEASE_ROW_SQL = 'SELECT holder, expires_at FROM session_turn_leases WHERE conversation_id = ?'
_DELETE_COMPRESSION_LOCK_SQL = 'DELETE FROM compression_locks WHERE session_id = ? AND holder = ?'
_DISPLAY_ACTIVE_CLAUSE = ' AND (active = 1 OR compacted = 1)'
DISPLAY_VISIBLE_SQL = f' AND COALESCE({_sql_json_extract('display_metadata', '$.' + MODEL_ONLY_DISPLAY_METADATA_KEY)}, 0) = 0'
_DISPLAY_INDEX_MISSING_SQL = 'SELECT 1 FROM messages WHERE session_id = ?' + _DISPLAY_ACTIVE_CLAUSE + ' AND (display_order IS NULL OR display_identity IS NULL) LIMIT 1'
_INVALID = object()

def _coerce_timestamp(value: Any, default: float) -> float:
    """Explicit message timestamp (datetime or number) or *default* when invalid or outside the sane
    epoch window — the write-side twin of the readers' ``coerce_epoch``: a bad row is never persisted."""
    result = coerce_epoch(value, field='message timestamp')
    if result is None:
        return default
    return 0.0 if result == 0.0 else result

def _parse_tool_calls(tool_calls: Any) -> Any:
    """tool_calls is a list (live agent) or JSON string (import/export); parse so json.dumps never double-encodes."""
    if not isinstance(tool_calls, str):
        return tool_calls
    try:
        return json.loads(tool_calls)
    except (json.JSONDecodeError, TypeError):
        return []

def _tool_calls_count(tool_calls: Any) -> int:
    return 0 if tool_calls is None else len(tool_calls) if isinstance(tool_calls, list) else 1

def _scrub_surrogates(value: Any) -> Any:
    """Lone surrogates make sqlite3 raise UnicodeEncodeError and abort the whole write."""
    return _sanitize_surrogates(value) if isinstance(value, str) else value

def _stale_holder(row, now: float) -> bool:
    """A lock/lease row whose holder is expired or a provably dead local process."""
    from hivemind_assembly.automation.state_engine.hermes_state import _compression_lock_holder_process_is_dead
    return float(row['expires_at']) <= now or _compression_lock_holder_process_is_dead(row['holder'])

class SessionMessagesMixin(SessionDetachedResultsMixin, SessionTodoResultMixin):
    """Message append/replace/rewind, reactions, resume conversations, replay dedupe (detached results: the base)."""

    @classmethod
    def _encode_content(cls, content: Any) -> Any:
        """Serialize list/dict content (multimodal parts) as a sentinel-prefixed JSON string (sqlite3 binds
        only scalars). Lone UTF-16 surrogates (unsanitized web-scraped tool results) are scrubbed here: left
        raw, sqlite3 raises UnicodeEncodeError and the session silently stops persisting. Pairs with
        :meth:`_decode_content`.

        A literal string carrying the reserved ``\\x00json:`` prefix is indistinguishable from
        stored structured content, so it is JSON-string-wrapped (decoded back verbatim on read)
        instead of written raw — a crafted import can't smuggle the marker in and have the read
        path decode attacker-chosen structure."""
        if isinstance(content, str):
            content = _sanitize_surrogates(content)
            if not content.startswith(cls._CONTENT_JSON_PREFIX):
                return content
        elif content is None or isinstance(content, (bytes, int, float)):
            return content
        try:
            return cls._CONTENT_JSON_PREFIX + json.dumps(content)
        except (TypeError, ValueError):
            return _sanitize_surrogates(str(content))

    @classmethod
    def _decode_content(cls, content: Any) -> Any:
        """Reverse :meth:`_encode_content`; returns scalars unchanged. Fail closed: a reserved-prefix
        string that isn't valid JSON (a legacy/malformed marker row) returns the raw string."""
        if isinstance(content, str) and content.startswith(cls._CONTENT_JSON_PREFIX):
            return _json_or(content[len(cls._CONTENT_JSON_PREFIX):], content, 'Failed to decode JSON-encoded message content; returning raw string')
        return content

    @staticmethod
    def _encode_display_metadata(display_metadata: Any) -> Optional[str]:
        """Serialize ``display_metadata`` for its TEXT column; an already-serialized JSON string
        (import/replace paths) is not double-encoded."""
        if not display_metadata:
            return None
        if isinstance(display_metadata, str):
            display_metadata = _json_or(display_metadata, _INVALID, 'Ignoring non-JSON display metadata on write')
            if display_metadata is _INVALID:
                return None
            if not isinstance(display_metadata, dict):
                logger.warning('Ignoring non-object display metadata on write')
                return None
        elif not isinstance(display_metadata, dict):
            logger.warning('Ignoring unexpected display metadata type on write: %s', type(display_metadata).__name__)
            return None
        return json.dumps(display_metadata)

    @staticmethod
    def _decode_display_metadata(raw: Any) -> Optional[dict[str, Any]]:
        """Decode a ``display_metadata`` column to a dict (never raw TEXT: the desktop does ``'task_count'
        in meta``). Pre-guard rows are double-encoded, so a second string layer is unwrapped."""
        if raw is None:
            return None
        meta = raw
        for _ in range(2):
            if isinstance(meta, str):
                meta = _json_or(meta, _INVALID, 'Ignoring invalid display metadata on message row')
        if meta is _INVALID:
            return None
        if not isinstance(meta, dict):
            logger.warning('Ignoring non-object display metadata on message row')
            return None
        return meta

    @staticmethod
    def _reasoning_json_text(value: Any) -> Optional[str]:
        """Serialize a structured reasoning field for its TEXT column. Strings are stored as-is: round-trips
        (get_messages -> replace_messages) hand back raw TEXT; re-dumping would double-encode it and
        reasoning-replay consumers (``isinstance(..., list)``) would drop it."""
        return None if not value else value if isinstance(value, str) else json.dumps(value)

    def _check_transcript_write_guards(self, conn, session_id: str, compression_lock_holder: Optional[str], turn_lease_holder: Optional[str]=None, turn_lease_ttl_seconds: float=300.0, reject_active_turn_lease: bool=False, reject_active_compression_lock: bool=False, allow_closed_compression_parent: bool=False) -> None:
        """Transcript-write admission checks, run INSIDE the write txn by every writer. Ordinary appends do
        NOT check compression_locks: the lock only stops two COMPRESSIONS colliding and archive_and_compact()
        commits against a watermark, so concurrent appends are safe (blocking them killed turns during slow
        summaries). Destructive user mutations opt in via ``reject_active_*`` so a compressor that captured
        its watermark cannot resurrect the removed turn.

        Shared by :meth:`append_message` and :meth:`append_messages_batch` so the two writers can never
        diverge on these correctness invariants (this guard has already needed targeted fixes — see the
        #74478 patience note below). User-initiated transcript mutations may opt in to rejecting an active
        unowned turn lease in that same transaction.
        """
        from hivemind_assembly.automation.state_engine.hermes_state import SessionCompressionInProgressError
        from hivemind_assembly.automation.state_engine.hermes_state_errors import CompressionSessionClosedError, SessionTurnLeaseLostError
        if reject_active_compression_lock:
            active_lock = conn.execute(_COMPRESSION_LOCK_ROW_SQL, (session_id,)).fetchone()
            if active_lock is not None:
                if _stale_holder(active_lock, time.time()):
                    conn.execute(_DELETE_COMPRESSION_LOCK_SQL, (session_id, active_lock['holder']))
                elif active_lock['holder'] != compression_lock_holder:
                    raise SessionCompressionInProgressError(f'Session {session_id!r} is being compressed by another writer')
        if turn_lease_holder or reject_active_turn_lease:
            conversation_id = self._session_turn_lease_key_on_conn(conn, session_id)
            lease = conn.execute(_TURN_LEASE_ROW_SQL, (conversation_id,)).fetchone()
            now = time.time()
            if turn_lease_holder:
                if lease is None or lease['holder'] != turn_lease_holder:
                    raise SessionTurnLeaseLostError(f'Session turn lease lost; refusing transcript write for {session_id!r}')
                if float(lease['expires_at']) <= now:
                    conn.execute('UPDATE session_turn_leases SET expires_at = ? WHERE conversation_id = ? AND holder = ?', (now + max(0.1, float(turn_lease_ttl_seconds)), conversation_id, turn_lease_holder))
            elif lease is not None:
                if not _stale_holder(lease, now):
                    raise SessionTurnLeaseLostError(f'Session has an active turn lease; refusing transcript mutation for {session_id!r}')
                conn.execute('DELETE FROM session_turn_leases WHERE conversation_id = ? AND holder = ?', (conversation_id, lease['holder']))
        if _ended_by_compression(conn.execute(_ENDED_ROW_SQL, (session_id,)).fetchone()) and (not allow_closed_compression_parent):
            raise CompressionSessionClosedError(session_id)

    def _message_row_params(self, session_id: str, role: str, msg: dict[str, Any], tool_calls: Any, message_timestamp: float, *, keep_reasoning: bool) -> tuple:
        """Bind values for ``_INSERT_MESSAGE_SQL`` from one message dict (*tool_calls* already parsed;
        *keep_reasoning* False NULLs every reasoning column). ``platform_message_id`` falls back to
        ``message_id`` (yuanbao's message-dict convention)."""
        _str_or_none = lambda v: _scrub_surrogates(v) if isinstance(v, str) else None
        _reasoning = lambda key: msg.get(key) if keep_reasoning else None
        encoded_content = self._encode_content(msg.get('content'))
        encoded_tool_calls = json.dumps(tool_calls) if tool_calls else None
        encoded_tool_name = _scrub_surrogates(msg.get('tool_name'))
        display_metadata = self._encode_display_metadata(msg.get('display_metadata'))
        identity_row = {'role': role, 'content': encoded_content, 'timestamp': message_timestamp, 'tool_call_id': msg.get('tool_call_id'), 'tool_calls': encoded_tool_calls, 'tool_name': encoded_tool_name, 'display_kind': msg.get('display_kind'), 'display_metadata': display_metadata}
        return (session_id, role, encoded_content, msg.get('tool_call_id'), encoded_tool_calls, encoded_tool_name, msg.get('effect_disposition'), message_timestamp, msg.get('token_count'), msg.get('finish_reason'), _scrub_surrogates(_reasoning('reasoning')), _scrub_surrogates(_reasoning('reasoning_content')), *(self._reasoning_json_text(_reasoning(k)) for k in ('reasoning_details', 'codex_reasoning_items', 'codex_message_items')), msg.get('platform_message_id') or msg.get('message_id'), 1 if msg.get('observed') else 0, 1 if msg.get('_compressed_summary') else 0, 1, _str_or_none(msg.get('api_content')), _str_or_none(msg.get('display_kind')), display_metadata, self._display_identity(self._display_dedupe_key(identity_row)), message_uid_or_none(msg), _absorbed_uids_json(msg), _tool_call_uids_json(msg), _tool_call_uid_or_none(msg))

    @staticmethod
    def _stamp_tool_call_uids(msg: dict[str, Any], tool_calls: Any, batch_index: dict[str, str]) -> None:
        """Per-occurrence tool-call identity at insert: an assistant row gets a uid for every tool call that
        has none yet (``_tool_call_uids``, keyed by the effective provider id, which stays untouched); a
        tool-result row that has none is resolved through *batch_index*, the calls the same batch's
        assistant rows named. A result flushed in a later batch is resolved from the live list by the flush
        (``tool_call_uid_from_history``) or, on restore, from the preceding assistant row."""
        role = msg.get('role')
        if role == 'assistant' and tool_calls:
            uids = _tool_call_uid_map(msg)
            for tc in tool_calls:
                call_id = coalesce_tool_call_id(tc)
                if call_id and call_id not in uids:
                    uids[call_id] = mint_uid()
            if uids:
                msg[TOOL_CALL_UIDS] = uids
            index_tool_call_uids(batch_index, msg)
        elif role == 'user':
            batch_index.clear()
        elif role == 'tool' and _tool_call_uid_or_none(msg) is None:
            uid = resolve_tool_call_uid(batch_index, msg.get('tool_call_id'))
            if uid:
                msg[TOOL_CALL_UID] = uid

    @staticmethod
    def _bump_session_counters(conn, session_id: str, inserted: int, tool_calls: int, *, unit: bool) -> None:
        """Bump sessions.* counters after an insert; *unit* bakes the ``+ 1`` literal into the SQL."""
        inc, params = ('1', ()) if unit else ('?', (inserted,))
        if tool_calls > 0:
            conn.execute(f'UPDATE sessions SET message_count = message_count + {inc},\n                       tool_call_count = tool_call_count + ? WHERE id = ?', (*params, tool_calls, session_id))
        elif inserted > 0:
            conn.execute(f'UPDATE sessions SET message_count = message_count + {inc} WHERE id = ?', (*params, session_id))

    def append_message(self, session_id: str, role: str, content: str | None=None, tool_name: str | None=None, tool_calls: Any=None, tool_call_id: str | None=None, token_count: int | None=None, finish_reason: str | None=None, reasoning: str | None=None, reasoning_content: str | None=None, reasoning_details: Any=None, codex_reasoning_items: Any=None, codex_message_items: Any=None, platform_message_id: str | None=None, observed: bool=False, effect_disposition: Optional[str]=None, _compressed_summary: bool=False, timestamp: Any=None, api_content: Optional[str]=None, display_kind: Optional[str]=None, display_metadata: Optional[dict[str, Any]]=None, compression_lock_holder: Optional[str]=None, turn_lease_holder: Optional[str]=None, turn_lease_ttl_seconds: float=300.0, message_uid: Optional[str]=None) -> int:
        """Append one message; returns the row id and bumps the session counters. ``platform_message_id``:
        the platform's own id. ``api_content``: byte-fidelity sidecar, the exact string sent to the API when
        it differed from ``content``, stored as sent except lone surrogates. ``message_uid``: the id a caller
        that keeps the message as a live dict already stamped on it (``stamp_message_uid``); minted when
        absent, but then only the row carries it."""
        msg = dict(locals())
        msg['display_metadata'] = self._encode_display_metadata(display_metadata)
        tool_calls = _parse_tool_calls(tool_calls)
        message_timestamp = _coerce_timestamp(timestamp, time.time())
        stamp_message_uid(msg)
        self._stamp_tool_call_uids(msg, tool_calls, {})
        params = self._message_row_params(session_id, role, msg, tool_calls, message_timestamp, keep_reasoning=True)

        def _do(conn):
            self._check_transcript_write_guards(conn, session_id, compression_lock_holder, turn_lease_holder=turn_lease_holder, turn_lease_ttl_seconds=turn_lease_ttl_seconds)
            msg_id = conn.execute(_INSERT_MESSAGE_SQL, params).lastrowid
            self._bump_session_counters(conn, session_id, 1, _tool_calls_count(tool_calls), unit=True)
            return msg_id
        return self._execute_write(_do, patience_s=self._TRANSCRIPT_WRITE_PATIENCE_S)
    _ROW_STATE_KEYS = ('_row_id', DB_ROW_SNAPSHOT, 'timestamp')

    def _message_column_names(self, conn) -> list[str]:
        """Column names of the messages table, cached per-connection era."""
        if not getattr(self, '_message_columns_cache', None):
            self._message_columns_cache = [r[1] for r in conn.execute('PRAGMA table_info(messages)').fetchall()]
        return self._message_columns_cache

    def _display_dedupe_key(self, row) -> tuple[Any, ...]:
        """Historical display identity, including normalized live content from user handoff carriers."""
        dedupe_content = row['content']
        if row['role'] == 'user':
            handoff, live_view = split_user_originated_turn({'role': 'user', 'content': self._decode_content(row['content']), 'display_kind': row['display_kind'], 'display_metadata': self._decode_display_metadata(row['display_metadata'])})
            if handoff is not None and live_view is not None:
                dedupe_content = self._encode_content(live_view.get('content'))
        return _stable_tool_key(row) or (row['role'], dedupe_content, row['timestamp'], row['tool_call_id'], row['tool_calls'], row['tool_name'])

    def _is_model_only_row(self, row) -> bool:
        """Python twin of :data:`DISPLAY_VISIBLE_SQL`."""
        return bool((self._decode_display_metadata(row['display_metadata']) or {}).get(MODEL_ONLY_DISPLAY_METADATA_KEY))

    @staticmethod
    def _display_identity(key: tuple[Any, ...]) -> bytes:
        """Fixed-width durable identity for indexed display-generation lookup."""
        return hashlib.sha256(repr(key).encode('utf-8', 'surrogatepass')).digest()

    def _dedupe_display_generations(self, rows, *, drop_removed: bool=False):
        """Collapse compaction generations so each logical message appears once (the protected tail is copied
        into each generation: same role/content/timestamp, different ``active``/id); prefer the live row, then
        the newest. The ONE definition every display projection shares. *rows* must be ordered by ``id``.

        *drop_removed*: *rows* also hold the removed rows (``active=0, compacted=0``: rewound, or replaced by a
        newer copy) and ``compacted``. A message whose newest copy is removed is not shown, so a rewind in a
        compression child never brings back the parent's copy. Copies share the display key or ``message_uid``
        (a micro-compaction merge also stands for the rows it absorbed)."""
        seen: dict[tuple[Any, ...], Any] = {}
        first_id: dict[tuple[Any, ...], int] = {}
        removed: dict[Any, bool] = {}
        identities: dict[tuple[Any, ...], list[Any]] = {}
        removed_ts: set[Any] = set()
        if drop_removed:
            rows = rows if isinstance(rows, list) else list(rows)
            removed_ts = {row['timestamp'] for row in rows if not row['active'] and (not row['compacted'])}
            drop_removed = bool(removed_ts)
        for row in rows:
            copies, key = (None, None)
            if drop_removed:
                gone = not row['active'] and (not row['compacted'])
                stored = row['display_identity'] if gone else None
                key = None if stored else self._display_dedupe_key(row)
                hashed = stored or (self._display_identity(key) if key is not None and (gone or row['timestamp'] in removed_ts) else None)
                copies = [*((hashed,) if hashed else ()), *(('uid', uid) for uid in (row['message_uid'], *_uid_list(row['absorbed_message_uids'])) if uid)]
                removed.update(dict.fromkeys(copies, gone))
                if gone:
                    continue
            if self._is_model_only_row(row):
                continue
            key = key or self._display_dedupe_key(row)
            cur = seen.get(key)
            if cur is None or (row['active'], row['id']) > (cur['active'], cur['id']):
                seen[key] = row
                identities[key] = copies
            first_id[key] = min(first_id.get(key, row['id']), row['id'])
        keys = sorted(seen, key=first_id.__getitem__)
        if drop_removed:
            keys = [key for key in keys if not any((removed[copy] for copy in identities[key]))]
        return [seen[key] for key in keys]

    def _reconcile_display_orders(self, conn, session_id: str) -> None:
        """Re-fold split display generations by the recomputed display key.

        A compaction generation that computed the display identity differently (or cloned
        without inheriting it) leaves one logical message in two ``display_order`` groups,
        and ``GROUP BY display_order`` then projects it twice (#122167). Folding by the same
        recomputed key :meth:`_dedupe_display_generations` uses keeps every display projection
        on one definition of a logical message; the live copy wins its group via the read
        path's ``ORDER BY candidate.active DESC, candidate.id DESC``. Writes only on drift."""
        first_id: dict[bytes, int] = {}
        last_id = 0
        while True:
            rows = conn.execute('SELECT id, role, content, timestamp, tool_call_id, tool_calls, tool_name, display_kind, display_metadata, display_order, display_identity FROM messages INDEXED BY idx_messages_session_id WHERE session_id = ? AND id > ? AND (active = 1 OR compacted = 1) ORDER BY id LIMIT 1000', (session_id, last_id))
            batch_start = last_id
            updates = []
            for row in rows:
                last_id = row['id']
                identity = self._display_identity(self._display_dedupe_key(row))
                kept = row['display_order'] if row['display_identity'] == identity else None
                order = first_id.setdefault(identity, last_id if kept is None else kept)
                if order != row['display_order'] or identity != row['display_identity']:
                    updates.append((order, identity, last_id))
            rows.close()
            if last_id == batch_start:
                break
            conn.executemany('UPDATE messages SET display_order = ?, display_identity = ? WHERE id = ?', updates)

    def _ensure_display_order(self, session_id: str) -> bool:
        """Backfill one legacy session once, preserving the pre-index display identity exactly."""
        with self._read_ctx() as conn:
            columns = set(self._message_column_names(conn))
        if not {'display_order', 'display_identity'} <= columns:
            return False
        if self._read_one(_DISPLAY_INDEX_MISSING_SQL, (session_id,)) is None:
            return True
        if getattr(self, 'read_only', False):
            return False

        def _do(conn):
            missing = conn.execute(_DISPLAY_INDEX_MISSING_SQL, (session_id,)).fetchone()
            if missing is None:
                return True
            self._reconcile_display_orders(conn, session_id)
            return True
        return bool(self._execute_write(_do))

    def _legacy_display_page(self, session_id: str, *, active_clause: str, limit: Optional[int], offset: int, latest: bool) -> list[Any]:
        """Project a legacy read-only display page without retaining transcript payloads."""
        representatives: dict[bytes, tuple[int, int]] = {}
        with self._read_ctx() as conn:
            conn.execute('BEGIN')
            try:
                has_session_index = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = ?", ('idx_messages_session_id',)).fetchone() is not None
                index_hint = 'INDEXED BY idx_messages_session_id' if has_session_index else 'NOT INDEXED'
                rows = conn.execute(f'SELECT id, role, content, timestamp, tool_call_id, tool_calls, tool_name, active, display_kind, display_metadata FROM messages {index_hint} WHERE session_id = ?{active_clause} ORDER BY id ASC', (session_id,))
                for row in rows:
                    if self._is_model_only_row(row):
                        continue
                    identity = self._display_identity(self._display_dedupe_key(row))
                    current = representatives.get(identity)
                    candidate = (row['active'], row['id'])
                    if current is None or candidate > current:
                        representatives[identity] = candidate
                rows.close()
                identities = list(representatives)
                identities = identities[::-1][offset:][:limit][::-1] if latest else identities[offset:][:limit]
                selected_ids = [representatives[identity][1] for identity in identities]
                selected = {}
                for start in range(0, len(selected_ids), 900):
                    chunk = selected_ids[start:start + 900]
                    selected.update({row['id']: row for row in conn.execute(f'SELECT * FROM messages WHERE session_id = ?{active_clause} AND id IN ({_placeholders(chunk)})', (session_id, *chunk))})
                return [selected[row_id] for row_id in selected_ids if row_id in selected]
            finally:
                if conn.in_transaction:
                    conn.execute('ROLLBACK')

    def _row_to_message_dict(self, row, *, warn_context: str, summary_flag: bool) -> dict[str, Any]:
        """``dict(row)`` with content/tool_calls/display_metadata decoded; *summary_flag* keeps
        ``_compressed_summary`` only as ``True``."""
        msg = dict(row)
        msg.pop('display_identity', None)
        msg.pop('display_order', None)
        if summary_flag and msg.pop('_compressed_summary', 0):
            msg['_compressed_summary'] = True
        msg['content'] = self._decode_content(msg['content'])
        if msg.get('tool_calls'):
            msg['tool_calls'] = _json_or(msg['tool_calls'], [], f'Failed to deserialize tool_calls in {warn_context}, falling back to []')
        if msg.get('display_metadata') is not None:
            msg['display_metadata'] = self._decode_display_metadata(msg['display_metadata'])
        for key, value in list(msg.items()):
            if key not in _MESSAGE_SCHEMA_KEYS and isinstance(value, (bytes, bytearray)):
                msg.pop(key)
        return msg

    @staticmethod
    def _display_rows_from_conn(conn, session_id: str, *, limit: Optional[int]=None, offset: int=0, latest: bool=False):
        """One display-history projection for normal reads and transactional verification."""
        direction = 'DESC' if latest else 'ASC'
        return conn.execute(f'WITH page AS (\n                   SELECT display_order FROM messages\n                   WHERE session_id = ? AND (active = 1 OR compacted = 1){DISPLAY_VISIBLE_SQL}\n                   GROUP BY display_order ORDER BY display_order {direction}\n                   LIMIT ? OFFSET ?\n               )\n               SELECT chosen.* FROM page\n               JOIN messages AS chosen ON chosen.id = (\n                   SELECT candidate.id FROM messages AS candidate\n                   WHERE candidate.session_id = ?\n                     AND candidate.display_order = page.display_order\n                     AND (candidate.active = 1 OR candidate.compacted = 1){DISPLAY_VISIBLE_SQL}\n                   ORDER BY candidate.active DESC, candidate.id DESC LIMIT 1\n               )\n               ORDER BY page.display_order ASC', (session_id, -1 if limit is None else limit, offset, session_id)).fetchall()

    @staticmethod
    def _active_clause(include_inactive: bool, include_compacted: bool) -> str:
        """Audit: every row; display: active plus compaction-archived (never Undo/Rewind rows); default: live."""
        return '' if include_inactive else _DISPLAY_ACTIVE_CLAUSE if include_compacted else ' AND active = 1'

    def get_messages(self, session_id: str, include_inactive: bool=False, include_compacted: bool=False, limit: Optional[int]=None, offset: int=0, latest: bool=False, after_id: Optional[int]=None, include_ancestors: bool=False) -> list[dict[str, Any]]:
        """Load messages in insertion order (id, never timestamp: clocks regress). ``include_inactive``:
        rewind rows too; ``include_compacted``: compaction-archived display history (not rewind rows).
        ``latest`` pages back from the newest but returns chronological order; ``after_id``: keyset paging.
        ``include_ancestors``: also load the compression lineage (root → tip, branch sessions exempt),
        mirroring ``get_messages_as_conversation(include_ancestors=True)`` — after a compression rotation
        the full transcript spans parent sessions, not just the child continuation (#51058)."""
        if after_id is not None and (latest or offset):
            raise ValueError('after_id is incompatible with latest/offset paging')
        if after_id is not None and include_compacted:
            raise ValueError('after_id is incompatible with include_compacted (deduped display reads use offset paging)')
        if after_id is not None and include_ancestors:
            raise ValueError('after_id is incompatible with include_ancestors (merged-lineage reads use offset paging)')
        active_clause = self._active_clause(include_inactive, include_compacted)
        session_ids = self._resume_lineage_ids(session_id) if include_ancestors else [session_id]
        if len(session_ids) > 1:
            display = include_compacted and (not include_inactive)
            rows = self._read_all(f'SELECT * FROM messages WHERE session_id IN ({_placeholders(session_ids)})' + active_clause + ' ORDER BY id ASC', session_ids)
            rows = self._dedupe_display_generations(self._with_removed_identities(rows, session_ids) if display else rows, drop_removed=display)
            rows = rows[::-1][offset:][:limit][::-1] if latest else rows[offset:][:limit]
        elif include_compacted and (not include_inactive) and self._ensure_display_order(session_id):
            rows = self._read_retrying_ioerr(lambda conn: self._display_rows_from_conn(conn, session_id, limit=limit, offset=offset, latest=latest))
        elif include_compacted:
            rows = self._legacy_display_page(session_id, active_clause=active_clause, limit=limit, offset=offset, latest=latest)
        else:
            sql = f'SELECT * FROM messages WHERE session_id = ?{active_clause}{(' AND id > ?' if after_id is not None else '')} ORDER BY id {('DESC' if latest else 'ASC')}'
            params: list = [session_id] if after_id is None else [session_id, after_id]
            if limit is not None or offset:
                sql += ' LIMIT ? OFFSET ?'
                params.extend([-1 if limit is None else limit, offset])
            rows = self._read_all(sql, params)
            if latest:
                rows.reverse()
        return [self._row_to_message_dict(row, warn_context='get_messages', summary_flag=True) for row in rows]

    def _with_removed_identities(self, rows, session_ids: list[str]) -> list[Any]:
        """*rows* (ordered by id) merged with the identities of the lineage's removed rows (``active=0,
        compacted=0``), which ``_dedupe_display_generations(drop_removed=True)`` needs only to hide a copy, never
        to show: no body (a legacy row without a stored display identity keeps its content for the key)."""
        removed = self._read_all(f'SELECT session_id, id, role, timestamp, tool_call_id, tool_calls, tool_name, display_kind, display_metadata, message_uid, absorbed_message_uids, display_identity, active, compacted, CASE WHEN display_identity IS NULL THEN content END AS content FROM messages WHERE session_id IN ({_placeholders(session_ids)}) AND active = 0 AND compacted = 0 ORDER BY id', tuple(session_ids))
        return sorted([*rows, *removed], key=lambda row: row['id']) if removed else list(rows)

    def _resume_lineage_ids(self, session_id: str) -> list[str]:
        """Session ids a display resume materializes: the VERIFIED compression lineage (root → tip; each
        hop's parent ended ``compression`` and the child is a genuine continuation), or the session alone
        for anything else — an explicit ``/branch`` copy, an API fork, a reset child, or a plain session.
        The raw parent walker ``_session_lineage_root_to_tip`` is intentionally NOT used here: it crosses
        fork/reset boundaries and misclassifies API forks (parent ended ``branched``, no marker) as
        compression lineages. Shared with the resume guard so it counts exactly what a resume loads."""
        if not session_id:
            return [session_id]
        session = self.get_session(session_id)
        if not session or self._is_explicit_fork_child_row(session):
            return [session_id]
        chain = [session_id]
        current = session
        seen = {session_id}
        while len(chain) < 100:
            if not self._is_compression_child_row(current):
                break
            parent = self.get_session(current['parent_session_id'])
            if not parent or parent['id'] in seen:
                break
            seen.add(parent['id'])
            chain.append(parent['id'])
            current = parent
        return list(reversed(chain))

    def message_count(self, session_id: str | None=None) -> int:
        """Count messages, optionally for a specific session."""
        sql = 'SELECT COUNT(*) FROM messages' + (' WHERE session_id = ?' if session_id else '')
        return self._read_one(sql, (session_id,) if session_id else ())[0]

    def _is_explicit_fork_child_row(self, session: dict[str, Any], *, include_reset: bool=False) -> bool:
        """True when *session* is a branch, delegate, or tool child of its parent (``include_reset``: also a
        reset fork). Markers only count when they point at ``parent_session_id``: compression copies
        ``model_config`` onto the continuation, so presence-only matching would misclassify it (same binding
        as ``_NON_CONTINUATION_CHILD_FILTER_SQL``)."""
        if session.get('source') == 'tool':
            return True
        cfg = session.get('model_config')
        if isinstance(cfg, str):
            try:
                cfg = json.loads(cfg)
            except json.JSONDecodeError:
                return False
        if not isinstance(cfg, dict):
            return False
        markers = (cfg.get('_branched_from'), cfg.get('_delegate_from'))
        if include_reset:
            markers += (cfg.get('_reset_from'),)
        parent_id = session.get('parent_session_id')
        return parent_id in markers if parent_id else any((m is not None for m in markers))
