"""Local assembly fixtures are not substitutes for Windows installation acceptance."""
import hashlib
import json
import os
from pathlib import Path
import socket
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dev'))
import assemble_offline as assembly
import offline_bootstrap
from hivemind_assembly import paths
from hivemind_assembly.learning import vectors
from test_owned_components import bundle


def sha(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    monkeypatch.setattr(socket, 'create_connection', lambda *a, **k: pytest.fail('network not permitted'))
    app = tmp_path / 'app'
    app.mkdir()
    wheels = tmp_path / 'wheels'
    wheels.mkdir()
    wheel = wheels / 'fixture-1.0-py3-none-any.whl'
    wheel.write_bytes(b'inert-wheel-fixture')
    (app / 'requirements-windows.lock').write_text('fixture==1.0 --hash=sha256:' + sha(wheel.read_bytes()) + '\n')
    for name in offline_bootstrap.REQUIRED:
        manager, entry, _ = bundle(tmp_path, name=name)
        (manager.bundle / (name + '-artifact.json')).write_text(json.dumps(entry))
    browser = tmp_path / 'browser'
    (browser / 'chromium-test').mkdir(parents=True)
    (browser / 'chromium-test/chrome.exe').write_bytes(b'inert-browser-fixture')
    model = tmp_path / 'model'
    model.mkdir()
    files = {}
    for name in ('model.onnx', 'vocab.txt'):
        value = ('inert-' + name).encode()
        (model / name).write_bytes(value)
        files[name] = (name, sha(value), len(value))
    monkeypatch.setattr(vectors, 'FILES', files)
    monkeypatch.setattr(assembly, 'FILES', files)
    return app, [tmp_path / 'packages'], wheels, browser, model


def test_complete_fixture_assembles_without_network(inputs):
    result = assembly.assemble(*inputs)
    assert result['verified'] and result['network_used'] is False
    app = inputs[0]
    assert (app / 'bootstrap/offline-required').is_file()
    assert offline_bootstrap.verify(app)['verified']
    with pytest.raises(ValueError, match='preserved'):
        assembly.assemble(*inputs)


def test_missing_component_does_not_mark_package_complete(inputs):
    app, folders, *_ = inputs
    (folders[0] / 'execution-artifact.json').unlink()
    with pytest.raises(ValueError, match='execution'):
        assembly.assemble(*inputs)
    assert not (app / 'offline-manifest.json').exists()
    assert not (app / 'bootstrap/offline-required').exists()


def test_wrong_wheel_rejected_before_assembly(inputs):
    (inputs[2] / 'fixture-1.0-py3-none-any.whl').write_bytes(b'changed')
    with pytest.raises(ValueError, match='pinned lock'):
        assembly.assemble(*inputs)
    assert not (inputs[0] / 'components').exists()


def test_missing_wheel_is_not_substituted(inputs):
    (inputs[2] / 'fixture-1.0-py3-none-any.whl').unlink()
    with pytest.raises(ValueError, match='packages missing'):
        assembly.assemble(*inputs)


def test_offline_manifest_requires_unchanged_lock(inputs):
    assembly.assemble(*inputs)
    (inputs[0] / 'requirements-windows.lock').write_text('changed')
    with pytest.raises(ValueError, match='lock'):
        offline_bootstrap.verify(inputs[0])


def test_corrupt_prepared_package_is_rejected(inputs):
    assembly.assemble(*inputs)
    (inputs[0] / 'components/execution.zip').write_bytes(b'changed')
    with pytest.raises(ValueError, match='missing or changed'):
        offline_bootstrap.verify(inputs[0])


def test_model_cannot_be_omitted_from_inventory(inputs):
    assembly.assemble(*inputs)
    path = inputs[0] / 'offline-manifest.json'
    content = json.loads(path.read_text())
    content['files'] = {k: v for k, v in content['files'].items() if not k.startswith('models/')}
    path.write_text(json.dumps(content))
    with pytest.raises(ValueError, match='search model'):
        offline_bootstrap.verify(inputs[0])


def test_existing_build_customization_is_preserved(inputs):
    target = inputs[0] / 'bootstrap/wheels/fixture-1.0-py3-none-any.whl'
    target.parent.mkdir(parents=True)
    target.write_bytes(b'local-customization')
    with pytest.raises(ValueError, match='preserved'):
        assembly.assemble(*inputs)
    assert target.read_bytes() == b'local-customization'


@pytest.mark.parametrize('name', ['../escape', '/absolute', 'a\\b', 'a:b', './bad', 'a//b'])
def test_inventory_paths_cannot_redirect(tmp_path, name):
    with pytest.raises(ValueError):
        offline_bootstrap.local_file(tmp_path, name)


def test_local_search_uses_bundle_not_upstream(inputs, store, monkeypatch):
    app = inputs[0]
    assembly.assemble(*inputs)
    monkeypatch.setattr(paths, 'APP_ROOT', app)
    index = vectors.VectorIndex(store, opener=lambda *a, **k: pytest.fail('unexpected download'))
    index.download()
    assert index._files_ready()
    assert (index.folder / 'model.onnx').read_bytes() == (inputs[4] / 'model.onnx').read_bytes()


def test_missing_bundled_search_has_no_network_fallback(inputs, store, monkeypatch):
    app = inputs[0]
    assembly.assemble(*inputs)
    (app / 'models' / vectors.MODEL_ID / 'model.onnx').unlink()
    monkeypatch.setattr(paths, 'APP_ROOT', app)
    index = vectors.VectorIndex(store, opener=lambda *a, **k: pytest.fail('unexpected download'))
    with pytest.raises(ValueError, match='no download'):
        index.download()


def test_existing_browser_selection_is_not_migrated(tmp_path, monkeypatch):
    from hivemind_assembly.application import app as module
    class WindowsView:
        name = 'nt'
        def __getattr__(self, key):
            return getattr(os, key)
    monkeypatch.setattr(module, 'os', WindowsView())
    monkeypatch.setattr(module, 'windows_chrome_installed', lambda: True)
    root = tmp_path / 'owner'
    root.mkdir()
    config = json.loads(module.DEFAULT.read_text())
    config['browser']['channel'] = 'msedge'
    (root / 'settings.json').write_text(json.dumps(config))
    application = module.Application(root)
    try:
        assert application.config['browser']['channel'] == 'msedge'
        assert application.broker.jobs.runtime.__self__ is application.builtins
    finally:
        application.close()
