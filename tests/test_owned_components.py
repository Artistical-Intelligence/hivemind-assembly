"""Offline component integrity, preservation and recovery contract tests."""
import hashlib
import json
import os
from pathlib import Path
import stat
import zipfile

import pytest

from hivemind_assembly.application.components import Components, relative_path
from hivemind_assembly.core.common import Blocked, ContractError


def sha(data):
    return hashlib.sha256(data).hexdigest()


def bundle(tmp_path, *, name='analysis', files=None, mutate=None, extra=()):
    packages = tmp_path / 'packages'
    packages.mkdir(exist_ok=True)
    files = files or {'scripts/main.js': b'console.log("HA fixture");\n'}
    metadata = {'schema': 1, 'component': name, 'version': 'test-1', 'platform': 'any',
                'entrypoint': next(iter(files)), 'files': {key: sha(data) for key, data in files.items()}}
    if mutate:
        mutate(metadata)
    archive = packages / (name + '.zip')
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('component.json', json.dumps(metadata))
        for key, data in files.items():
            z.writestr('payload/' + key, data)
        for key, data in extra:
            z.writestr(key, data)
    entry = {'component': name, 'version': 'test-1', 'platform': 'any', 'file': archive.name,
             'sha256': sha(archive.read_bytes()), 'entrypoint': next(iter(files))}
    catalogue_path = packages / 'catalogue.json'
    catalogue = json.loads(catalogue_path.read_text()) if catalogue_path.exists() else {'schema': 1, 'components': []}
    catalogue['components'].append(entry)
    catalogue_path.write_text(json.dumps(catalogue))
    return Components(tmp_path / 'state', packages), entry, archive


def test_offline_prepare_and_reopen(tmp_path, monkeypatch):
    import socket
    monkeypatch.setattr(socket, 'create_connection', lambda *a, **kw: pytest.fail('Unexpected network call'))
    manager, entry, archive = bundle(tmp_path)
    assert manager.snapshot()['components'][0]['state'] == 'ready_to_prepare'
    assert not (tmp_path / 'state').exists()
    result = manager.prepare()
    assert result['network_used'] is False
    component = manager.resolve('analysis')
    assert component.entrypoint.read_bytes() == b'console.log("HA fixture");\n'
    reopened = Components(tmp_path / 'state', tmp_path / 'packages')
    assert reopened.resolve('analysis').digest == entry['sha256']
    assert reopened.snapshot()['components'][0]['installed'] is True
    assert reopened.prepare()['state'] == 'prepared'


def test_missing_package_never_downloads(tmp_path):
    manager, entry, archive = bundle(tmp_path)
    archive.unlink()
    with pytest.raises(Blocked, match='No download'):
        manager.prepare()
    assert not manager.path.exists()


def test_archive_digest_is_checked_before_install(tmp_path):
    manager, entry, archive = bundle(tmp_path)
    archive.write_bytes(archive.read_bytes() + b'changed')
    with pytest.raises(Blocked, match='integrity'):
        manager.prepare()
    assert not manager.path.exists()


def test_changed_payload_preserved_and_repaired_from_local_archive(tmp_path):
    manager, entry, archive = bundle(tmp_path)
    manager.prepare()
    component = manager.resolve('analysis')
    component.entrypoint.write_text('preserve this local change')
    with pytest.raises(Blocked):
        manager.resolve('analysis')
    with pytest.raises(Blocked, match='Repair'):
        manager.prepare()
    archive.unlink()
    result = manager.prepare(repair=True)
    assert result['network_used'] is False
    assert manager.resolve('analysis').entrypoint.read_text().startswith('console.log')
    preserved = list((manager.root / 'preserved').glob('*/payload/scripts/main.js'))
    assert len(preserved) == 1
    assert preserved[0].read_text() == 'preserve this local change'


def test_changed_inventory_cannot_reauthorize_changed_payload(tmp_path):
    manager, entry, _ = bundle(tmp_path)
    manager.prepare()
    component = manager.resolve('analysis')
    component.entrypoint.write_bytes(b'unauthorized')
    manifest = component.home.parent / 'component.json'
    meta = json.loads(manifest.read_text())
    meta['files']['scripts/main.js'] = sha(b'unauthorized')
    manifest.write_text(json.dumps(meta))
    with pytest.raises(Blocked, match='inventory was changed'):
        manager.resolve('analysis')


@pytest.mark.parametrize('bad', ['../outside', '/absolute', 'a/../b', 'a//b', 'a\\b',
                                  'a:stream', 'CON', 'x/NUL.txt', 'x. ', 'x/y.', './x', '', '.', 'C:/x'])
def test_nonportable_paths_rejected(bad):
    with pytest.raises(ContractError):
        relative_path(bad)


