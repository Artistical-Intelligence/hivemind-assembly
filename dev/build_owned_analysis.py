"""Build HA's internal analysis runtime from pinned source, without donor setup.

Dependency lifecycle hooks are disabled. The donor's Windows native safety
helper is cross-compiled through its supported Linux lane and verified again
on Windows. No user provider configuration, skills or updater is installed.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile
from acquire_donor_sources import preserve, SOURCES


def run(argv, cwd):
    env = dict(os.environ, npm_config_audit='false', npm_config_fund='false',
               npm_config_ignore_scripts='true', HUSKY='0', DO_NOT_TRACK='1',
               TURBO_TELEMETRY_DISABLED='1')
    if argv[0] == 'npm' and os.name == 'nt':
        npm = Path(shutil.which('npm') or '')
        cli = npm.parent / 'node_modules/npm/bin/npm-cli.js'
        if not cli.is_file():
            raise RuntimeError('Build Node/npm installation is incomplete')
        argv = [str(Path(shutil.which('node'))), str(cli), *argv[1:]]
    subprocess.run(argv, cwd=cwd, env=env, check=True, timeout=1200)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def source_tree(work):
    snapshots = work / 'sources'
    preserve(snapshots, ['rea'])
    archive = next(snapshots.glob('rea-*.zip'))
    with zipfile.ZipFile(archive) as z:
        z.extractall(work)  # Exact git archive, not user-supplied input.
    return work / 'rea', archive


def build_native(destination):
    if os.name == 'nt':
        raise RuntimeError('Windows native helper must be cross-built on Linux')
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ha-native-build-') as directory:
        source, _ = source_tree(Path(directory))
        run(['node', 'scripts/build-windows-native.mjs'], source)
        run(['node', 'scripts/verify-windows-native-artifact.mjs'], source)
        for path in (source / 'native/windows/build').iterdir():
            if path.is_file():
                shutil.copy2(path, destination / path.name)
        (destination / 'source-revision.txt').write_text(SOURCES['rea'][1] + '\n')


def build(destination, native_input=None):
    destination.mkdir(parents=True, exist_ok=True)
    platform = 'windows-x64' if os.name == 'nt' else 'linux-x64'
    with tempfile.TemporaryDirectory(prefix='ha-analysis-build-') as directory:
        work = Path(directory)
        source, archive = source_tree(work)
        run(['npm', 'ci', '--ignore-scripts', '--no-audit', '--no-fund'], source)
        run(['npm', 'run', 'compile', '--ignore-scripts'], source)
        if os.name == 'nt':
            if native_input is None or (native_input / 'source-revision.txt').read_text().strip() != SOURCES['rea'][1]:
                raise RuntimeError('A source-matched Windows native helper is required')
            for name in ('manifest.json', 'rea-windows-x64.node'):
                target = source / 'native/windows/build' / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(native_input / name, target)
            run(['node', 'scripts/verify-windows-native-artifact.mjs'], source)
        run(['npm', 'prune', '--omit=dev', '--omit=optional', '--ignore-scripts', '--no-audit', '--no-fund'], source)
        run(['node', 'scripts/rea.mjs', '--help'], source)
        package = work / 'package'
        package.mkdir()
        for name in ('package.json', 'package-lock.json', 'LICENSE', 'THIRD_PARTY_NOTICES.md',
                     'dist', 'bridge', 'licenses', 'node_modules', 'native', 'scripts'):
            src = source / name
            if not src.exists():
                continue
            if src.is_dir():
                shutil.copytree(src, package / name, symlinks=False,
                    ignore=shutil.ignore_patterns('.bin', '.cache', '*.test.*', '__pycache__'))
            else:
                shutil.copy2(src, package / name)
        files = {p.relative_to(package).as_posix(): digest(p) for p in sorted(package.rglob('*')) if p.is_file()}
        metadata = {'schema': 1, 'component': 'analysis', 'version': '6.7.0-ha.1',
                    'platform': platform, 'repository': SOURCES['rea'][0], 'revision': SOURCES['rea'][1],
                    'license': 'MIT', 'entrypoint': 'scripts/rea.mjs', 'files': files,
                    'build': {'node': subprocess.check_output(['node', '--version'], text=True).strip(),
                              'lifecycle_scripts': False, 'upstream_setup_executed': False,
                              'source_archive_sha256': digest(archive)}}
        out = destination / ('HA-analysis-6.7.0-ha.1-' + platform + '.zip')
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for rel in files:
                z.write(package / rel, 'payload/' + rel)
            z.writestr('component.json', json.dumps(metadata, indent=2) + '\n')
        shutil.copy2(source / 'package-lock.json', destination / ('analysis-' + platform + '-package-lock.json'))
        shutil.copy2(archive, destination / archive.name)
        record = {'component': 'analysis', 'version': metadata['version'], 'platform': platform,
                  'file': out.name, 'sha256': digest(out), 'bytes': out.stat().st_size,
                  'file_count': len(files), 'entrypoint': metadata['entrypoint'], 'revision': metadata['revision']}
        (destination / ('analysis-' + platform + '-artifact.json')).write_text(json.dumps(record, indent=2) + '\n')
        print(json.dumps(record), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--native-only', action='store_true')
    parser.add_argument('--native-input', type=Path)
    args = parser.parse_args()
    if args.native_only:
        build_native(args.destination)
    else:
        build(args.destination, args.native_input)
