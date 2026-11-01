"""A testing prerelease cannot silently become a stable release or new runtime."""
import importlib.util
import json
from pathlib import Path
import stat
import zipfile

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'dev/package_beta.py'


@pytest.fixture
def builder(tmp_path):
    spec = importlib.util.spec_from_file_location('beta_packaging', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = tmp_path
    (tmp_path / 'dev').mkdir()
    return module


def authorize(builder, **changes):
    value = {'schema': 1, 'channel': 'beta', 'version': '0.38.0-beta.1',
             'owner_testing_beta_authorized': True, 'independent_review_complete': False}
    value.update(changes)
    (builder.ROOT / 'dev/beta_release_request.json').write_text(json.dumps(value), encoding='utf-8')


@pytest.mark.parametrize('changes', [
    {'channel': 'stable'}, {'owner_testing_beta_authorized': False},
    {'version': '0.38.0'}, {'version': '../escape'}, {'schema': 2},
    {'independent_review_complete': True},
])
def test_explicit_beta_request_required(builder, changes):
    authorize(builder, **changes)
    with pytest.raises(ValueError, match='beta-only'):
        builder.request()


def test_authorized_request_stays_unreviewed_beta(builder):
    authorize(builder)
    assert builder.request()['channel'] == 'beta'
    assert builder.request()['independent_review_complete'] is False


@pytest.mark.parametrize('name', ['../escape', '/absolute', 'elsewhere/file',
                                  'Hivemind_Assembly/../escape',
                                  'Hivemind_Assembly/a\\b', 'Hivemind_Assembly/a:b'])
def test_archive_cannot_leave_its_product_root(builder, tmp_path, name):
    archive = tmp_path / 'input.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr(name, b'fixture')
    with pytest.raises(ValueError, match='archive member'):
        builder.safe_extract(archive, tmp_path / 'staged')
    assert not (tmp_path / 'escape').exists()


def test_archive_rejects_case_aliases_before_extraction(builder, tmp_path):
    archive = tmp_path / 'input.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('Hivemind_Assembly/file.txt', b'one')
        z.writestr('Hivemind_Assembly/FILE.txt', b'two')
    with pytest.raises(ValueError):
        builder.safe_extract(archive, tmp_path / 'staged')
    assert not list((tmp_path / 'staged').iterdir())


def test_archive_rejects_links(builder, tmp_path):
    archive = tmp_path / 'input.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        member = zipfile.ZipInfo('Hivemind_Assembly/link')
        member.create_system = 3
        member.external_attr = (stat.S_IFLNK | 0o777) << 16
        z.writestr(member, '../outside')
    with pytest.raises(ValueError):
        builder.safe_extract(archive, tmp_path / 'staged')


def test_valid_archive_preserves_bytes(builder, tmp_path):
    archive = tmp_path / 'input.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('Hivemind_Assembly/_app/item', b'\x00\xff\r\n')
    root = builder.safe_extract(archive, tmp_path / 'staged')
    assert (root / '_app/item').read_bytes() == b'\x00\xff\r\n'


def test_no_publication_notes_on_failed_installed_acceptance(builder, tmp_path):
    authorize(builder)
    output = tmp_path / 'output'
    output.mkdir()
    (output / 'offline-acceptance.json').write_text('{"passed": false}')
    with pytest.raises(ValueError, match='did not pass'):
        builder.finalize(output)
    assert not (output / 'release-notes.md').exists()


def test_complete_installer_required_before_publication(builder, tmp_path):
    authorize(builder)
    output = tmp_path / 'output'
    output.mkdir()
    (output / 'offline-acceptance.json').write_text('{"passed": true}')
    (output / 'Incomplete_Setup.exe').write_bytes(b'not-an-installer')
    with pytest.raises(ValueError, match='split installer'):
        builder.finalize(output)
    assert not (output / 'SHA256SUMS.txt').exists()
