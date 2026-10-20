import hashlib
import io
import json
import os
import sys
import time
import zipfile
from pathlib import Path
import pytest
from hivemind_assembly.application.app import Application
from hivemind_assembly.integrations.tunnel import Tunnel
from hivemind_assembly.core.common import Blocked


@pytest.fixture
def app(tmp_path):
    a=Application(tmp_path/'state')
    yield a
    a.close()


def test_secret_is_session_only_and_profile_is_scoped(app):
    tunnel=app.tunnel
    secret='test-runtime-credential'
    tunnel.configure('tunnel_0123456789abcdef',secret)
    profile=json.loads(tunnel.config.read_text())
    assert secret not in tunnel.config.read_text()
    assert profile['control_plane']['api_key']=='env:CONTROL_PLANE_API_KEY'
    assert profile['health']['listen_addr']=='127.0.0.1:0'
    assert ' mcp ' in profile['mcp']['commands'][0]['command']
    assert secret not in json.dumps(app.status())
    assert tunnel.secret==secret
    with pytest.raises(Blocked,match='Enable'):
        tunnel.start()


def test_official_asset_platform_and_digest_validation():
    release={'tag_name':'v1','assets':[{'name':'tunnel-client-v1-windows-amd64.zip','digest':'sha256:'+'a'*64}]}
    assert Tunnel.release_asset(release,'Windows','AMD64')['name'].endswith('windows-amd64.zip')
    with pytest.raises(Blocked):Tunnel.release_asset(release,'Linux','x86_64')
    release['assets'][0]['digest']=''
    with pytest.raises(Blocked):Tunnel.release_asset(release,'Windows','AMD64')


def test_binary_integrity_and_vault_separation(app,tmp_path):
    t=app.tunnel
    assert t.vault.service!='HivemindAssembly.GitHub'
    t.configure('tunnel_0123456789abcdef','test-runtime-credential')
    executable=tmp_path/'fixture'
    executable.write_bytes(b'fixture')
    t.installation.write_text(json.dumps({'binary':str(executable),'binary_sha256':hashlib.sha256(b'fixture').hexdigest(),'version':'test'}))
    binary,env,key=t.runtime()
    assert key==env['CONTROL_PLANE_API_KEY']
    assert set(env)-{'CONTROL_PLANE_API_KEY'} <= {'PATH','HOME','USERPROFILE','SystemRoot','WINDIR','TEMP','TMP','LOCALAPPDATA'}
    executable.write_bytes(b'changed')
    with pytest.raises(Blocked,match='checksum'):t.runtime()


@pytest.mark.skipif(os.name=='nt',reason='POSIX executable fixture; production Windows uses the official EXE')
def test_supervised_process_redacts_key_and_stops_children(app,tmp_path):
    cfg=app.connections.settings();cfg['enabled']=True;app.connections.save(cfg)
    t=app.tunnel;t.configure('tunnel_0123456789abcdef','test-runtime-credential')
    executable=tmp_path/'tunnel-fixture'
    executable.write_text('#!'+sys.executable+'\nimport os,time\nprint(os.environ["CONTROL_PLANE_API_KEY"],flush=True)\ntime.sleep(30)\n')
    executable.chmod(0o700)
    t.installation.write_text(json.dumps({'binary':str(executable),'binary_sha256':hashlib.sha256(executable.read_bytes()).hexdigest(),'version':'fixture'}))
    assert t.start()['process_running']
    pid=t.process.pid
    assert t.start()['process_running'] and t.process.pid==pid
    for _ in range(100):
        if t.messages:break
        time.sleep(.01)
    assert '[redacted]' in str(t.status()) and 'test-runtime-credential' not in str(t.status())
    assert not t.stop()['process_running']
