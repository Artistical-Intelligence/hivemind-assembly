"""Windows acceptance for the actual one-file installer, not a download mock.

Local HTTP fixtures use a separately compiled test binary. Production URLs cannot
be overridden at runtime. The real-payload tier downloads the published beta,
installs it, verifies its files, reuses cache and repairs a changed cached EXE.
"""
from __future__ import annotations
import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

from build_online_installer import ROOT, compile_script, digest, validate_request


def run_installer(executable, cache, destination, log, *, timeout=300):
    process = subprocess.Popen([str(executable), '/VERYSILENT', '/SUPPRESSMSGBOXES',
        '/NORESTART', '/NOICONS', '/CACHE=' + str(cache), '/DIR=' + str(destination),
        '/LOG=' + str(log)])
    try:
        code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, timeout=20)
        raise AssertionError('The installer did not complete within its acceptance timeout') from None
    raw = Path(log).read_bytes() if Path(log).exists() else b''
    text = raw.decode('utf-16' if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig', errors='replace')
    return code, text


def assert_cache(cache, assets):
    for asset in assets:
        path = cache / asset['name']
        assert path.is_file() and path.stat().st_size == asset['size']
        assert digest(path) == asset['sha256']


def fixtures(iscc, work):
    work.mkdir(parents=True)
    source = work / 'child.cs'
    source.write_text('''using System; using System.IO;
class Child {
  static int Main(string[] args) {
    string dir = null;
    foreach (string arg in args) if (arg.StartsWith("/DIR=", StringComparison.OrdinalIgnoreCase)) dir = arg.Substring(5).Trim('"');
    if (dir == null) return 10;
    if (dir.EndsWith("fail-child")) return 9;
    Directory.CreateDirectory(dir); File.WriteAllText(Path.Combine(dir, "installed.txt"), "verified-child");
    return 0;
  }
}''', encoding='utf-8')
    csc = Path(os.environ['WINDIR']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    child = work / 'child.exe'
    subprocess.run([str(csc), '/nologo', '/target:exe', '/out:' + str(child), str(source)], check=True, timeout=60)
    data = json.loads((ROOT / 'dev/online_installer_request.json').read_text())
    bodies = {}
    for index, item in enumerate(data['assets']):
        content = child.read_bytes() if index == 0 else bytes([index]) * (256 * 1024)
        bodies[item['name']] = content
        import hashlib
        item['size'], item['sha256'] = len(content), hashlib.sha256(content).hexdigest()
    requests, mode = [], {'value': 'normal'}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            name = unquote(self.path.lstrip('/'))
            requests.append(name)
            if mode['value'] == 'offline':
                self.send_error(503); return
            if name not in bodies:
                self.send_error(404); return
            value = bodies[name]
            second = name == data['assets'][1]['name']
            if second and mode['value'] == 'corrupt':
                value = b'X' + value[1:]
            self.send_response(200)
            self.send_header('Content-Length', str(len(value)))
            self.send_header('Connection', 'close')
            self.end_headers()
            if second and mode['value'] == 'truncate':
                self.wfile.write(value[:1024]); self.wfile.flush(); self.close_connection = True
            else:
                self.wfile.write(value)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    results = []
    try:
        setup = compile_script(data, (ROOT / 'dev/online_installer.iss').read_text(),
            work / 'compiled', iscc, fixture_base='http://127.0.0.1:' + str(server.server_port) + '/')
        cache, installed = work / 'cache with spaces', work / 'installed with spaces'
        code, text = run_installer(setup, cache, installed, work / 'fresh.log')
        assert code == 0 and (installed / 'installed.txt').read_text() == 'verified-child', text
        assert_cache(cache, data['assets'])
        assert len(requests) == len(data['assets'])
        results.append('compiled_download_hash_verification_and_child_launch')
        mode['value'] = 'offline'
        requests.clear()
        code, text = run_installer(setup, cache, installed, work / 'reuse.log')
        assert code == 0 and not requests and 'HA_DOWNLOAD ' not in text, text
        results.append('offline_cache_reuse_without_http_requests')
        damaged = cache / data['assets'][1]['name']
        damaged.write_bytes(b'changed-by-fixture')
        (installed / 'installed.txt').unlink()
        code, text = run_installer(setup, cache, installed, work / 'damaged-offline.log')
        assert code != 0 and not (installed / 'installed.txt').exists() and 'HA_CHILD_START' not in text, text
        assert any(p.read_bytes() == b'changed-by-fixture' for p in cache.glob('*.rejected-*'))
        results.append('changed_cache_blocks_execution_and_retains_rejected_bytes')
        mode['value'] = 'normal'
        requests.clear()
        code, text = run_installer(setup, cache, installed, work / 'repair.log')
        assert code == 0 and requests == [data['assets'][1]['name']], text
        assert_cache(cache, data['assets'])
        results.append('repair_downloads_only_the_missing_or_changed_file')
        for scenario in ('corrupt', 'truncate'):
            mode['value'] = scenario
            target = work / ('no-install-' + scenario)
            failed_cache = work / ('cache-' + scenario)
            code, text = run_installer(setup, failed_cache, target, work / (scenario + '.log'), timeout=90)
            assert code != 0 and not (target / 'installed.txt').exists() and 'HA_CHILD_START' not in text, text
            assert digest(failed_cache / data['assets'][0]['name']) == data['assets'][0]['sha256']
            results.append(scenario + '_download_never_executes_and_keeps_completed_files')
        mode['value'] = 'offline'
        code, text = run_installer(setup, cache, work / 'fail-child', work / 'child-failure.log')
        assert code != 0 and 'HA_INSTALL_COMPLETE' not in text and 'code 9' in text, text
        results.append('child_installation_failure_is_not_reported_as_success')
        code, text = run_installer(setup, cache, cache / 'app', work / 'overlap.log')
        assert code != 0 and 'HA_CHILD_START' not in text, text
        results.append('cache_and_application_must_be_separate')
        junction = work / 'linked-cache'
        outside = work / 'not-owned-by-installer'
        outside.mkdir()
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(junction), str(outside)], check=True, capture_output=True)
        code, text = run_installer(setup, junction, work / 'linked-install', work / 'junction.log')
        assert code != 0 and not list(outside.iterdir()) and 'HA_CHILD_START' not in text, text
        results.append('junction_redirected_cache_rejected')
        # Existing offline files beside the small EXE are copied, not consumed.
        for item in data['assets']:
            (setup.parent / item['name']).write_bytes(bodies[item['name']])
        requests.clear()
        code, text = run_installer(setup, work / 'imported-cache', work / 'imported-app', work / 'import.log')
        assert code == 0 and not requests, text
        assert all((setup.parent / a['name']).is_file() for a in data['assets'])
        results.append('offline_files_beside_setup_are_reused_without_moving_originals')
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
    return results


