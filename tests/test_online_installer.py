"""Build-time contracts; actual compiled Windows checks are separate."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ha_online_build', ROOT / 'dev/build_online_installer.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


@pytest.fixture
def request_data():
    return json.loads((ROOT / 'dev/online_installer_request.json').read_text())


@pytest.fixture
def release(request_data):
    return {'id': request_data['release_id'], 'tag_name': request_data['tag'],
            'prerelease': True, 'draft': False, 'assets': [
                {'name': a['name'], 'size': a['size'], 'digest': 'sha256:' + a['sha256'],
                 'state': 'uploaded', 'browser_download_url': 'https://github.com/' + build.REPOSITORY +
                   '/releases/download/' + request_data['tag'] + '/' + a['name']}
                for a in request_data['assets']]}


def test_pinned_publication_identity(request_data, release):
    assert build.verify_release(request_data, release) is release


@pytest.mark.parametrize('field,value', [('id', 1), ('draft', True), ('prerelease', False), ('tag_name', 'v0.37.4')])
def test_wrong_release_blocked(request_data, release, field, value):
    release[field] = value
    with pytest.raises(ValueError, match='identity'):
        build.verify_release(request_data, release)


@pytest.mark.parametrize('field,value', [('size', 12), ('digest', 'sha256:' + '0'*64),
                                        ('browser_download_url', 'https://evil.invalid/setup.exe'),
                                        ('state', 'new')])
def test_changed_published_payload_blocked(request_data, release, field, value):
    release['assets'][0][field] = value
    with pytest.raises(ValueError):
        build.verify_release(request_data, release)


@pytest.mark.parametrize('edit', ['missing', 'duplicate', 'path', 'size', 'hash', 'url', 'approval', 'version'])
def test_invalid_manifest_cannot_emit_script(request_data, edit):
    if edit == 'missing': request_data['assets'].pop(1)
    elif edit == 'duplicate': request_data['assets'].append(copy.deepcopy(request_data['assets'][0]))
    elif edit == 'path': request_data['assets'][0]['name'] = '../setup.exe'
    elif edit == 'size': request_data['assets'][0]['size'] = True
    elif edit == 'hash': request_data['assets'][0]['sha256'] = "'; Execute('bad')"
    elif edit == 'url': request_data['assets'][0]['url'] = 'https://elsewhere.invalid'
    elif edit == 'approval': request_data['owner_authorized'] = False
    elif edit == 'version': request_data['version'] = '0.38.0\n[Run]'
    with pytest.raises(ValueError):
        build.validate_request(request_data)


def test_generated_installer_embeds_all_exact_pins(request_data):
    template = (ROOT / 'dev/online_installer.iss').read_text()
    name, output = build.render_script(request_data, template)
    assert name.endswith('_Install')
    assert 'CreateAppDir=yes' in output
    assert 'Uninstallable=no' in output
    assert 'CreateUninstallRegKey=no' in output
    assert '#include' not in output
    assert 'DefineAssets' in output
    for asset in request_data['assets']:
        assert asset['sha256'] in output
        assert str(asset['size']) in output
        assert 'https://github.com/' + build.REPOSITORY + '/releases/download/' + request_data['tag'] + '/' + asset['name'] in output
    assert 'http://127.0.0.1' not in output
    assert '{param:URL' not in output and '{param:MANIFEST' not in output
    assert 'PowerShell' not in output[output.index('[Code]'):]


def test_cache_is_outside_app_and_validated_before_launch():
    text = (ROOT / 'dev/online_installer.iss').read_text()
    assert 'InstallerCache' in text
    assert 'ReparsePoint' in text
    assert 'GetSHA256OfFile' in text and 'FileSize64' in text
    assert text.index('for I := 0 to AssetCount - 1 do EnsureFile(I)') < text.index("Log('HA_CHILD_START')")
    assert text.index("if not Verified(AddBackslash(CacheDir)") < text.index("Log('HA_CHILD_START')")
    assert 'no automatic retry' in text
    assert 'PreserveRejected(Target)' in text
    assert 'FileCopy(BesideSetup, Temporary' in text
    assert '[UninstallDelete]' not in text and '[InstallDelete]' not in text


@pytest.mark.parametrize('origin', ['https://other.invalid/', 'http://example.com/',
                                    'http://127.0.0.1:9000/?redirect=evil', 'http://user@127.0.0.1:8000/'])
def test_test_builder_cannot_be_pointed_at_other_hosts(request_data, origin):
    with pytest.raises(ValueError):
        build.render_script(request_data, (ROOT / 'dev/online_installer.iss').read_text(), fixture_base=origin)
