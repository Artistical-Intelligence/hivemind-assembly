"""Generated evidence updates do not grant arbitrary root-file access."""
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'dev/apply_integration_edits.py'


@pytest.fixture
def publisher(tmp_path):
    spec = importlib.util.spec_from_file_location('document_publisher', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = tmp_path
    return module


@pytest.mark.parametrize('path', ['AGENTS.md', 'CHECKS_STATUS.md', 'STATUS.md',
                                  '.github/workflows/release.yml', 'README.md/../AGENTS.md',
                                  'dev/apply_integration_edits.py', 'dev/integration_edits.json'])
def test_other_root_and_publisher_files_remain_protected(publisher, path):
    with pytest.raises(ValueError):
        publisher.safe_path(path)


@pytest.mark.parametrize('newline', [b'\n', b'\r\n'])
def test_readme_still_requires_exact_before_and_after_hashes(publisher, tmp_path, newline):
    # Hashes describe bytes, not platform-translated text. Exercise both formats
    # on every OS without weakening the publisher's exact-byte identity check.
    before, after = b'old' + newline, b'new' + newline
    readme = tmp_path / 'README.md'
    readme.write_bytes(before)
    manifest = tmp_path / 'request.json'
    edit = {'path':'README.md','before_sha256':publisher.sha(before),
            'after_sha256':publisher.sha(after),
            'replacements':[{'old':before.decode(), 'new':after.decode()}]}
    manifest.write_text(json.dumps({'schema':1,'id':'docs','edits':[edit]}), encoding='utf-8')
    result = publisher.apply(manifest)
    assert result['files'] == ['README.md']
    assert result['independent_review'] is False
    assert result['release_approved'] is False
    assert readme.read_bytes() == after
    assert publisher.apply(manifest)['files'] == []
    changed = b'someone else edited this' + newline
    readme.write_bytes(changed)
    with pytest.raises(ValueError, match='Concurrent'):
        publisher.apply(manifest)
    assert readme.read_bytes() == changed


def test_invalid_later_edit_does_not_partially_change_readme(publisher, tmp_path):
    readme = tmp_path / 'README.md'
    readme.write_bytes(b'old\n')
    valid = {'path':'README.md','before_sha256':publisher.sha(b'old\n'),
             'after_sha256':publisher.sha(b'new\n'),
             'replacements':[{'old':'old\n','new':'new\n'}]}
    manifest = tmp_path / 'request.json'
    manifest.write_text(json.dumps({'schema':1,'id':'docs','edits':[valid,{'path':'AGENTS.md'}]}), encoding='utf-8')
    with pytest.raises(ValueError):
        publisher.apply(manifest)
    assert readme.read_bytes() == b'old\n'
