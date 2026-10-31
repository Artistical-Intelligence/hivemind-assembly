"""Exercise a fresh local HA installation; hosted services are not accepted here."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import socket
import sys
import threading
import zipfile


def preservation_fixture(data_root):
    """Create only the test-owned file; fresh state need not have a private folder."""
    canary = Path(data_root) / 'private/offline-preservation-canary.txt'
    canary.parent.mkdir(parents=True, exist_ok=True)
    with canary.open('x', encoding='utf-8') as stream:
        stream.write('retained-local-owner-data')
    return canary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-root', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--programs', action='store_true')
    args = parser.parse_args()
    app_root, data_root = args.app_root.resolve(), args.data_root.resolve()
    sys.path.insert(0, str(app_root))
    from offline_bootstrap import local_file, verify
    integrity = verify(app_root)
    if args.programs:
        programs = {data_root / 'runtime-python312/python.exe', data_root / 'runtime-python312/pythonw.exe'}
        catalogue = json.loads((app_root / 'components/catalogue.json').read_text())
        for entry in catalogue['components']:
            archive = local_file(app_root / 'components', entry['file'])
            with zipfile.ZipFile(archive) as z:
                metadata = json.loads(z.read('component.json'))
            payload = data_root / 'components/objects' / entry['sha256'] / 'payload'
            for name in metadata['files']:
                if name.lower().endswith('.exe'):
                    programs.add(local_file(payload, name))
        programs.update(p for p in (app_root / 'browsers').rglob('*.exe') if p.is_file())
        print(json.dumps(sorted(str(p) for p in programs)))
        return 0
    if os.name != 'nt' or os.environ.get('GITHUB_ACTIONS') != 'true' or args.report is None:
        raise RuntimeError('This acceptance command is restricted to the dedicated Windows CI job')
    report = {'schema': 1, 'commit': os.environ.get('GITHUB_SHA'), 'checks': {},
              'release_approved': False, 'hosted_service_acceptance': False,
              'network_boundary': 'CI program-scoped outbound firewall; localhost remains available'}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    def save():
        args.report.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    def check(name, operation):
        try:
            result = operation()
            if result is False:
                raise AssertionError('Acceptance condition failed')
            report['checks'][name] = {'passed': True, 'evidence': result}
        except Exception as error:
            report['checks'][name] = {'passed': False, 'error': str(error)[:2000]}
        save()
    def network_blocked():
        try:
            connection = socket.create_connection(('1.1.1.1', 443), timeout=2)
        except OSError:
            return {'external_connection_blocked': True}
        else:
            connection.close()
            raise AssertionError('The offline test runtime can still reach the internet')
    check('network_boundary_probe', network_blocked)
    if not report['checks']['network_boundary_probe']['passed']:
        return 1
    check('local_payload_integrity', lambda: integrity)
    from hivemind_assembly.application.app import Application, make_server
    from hivemind_assembly.learning.vectors import VectorIndex
    app = Application(data_root)
    try:
        canary = preservation_fixture(data_root)
        def prepare():
            result = app.builtins.run('prepare')
            if result['state'] != 'ready':
                report['foundation_details'] = result
                raise AssertionError('One or more real local foundation checks failed')
            return result
        check('built_in_preparation_and_foundations', prepare)
        def execution():
            result = app.broker.jobs.run('offline-runtime',
                [sys.executable, '-c', 'print("ha-owned-runtime")'], data_root, timeout=10)
            assert result['status'] == 'completed' and result['exit_code'] == 0
            assert result['output'].strip() == 'ha-owned-runtime'
            assert app.builtins.execution_runtime() is not None
            return {'owned_helper_used': True}
        check('actual_execution_route', execution)
        def search_model():
            import numpy
            index = VectorIndex(app.store)
            index.download()
            result = index.embedder().embed(['Local HA search', 'Retained offline knowledge'])
            assert result.shape == (2, 384) and numpy.isfinite(result).all()
            return {'local_model_loaded': True, 'dimensions': 384}
        check('local_search_model', search_model)
        def dashboard():
            from playwright.sync_api import sync_playwright, expect
            server = make_server(app, 0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            rejected = []
            try:
                with sync_playwright() as browser_api:
                    browser = browser_api.chromium.launch(headless=True)
                    context = browser.new_context()
                    def local_only(route):
                        from urllib.parse import urlsplit
                        if urlsplit(route.request.url).hostname not in ('127.0.0.1', 'localhost', '::1'):
                            rejected.append('nonlocal-request')
                            route.abort()
                        else:
                            route.continue_()
                    context.route('**/*', local_only)
                    page = context.new_page()
                    page.goto('http://127.0.0.1:' + str(server.server_port) + '/#' + app.token)
                    page.locator('#ha-prepare').wait_for(state='attached')
                    assert page.locator('#ha-connect-sign-in').count() == 1
                    assert page.locator('#ha-remote-enable').count() == 1
                    # Locator assertions work under HA's strict CSP; do not use
                    # string-evaluating waiters or enable unsafe-eval for a test.
                    page.locator('[data-tab="settings"]').click()
                    expect(page.locator("#ha-capabilities")).to_contain_text("Sessions and tasks")
                    expect(page.locator("#ha-prepare")).to_be_visible()
                    expect(page.locator("#ha-analysis-advanced")).not_to_have_attribute("open", "")
                    expect(page.locator("#install")).not_to_be_visible()
                    page.screenshot(path=str(args.report.with_name('offline-dashboard.png')), full_page=True)
                    context.close()
                    browser.close()
                assert not rejected, 'The local dashboard requested an external resource'
                return {'bundled_browser': True, 'ha_dashboard': True, 'nonlocal_requests': 0}
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
        check('bundled_browser_and_ha_interface', dashboard)
        saved_browser = dict(app.config['browser'])
    finally:
        app.close()
    def reopen():
        again = Application(data_root)
        try:
            assert again.config['browser'] == saved_browser
            assert canary.read_text(encoding='utf-8') == 'retained-local-owner-data'
            assert again.builtins.execution_runtime() is not None
            return {'settings_and_canary_preserved': True}
        finally:
            again.close()
    check('restart_preserves_configuration', reopen)
    report['passed'] = all(item['passed'] for item in report['checks'].values())
    save()
    print(json.dumps({'passed': report['passed'], 'checks': report['checks']}))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
