import json
import threading
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pytest
from hivemind_assembly.integrations.remote_access import RemoteAccess
from hivemind_assembly.core.common import Blocked, ContractError


class Network:
    def __init__(self):
        self.calls = []
        self.config = {'Web': {}, 'TCP': {}}
        self.hostname = 'computer.example.ts.net'

    def __call__(self, args):
        self.calls.append(list(args))
        if args == ['status', '--json']:
            return json.dumps({'BackendState': 'Running', 'Self': {'DNSName': self.hostname + '.'}})
        if args == ['serve', 'status', '--json']:
            return json.dumps(self.config)
        if args[:3] == ['serve', '--bg', '--https=8443']:
            self.config['Web'][self.hostname + ':8443'] = {'Handlers': {'/': {'Proxy': args[-1]}}}
            self.config['TCP']['8443'] = {'HTTPS': True}
            return ''
        if args == ['serve', '--https=8443', 'off']:
            self.config['Web'].pop(self.hostname + ':8443', None)
            self.config['TCP'].pop('8443', None)
            return ''
        raise AssertionError(args)


@pytest.fixture
def network():
    return Network()


@pytest.fixture
def remote(tmp_path, network):
    received = []
    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_GET(self):
            received.append((self.path, self.headers.get('X-Workbench-Token')))
            body = b'{"application":"Hivemind Assembly"}'
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    value = RemoteAccess(tmp_path, 'local-owner-token-not-a-device-key', network)
    value.bind(server.server_port)
    value.received = received
    yield value
    value.close()
    server.shutdown()
    server.server_close()


def request(remote, token=None, path='/api/status', origin=None, host=None):
    headers = {'Host': host or 'computer.example.ts.net:8443'}
    if token: headers['X-Workbench-Token'] = token
    if origin: headers['Origin'] = origin
    req = urllib.request.Request(f'http://127.0.0.1:{remote.server.server_port}' + path, headers=headers)
    return urllib.request.urlopen(req, timeout=3)


def test_passive_status_no_external_processes(remote, network):
    assert remote.snapshot()['state'] == 'unchecked'
    assert not network.calls and remote.server is None


def test_pair_gateway_revoke_expiry_and_no_secret_storage(remote, network):
    assert remote.enable()['state'] == 'configured'
    pair = remote.pair('My phone')
    token = pair['url'].split('#')[1]
    assert token not in remote.path.read_text()
    assert token not in json.dumps(remote.snapshot())
    assert remote.owner_token not in json.dumps(pair)
    with request(remote, token, origin=remote.state['origin']) as response:
        assert json.load(response)['application'] == 'Hivemind Assembly'
    assert remote.received == [('/api/status', remote.owner_token)]
    for denied in (remote.owner_token, 'a' * 43, None):
        with pytest.raises(urllib.error.HTTPError) as error:
            request(remote, denied)
        assert error.value.code == 403
    remote.state['devices'][0]['expires'] = 0
    assert not remote.authorized(token)
    remote.revoke(pair['id'])
    assert remote.snapshot()['devices'] == []


def test_remote_cannot_enroll_devices_or_use_wrong_origin(remote):
    remote.enable()
    token = remote.pair('Phone')['url'].split('#')[1]
    for kwargs in ({'path': '/api/remote/pair'}, {'origin': 'https://evil.example'}, {'host':'evil.example'}):
        with pytest.raises(urllib.error.HTTPError) as error:
            request(remote, token, **kwargs)
        assert error.value.code == 403
    assert not remote.received


def test_mapping_conflict_is_not_overwritten(remote, network):
    network.config = {'TCP': {'8443': {'HTTPS': True}}, 'Web': {'computer.example.ts.net:8443': {'Handlers': {'/': {'Proxy': 'http://127.0.0.1:9999'}}}}}
    original = json.dumps(network.config, sort_keys=True)
    with pytest.raises(Blocked): remote.enable()
    assert json.dumps(network.config, sort_keys=True) == original
    assert all(args[-1] == '--json' for args in network.calls)


def test_enable_reconciles_and_disable_preserves_other_mapping(remote, network):
    network.config['Web']['computer.example.ts.net:443'] = {'Handlers': {'/': {'Proxy': 'http://127.0.0.1:7000'}}}
    remote.enable()
    remote.enable()
    assert sum(args[:2] == ['serve','--bg'] for args in network.calls) == 1
    remote.pair('Phone')
    assert remote.disable()['enabled'] is False
    assert remote.state['devices'] == []
    assert network.config['Web']['computer.example.ts.net:443']['Handlers']['/']['Proxy'].endswith(':7000')
    assert not any('reset' in args or 'funnel' in args for args in network.calls)


def test_account_change_does_not_migrate_device_grants(remote, network):
    remote.enable()
    remote.pair('Phone')
    old = remote.state['origin']
    network.hostname = 'another.different.ts.net'
    with pytest.raises(Blocked): remote.check()
    assert remote.state['origin'] == old
    assert remote.state['transport'] == 'account_changed'


def test_pairing_needs_enabled_mapping(remote):
    with pytest.raises(Blocked): remote.pair('Phone')
    remote.enable()
    with pytest.raises(ContractError): remote.pair('Phone', 1000)


def test_disabling_revokes_devices_even_when_transport_is_unavailable(remote):
    remote.enable()
    token = remote.pair('Phone')['url'].split('#')[1]
    remote.runner = lambda args: (_ for _ in ()).throw(Blocked('Transport unavailable'))
    result = remote.disable()
    assert not result['enabled'] and result['state'] == 'disabled_cleanup_pending'
    assert not remote.authorized(token)
    with pytest.raises(urllib.error.HTTPError) as error:
        request(remote, token, path='/')
    assert error.value.code == 403


def test_damaged_optional_remote_settings_do_not_break_local_startup(tmp_path):
    path = tmp_path / 'private/remote-access/settings.json'
    path.parent.mkdir(parents=True)
    path.write_text('{broken')
    remote = RemoteAccess(tmp_path, 'owner')
    assert remote.snapshot()['state'] == 'settings_need_recovery'
    assert not remote.snapshot()['enabled']
    assert path.read_text() == '{broken'
    with pytest.raises(Blocked): remote.enable()
    assert path.read_text() == '{broken'
