"""Optional GitHub Codespaces lifecycle and concurrent, explicit snapshot jobs."""
from __future__ import annotations
import base64
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import threading
import tempfile
import time
from urllib.parse import quote
from hivemind_assembly.core.common import Blocked, ContractError, Conflict, canonical, digest, uid, atomic_write


class Codespaces:
    def __init__(self, app):
        self.app, self.store = app, app.store
        self.path = self.store.root / 'private' / 'codespaces.json'
        self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='ha-cloud')
        self.locks = {}
        self.queues = {}
        self.active_spaces = set()
        self.lock = threading.RLock()
        self.closed = False
        self.processes = set()
        # An interrupted local delivery is never automatically sent again.
        for row in self.jobs():
            if row['status'] in ('queued', 'running'):
                self.state('cloud_job:'+row['id'], {**row, 'status': 'cancelled' if row['status']=='queued' else 'uncertain', 'error':'HA restarted; reconcile any previously running remote work.'})

    def settings(self):
        return json.loads(self.path.read_text()) if self.path.exists() else {'enabled':False, 'allow_execution':False, 'spaces':[]}

    def save(self, value):
        if not isinstance(value, dict) or set(value) != {'enabled','allow_execution','spaces'} or any(type(value[k]) is not bool for k in ('enabled','allow_execution')):
            raise ContractError('Codespaces settings require enabled, allow_execution and spaces')
        if not isinstance(value['spaces'], list) or len(value['spaces']) > 16:
            raise ContractError('Select at most 16 Codespaces')
        for name in value['spaces']:
            self.name(name)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(self.path, canonical(value))
        return value

    @staticmethod
    def name(value):
        if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', value):
            raise ContractError('Invalid Codespace name')
        return value

    def api(self, method, path, data=None):
        if not self.settings()['enabled']:
            raise Blocked('Codespaces is optional and currently disabled')
        saved = self.app.github_auth.credentials()
        try:
            return self.app.github_auth.http.request(method, path, token=saved['access_token'], data=data)
        except Blocked as error:
            raise Blocked(str(error) + ' Codespaces access requires the codespace OAuth scope; reconnect with Codespaces enabled.') from None

    def listing(self):
        return self.api('GET', '/user/codespaces?per_page=100')

    def machines(self, owner, repo):
        for value in (owner, repo):
            self.name(value)
        return self.api('GET', f'/repos/{owner}/{repo}/codespaces/machines')

    def create(self, owner, repo, machine, request_id, ref=None):
        for value in (owner,repo,request_id):
            self.name(value)
        if not isinstance(machine,str) or not machine:
            raise ContractError('Select a machine from the repository machine list')
        body = {'machine':machine,'display_name':'HA-' + request_id, 'idle_timeout_minutes':30}
        if ref:
            if not isinstance(ref,str) or len(ref)>250:
                raise ContractError('Invalid repository ref')
            body['ref'] = ref
        key = 'codespace_create:' + request_id
        old = self.latest(key)
        fingerprint = digest({'owner':owner,'repo':repo,**body})
        if old:
            if old['hash'] != fingerprint:
                raise Conflict('Codespace creation ID already has different parameters')
            if old['status']=='created':
                return old['result']
            raise Blocked('Creation response is uncertain. Refresh Codespaces and select the retained HA display name; do not recreate.')
        available = self.machines(owner,repo)
        if machine not in [m['name'] for m in available['machines']]:
            raise Blocked('Selected machine is not available for this repository')
        self.state(key, {'status':'creating','hash':fingerprint})
        result = self.api('POST',f'/repos/{owner}/{repo}/codespaces',body)
        self.state(key, {'status':'created','hash':fingerprint,'result':result})
        cfg = self.settings()
        if result['name'] not in cfg['spaces']:
            cfg['spaces'].append(result['name'])
            self.save(cfg)
        return result

    def control(self, name, action):
        self.name(name)
        if name not in self.settings()['spaces'] or action not in ('start','stop'):
            raise Blocked('Select an authorized Codespace and start or stop')
        return self.api('POST', f'/user/codespaces/{name}/{action}')

    def state(self, kind, value):
        with self.lock:
            if not self.closed:
                self.store.put(kind, uid('cloud'), value)
        return value

    def latest(self, kind):
        rows = self.store.rows('SELECT payload FROM records WHERE kind=? ORDER BY rowid DESC LIMIT 1', (kind,))
        return json.loads(rows[0]['payload']) if rows else None

    def jobs(self):
        rows = self.store.rows("SELECT DISTINCT kind FROM records WHERE kind LIKE 'cloud_job:%'")
        return [self.latest(r['kind']) for r in rows]

    def remote(self, name, request, timeout=60):
        self.name(name)
        if not self.settings()['enabled'] or name not in self.settings()['spaces']:
            raise Blocked('Codespace is not enabled for HA')
        command = shutil.which('gh')
        if not command:
            raise Blocked('Install GitHub CLI using HA prerequisites before Codespaces execution')
        code = Path(__file__).with_name('cloud_runner.py').read_bytes()
        encoded = base64.b64encode(code).decode('ascii')
        expression = "import base64;exec(base64.b64decode(" + repr(encoded) + "))"
        remote_command = 'python3 -c ' + shlex.quote(expression)
        env = {k:v for k,v in os.environ.items() if k in ('PATH','HOME','USERPROFILE','SystemRoot','WINDIR','TEMP','TMP','LOCALAPPDATA')}
        env['GH_TOKEN'] = self.app.github_auth.credentials()['access_token']
        env['GH_PROMPT_DISABLED'] = '1'
        try:
            with self.lock:
                if self.closed:
                    raise Blocked('HA is closing; reconcile remote work after restart')
                process = subprocess.Popen([command,'codespace','ssh','--codespace',name,'--',remote_command], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
                self.processes.add(process)
            try:
                stdout, _ = process.communicate(canonical(request), timeout=timeout)
                completed = subprocess.CompletedProcess(process.args, process.returncode, stdout)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()
                with self.lock:
                    self.processes.discard(process)
        except (subprocess.TimeoutExpired, OSError):
            raise Blocked('Codespace connection interrupted; reconcile the retained remote job before retrying') from None
        if completed.returncode != 0:
            raise Blocked('Codespace command failed; check its state and connection. Job delivery may be uncertain.')
        try:
            return json.loads(completed.stdout)
        except ValueError:
            raise Blocked('Codespace returned an invalid result; reconcile before retrying') from None

    def probe(self, name):
        result = self.remote(name, {'id':'capabilities','action':'probe'})
        self.state('cloud_capabilities:'+name, result)
        return result

    def submit(self, data):
        with self.lock:
            return self._submit(data)

    def submit_worker(self, task_id, operation_id, args):
        # Caller is the fenced broker. User interfaces use submit(), which
        # requires a paused project. Both routes use the same export guards.
        with self.lock:
            return self._submit({**args,'task':task_id,'request_id':operation_id}, worker=True)

    def _submit(self, data, worker=False):
        if self.closed or not self.settings()['enabled'] or not self.settings()['allow_execution']:
            raise Blocked('Enable optional Codespaces execution first')
        task = self.store.task(data['task']) if worker else self.app.workspace.guard(data['task'])
        space = self.name(data['space'])
        if space not in self.settings()['spaces']:
            raise Blocked('Select a Codespace in settings')
        requirements = data.get('requires', {})
        if not isinstance(requirements, dict) or set(requirements)-{'gpu','tools'} or type(requirements.get('gpu',False)) is not bool or not isinstance(requirements.get('tools',[]),list) or any(not isinstance(x,str) for x in requirements.get('tools',[])):
            raise ContractError('Runner requirements support gpu and a tool-name list')
        if requirements.get('gpu') or requirements.get('tools'):
            caps = self.latest('cloud_capabilities:'+space)
            if not caps or (requirements.get('gpu') and not caps.get('gpu')) or any(not caps.get('tools',{}).get(t) for t in requirements.get('tools',[])):
                raise Blocked('Probe the selected Codespace and select a runner with the required capabilities')
        key = self.name(data['request_id'])
        commands = data['commands']
        if not isinstance(commands,list) or not 1 <= len(commands) <= 32 or any(not isinstance(c,list) or not c or any(not isinstance(v,str) or '\x00' in v or len(v)>8000 for v in c) for c in commands):
            raise ContractError('Commands must be 1–32 explicit argument lists')
        timeout = data.get('timeout',3600)
        if type(timeout) is not int or not 1 <= timeout <= 40000:
            raise ContractError('Job timeout must be 1–40000 seconds, below the Codespaces session limit')
        inputs, outputs = data.get('files',[]), data.get('outputs',[])
        if not isinstance(inputs,list) or not isinstance(outputs,list) or len(inputs)>1000 or len(outputs)>100:
            raise ContractError('Provide explicit file and output path lists')
        for name in outputs:
            self.app.workspace.path(task['id'],name)
        files, hashes, total = {}, {}, 0
        for name in inputs:
            path = self.app.workspace.path(task['id'],name)
            raw = path.read_bytes()
            total += len(raw)
            if total > 16 * 1024 * 1024:
                raise ContractError('Cloud input snapshot exceeds 16 MiB')
            # Export only owner-selected files, subject to the same secret checks as checkpoints.
            self.app.broker.publications._safe_text(name, raw)
            files[name] = base64.b64encode(raw).decode()
            import hashlib
            hashes[name] = hashlib.sha256(raw).hexdigest()
        request = {'id':key,'commands':commands,'files':files,'hashes':hashes,'outputs':outputs,'timeout':timeout,'requires':requirements}
        request['request_hash'] = digest(request)
        kind = 'cloud_job:'+key
        old = self.latest(kind)
        if old:
            if old['request_hash'] != request['request_hash'] or old['space'] != space or old['task'] != task['id']:
                raise Conflict('Remote job ID already used with different inputs')
            return old
        row = {'id':key,'task':task['id'],'project':task['project_id'],'space':space,'status':'queued','request_hash':request['request_hash'],'revision':self.store.project(task['project_id'])['revision'],'created':time.time(),'claim':'Remote execution evidence; not independent project acceptance'}
        self.store.put('cloud_request',key,request)
        self.state(kind,row)
        self.queues.setdefault(space, []).append((row,request))
        if space not in self.active_spaces:
            self.active_spaces.add(space)
            self.pool.submit(self._drain,space)
        return row

    def _drain(self, space):
        while True:
            with self.lock:
                pending = self.queues.get(space, [])
                if self.closed or not pending:
                    self.active_spaces.discard(space)
                    return
                row,request = pending.pop(0)
            self._work(row,request)

    def _work(self,row,request):
        with self.lock:
            lock = self.locks.setdefault(row['space'],threading.Lock())
        with lock:
            with self.lock:
                if self.closed or self.latest('cloud_job:'+row['id'])['status'] == 'cancelled':
                    return
                self.state('cloud_job:'+row['id'],{**row,'status':'running'})
            try:
                result = self.remote(row['space'],request,request['timeout']+90)
                self.retain(row,result)
            except Exception:
                self.state('cloud_job:'+row['id'],{**row,'status':'uncertain','error':'Remote execution may have started. Use reconcile; the job is never replayed automatically.'})

    def retain(self,row,result):
        if result.get('id') != row['id'] or (result.get('request_hash') and result['request_hash'] != row['request_hash']):
            raise Blocked('Remote result does not match submitted snapshot')
        with self.lock:
            if self.closed:
                return {**row,'status':'uncertain'}
            artifact = self.app.broker.artifacts.add(canonical(result),row['id']+'.json',row['project'])
            return self.state('cloud_job:'+row['id'],{**row,'status':result.get('status','unknown'),'passed':result.get('passed'), 'result_artifact':artifact['id']})

    def reconcile(self,key):
        row = self.latest('cloud_job:'+self.name(key))
        if not row:
            raise ContractError('Unknown cloud job')
        return self.retain(row,self.remote(row['space'],{'id':key,'action':'status'}))

    def cancel(self,key):
        row = self.latest('cloud_job:'+self.name(key))
        if not row:
            raise ContractError('Unknown cloud job')
        with self.lock:
            row = self.latest('cloud_job:'+key)
            if row['status'] == 'queued':
                return self.state('cloud_job:'+key, {**row,'status':'cancelled'})
            if row['status'] in ('completed','cancelled'):
                return row
        return self.remote(row['space'],{'id':key,'action':'cancel'})

    def result(self, key):
        row = self.latest('cloud_job:'+self.name(key))
        if not row or not row.get('result_artifact'):
            raise Blocked('No retained remote result yet')
        return json.loads(self.app.broker.artifacts.read(row['result_artifact'], 'controller'))

    def import_output(self, key, name, expected_sha=None):
        row = self.latest('cloud_job:'+self.name(key))
        if not row:
            raise ContractError('Unknown cloud job')
        result = self.result(key)
        if result.get('request_hash') != row['request_hash'] or name not in result.get('outputs',{}):
            raise Blocked('No matching output in this job result')
        raw = base64.b64decode(result['outputs'][name], validate=True)
        if len(raw) > 8 * 1024 * 1024:
            raise Blocked('Output exceeds import limit')
        with tempfile.TemporaryDirectory(prefix='ha-cloud-import-') as folder:
            stage = Path(folder)/'output'
            stage.write_bytes(raw)
            return self.app.workspace.install(row['task'],name,stage,expected_sha)

    def close(self):
        with self.lock:
            if self.closed:
                return
            for row in self.jobs():
                if row['status'] == 'queued':
                    self.state('cloud_job:'+row['id'], {**row,'status':'cancelled'})
                elif row['status'] == 'running':
                    self.state('cloud_job:'+row['id'], {**row,'status':'uncertain','error':'HA closed during remote execution; reconcile after restart.'})
            self.closed = True
            for process in tuple(self.processes):
                if process.poll() is None:
                    process.kill()
        # Active SSH connections are killed above; drain callbacks before DB close.
        self.pool.shutdown(wait=True,cancel_futures=True)
