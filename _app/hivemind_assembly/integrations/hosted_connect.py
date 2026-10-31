"""HA-owned T3 Connect integration using retained T3 signing/verification code.

OAuth credentials and environment keys stay in the OS credential store. The
public configuration is T3's pinned source-build configuration, not a private
service key. Local HA and direct Tailscale authentication remain independent.
"""
from __future__ import annotations
import base64
from datetime import datetime, timezone
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import platform
import secrets
import sqlite3
import subprocess
import threading
import time
from urllib.parse import parse_qs, urlencode, urlsplit
import urllib.error
import urllib.request
import uuid

from hivemind_assembly.core.common import Blocked, ContractError, atomic_write, canonical
from hivemind_assembly.application.components import Components
from .github import CredentialVault
from .remote_access import RemoteAccess

RELAY = 'https://relay.t3.codes'
CLERK = 'https://clerk.t3.codes'
CLIENT_ID = 'hzxSgY2cH10sDU2r'
CALLBACK_PORT = 34338
CALLBACK = 'http://127.0.0.1:34338/callback'
LIMIT = 512 * 1024
PROTOCOL_PATHS = {'/api/t3-connect/health', '/api/t3-connect/mint-credential', '/oauth/token'}


def public_origin(value):
    try:
        url = urlsplit(value)
        return (isinstance(value, str) and value == value.strip() and url.scheme == 'https'
                and url.username is None and url.password is None and url.port in (None, 443)
                and url.path in ('', '/') and not url.query and not url.fragment
                and url.hostname and '.' in url.hostname and not url.hostname.endswith(('.local', '.localhost', '.internal'))
                and not url.hostname.replace('.', '').isdigit())
    except (ValueError, TypeError):
        return False


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise Blocked('A connection service attempted an unexpected redirect; no credential was forwarded')


def request_json(method, url, payload=None, token=None, form=False):
    # All authenticated requests remain on the selected documented service.
    if urlsplit(url).scheme != 'https' or urlsplit(url).netloc not in ('relay.t3.codes', 'clerk.t3.codes'):
        raise ContractError('Connection request escaped its approved service')
    data = (urlencode(payload).encode() if form else canonical(payload).encode()) if payload is not None else None
    headers = {'Accept': 'application/json', 'User-Agent': 'HivemindAssembly-connect/1',
               'Content-Type': 'application/x-www-form-urlencoded' if form else 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=25) as response:
            raw = response.read(LIMIT + 1)
    except urllib.error.HTTPError as error:
        raise Blocked('The connection service rejected this step (HTTP ' + str(error.code) + '). No alternate account or paid route was used.') from None
    except (OSError, urllib.error.URLError):
        raise Blocked('The connection service did not confirm this step. HA preserved the state and did not repeat it.') from None
    if len(raw) > LIMIT:
        raise Blocked('The connection service returned an oversized reply')
    try:
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except (ValueError, TypeError):
        raise Blocked('The connection service returned an invalid reply') from None


class ConnectProtocol:
    """A bounded private process, never a raw crypto/debug network endpoint."""
    def __init__(self, root):
        self.root = root
        self.paths = None
        self.limit = threading.BoundedSemaphore(4)

    def ready(self):
        if self.paths is None:
            components = Components(self.root)
            self.paths = (components.resolve('node').entrypoint, components.resolve('connect').entrypoint)
        return self.paths

    def __call__(self, action, **fields):
        node, script = self.ready()
        body = canonical({'action': action, **fields}).encode()
        if len(body) > LIMIT:
            raise ContractError('Connection protocol request is too large')
        if not self.limit.acquire(timeout=2):
            raise Blocked('The connection verifier is busy; no request was authorized')
        try:
            env = {key: value for key, value in os.environ.items()
                   if key.upper() in ('PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP')}
            process = subprocess.run([str(node), str(script)], input=body,
                                     capture_output=True, env=env, timeout=15)
            if process.returncode or len(process.stdout) > LIMIT:
                raise ValueError()
            result = json.loads(process.stdout)
            if result.get('ok') is not True:
                raise ValueError()
            return result['result']
        except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
            raise Blocked('The signed connection request was not accepted') from None
        finally:
            self.limit.release()


def iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace('+00:00', 'Z')