def test_archive_extra_file_rejected(tmp_path):
    manager, _, _ = bundle(tmp_path, extra=[('payload/unlisted.js', b'x')])
    with pytest.raises(ContractError, match='inventory disagree'):
        manager.prepare()


def test_archive_traversal_rejected(tmp_path):
    manager, _, _ = bundle(tmp_path, extra=[('../escaped', b'x')])
    with pytest.raises(ContractError, match='path'):
        manager.prepare()
    assert not (tmp_path / 'escaped').exists()


def test_archive_case_alias_rejected(tmp_path):
    manager, _, _ = bundle(tmp_path, files={'main.js': b'a', 'MAIN.js': b'b'})
    with pytest.raises(ContractError, match='Duplicate|ambiguous'):
        manager.prepare()


def test_archive_wrong_payload_digest_rejected(tmp_path):
    manager, _, _ = bundle(tmp_path, mutate=lambda meta: meta['files'].update({'scripts/main.js': '0' * 64}))
    with pytest.raises(ContractError, match='integrity'):
        manager.prepare()
    assert not manager.path.exists()


def test_archive_link_rejected(tmp_path):
    info = zipfile.ZipInfo('payload/link')
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    manager, _, _ = bundle(tmp_path, extra=[(info, b'/somewhere')])
    with pytest.raises(ContractError, match='non-regular'):
        manager.prepare()


def test_local_link_rejected(tmp_path):
    manager, _, _ = bundle(tmp_path)
    manager.prepare()
    component = manager.resolve('analysis')
    outside = tmp_path / 'outside.js'
    outside.write_bytes(component.entrypoint.read_bytes())
    component.entrypoint.unlink()
    try:
        component.entrypoint.symlink_to(outside)
    except OSError:
        pytest.skip('Host does not permit test symlinks')
    with pytest.raises(Blocked, match='symbolic link'):
        manager.resolve('analysis')


def test_corrupt_state_does_not_overwrite_original(tmp_path):
    manager, _, _ = bundle(tmp_path)
    manager.prepare()
    manager.path.write_text('{bad state')
    reopened = Components(tmp_path / 'state', tmp_path / 'packages')
    assert reopened.snapshot()['error']
    with pytest.raises(Blocked):
        reopened.prepare()
    assert manager.path.read_text() == '{bad state'


def test_two_instances_do_not_lose_other_preparations(tmp_path):
    bundle(tmp_path, name='first')
    manager, _, _ = bundle(tmp_path, name='second')
    earlier = Components(tmp_path / 'state', tmp_path / 'packages')
    manager.prepare(['first'])
    earlier.prepare(['second'])
    reopened = Components(tmp_path / 'state', tmp_path / 'packages')
    assert set(reopened.active) == {'first', 'second'}
    assert reopened.resolve('first')
    assert reopened.resolve('second')


def test_changed_state_rechecked_under_lock(tmp_path):
    manager, _, _ = bundle(tmp_path)
    manager.root.mkdir(parents=True)
    bad = {'schema': 1, 'active': {'analysis': {'sha256': '../not-a-hash'}}}
    manager.path.write_text(json.dumps(bad))
    with pytest.raises((Blocked, ContractError)):
        manager.prepare()
    assert json.loads(manager.path.read_text()) == bad


def test_storage_subdirectory_symlink_is_not_followed(tmp_path):
    manager, _, _ = bundle(tmp_path)
    outside = tmp_path / 'outside'
    outside.mkdir()
    manager.root.mkdir(parents=True)
    try:
        (manager.root / 'objects').symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('Host does not permit test symlinks')
    with pytest.raises(Blocked, match='redirect|symbolic'):
        manager.prepare()
    assert list(outside.iterdir()) == []


def test_corrupt_catalogue_keeps_local_status_usable(tmp_path):
    manager, _, _ = bundle(tmp_path)
    (manager.bundle / 'catalogue.json').write_text('[]')
    reopened = Components(tmp_path / 'state', manager.bundle)
    assert reopened.snapshot()['error']
    with pytest.raises(Blocked):
        reopened.prepare()


def test_metadata_duplicate_keys_rejected(tmp_path):
    manager, _, _ = bundle(tmp_path)
    (manager.bundle / 'catalogue.json').write_text('{"schema":1,"schema":2,"components":[]}')
    reopened = Components(tmp_path / 'state', manager.bundle)
    assert reopened.snapshot()['error']


def test_foreign_platform_not_activated(tmp_path):
    manager, _, _ = bundle(tmp_path)
    data = json.loads((manager.bundle / 'catalogue.json').read_text())
    data['components'][0]['platform'] = 'not-this-platform'
    (manager.bundle / 'catalogue.json').write_text(json.dumps(data))
    reopened = Components(tmp_path / 'state', manager.bundle)
    assert reopened.snapshot()['components'] == []
    with pytest.raises(Blocked):
        reopened.prepare(['analysis'])
