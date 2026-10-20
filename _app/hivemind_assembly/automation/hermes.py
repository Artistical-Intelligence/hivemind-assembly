from pathlib import Path
import sys
from hivemind_assembly.core.common import Blocked, digest


class HermesHost:
    """Native session host and dependency scheduling using unmodified Hermes modules.

    Model API clients are never instantiated. The native team state machine is
    a transport extension; Hermes owns the task graph, claims and retained sessions.
    """

    def __init__(self, source, state_root):
        if not source or not (Path(source) / "hermes_state.py").is_file():
            raise Blocked(
                "Pinned complete Hermes source is required for native team hosting"
            )
        sys.path.insert(0, str(Path(source).resolve()))
        try:
            from hermes_state import SessionDB

            self.db = SessionDB(Path(state_root) / "hermes-sessions.sqlite3")
        except Exception as e:
            raise Blocked("Hermes session host unavailable: " + str(e)) from e
        from .hermes_board import HermesBoard

        self.board = HermesBoard(state_root)
        self.sessions = {}

    def ensure_role(self, role, conversation):
        session = (
            "workbench-" + digest({"role": role, "conversation": conversation})[:24]
        )
        if session not in self.sessions:
            self.db.create_session(
                session,
                "workbench-native",
                model_config={"route": role, "inference_transport": "native_browser"},
            )
            self.sessions[session] = True
        return session

    def record(self, role, conversation, speaker, text, message_id):
        session = self.ensure_role(role, conversation)
        self.db.append_message(session, speaker, text, message_uid=message_id)

    def close(self):
        self.db.close()