class HostedConnect:
    def __init__(self, root, owner_token, *, protocol=None, vault=None, http=None):
        self.root = Path(root)
        self.folder = self.root / 'private' / 'connect'
        self.path = self.folder / 'state.json'
        self.vault = vault or CredentialVault(self.root, service='HAConnect')
        self.protocol = protocol or ConnectProtocol(root)
        self.http = http or request_json
        self.lock = threading.RLock()
        self.process = None
        self.callback = None
        self.pending = None
        self.secrets = None
        self.generation = 0
        self.error = None
        self.state = {'schema': 1, 'environment_id': 'ha-' + uuid.uuid4().hex,
                      'enabled': False, 'state': 'not_connected', 'origin': None}
        self.gateway = RemoteAccess(root, owner_token, namespace='hosted-access', allow_origin=public_origin)
        self.gateway.protocol_request = self.protocol_request
        self.gateway.authorize_extra = self.authorized_dpop
        if self.path.exists():
            try:
                if self.path.is_symlink() or self.path.stat().st_size > LIMIT:
                    raise ValueError()
                saved = json.loads(self.path.read_text())
                if (not isinstance(saved, dict) or saved.get('schema') != 1 or type(saved.get('enabled')) is not bool
                    or not isinstance(saved.get('environment_id'), str)
                    or not saved['environment_id'].startswith('ha-')
                    or len(saved['environment_id']) > 100
                    or saved.get('origin') is not None and not public_origin(saved['origin'])):
                    raise ValueError()
                self.state = saved
                if saved['enabled']:
                    self.state['state'] = 'reconnect_required'
            except (OSError, ValueError, TypeError):
                self.error = 'Saved hosted connection settings need repair. They were preserved; local HA is still available.'
                self.state['state'] = 'settings_need_recovery'

    def save(self):
        if self.error:
            raise Blocked(self.error)
        self.folder.mkdir(parents=True, exist_ok=True)
        atomic_write(self.path, canonical(self.state))

    def secret(self):
        if self.secrets is None:
            saved = self.vault.read()
            if saved is not None and not isinstance(saved, dict):
                raise Blocked('The saved connection credential is invalid')
            self.secrets = saved or {}
        return self.secrets

    def store_secret(self):
        self.vault.write(self.secrets)

    def bind(self, port):
        # Restore only the local gateway. Reconnect is explicit after restart;
        # opening HA never starts an unconfirmed new hosted registration.
        self.gateway.bind(port)

    def snapshot(self):
        with self.lock:
            running = self.process is not None and self.process.poll() is None
            return {'state': self.state['state'], 'enabled': self.state['enabled'],
                    'origin': self.state.get('origin'), 'environment_id': self.state['environment_id'],
                    'tunnel_running': running, 'error': self.error,
                    'sign_in_pending': bool(self.pending and self.pending['expires'] > time.time()),
                    'devices': self.gateway.snapshot()['devices'],
                    'hosted_interoperability_verified': bool(self.state.get('verified_at')),
                    'service': 'T3 Connect', 'local_operation_independent': True}

    def descriptor(self):
        os_name = 'windows' if os.name == 'nt' else 'darwin' if platform.system() == 'Darwin' else 'linux'
        return {'environmentId': self.state['environment_id'], 'label': 'Hivemind Assembly',
                'platform': {'os': os_name, 'arch': 'arm64' if platform.machine().lower() in ('arm64','aarch64') else 'x64'},
                'serverVersion': 'HA-integrated-1',
                # Do not claim T3's unrelated orchestration RPC or UI compatibility.
                'capabilities': {'repositoryIdentity': False, 'agentActivityPublishing': False}}

    def _claims(self, audience, subject, **fields):
        now = int(time.time())
        return {'iss': 't3-env:' + self.state['environment_id'], 'aud': audience, 'sub': subject,
                'jti': uuid.uuid4().hex, 'iat': now, 'exp': now + 120, **fields}

    def sign(self, typ, payload):
        return self.protocol('sign', typ=typ, privateKey=self.secret()['private_key'], payload=payload)['proof']

    def _keys(self):
        data = self.secret()
        if not data.get('private_key'):
            if self.state.get('cloud_user_id'):
                raise Blocked('The existing host identity key is missing. It was not silently replaced.')
            pair = self.protocol('keygen')
            data.update(private_key=pair['privateKey'], public_key=pair['publicKey'])
            self.store_secret()

    def start_sign_in(self):
        with self.lock:
            if self.error:
                raise Blocked(self.error)
            if self.pending and self.pending['expires'] > time.time():
                return {'url': self.pending['url'], 'state': 'awaiting_sign_in'}
            if self.callback:
                raise Blocked('The previous sign-in callback is closing. Retry after its cancellation completes.')
            self._keys()
            verifier = secrets.token_urlsafe(48)
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
            state = secrets.token_urlsafe(32)
            url = self.protocol('authorize', state=state, challenge=challenge)['url']
            generation = self.generation
            host = self
            class Callback(BaseHTTPRequestHandler):
                def log_message(self, *args): pass
                def do_GET(self):
                    self.connection.settimeout(15)
                    result = False
                    if self.headers.get('Host') == '127.0.0.1:34338' and len(self.path) <= 8192 and urlsplit(self.path).path == '/callback':
                        query = parse_qs(urlsplit(self.path).query, max_num_fields=10)
                        if len(query.get('state', [])) == 1 and len(query.get('code', [])) == 1:
                            result = host.finish_sign_in(query['state'][0], query['code'][0], generation)
                    body = (b'HA sign-in received. Return to HA to finish connecting.' if result else b'HA could not accept this sign-in. Return to HA; no account was changed.')
                    self.send_response(200 if result else 400)
                    self.send_header('Content-Type', 'text/plain; charset=utf-8')
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('Referrer-Policy', 'no-referrer')
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers(); self.wfile.write(body)
            try:
                callback = ThreadingHTTPServer(('127.0.0.1', CALLBACK_PORT), Callback)
            except OSError:
                raise Blocked('The supported sign-in callback port is in use. HA did not stop the other application.') from None
            self.callback = callback
            self.pending = {'state': state, 'verifier': verifier, 'url': url, 'expires': time.time() + 600, 'generation': generation}
            self.state['state'] = 'awaiting_sign_in'; self.save()
            threading.Thread(target=callback.serve_forever, daemon=True, name='HA-connect-sign-in').start()
            def expire():
                with self.lock:
                    if self.callback is callback:
                        self.pending = None
                        self.callback = None
                        if self.state['state'] == 'awaiting_sign_in':
                            self.state['state'] = 'sign_in_expired'; self.save()
                callback.shutdown(); callback.server_close()
            timer = threading.Timer(600, expire); timer.daemon = True; timer.start()
            return {'url': url, 'state': 'awaiting_sign_in'}

    def finish_sign_in(self, state, code, generation):
        with self.lock:
            pending = self.pending
            if (not pending or pending['expires'] <= time.time() or generation != self.generation
                or not hmac.compare_digest(pending['state'], state) or not 1 <= len(code) <= 4096):
                return False
            self.pending = None  # Never exchange the same authorization code twice.
        try:
            token = self.http('POST', CLERK + '/oauth/token', {'grant_type': 'authorization_code',
                'client_id': CLIENT_ID, 'code': code, 'redirect_uri': CALLBACK,
                'code_verifier': pending['verifier']}, form=True)
            access = token.get('access_token')
            if not isinstance(access, str) or not 1 <= len(access) <= 32768:
                raise ValueError()
            with self.lock:
                if generation != self.generation:
                    return False
                self.secret().update(oauth=token, oauth_received=time.time())
                self.store_secret()
                self.state['state'] = 'signed_in'; self.save()
            return True
        except (OSError, ValueError):
            with self.lock:
                if generation == self.generation:
                    self.state['state'] = 'sign_in_not_confirmed'; self.save()
            return False
        finally:
            callback, self.callback = self.callback, None
            if callback:
                def stop(): callback.shutdown(); callback.server_close()
                threading.Thread(target=stop, daemon=True).start()

    def _access_token(self):
        token = self.secret().get('oauth') or {}
        if not token.get('access_token'):
            raise Blocked('Sign in from HA before enabling hosted access')
        expires = token.get('expires_in', 300)
        if not isinstance(expires, (float, int)) or time.time() > self.secret().get('oauth_received', 0) + expires - 30:
            if not token.get('refresh_token'):
                raise Blocked('Hosted sign-in expired. Sign in again from HA.')
            refreshed = self.http('POST', CLERK + '/oauth/token', {'grant_type': 'refresh_token',
                'client_id': CLIENT_ID, 'refresh_token': token['refresh_token']}, form=True)
            if not isinstance(refreshed.get('access_token'), str):
                raise Blocked('The connection service did not confirm renewed sign-in')
            if not refreshed.get('refresh_token'):
                refreshed['refresh_token'] = token['refresh_token']
            self.secret().update(oauth=refreshed, oauth_received=time.time()); self.store_secret()
            token = refreshed
        return token['access_token']

    def connect(self):
        with self.lock:
            if self.error:
                raise Blocked(self.error)
            self._keys()
            if self.state['state'] == 'link_outcome_unknown':
                raise Blocked('The previous link was not confirmed. HA will not create another tunnel blindly; inspect the linked host in T3 Connect before reconnecting.')
            if self.state.get('cloud_user_id'):
                return self.reconnect()
            self.gateway.start_gateway()
            origin = {'localHttpHost': '127.0.0.1', 'localHttpPort': self.gateway.server.server_port}
            flags = {'notificationsEnabled': False, 'liveActivitiesEnabled': False, 'managedTunnelsEnabled': True}
            token = self._access_token()
            challenge = self.http('POST', RELAY + '/v1/client/environment-link-challenges', flags, token=token)
            if not isinstance(challenge.get('challenge'), str) or not challenge['challenge']:
                raise Blocked('The connection service did not issue a link challenge')
            endpoint = {'httpBaseUrl': self.gateway.proxy_url(),
                        'wsBaseUrl': self.gateway.proxy_url().replace('http:', 'ws:', 1), 'providerKind': 'cloudflare_tunnel'}
            payload = self._claims(RELAY, self.state['environment_id'], challenge=challenge['challenge'],
                descriptor=self.descriptor(), environmentId=self.state['environment_id'],
                environmentPublicKey=self.secret()['public_key'], endpoint=endpoint, origin=origin,
                scopes=['managed_tunnels'])
            self.state['state'] = 'link_outcome_unknown'; self.save()
            result = self.http('POST', RELAY + '/v1/client/environment-links',
                               {**flags, 'proof': self.sign('t3-env-link+jwt', payload)}, token=token)
            if result.get('ok') is not True or result.get('environmentId') != self.state['environment_id']:
                raise Blocked('The linked host identity was not confirmed')
            for field in ('cloudUserId','environmentCredential','cloudMintPublicKey','relayIssuer'):
                if not isinstance(result.get(field), str) or not 1 <= len(result[field]) <= 32768:
                    raise Blocked('The connection service returned an incomplete link')
            if result['relayIssuer'].rstrip('/') != RELAY:
                raise Blocked('The connection signing authority changed; the link was not activated')
            self.secret().update(environment_credential=result['environmentCredential'],
                mint_public_key=result['cloudMintPublicKey'], runtime=result['endpointRuntime'])
            self.store_secret()
            self.state.update(cloud_user_id=result['cloudUserId'], relay_issuer=result['relayIssuer'])
            self._activate_endpoint(result['endpoint'], result['endpointRuntime'])
            return self.snapshot()

    def _activate_endpoint(self, endpoint, runtime):
        if (not isinstance(endpoint, dict) or endpoint.get('providerKind') != 'cloudflare_tunnel'
            or not public_origin(endpoint.get('httpBaseUrl')) or not isinstance(runtime, dict)
            or runtime.get('providerKind') != 'cloudflare_tunnel' or not isinstance(runtime.get('connectorToken'), str)):
            raise Blocked('The hosted tunnel configuration was not accepted')
        origin = endpoint['httpBaseUrl'].rstrip('/')
        if self.state.get('origin') not in (None, origin):
            raise Blocked('The hosted address changed. Existing paired credentials were not moved to another address.')
        self.secret()['runtime'] = runtime; self.store_secret()
        self.state.update(enabled=True, origin=origin, state='starting')
        self.gateway.state.update(enabled=True, origin=origin, transport='configured')
        self.gateway.save(); self.save()
        executable = Components(self.root).resolve('tunnel').entrypoint
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try: self.process.wait(timeout=5)
            except subprocess.TimeoutExpired: self.process.kill(); self.process.wait(timeout=5)
        env = {k: v for k, v in os.environ.items() if k.upper() in ('PATH','SYSTEMROOT','WINDIR','TEMP','TMP')}
        env['TUNNEL_TOKEN'] = runtime['connectorToken']
        self.process = subprocess.Popen([str(executable), 'tunnel', '--no-autoupdate', '--loglevel', 'error',
                                        '--metrics', '127.0.0.1:0', 'run'], env=env,
                                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.state['state'] = 'running_unverified'; self.save()

    def reconnect(self):
        with self.lock:
            if not self.state.get('cloud_user_id'):
                return self.connect()
            self.gateway.start_gateway()
            origin = {'localHttpHost': '127.0.0.1', 'localHttpPort': self.gateway.server.server_port}
            user = self.state['cloud_user_id']
            payload = self._claims(RELAY, user, action='recover', environmentId=self.state['environment_id'], cloudUserId=user, origin=origin)
            result = self.http('POST', RELAY + '/v1/environments/' + self.state['environment_id'] + '/tunnel',
                {'cloudUserId': user, 'origin': origin, 'proof': self.sign('t3-env-managed-tunnel-recovery+jwt', payload)},
                token=self.secret().get('environment_credential'))
            self._activate_endpoint(result['endpoint'], result['endpointRuntime'])
            return self.snapshot()

    def _db(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.folder / 'proofs.sqlite3', timeout=5)
        conn.execute('CREATE TABLE IF NOT EXISTS seen(key TEXT PRIMARY KEY,expires REAL NOT NULL)')
        conn.execute('CREATE TABLE IF NOT EXISTS grants(hash TEXT PRIMARY KEY,kind TEXT NOT NULL,thumbprint TEXT NOT NULL,expires REAL NOT NULL)')
        return conn

    def consume(self, keys, expires):
        with self.lock, self._db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('DELETE FROM seen WHERE expires<?', (time.time(),))
            if conn.execute('SELECT count(*) FROM seen').fetchone()[0] > 10000:
                raise Blocked('The connection replay journal is full')
            if any(conn.execute('SELECT 1 FROM seen WHERE key=?', (key,)).fetchone() for key in keys):
                raise Blocked('This signed connection request was already consumed')
            conn.executemany('INSERT INTO seen VALUES(?,?)', [(key, expires) for key in keys])

    def protocol_request(self, path, method, headers, raw):
        if path not in PROTOCOL_PATHS:
            return None
        try:
            if method != 'POST' or not self.state['enabled'] or len(raw) > LIMIT:
                raise Blocked('Hosted access is unavailable')
            if path == '/oauth/token':
                data = dict((key, values[0]) for key, values in parse_qs(raw.decode(), max_num_fields=10).items() if len(values) == 1)
                return 200, self.exchange(data, headers.get('DPoP'))
            data = json.loads(raw)
            kind = 'health' if path.endswith('/health') else 'mint'
            claims = self.protocol('verify_cloud', kind=kind, token=data['proof'],
                publicKey=self.secret()['mint_public_key'], issuer=self.state['relay_issuer'],
                environmentId=self.state['environment_id'], cloudUserId=self.state['cloud_user_id'])['payload']
            self.consume([kind + ':jti:' + claims['jti'], kind + ':nonce:' + claims['nonce']], claims['exp'] + 60)
            if kind == 'health':
                now = iso(time.time())
                result = {'environmentId': self.state['environment_id'], 'status': 'online',
                          'descriptor': self.descriptor(), 'checkedAt': now}
                payload = self._claims(RELAY, self.state['cloud_user_id'], requestNonce=claims['nonce'], **result)
                result['proof'] = self.sign('t3-env-health+jwt', payload)
                self.state.update(state='connected', verified_at=time.time()); self.save()
                return 200, result
            token = secrets.token_urlsafe(32)
            expires = time.time() + 90
            with self._db() as conn:
                conn.execute('DELETE FROM grants WHERE expires<?', (time.time(),))
                conn.execute('INSERT INTO grants VALUES(?,?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), 'bootstrap', claims['clientProofKeyThumbprint'], expires))
            payload = self._claims(RELAY, self.state['cloud_user_id'], environmentId=self.state['environment_id'],
                                   requestNonce=claims['nonce'], clientProofKeyThumbprint=claims['clientProofKeyThumbprint'], credential=token)
            return 200, {'credential': token, 'expiresAt': iso(expires), 'proof': self.sign('t3-env-mint+jwt', payload)}
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
            return 403, {'error': 'invalid_request', 'message': 'The connection proof was not accepted'}

    def exchange(self, data, proof):
        if (data.get('grant_type') != 'urn:ietf:params:oauth:grant-type:token-exchange'
            or data.get('subject_token_type') != 'urn:t3:params:oauth:token-type:environment-bootstrap'
            or data.get('requested_token_type') not in (None, 'urn:ietf:params:oauth:token-type:access_token')):
            raise Blocked('Unsupported token exchange')
        token = data.get('subject_token', '')
        if not isinstance(token, str) or not 20 <= len(token) <= 256:
            raise Blocked('Invalid bootstrap credential')
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.lock, self._db() as conn:
            row = conn.execute('SELECT thumbprint,expires FROM grants WHERE hash=? AND kind=?', (digest,'bootstrap')).fetchone()
            if row is None or row[1] <= time.time():
                raise Blocked('Expired or consumed bootstrap credential')
            verified = self.protocol('verify_dpop', proof=proof, method='POST', url=self.state['origin'] + '/oauth/token', thumbprint=row[0])
            if not verified.get('ok'):
                raise Blocked('Invalid proof key')
            self.consume(['dpop:' + verified['thumbprint'] + ':' + verified['jti']], time.time() + 600)
            conn.execute('DELETE FROM grants WHERE hash=?', (digest,))
            access = secrets.token_urlsafe(32)
            conn.execute('INSERT INTO grants VALUES(?,?,?,?)', (hashlib.sha256(access.encode()).hexdigest(), 'access', row[0], time.time()+3600))
        return {'access_token': access, 'token_type': 'DPoP', 'expires_in': 3600,
                'issued_token_type': 'urn:ietf:params:oauth:token-type:access_token', 'scope': 'environment:connect'}

    def authorized_dpop(self, headers, method, path):
        try:
            auth = headers.get('Authorization', '')
            if not self.state['enabled'] or not auth.startswith('DPoP '):
                return False
            token = auth[5:]
            if not 20 <= len(token) <= 256:
                return False
            with self._db() as conn:
                row = conn.execute('SELECT thumbprint,expires FROM grants WHERE hash=? AND kind=?', (hashlib.sha256(token.encode()).hexdigest(),'access')).fetchone()
            if row is None or row[1] <= time.time():
                return False
            verified = self.protocol('verify_dpop', proof=headers.get('DPoP'), method=method,
                url=self.state['origin']+path, thumbprint=row[0], accessToken=token)
            if not verified.get('ok'):
                return False
            self.consume(['dpop:' + verified['thumbprint'] + ':' + verified['jti']], time.time()+600)
            return True
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
            return False

    def pair(self, label, days=30):
        return self.gateway.pair(label, days)

    def disconnect(self):
        with self.lock:
            self.generation += 1; self.pending = None
            self.state.update(enabled=False, state='disconnected'); self.save()
            self.gateway.state.update(enabled=False, devices=[], transport='disabled'); self.gateway.save()
            with self._db() as conn: conn.execute('DELETE FROM grants')
            self.close(release=False)
            try:
                if self.state.get('cloud_user_id'):
                    self.http('DELETE', RELAY + '/v1/client/environment-links/' + self.state['environment_id'], token=self._access_token())
                    self.state.pop('cloud_user_id', None); self.state.pop('origin', None)
                    self.secret().pop('environment_credential', None); self.secret().pop('runtime', None); self.store_secret()
            except (OSError, ValueError):
                self.state['state'] = 'disconnected_cleanup_pending'
            self.save()
            return self.snapshot()

    def close(self, release=True):
        process, self.process = self.process, None
        if process and process.poll() is None:
            process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
        self.gateway.close()
        callback, self.callback = self.callback, None
        if callback: callback.shutdown(); callback.server_close()
        if release and self.state.get('enabled') and self.state.get('cloud_user_id'):
            try:
                self.http('DELETE', RELAY + '/v1/client/environment-links/' + self.state['environment_id'] + '/tunnel', token=self._access_token())
                self.state['state'] = 'reconnect_required'; self.save()
            except (OSError, ValueError):
                self.state['state'] = 'reconnect_required'; self.save()