def real_payload(setup, work):
    work.mkdir(parents=True)
    data = validate_request(json.loads((ROOT / 'dev/online_installer_request.json').read_text()))
    cache, installed = work / 'retained offline installer', work / 'HA installed with spaces'
    user_data = Path(os.environ['LOCALAPPDATA']) / 'UnifiedWorkbench'
    user_data.mkdir(exist_ok=True)
    sentinel = user_data / 'online-installer-acceptance-canary.txt'
    if sentinel.exists(): raise AssertionError('Fresh CI test canary already exists')
    sentinel.write_text('retained-owner-state')
    code, text = run_installer(setup, cache, installed, work / 'online-first-install.log', timeout=1200)
    assert code == 0 and 'HA_INSTALL_COMPLETE' in text, text[-5000:]
    assert text.count('HA_DOWNLOAD ') == len(data['assets']), 'Real payload was not fetched by the installer'
    assert_cache(cache, data['assets'])
    assert (cache / 'OFFLINE-SHA256SUMS.txt').is_file()
    assert (cache / 'OFFLINE-README.txt').is_file()
    app = installed / '_app'
    manifest = json.loads((app / 'package_manifest.json').read_text())
    for relative, expected in manifest['files'].items():
        assert digest(installed / relative) == expected, relative
    subprocess.run([sys.executable, str(app / 'offline_bootstrap.py'), '--app-root', str(app)],
                   check=True, timeout=180)
    assert sentinel.read_text() == 'retained-owner-state'
    code, text = run_installer(setup, cache, installed, work / 'cached-reinstall.log', timeout=600)
    assert code == 0 and 'HA_DOWNLOAD ' not in text, text[-5000:]
    assert sentinel.read_text() == 'retained-owner-state'
    # Only the small cached offline EXE is damaged; large payloads must be reused.
    (cache / data['assets'][0]['name']).write_bytes(b'changed-cache-exe')
    code, text = run_installer(setup, cache, installed, work / 'real-repair.log', timeout=600)
    assert code == 0 and text.count('HA_DOWNLOAD ') == 1, text[-5000:]
    assert data['assets'][0]['name'] in text
    assert_cache(cache, data['assets'])
    assert any(p.read_bytes() == b'changed-cache-exe' for p in cache.glob('*.rejected-*'))
    uninstaller = next(installed.glob('unins*.exe'))
    subprocess.run([str(uninstaller), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'], check=True, timeout=120)
    deadline = time.monotonic() + 60
    while app.exists() and time.monotonic() < deadline: time.sleep(0.25)
    assert not app.exists()
    assert sentinel.read_text() == 'retained-owner-state'
    assert_cache(cache, data['assets'])
    return {'actual_github_download': True, 'payload_bytes': sum(a['size'] for a in data['assets']),
            'package_manifest_files_verified': len(manifest['files']),
            'offline_payload_integrity': True, 'cached_reinstall_no_downloads': True,
            'selective_corrupt_cache_repair': True, 'uninstall_keeps_cache_and_user_data': True,
            'runtime_unchanged': True, 'owner_desktop_test': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--setup', type=Path, required=True)
    parser.add_argument('--iscc', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if os.name != 'nt' or os.environ.get('GITHUB_ACTIONS') != 'true':
        raise RuntimeError('This installer acceptance run is restricted to disposable Windows CI')
    args.output.mkdir(parents=True, exist_ok=True)
    report = {'schema': 1, 'commit': os.environ.get('GITHUB_SHA'), 'passed': False,
              'installer_sha256': digest(args.setup), 'independent_review_complete': False}
    path = args.output / 'online-installer-acceptance.json'
    try:
        report['compiled_fixture_checks'] = fixtures(args.iscc, args.output / 'fixtures')
        report['actual_published_beta'] = real_payload(args.setup.resolve(), args.output / 'real')
        report['passed'] = True
    finally:
        path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
