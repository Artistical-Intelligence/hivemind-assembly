"""Verify a complete local installation payload using only Python's standard library.

This checks a build-owned manifest, not a signature or an operating-system sandbox.
No network calls, executable imports, package installers or repair side effects.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys

REQUIRED = frozenset({'node', 'jdk', 'analysis', 'ghidra', 'compiler', 'execution', 'connect', 'tunnel'})
HASH = re.compile(r'[a-f0-9]{64}\Z')


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def local_file(root, relative):
    if not isinstance(relative, str) or any(c in relative for c in ('\\', ':', '\x00')):
        raise ValueError('Invalid offline inventory path')
    path = PurePosixPath(relative)
    if not path.parts or path.is_absolute() or str(path) != relative or any(p in ('.', '..') for p in path.parts):
        raise ValueError('Invalid offline inventory path')
    target = Path(root)
    for part in path.parts:
        target = target / part
        if target.is_symlink() or (hasattr(target, 'is_junction') and target.is_junction()):
            raise ValueError('Redirected offline inventory path')
    if not target.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError('Offline inventory escaped application')
    return target


def read_json(path):
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError('Offline inventory is too large')
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('Duplicate offline inventory field')
            value[key] = item
        return value
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique)


def verify(app_root):
    root = Path(app_root).resolve()
    data = read_json(local_file(root, 'offline-manifest.json'))
    if not isinstance(data, dict) or data.get('schema') != 1 or data.get('platform') != 'windows-x64':
        raise ValueError('Unsupported offline installation')
    inventory = data.get('files')
    if not isinstance(inventory, dict) or not 1 <= len(inventory) <= 100000:
        raise ValueError('Missing offline file inventory')
    if len({name.casefold() for name in inventory}) != len(inventory):
        raise ValueError('Ambiguous offline file inventory')
    if set(data.get('required_components', [])) != REQUIRED:
        raise ValueError('Incomplete offline capability declaration')
    if data.get('requirements_sha256') != digest(local_file(root, 'requirements-windows.lock')):
        raise ValueError('Offline dependency lock does not match this application')
    if 'components/catalogue.json' not in inventory or not any(name.startswith('bootstrap/wheels/') for name in inventory):
        raise ValueError('Offline runtime dependencies are missing')
    if not any(name.startswith('browsers/') and name.endswith('/chrome.exe') for name in inventory):
        raise ValueError('Bundled browser is missing')
    for name, expected in inventory.items():
        if not isinstance(expected, str) or not HASH.fullmatch(expected):
            raise ValueError('Invalid offline file digest')
        path = local_file(root, name)
        if not path.is_file() or digest(path) != expected:
            raise ValueError('Offline file missing or changed: ' + name)
    # This module imports only the standard library; no model is loaded here.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from hivemind_assembly.learning.vectors import FILES, MODEL_ID, REVISION
    if data.get('search_model_revision') != REVISION:
        raise ValueError('Offline search model revision does not match HA')
    for name, (_, expected, _) in FILES.items():
        if inventory.get('models/' + MODEL_ID + '/' + name) != expected:
            raise ValueError('Offline search model is incomplete')
    catalogue = read_json(local_file(root, 'components/catalogue.json'))
    if not isinstance(catalogue, dict) or catalogue.get('schema') != 1 or not isinstance(catalogue.get('components'), list):
        raise ValueError('Invalid offline component catalogue')
    entries = catalogue['components']
    selected = {item['component']: item for item in entries if item.get('platform') in ('windows-x64', 'any')}
    if len(selected) != sum(item.get('platform') in ('windows-x64', 'any') for item in entries):
        raise ValueError('Ambiguous offline component catalogue')
    if not REQUIRED <= selected.keys():
        raise ValueError('Offline catalogue lacks a required capability')
    for item in selected.values():
        if inventory.get('components/' + item['file']) != item['sha256']:
            raise ValueError('Component archive is absent from the offline inventory')
    return {'verified': True, 'files': len(inventory), 'network_used': False,
            'requirements_sha256': data['requirements_sha256']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-root', type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    print(json.dumps(verify(args.app_root)))
