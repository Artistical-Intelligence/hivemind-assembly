"""Real extracted storage behavior, without network or an upstream installation."""
import socket
import sys
import pytest
from hivemind_assembly.automation.hermes import HermesHost
from hivemind_assembly.core.common import Blocked


def test_built_in_sessions_reopen_deduplicate_and_do_not_load_external_source(tmp_path, monkeypatch):
    root = tmp_path / 'HA data'
    root.mkdir()
    outside = tmp_path / 'external'
    outside.mkdir()
    (outside / 'hermes_state.py').write_text('raise RuntimeError("MUST NOT IMPORT")')
    monkeypatch.setenv('HERMES_HOME', str(tmp_path / 'unrelated-account'))
    monkeypatch.setattr(socket, 'create_connection', lambda *a, **k: (_ for _ in ()).throw(AssertionError('Network not allowed')))
    before = set(sys.modules)
    host = HermesHost(outside, root)
    try:
        session = host.ensure_role('worker.fixture', 'conversation-one')
        host.record('worker.fixture', 'conversation-one', 'user', 'retained message', 'message-one')
        host.record('worker.fixture', 'conversation-one', 'user', 'retained message', 'message-one')
        assert len(host.db.get_messages(session)) == 1
        with pytest.raises(Blocked):
            host.record('worker.fixture', 'conversation-one', 'user', 'different message', 'message-one')
        task = {'id': 'test-task', 'project_id': 'test-project', 'objective': 'Retain task status'}
        assert host.board.claim(task)
        host.board.complete(task, {'passed': True})
    finally:
        host.close()
    reopened = HermesHost(None, root)
    try:
        assert reopened.db.get_messages(session)[0]['content'] == 'retained message'
        assert not reopened.board.claim(task)
    finally:
        reopened.close()
    assert (root / 'hermes-sessions.sqlite3').is_file()
    assert (root / 'hermes-kanban.sqlite3').is_file()
    assert not (tmp_path / 'unrelated-account').exists()
    loaded = set(sys.modules) - before
    assert not any(m == 'hermes_state' or m.startswith(('hermes_cli.', 'plugins.', 'providers.')) for m in loaded)
