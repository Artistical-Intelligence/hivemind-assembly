"""Build offline HA packages for pinned native runtimes; never run their installers.

All network access happens in the release-builder, not in HA's runtime. Keep
original downloads, notices, publisher checksum records and a file inventory.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '_app'))
from hivemind_assembly.application.components import relative_path
from hivemind_assembly.application.setup import PINS

NODE_VERSION = '24.15.0'
CLOUDFLARED = {
    'windows-x64': ('cloudflared-windows-amd64.exe', '411b16d40c8d872243efeb52c550053d00af0a8a97fbb32e730fb8aba429eaa8'),
    'linux-x64': ('cloudflared-linux-amd64', 'ae5e8add7884b0531d66bbca4570d1de491ff6da51e4ebe7eb160cdf241d9e42'),
}


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def download(url, path, expected=None):
    path = Path(path)
    pending = path.with_suffix('.download')
    urllib.request.urlretrieve(url, pending)
    actual = digest(pending)
    if expected and expected != actual:
        pending.unlink(missing_ok=True)
        raise RuntimeError('Publisher digest mismatch: ' + path.name)
    pending.replace(path)
    return {'url': url, 'file': path.name, 'bytes': path.stat().st_size, 'sha256': actual}


def pack(destination, component, version, platform_name, payload, entrypoint, provenance):
    relative_path(entrypoint)
    files = {}
    for path in sorted(Path(payload).rglob('*')):
        if not path.is_file():
            continue
        # Internal distribution symlinks are dereferenced into the owned archive.
        # A link outside the original distribution is never followed.
        if not path.resolve().is_relative_to(Path(payload).resolve()):
            raise RuntimeError('Distribution link escapes its root')
        rel = relative_path(path.relative_to(payload).as_posix())
        files[rel] = digest(path)
    if entrypoint not in files:
        raise RuntimeError('Native entry point is missing')
    if len({key.casefold() for key in files}) != len(files):
        raise RuntimeError('Distribution contains case-ambiguous files')
    manifest = {'schema': 1, 'component': component, 'version': version,
                'platform': platform_name, 'entrypoint': entrypoint,
                'files': files, 'provenance': provenance}
    out = Path(destination) / f'HA-{component}-{version}-{platform_name}.zip'
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for rel in files:
            z.write(Path(payload) / rel, 'payload/' + rel)
        z.writestr('component.json', json.dumps(manifest, indent=2) + '\n')
    record = {'component': component, 'version': version, 'platform': platform_name,
              'file': out.name, 'sha256': digest(out), 'bytes': out.stat().st_size,
              'entrypoint': entrypoint, 'file_count': len(files)}
    (Path(destination) / (component + '-' + platform_name + '-artifact.json')).write_text(
        json.dumps(record, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(record), flush=True)
    return record


def build(destination, *, include_ghidra=False):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    platform_name = 'windows-x64' if os.name == 'nt' else 'linux-x64'
    if platform.machine().lower() not in ('x86_64', 'amd64'):
        raise RuntimeError('This builder currently targets x64')
    originals = destination / 'originals'
    originals.mkdir(exist_ok=True)
    records = []
    with tempfile.TemporaryDirectory(prefix='ha-platform-') as folder:
        work = Path(folder)
        # The build workflow pins setup-node; package only the required runtime,
        # not an npm installer or a general automatic package loader.
        node_version = subprocess.check_output(['node', '--version'], text=True).strip().lstrip('v')
        if node_version != NODE_VERSION:
            raise RuntimeError('Unexpected Node runtime in builder')
        node_home = work / 'node'
        node_home.mkdir()
        node_file = 'node.exe' if os.name == 'nt' else 'node'
        shutil.copy2(shutil.which('node'), node_home / node_file)
        license_url = f'https://raw.githubusercontent.com/nodejs/node/v{NODE_VERSION}/LICENSE'
        provenance = [download(license_url, node_home / 'LICENSE')]
        source_record = {'source': f'https://github.com/nodejs/node/tree/v{NODE_VERSION}',
                         'runtime_sha256': digest(node_home / node_file),
                         'acquired_by': 'actions/setup-node with exact version ' + NODE_VERSION}
        records.append(pack(destination, 'node', NODE_VERSION, platform_name,
                            node_home, node_file, [*provenance, source_record]))

        java_home = Path(os.environ['JAVA_HOME']).resolve()
        release = (java_home / 'release').read_text(encoding='utf-8')
        if 'JAVA_VERSION="21.0.13"' not in release:
            raise RuntimeError('Expected pinned Temurin 21.0.13 runtime')
        records.append(pack(destination, 'jdk', '21.0.13+9', platform_name,
                            java_home, 'bin/java.exe' if os.name == 'nt' else 'bin/java',
                            [{'source': 'https://github.com/adoptium/temurin21-binaries/releases/tag/jdk-21.0.13%2B9',
                              'acquired_by': 'actions/setup-java pinned Temurin 21.0.13+9', 'release': release}]))

        cloud_home = work / 'tunnel'
        cloud_home.mkdir()
        asset, expected = CLOUDFLARED[platform_name]
        url = 'https://github.com/cloudflare/cloudflared/releases/download/2026.10.4/' + asset
        provenance = [download(url, cloud_home / asset, expected)]
        if os.name != 'nt':
            (cloud_home / asset).chmod(0o755)
        provenance.append(download('https://raw.githubusercontent.com/cloudflare/cloudflared/2026.10.4/LICENSE', cloud_home / 'LICENSE'))
        records.append(pack(destination, 'tunnel', '2026.10.4', platform_name,
                            cloud_home, asset, provenance))
        if include_ghidra:
            pin = PINS['ghidra']
            archive = originals / 'ghidra-pinned.zip'
            provenance = download(pin['url'], archive, pin['sha256'])
            with zipfile.ZipFile(archive) as z:
                for item in z.infolist():
                    if not (work / item.filename).resolve().is_relative_to(work):
                        raise RuntimeError('Unsafe Ghidra distribution member')
                z.extractall(work)
                if os.name != 'nt':
                    for item in z.infolist():
                        path = work / item.filename
                        if path.is_file():
                            path.chmod(0o755 if (item.external_attr >> 16) & 0o111 else 0o644)
            records.append(pack(destination, 'ghidra', '12.1.4', platform_name,
                                work / pin['folder'],
                                'support/analyzeHeadless.bat' if os.name == 'nt' else 'support/analyzeHeadless',
                                [provenance, {'source': pin['source'], 'tag': pin['tag']}]))
    (destination / 'platform-inventory.json').write_text(json.dumps({'schema': 1, 'components': records}, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--ghidra', action='store_true')
    args = parser.parse_args()
    build(args.destination, include_ghidra=args.ghidra)
