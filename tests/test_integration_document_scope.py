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


def test_readme_still_requires_exact_before_and_after_hashes(publisher, tmp_path):
    readme = tmp_path / 'README.md'
    readme.write_text('old\n')
    manifest = tmp_path / 'request.json'
    edit = {'path':'README.md','before_sha256':publisher.sha(b'old\n'),
            'after_sha256':publisher.sha(b'new\n'),
            'replacements':[{'old':'old\n','new':'new\n'}]}
    manifest.write_text(json.dumps({'schema':1,'id':'docs','edits':[edit]}))
    result = publisher.apply(manifest)
    assert result['files'] == ['README.md']
    assert result['independent_review'] is False
    assert result['release_approved'] is False
    assert readme.read_text() == 'new\n'
    assert publisher.apply(manifest)['files'] == []
    readme.write_text('someone else edited this\n')
    with pytest.raises(ValueError, match='Concurrent'):
        publisher.apply(manifest)
    assert readme.read_text() == 'someone else edited this\n'


def test_invalid_later_edit_does_not_partially_change_readme(publisher, tmp_path):
    readme = tmp_path / 'README.md'
    readme.write_text('old\n')
    valid = {'path':'README.md','before_sha256':publisher.sha(b'old\n'),
             'after_sha256':publisher.sha(b'new\n'),
             'replacements':[{'old':'old\n','new':'new\n'}]}
    manifest = tmp_path / 'request.json'
    manifest.write_text(json.dumps({'schema':1,'id':'docs','edits':[valid,{'path':'AGENTS.md'}]}))
    with pytest.raises(ValueError):
        publisher.apply(manifest)
    assert readme.read_text() == 'old\n'
