"""Package HA's native runtimes offline, retaining publisher archives and notices.

Downloads occur only in the release builder. The CI runner's patched Java trust
store is never redistributed; use the original checksum-verified JDK archive.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
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


def original_jdk(work, originals):
    tag = 'jdk-21.0.13+9'
    api = 'https://api.github.com/repos/adoptium/temurin21-binaries/releases/tags/' + urllib.parse.quote(tag, safe='')
    request = urllib.request.Request(api, headers={'User-Agent': 'HA-release-builder'})
    with urllib.request.urlopen(request, timeout=60) as response:
        release = json.load(response)
    suffix = '_windows_hotspot_21.0.13_9.zip' if os.name == 'nt' else '_linux_hotspot_21.0.13_9.tar.gz'
    matches = [a for a in release['assets'] if a['name'].startswith('OpenJDK21U-jdk_x64_') and a['name'].endswith(suffix)]
    if len(matches) != 1:
        raise RuntimeError('The pinned publisher JDK archive is unavailable or ambiguous')
    asset = matches[0]
    checks = [a for a in release['assets'] if a['name'] == asset['name'] + '.sha256.txt']
    if len(checks) != 1:
        raise RuntimeError('The pinned JDK publisher checksum is missing')
    checksum = originals / checks[0]['name']
    download(checks[0]['browser_download_url'], checksum)
    expected = checksum.read_text().split()[0].lower()
    if not re.fullmatch(r'[a-f0-9]{64}', expected):
        raise RuntimeError('Invalid JDK publisher checksum')
    archive = originals / asset['name']
    provenance = download(asset['browser_download_url'], archive, expected)
    output = work / 'jdk-original'
    output.mkdir()
    if os.name == 'nt':
        with zipfile.ZipFile(archive) as z:
            for member in z.infolist():
                if not (output / member.filename).resolve().is_relative_to(output):
                    raise RuntimeError('Unsafe JDK archive path')
            z.extractall(output)
    else:
        with tarfile.open(archive) as tar:
            tar.extractall(output, filter='data')
    roots = [p for p in output.iterdir() if p.is_dir() and (p / 'release').is_file()]
    if len(roots) != 1 or 'JAVA_VERSION="21.0.13"' not in (roots[0] / 'release').read_text():
        raise RuntimeError('The original JDK version does not match the pin')
    return roots[0], [provenance, {'release_tag': tag, 'publisher_checksum': expected}]


def pack(destination, component, version, platform_name, payload, entrypoint, provenance):
    relative_path(entrypoint)
    files = {}
    for path in sorted(Path(payload).rglob('*')):
        if not path.is_file():
            continue
        if not path.resolve().is_relative_to(Path(payload).resolve()):
            raise RuntimeError('Distribution link escapes its root')
        rel = relative_path(path.relative_to(payload).as_posix())
        files[rel] = digest(path)
    if entrypoint not in files:
        raise RuntimeError('Native entry point is missing')
    if len({key.casefold() for key in files}) != len(files):
        raise RuntimeError('Distribution contains case-ambiguous files')
    manifest = {'schema': 1, 'component': component, 'version': version, 'platform': platform_name,
                'entrypoint': entrypoint, 'files': files, 'provenance': provenance}
    out = Path(destination) / f'HA-{component}-{version}-{platform_name}.zip'
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for rel in files:
            z.write(Path(payload) / rel, 'payload/' + rel)
        z.writestr('component.json', json.dumps(manifest, indent=2) + '\n')
    record = {'component': component, 'version': version, 'platform': platform_name,
              'file': out.name, 'sha256': digest(out), 'bytes': out.stat().st_size,
              'entrypoint': entrypoint, 'file_count': len(files)}
    (Path(destination) / (component + '-' + platform_name + '-artifact.json')).write_text(json.dumps(record, indent=2) + '\n')
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
        node_version = subprocess.check_output(['node', '--version'], text=True).strip().lstrip('v')
        if node_version != NODE_VERSION:
            raise RuntimeError('Unexpected Node runtime in builder')
        node_home = work / 'node'
        node_home.mkdir()
        node_file = 'node.exe' if os.name == 'nt' else 'node'
        shutil.copy2(shutil.which('node'), node_home / node_file)
        license_url = f'https://raw.githubusercontent.com/nodejs/node/v{NODE_VERSION}/LICENSE'
        provenance = [download(license_url, node_home / 'LICENSE')]
        provenance.append({'source': f'https://github.com/nodejs/node/tree/v{NODE_VERSION}',
                           'runtime_sha256': digest(node_home / node_file),
                           'acquired_by': 'actions/setup-node with exact version ' + NODE_VERSION})
        records.append(pack(destination, 'node', NODE_VERSION, platform_name, node_home, node_file, provenance))
        java_home, java_provenance = original_jdk(work, originals)
        records.append(pack(destination, 'jdk', '21.0.13+9', platform_name, java_home,
                            'bin/java.exe' if os.name == 'nt' else 'bin/java', java_provenance))
        if os.name == 'nt':
            compiler = Path(shutil.which('clang') or '').resolve()
            compiler_home = compiler.parent.parent
            if compiler.name.lower() != 'clang.exe' or not (compiler_home / 'lib/clang').is_dir():
                raise RuntimeError('The Windows LLVM distribution is missing')
            version_text = subprocess.check_output([str(compiler), '--version'], text=True)
            match = re.search(r'clang version (\d+\.\d+\.\d+)', version_text)
            if not match:
                raise RuntimeError('Cannot identify the native compiler')
            version = match.group(1)
            compiler_copy = work / 'llvm'
            shutil.copytree(compiler_home, compiler_copy, symlinks=False)
            license_record = download(f'https://raw.githubusercontent.com/llvm/llvm-project/llvmorg-{version}/llvm/LICENSE.TXT',
                                      compiler_copy / 'HA-UPSTREAM-LICENSE.txt')
            records.append(pack(destination, 'compiler', version, platform_name, compiler_copy, 'bin/clang.exe',
                                [license_record, {'source': f'https://github.com/llvm/llvm-project/tree/llvmorg-{version}',
                                  'version_output': version_text, 'runner_image': os.environ.get('ImageVersion', 'unknown'),
                                  'acquisition': 'LLVM distribution from the recorded GitHub Actions Windows image'}]))
        cloud_home = work / 'tunnel'
        cloud_home.mkdir()
        asset, expected = CLOUDFLARED[platform_name]
        url = 'https://github.com/cloudflare/cloudflared/releases/download/2026.10.4/' + asset
        provenance = [download(url, cloud_home / asset, expected)]
        if os.name != 'nt':
            (cloud_home / asset).chmod(0o755)
        provenance.append(download('https://raw.githubusercontent.com/cloudflare/cloudflared/2026.10.4/LICENSE', cloud_home / 'LICENSE'))
        records.append(pack(destination, 'tunnel', '2026.10.4', platform_name, cloud_home, asset, provenance))
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
            records.append(pack(destination, 'ghidra', '12.1.4', platform_name, work / pin['folder'],
                                'support/analyzeHeadless.bat' if os.name == 'nt' else 'support/analyzeHeadless',
                                [provenance, {'source': pin['source'], 'tag': pin['tag']}]))
    (destination / 'platform-inventory.json').write_text(json.dumps({'schema': 1, 'components': records}, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--ghidra', action='store_true')
    args = parser.parse_args()
    build(args.destination, include_ghidra=args.ghidra)
