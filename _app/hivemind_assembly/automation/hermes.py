"""HA-owned session storage; legacy class and database names remain compatible."""
from contextlib import contextmanager
from pathlib import Path
from threading import RLock

from hivemind_assembly.core.common import Blocked, digest


@contextmanager
def state_home(root):
    """Scope helper files to this HA installation, never ~/.hermes or a profile."""
    from .state_engine.hermes_constants import (
        set_hermes_home_override,
        reset_hermes_home_override,
    )

    token = set_hermes_home_override(Path(root) / "private" / "state-engine")
    try:
        yield
    finally:
        reset_hermes_home_override(token)


class HermesHost:
    """Built-in HA sessions and task graph derived from the retained MIT source.

    ``source`` is retained only for settings/caller compatibility. An external
    checkout is never imported, modified or needed. Existing database names and
    session identities are deliberately unchanged.
    """

    def __init__(self, source, state_root):
        self.root = Path(state_root)
        self.lock = RLock()
        self.sessions = {}
        try:
            with state_home(self.root):
                from .state_engine.hermes_state import SessionDB
                from .hermes_board import HermesBoard

                self.db = SessionDB(self.root / "hermes-sessions.sqlite3")
                try:
                    self.board = HermesBoard(self.root)
                except Exception:
                    self.db.close()
                    raise
        except Exception as error:
            raise Blocked("HA session storage is unavailable: " + str(error)) from error

    def ensure_role(self, role, conversation):
        session = "workbench-" + digest({"role": role, "conversation": conversation})[:24]
        with self.lock, state_home(self.root):
            if session not in self.sessions:
                self.db.create_session(
                    session,
                    "workbench-native",
                    model_config={"route": role, "inference_transport": "native_browser"},
                )
                self.sessions[session] = True
        return session

    def record(self, role, conversation, speaker, text, message_id):
        with self.lock, state_home(self.root):
            session = self.ensure_role(role, conversation)
            # HA owns one writer per data root. Replayed provider events must not
            # append the same logical message again after a transport reconnect.
            existing = self.db._read_one(
                "SELECT role, content FROM messages WHERE session_id=? AND message_uid=? ORDER BY id DESC LIMIT 1",
                (session, message_id),
            ) if message_id else None
            if existing is not None:
                if existing["role"] != speaker or self.db._decode_content(existing["content"]) != text:
                    raise Blocked("A retained message ID was reused for different content")
                return
            self.db.append_message(session, speaker, text, message_uid=message_id)

    def close(self):
        with self.lock, state_home(self.root):
            self.db.close()
