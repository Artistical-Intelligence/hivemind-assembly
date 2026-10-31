"""Collect pinned first-launch assets in the build environment, never at runtime."""
from __future__ import annotations
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '_app'))
from offline_bootstrap import digest
from hivemind_assembly.learning.vectors import FILES, MODEL_ID, REVISION, SOURCE


def prepare(destination):
    if os.name != 'nt':
        raise RuntimeError('The offline browser and wheel payload must be prepared on Windows')
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    wheels, browser, model = (destination / name for name in ('wheels', 'browser', 'model'))
    wheels.mkdir(exist_ok=True)
    model.mkdir(exist_ok=True)
    lock = ROOT / '_app/requirements-windows.lock'
    match = re.search(r'^playwright==([^\s]+)', lock.read_text(), re.M)
    if not match or importlib.metadata.version('playwright') != match[1]:
        raise RuntimeError('The browser builder must use HA\'s pinned Playwright version')
    subprocess.run([sys.executable, '-m', 'pip', '--isolated', 'download',
                    '--disable-pip-version-check', '--only-binary=:all:', '--require-hashes',
                    '--no-deps', '--find-links', str(ROOT / '_app/bootstrap/wheels'),
                    '-r', str(lock), '--dest', str(wheels)], check=True, timeout=900)
    env = dict(os.environ, PLAYWRIGHT_BROWSERS_PATH=str(browser), DO_NOT_TRACK='1')
    subprocess.run([sys.executable, '-m', 'playwright', 'install', 'chromium'],
                   env=env, check=True, timeout=900)
    provenance = []
    for name, (remote, expected, size) in FILES.items():
        target = model / name
        url = SOURCE.format(revision=REVISION, path=remote)
        if not target.is_file() or target.stat().st_size != size or digest(target) != expected:
            pending = target.with_suffix('.download')
            request = urllib.request.Request(url, headers={'User-Agent': 'HA-offline-builder'})
            try:
                total = 0
                with urllib.request.urlopen(request, timeout=120) as response, pending.open('wb') as out:
                    for chunk in iter(lambda: response.read(1024 * 1024), b''):
                        total += len(chunk)
                        if total > size:
                            raise RuntimeError('Search model exceeded its pinned size')
                        out.write(chunk)
                if total != size or digest(pending) != expected:
                    raise RuntimeError('Search model failed pinned integrity verification')
                pending.replace(target)
            finally:
                pending.unlink(missing_ok=True)
        provenance.append({'file': name, 'url': url, 'sha256': expected, 'bytes': size})
    # The pinned model card declares Apache-2.0; that snapshot has no LICENSE file.
    for name, url in (('README.md', SOURCE.format(revision=REVISION, path='README.md')),
                      ('LICENSE-APACHE-2.0.txt', 'https://www.apache.org/licenses/LICENSE-2.0.txt')):
        request = urllib.request.Request(url, headers={'User-Agent': 'HA-offline-builder'})
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            raise RuntimeError('Model attribution document is too large')
        if name == 'README.md' and not re.search(rb'^license:\s*apache-2.0\s*$', data, re.M):
            raise RuntimeError('The retained model license declaration needs review')
        (model / name).write_bytes(data)
        provenance.append({'file': name, 'url': url, 'sha256': digest(model / name), 'bytes': len(data)})
    record = {'requirements_sha256': digest(lock), 'playwright_version': match[1],
              'search_model': MODEL_ID, 'revision': REVISION, 'sources': provenance,
              'files': {p.relative_to(destination).as_posix(): digest(p)
                        for p in sorted(destination.rglob('*')) if p.is_file() and '.links' not in p.parts}}
    (destination / 'asset-provenance.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'prepared': True, 'files': len(record['files']), 'runtime_download_required': False}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    prepare(parser.parse_args().destination)
