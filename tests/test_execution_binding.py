"""Owned helper resolution is independent of PATH and fails closed on damage."""
from pathlib import Path

import pytest

from hivemind_assembly.application.capabilities import BuiltinCapabilities
from hivemind_assembly.core.common import Blocked
from test_owned_components import bundle


def capabilities(tmp_path):
    return BuiltinCapabilities(tmp_path / 'state', tmp_path / 'config.json', {},
                               bundle_root=tmp_path / 'packages')


def test_developer_copy_has_no_implicit_helper(tmp_path, monkeypatch):
    monkeypatch.setenv('PATH', str(tmp_path))
    assert capabilities(tmp_path).execution_runtime() is None
    assert not (tmp_path / 'state').exists()


def test_configured_helper_must_be_prepared(tmp_path):
    bundle(tmp_path, name='execution', files={'ha-runtime': b'fixture-not-an-executable'})
    with pytest.raises(Blocked):
        capabilities(tmp_path).execution_runtime()


def test_helper_resolves_owned_payload_and_detects_tampering(tmp_path):
    manager, _, _ = bundle(tmp_path, name='execution', files={'ha-runtime': b'fixture-not-an-executable'})
    manager.prepare()
    owner = capabilities(tmp_path)
    runtime = owner.execution_runtime()
    assert runtime.command == (str(manager.resolve('execution').entrypoint),)
    Path(runtime.command[0]).write_bytes(b'changed')
    with pytest.raises(Blocked):
        owner.execution_runtime()


def test_damaged_inventory_cannot_enable_legacy_fallback(tmp_path):
    manager, _, _ = bundle(tmp_path, name='execution')
    (manager.bundle / 'catalogue.json').write_text('{damaged')
    with pytest.raises(Blocked, match='inventory'):
        capabilities(tmp_path).execution_runtime()


def test_active_helper_removed_from_catalogue_does_not_fallback(tmp_path):
    manager, _, _ = bundle(tmp_path, name='execution')
    manager.prepare()
    (manager.bundle / 'catalogue.json').write_text('{"schema":1,"components":[]}')
    with pytest.raises(Blocked, match='missing'):
        capabilities(tmp_path).execution_runtime()
