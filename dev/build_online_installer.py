"""Build the owner-authorized single-download installer for an existing beta.

The payload is unchanged. Hashes and URLs are compiled into the installer from
reviewable source, never accepted from a remote manifest at installation time.
The regular CLI cannot select a different download server or arbitrary executable.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import urllib.request
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'Artistical-Intelligence/hivemind-assembly'
VERSION = re.compile(r'\d+\.\d+\.\d+-beta\.\d+\Z')
HASH = re.compile(r'[a-f0-9]{64}\Z')


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def validate_request(data):
    if (not isinstance(data, dict) or data.get('schema') != 1
            or data.get('owner_authorized') is not True or data.get('channel') != 'beta'
            or data.get('independent_review_complete') is not False
            or not isinstance(data.get('version'), str) or not VERSION.fullmatch(data['version'])
            or data.get('tag') != 'v' + data['version']
            or type(data.get('release_id')) is not int or data['release_id'] <= 0):
        raise ValueError('An explicit owner-authorized beta packaging request is required')
    assets = data.get('assets')
    if not isinstance(assets, list) or not 2 <= len(assets) <= 16:
        raise ValueError('A complete offline installer is required')
    prefix = 'Hivemind_Assembly_' + data['version'] + '_Setup'
    expected = [prefix + '.exe'] + [prefix + '-' + str(i) + '.bin' for i in range(1, len(assets))]
    if [a.get('name') for a in assets if isinstance(a, dict)] != expected:
        raise ValueError('Unexpected or incomplete offline asset names')
    for item in assets:
        if (type(item.get('size')) is not int or not 0 < item['size'] < 2 * 1024**3
                or not isinstance(item.get('sha256'), str) or not HASH.fullmatch(item['sha256'])
                or set(item) != {'name', 'size', 'sha256'}):
            raise ValueError('Every payload needs an exact length and SHA-256')
    return data


def verify_release(data, release):
    validate_request(data)
    if (release.get('id') != data['release_id'] or release.get('tag_name') != data['tag']
            or release.get('draft') is not False or release.get('prerelease') is not True):
        raise ValueError('The published beta identity changed')
    entries = release.get('assets', [])
    for item in data['assets']:
        matches = [a for a in entries if a.get('name') == item['name']]
        if len(matches) != 1:
            raise ValueError('Offline asset missing or ambiguous: ' + item['name'])
        actual = matches[0]
        expected_url = 'https://github.com/' + REPOSITORY + '/releases/download/' + data['tag'] + '/' + item['name']
        if (actual.get('state') != 'uploaded' or actual.get('size') != item['size']
                or actual.get('digest') != 'sha256:' + item['sha256']
                or actual.get('browser_download_url') != expected_url):
            raise ValueError('Offline asset differs from the pinned release: ' + item['name'])
    return release


def fetch_release(data):
    request = urllib.request.Request('https://api.github.com/repos/' + REPOSITORY +
        '/releases/' + str(data['release_id']), headers={'User-Agent': 'HA-installer-builder',
                                                       'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = response.read(2 * 1024**2 + 1)
    if len(payload) > 2 * 1024**2:
        raise ValueError('Release metadata too large')
    return verify_release(data, json.loads(payload))


def render_script(data, template, *, fixture_base=None):
    validate_request(data)
    version = data['version']
    output_name = 'Hivemind_Assembly_' + version + '_Install'
    if fixture_base is None:
        base = 'https://github.com/' + REPOSITORY + '/releases/download/' + data['tag'] + '/'
    else:
        # Only a build-time test interface. No endpoint override is compiled into
        # or accepted by the shipping installer's command line.
        parsed = urlsplit(fixture_base)
        if (parsed.scheme != 'http' or parsed.hostname != '127.0.0.1'
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or not re.fullmatch(r'http://127\.0\.0\.1:\d+/', fixture_base)):
            raise ValueError('Fixtures must use a local HTTP server')
        base = fixture_base
        output_name = 'HA_test_fixture_Install'
    defines = ('#define AppVersion "' + version + '"\n#define OnlineName "' + output_name +
               '"\n#define NumericVersion "' + version.replace('-beta.', '.') + '"')
    if template.count('#include "online-assets.iss"') != 1:
        raise ValueError('Installer template include changed')
    text = template.replace('#include "online-assets.iss"', defines)
    text = text.replace('AppVersion={#AppVersion}\n',
                        'AppVersion={#AppVersion}\nVersionInfoVersion={#NumericVersion}\n', 1)
    count = len(data['assets'])
    declaration = ('const AssetCount = ' + str(count) + ';\nvar\n'
                   '  AssetNames, AssetHashes, AssetUrls: array[0..' + str(count - 1) + '] of String;\n'
                   '  AssetSizes: array[0..' + str(count - 1) + '] of Int64;\n')
    text = text.replace('[Code]\n', '[Code]\n' + declaration, 1)
    lines = ['procedure DefineAssets;', 'begin']
    for index, asset in enumerate(data['assets']):
        for field, value in [('AssetNames', asset['name']), ('AssetHashes', asset['sha256']),
                             ('AssetUrls', base + asset['name'])]:
            lines.append('  ' + field + '[' + str(index) + "] := '" + value + "';")
        lines.append('  AssetSizes[' + str(index) + '] := ' + str(asset['size']) + ';')
    lines.extend(['end;', ''])
    text = text.replace('function GetFileAttributesW(', '\n'.join(lines) + '\nfunction GetFileAttributesW(', 1)
    return output_name, text


def compile_script(data, template, output, iscc, *, fixture_base=None):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    name, text = render_script(data, template, fixture_base=fixture_base)
    source = output / (name + '.iss')
    source.write_text(text, encoding='utf-8-sig')
    subprocess.run([str(iscc), '/DOutputDir=' + str(output), str(source)], check=True, timeout=180)
    binary = output / (name + '.exe')
    if not binary.is_file() or binary.stat().st_size > 32 * 1024**2:
        raise ValueError('The small standalone installer was not produced')
    return binary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--iscc', type=Path)
    args = parser.parse_args()
    data = validate_request(json.loads((ROOT / 'dev/online_installer_request.json').read_text()))
    release = fetch_release(data)
    compiler = args.iscc or Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)')) / 'Inno Setup 6/ISCC.exe'
    if not compiler.is_file():
        raise RuntimeError('Inno Setup compiler is not available in the build environment')
    template = (ROOT / 'dev/online_installer.iss').read_text(encoding='utf-8')
    binary = compile_script(data, template, args.output, compiler)
    provenance = {'schema': 1, 'version': data['version'], 'release_id': data['release_id'],
        'release_source_commit': release['target_commitish'], 'packaging_commit': os.environ.get('GITHUB_SHA'),
        'installer': binary.name, 'installer_sha256': digest(binary), 'installer_bytes': binary.stat().st_size,
        'request_sha256': digest(ROOT / 'dev/online_installer_request.json'),
        'template_sha256': digest(ROOT / 'dev/online_installer.iss'),
        'offline_assets': data['assets'], 'runtime_changed': False,
        'independent_review_complete': False, 'stable_release_approved': False}
    (args.output / 'online-build-provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
    (args.output / 'ONLINE-SHA256SUMS.txt').write_text(digest(binary) + '  ' + binary.name + '\n')
    print(json.dumps(provenance))


if __name__ == '__main__':
    main()
