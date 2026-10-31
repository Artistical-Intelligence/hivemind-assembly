"""Assemble already-built components into a local-only HA Windows installation.

This is an assembly/checking step, not an upstream downloader. Required packages,
locked wheels, browser files and the local search model must all be present.
The release-review gate is separate; assembly alone never approves a release.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '_app'))
from offline_bootstrap import REQUIRED, digest, local_file, verify
from hivemind_assembly.application.components import Components, relative_path
from hivemind_assembly.learning.vectors import FILES, MODEL_ID, REVISION


def copy_checked(source, target, expected=None):
    source, target = Path(source), Path(target)
    if source.is_symlink() or not source.is_file():
        raise ValueError('Only regular build artifacts may be assembled')
    actual = digest(source)
    if expected is not None and expected != actual:
        raise ValueError('Artifact digest mismatch: ' + source.name)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.is_symlink() or digest(target) != actual:
            raise ValueError('Existing application file preserved: ' + str(target))
        return actual
    with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.assembling-', delete=False) as out:
        pending = Path(out.name)
        try:
            with source.open('rb') as inp:
                shutil.copyfileobj(inp, out, 1024 * 1024)
        except BaseException:
            pending.unlink(missing_ok=True)
            raise
    try:
        if digest(pending) != actual:
            raise ValueError('Artifact changed during assembly')
        pending.replace(target)
    finally:
        pending.unlink(missing_ok=True)
    return actual


def locked_wheels(lock, folder):
    pins = {}
    for line in Path(lock).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        match = re.fullmatch(r'([A-Za-z0-9_.-]+)==([^\s]+)((?:\s+--hash=sha256:[a-f0-9]{64})+)', line)
        if not match:
            raise ValueError('Unsupported offline lock syntax')
        name = re.sub(r'[-_.]+', '_', match[1]).lower()
        key = (name, match[2])
        if key in pins:
            raise ValueError('Duplicate pinned requirement')
        pins[key] = set(re.findall(r'sha256:([a-f0-9]{64})', match[3]))
    found = {}
    for path in sorted(Path(folder).glob('*.whl')):
        parts = path.name.split('-')
        if len(parts) < 5:
            continue
        key = (parts[0].lower(), parts[1])
        if key not in pins:
            continue
        actual = digest(path)
        if actual not in pins[key]:
            raise ValueError('Wheel does not match the pinned lock: ' + path.name)
        found.setdefault(key, []).append((path, actual))
    absent = pins.keys() - found.keys()
    if absent:
        raise ValueError('Offline Python packages missing: ' + ', '.join(name for name, _ in sorted(absent)))
    return [item for key in sorted(found) for item in found[key]]


def assemble(app_root, component_folders, wheel_folder, browser_folder, model_folder):
    app = Path(app_root).resolve()
    if (app / 'offline-manifest.json').exists():
        raise ValueError('Use a fresh build tree; the previous offline installation is preserved')
    wheels = locked_wheels(app / 'requirements-windows.lock', wheel_folder)
    selected = {}
    for folder in component_folders:
        for path in sorted(Path(folder).rglob('*-artifact.json')):
            entry = json.loads(path.read_text(encoding='utf-8'))
            if entry.get('platform') not in ('windows-x64', 'any'):
                continue
            name = entry['component']
            relative_path(entry['file'])
            source = local_file(path.parent, entry['file'])
            if name in selected and entry != selected[name][0]:
                raise ValueError('Conflicting component versions: ' + name)
            selected[name] = (entry, source)
    if not REQUIRED <= selected.keys():
        raise ValueError('Required components missing: ' + ', '.join(sorted(REQUIRED - selected.keys())))
    browser = Path(browser_folder).resolve()
    browser_files = [p for p in sorted(browser.rglob('*')) if p.is_file() and '.links' not in p.relative_to(browser).parts]
    if not any(p.name == 'chrome.exe' for p in browser_files):
        raise ValueError('The matching Windows Chromium distribution is missing')
    model = Path(model_folder).resolve()
    for name, (_, expected, size) in FILES.items():
        path = local_file(model, name)
        if not path.is_file() or path.stat().st_size != size or digest(path) != expected:
            raise ValueError('Pinned search model missing or changed: ' + name)
    inventory = {}
    packages = app / 'components'
    packages.mkdir(exist_ok=True)
    entries = [selected[name][0] for name in sorted(selected)]
    for entry, source in selected.values():
        rel = 'components/' + entry['file']
        inventory[rel] = copy_checked(source, local_file(app, rel), entry['sha256'])
    catalogue = packages / 'catalogue.json'
    content = json.dumps({'schema': 1, 'components': entries}, indent=2) + '\n'
    if catalogue.exists() and catalogue.read_text() != content:
        raise ValueError('Existing component catalogue preserved')
    catalogue.write_text(content, encoding='utf-8')
    inventory['components/catalogue.json'] = digest(catalogue)
    # Exercise the same archive/path/inventory validation used by actual setup.
    # One temporary installation at a time bounds extra disk usage.
    for name in selected:
        with tempfile.TemporaryDirectory(prefix='ha-package-check-') as temporary:
            manager = Components(temporary, packages, platform_name='windows-x64')
            manager.prepare([name])
            manager.resolve(name)
    for source, expected in wheels:
        rel = 'bootstrap/wheels/' + source.name
        inventory[rel] = copy_checked(source, local_file(app, rel), expected)
    for source in browser_files:
        rel = 'browsers/' + relative_path(source.relative_to(browser).as_posix())
        inventory[rel] = copy_checked(source, local_file(app, rel))
    for source in sorted(model.iterdir()):
        if source.is_file():
            rel = 'models/' + MODEL_ID + '/' + relative_path(source.name)
            inventory[rel] = copy_checked(source, local_file(app, rel))
    manifest = {'schema': 1, 'platform': 'windows-x64', 'required_components': sorted(REQUIRED),
                'requirements_sha256': digest(app / 'requirements-windows.lock'),
                'search_model_revision': REVISION, 'files': inventory,
                'release_approved': False, 'live_provider_acceptance': False}
    path = app / 'offline-manifest.json'
    path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    try:
        result = verify(app)
    except BaseException:
        path.unlink()
        raise
    (app / 'bootstrap/offline-required').write_text('HA local installation payload v1\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-root', type=Path, default=ROOT / '_app')
    parser.add_argument('--components', type=Path, action='append', required=True)
    parser.add_argument('--wheels', type=Path, required=True)
    parser.add_argument('--browser', type=Path, required=True)
    parser.add_argument('--model', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(assemble(args.app_root, args.components, args.wheels, args.browser, args.model)))
