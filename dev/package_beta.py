"""Package the owner-authorized beta from the exact passing offline payload.

Stable release approval is unchanged. Pending review markers are retained. Only
release identity/documentation may differ from the tested application snapshot;
any application-code difference requires new acceptance rather than a shortcut.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MAX_ASSET = 2 * 1024**3


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def request():
    data = json.loads((ROOT / 'dev/beta_release_request.json').read_text(encoding='utf-8'))
    if (data.get('schema') != 1 or data.get('channel') != 'beta'
            or data.get('owner_testing_beta_authorized') is not True
            or not re.fullmatch(r'\d+\.\d+\.\d+-beta\.\d+', data.get('version', ''))
            or data.get('independent_review_complete') is not False):
        raise ValueError('An explicit, beta-only publication request is required')
    return data


def safe_extract(archive, destination):
    destination.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(archive) as z:
        seen = set()
        total = 0
        for entry in z.infolist():
            name = entry.filename.rstrip('/')
            path = PurePosixPath(name)
            if (not name or path.is_absolute() or str(path) != name
                    or '..' in path.parts or any(c in name for c in ('\\', ':', '\0'))
                    or path.parts[0] != 'Hivemind_Assembly'
                    or name.casefold() in seen
                    or stat.S_ISLNK(entry.external_attr >> 16)):
                raise ValueError('Invalid retained archive member')
            seen.add(name.casefold())
            total += entry.file_size
            if total > 20 * 1024**3:
                raise ValueError('Retained payload exceeds the build limit')
        z.extractall(destination)
    return destination / 'Hivemind_Assembly'


def stage(inputs, destination, output):
    data = request()
    archives = list(Path(inputs).rglob('HA-offline-acceptance-input.zip'))
    records = list(Path(inputs).rglob('tested-source.json'))
    if len(archives) != 1 or len(records) != 1:
        raise ValueError('Expected one preserved acceptance input and source receipt')
    record = json.loads(records[0].read_text(encoding='utf-8'))
    if (record.get('commit') != data['tested_application_commit']
            or record.get('component_build_commit') != data['component_build_commit']
            or record.get('component_build_run') != data['component_build_run']
            or record.get('archive_sha256') != digest(archives[0])):
        raise ValueError('Retained offline input does not match its tested source')
    # This proves that reusing the passing payload is still justified. Only
    # status/documentation changes are permitted in the application's tree.
    changed = subprocess.check_output(
        ['git', 'diff', '--name-only', data['tested_application_commit'], 'HEAD',
         '--', '_app', 'Start_Hivemind_Assembly.cmd'], cwd=ROOT, text=True).splitlines()
    allowed = [p for p in changed if p == '_app/release_status.json' or Path(p).name == 'STATUS.md']
    if sorted(changed) != sorted(allowed):
        raise ValueError('Application changed since offline acceptance: ' + ', '.join(changed))
    package = safe_extract(archives[0], Path(destination))
    app = package / '_app'
    for name in [*allowed, 'README.md']:
        source = ROOT / name
        target = package / name
        if source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    version = data['version']
    status_path = app / 'release_status.json'
    status_data = json.loads(status_path.read_text(encoding='utf-8'))
    base_version = status_data['version']
    status_data.update(version=version, requested_product_complete=False,
                       beta_publication={'owner_testing_authorized': True,
                                         'independent_review_complete': False,
                                         'remaining_testing': data['remaining_testing']})
    status_path.write_text(json.dumps(status_data, indent=2) + '\n', encoding='utf-8')
    init = app / 'hivemind_assembly/__init__.py'
    content = init.read_text(encoding='utf-8')
    old = '__version__ = ' + json.dumps(base_version)
    if content.count(old) != 1:
        raise ValueError('Unexpected application version declaration')
    init.write_text(content.replace(old, '__version__ = ' + json.dumps(version)), encoding='utf-8')
    spec = importlib.util.spec_from_file_location('beta_status_docs', ROOT / 'dev/status_docs.py')
    docs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(docs)
    readme = package / 'README.md'
    text = readme.read_text(encoding='utf-8').replace('Current version: ' + base_version,
                                                    'Current version: ' + version)
    readme.write_text(docs.apply(text, docs.render(status_data)), encoding='utf-8')
    instructions = (
        '# Hivemind Assembly ' + version + '\n\n'
        'Owner-authorized beta for testing, not a production release.\n\n'
        'Download the Setup.exe and every matching Setup-*.bin file into the same '
        'folder, then run Setup.exe. No separate Java, Node, Ghidra, REA or Hermes '
        'installation is needed. Keep all installer files for offline recovery.\n\n'
        'Close HA before installing. Use HA\'s Back up now first when upgrading. '
        'Application files are replaced; projects, settings, profiles and histories '
        'in %LOCALAPPDATA%\\UnifiedWorkbench are retained. No automatic downgrade '
        'of user databases is promised.\n\n'
        'First launch prepares the bundled local runtime. In Settings, select '
        'Prepare HA, then Check installation. Hosted AI accounts and remote access '
        'still require internet access and your sign-in.\n\n'
        'The installer is unsigned. Verify SHA256SUMS.txt before deciding whether '
        'to accept a Windows publisher warning.\n\n'
        'Still to test/review:\n' + ''.join('- ' + x + '\n' for x in data['remaining_testing'])
    )
    (package / 'BETA_README.md').write_text(instructions, encoding='utf-8')
    (package / 'ACCEPTANCE_ONLY.txt').write_text(
        'Owner-authorized beta based on the passing offline acceptance input. '
        'Independent review and live-account acceptance remain pending. '
        'Not production-approved. See BETA_README.md.\n', encoding='utf-8')
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    provenance = {'version': version, 'release_source_commit': commit,
                  'tested_application_commit': data['tested_application_commit'],
                  'offline_run': data['offline_run'], 'offline_artifact_id': data['offline_artifact_id'],
                  'retained_archive_sha256': record['archive_sha256'],
                  'component_build_commit': data['component_build_commit'],
                  'component_build_run': data['component_build_run'],
                  'runtime_changes': 'Release version metadata only; application code is unchanged.',
                  'metadata_updates': allowed, 'stable_release_approved': False,
                  'independent_review_complete': False}
    (app / 'beta-build.json').write_text(json.dumps(provenance, indent=2) + '\n', encoding='utf-8')
    manifest_path = app / 'package_manifest.json'
    files = {p.relative_to(package).as_posix(): digest(p)
             for p in sorted(package.rglob('*'))
             if p.is_file() and p != manifest_path and '__pycache__' not in p.parts}
    manifest_path.write_text(json.dumps({'version': version, 'kind': 'Windows', 'files': files}, indent=2) + '\n', encoding='utf-8')
    subprocess.run([os.sys.executable, str(app / 'offline_bootstrap.py'), '--app-root', str(app)],
                   check=True, timeout=180)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    shutil.copy2(package / 'BETA_README.md', output / 'BETA_README.md')
    shutil.copy2(app / 'beta-build.json', output / 'build-provenance.json')
    installer = (ROOT / 'dev/installer.iss').read_text(encoding='utf-8')
    installer = installer.replace('Compression=lzma2/max', 'Compression=lzma2/fast')
    installer = installer.replace('SolidCompression=yes',
        'SolidCompression=no\nDiskSpanning=yes\nDiskSliceSize=1500000000\nDiskClusterSize=1\nSlicesPerDisk=1\nVersionInfoVersion=0.38.0.1')
    installer = installer.replace(
        'The first start prepares its private Python runtime and needs internet access.',
        'This beta includes the local runtime and analysis components. Hosted AI and remote access still need internet access.')
    (output / 'beta-installer.iss').write_text(installer, encoding='utf-8')
    print(json.dumps({'package': str(package), 'version': version, 'provenance': provenance}))


def finalize(output):
    data = request()
    folder = Path(output)
    report = json.loads((folder / 'offline-acceptance.json').read_text(encoding='utf-8'))
    if report.get('passed') is not True:
        raise ValueError('Installed beta offline acceptance did not pass')
    packages = sorted([*folder.glob('*_Setup.exe'), *folder.glob('*_Setup-*.bin')])
    if sum(p.suffix == '.exe' for p in packages) != 1 or not any(p.suffix == '.bin' for p in packages):
        raise ValueError('The complete split installer is missing')
    if any(p.stat().st_size >= MAX_ASSET for p in packages):
        raise ValueError('An installer asset exceeds GitHub\'s limit')
    public = packages + [folder / name for name in
                         ('BETA_README.md', 'build-provenance.json', 'offline-acceptance.json',
                          'installer-acceptance.json', 'beta-tests.xml')]
    sums = '\n'.join(digest(p) + '  ' + p.name for p in public) + '\n'
    (folder / 'SHA256SUMS.txt').write_text(sums, encoding='utf-8')
    version = data['version']
    base = 'https://github.com/Artistical-Intelligence/hivemind-assembly/releases/download/v' + version + '/'
    downloads = '\n'.join('- [' + p.name + '](' + base + p.name + ')' for p in packages)
    notes = ('## Hivemind Assembly ' + version + '\n\n'
             '**Beta for owner testing. This is the new unified, offline-capable build, '
             'not the earlier 0.37.4 installer.**\n\n'
             '### Install\nDownload **all three installer files** below into the same '
             'folder, then run the `.exe`. Keep the `.bin` names unchanged.\n\n' + downloads + '\n\n'
             'Close HA and use **Back up now** before upgrading. The installer updates '
             'application files and retains user data in `%LOCALAPPDATA%\\UnifiedWorkbench`. '
             'It is unsigned; hashes are provided in `SHA256SUMS.txt`.\n\n'
             '### Included\nOne **Settings → Prepare HA** flow, built-in sessions and task '
             'storage, browser automation, guarded process execution and patch editing, '
             'and the bundled analysis/build/browser/search dependencies. The selected '
             'remote-access implementations are included; live interoperability is not yet accepted.\n\n'
             '### Verified for this package\nInstalled Windows beta: local-only bootstrap, '
             'all seven offline acceptance groups, actual analysis and execution, local '
             'search, bundled dashboard, reinstall and uninstall with user-data preservation. '
             'The beta build retests the corrected cross-platform documentation fixture. '
             'Prior real execution/patch tests passed 79 tests per platform. '
             'These are not live model or real remote-account acceptance.\n\n'
             '### Remaining beta checks\n' + ''.join('- ' + x + '\n' for x in data['remaining_testing']) + '\n'
             'Pending source-review markers remain. This owner-authorized prerelease '
             'does not mark them resolved, replace the stable release, or claim the full '
             'requested product is finished. Exact source and component provenance are attached.\n')
    if len(packages) != 3:
        notes = notes.replace('all three installer files', 'all ' + str(len(packages)) + ' installer files')
    (folder / 'release-notes.md').write_text(notes, encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', type=Path)
    parser.add_argument('--stage', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--finalize', action='store_true')
    args = parser.parse_args()
    if args.finalize:
        finalize(args.output)
    else:
        if args.inputs is None or args.stage is None:
            parser.error('--inputs and --stage are required')
        stage(args.inputs, args.stage, args.output)
