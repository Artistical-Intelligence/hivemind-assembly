"""Protocol regressions and opt-in actual compiled-helper acceptance."""
import json
import os
from pathlib import Path
import sys
import threading
import time

import pytest

from hivemind_assembly.core.common import Blocked, ContractError
from hivemind_assembly.core.execution import ExecutionClient
from hivemind_assembly.core.jobs import Jobs


FAKE = r'''
import base64, json, sys
from pathlib import Path
request = json.loads(sys.stdin.readline())
key = request['id']
mode = request['argv'][0]
def send(kind, **fields):
    print(json.dumps({'type': kind, 'id': key, **fields}), flush=True)
def finish(count=0, state='completed'):
    send('finished', status=state, exit_code=0, bytes=count)
if mode == 'wrong-id':
    key = 'other'
send('started', pty=False)
if mode == 'wait':
    control = json.loads(sys.stdin.readline())
    assert control == {'action': 'terminate'}
    finish(state='cancelled')
elif mode == 'exit':
    Path('effect.txt').write_text('once')
elif mode == 'malformed':
    print('not-json', flush=True)
elif mode == 'long-frame':
    print('x' * (1024 * 1024 + 1), flush=True)
elif mode == 'bad-base64':
    send('output', stream='stdout', offset=0, data='%%%')
elif mode == 'offset':
    send('output', stream='stdout', offset=1, data='eA==')
elif mode == 'duplicate-start':
    send('started', pty=False)
elif mode == 'bad-count':
    finish(1)
elif mode == 'after-finish':
    finish()
    send('started', pty=False)
elif mode == 'environment':
    value = json.dumps(request['environment']).encode()
    send('output', stream='stdout', offset=0, data=base64.b64encode(value).decode())
    finish(len(value))
else:
    send('output', stream='stdout', offset=0, data=base64.b64encode(b'hello ').decode())
    send('output', stream='stderr', offset=6, data=base64.b64encode(b'world').decode())
    finish(11)
'''


@pytest.fixture
def fake(tmp_path):
    script = tmp_path / 'helper.py'
    script.write_text(FAKE, encoding='utf-8')
    return ExecutionClient([sys.executable, '-u', str(script)])


def test_protocol_round_trip(fake, tmp_path):
    result = Jobs(runtime=lambda: fake).run('example', ['ok'], tmp_path)
    assert result['status'] == 'completed'
    assert result['exit_code'] == 0
    assert result['output'] == 'hello world'
    assert not result['output_truncated']


@pytest.mark.parametrize('mode', ['wrong-id', 'exit', 'malformed', 'long-frame',
                                  'bad-base64', 'offset', 'duplicate-start',
                                  'bad-count', 'after-finish'])
def test_invalid_response_never_replays(fake, tmp_path, mode, monkeypatch):
    jobs = Jobs(runtime=lambda: fake)
    monkeypatch.setattr(jobs, '_run_native', lambda *a: pytest.fail('must not replay'))
    with pytest.raises(Blocked, match='reconcile'):
        jobs.run('example', [mode], tmp_path, timeout=5)
    assert not jobs.reservations
    if mode == 'exit':
        assert (tmp_path / 'effect.txt').read_text() == 'once'


def test_credentials_not_inherited(fake, tmp_path, monkeypatch):
    monkeypatch.setenv('HA_TEST_PRIVATE_SECRET', 'should-not-be-forwarded')
    result = Jobs(runtime=lambda: fake).run('env', ['environment'], tmp_path,
                                          environment={'JAVA_HOME': str(tmp_path)})
    environment = json.loads(result['output'])
    assert 'HA_TEST_PRIVATE_SECRET' not in environment
    assert environment['JAVA_HOME'] == str(tmp_path)


def test_cancel_before_spawn(fake, tmp_path):
    stop = threading.Event()
    stop.set()
    jobs = Jobs(runtime=lambda: pytest.fail('must not resolve or spawn'))
    assert jobs.run('cancel', ['exit'], tmp_path, cancel=stop)['status'] == 'cancelled'
    assert not (tmp_path / 'effect.txt').exists()


def test_timeout_requests_owned_child_stop(fake, tmp_path):
    result = Jobs(runtime=lambda: fake).run('wait', ['wait'], tmp_path, timeout=0.4)
    assert result['status'] == 'timeout'
    assert result['elapsed'] < 8


def test_cancel_and_single_operation_owner(fake, tmp_path):
    jobs = Jobs(runtime=lambda: fake)
    result, errors = [], []
    def run():
        try:
            result.append(jobs.run('wait', ['wait'], tmp_path, timeout=10))
        except BaseException as exc:
            errors.append(exc)
    thread = threading.Thread(target=run)
    thread.start()
    deadline = time.monotonic() + 3
    while 'wait' not in jobs.reservations and time.monotonic() < deadline:
        time.sleep(0.01)
    try:
        with pytest.raises(ContractError, match='already running'):
            jobs.run('wait', ['ok'], tmp_path)
    finally:
        jobs.stop('wait')
        thread.join(timeout=12)
    assert not thread.is_alive()
    assert not errors
    assert result[0]['status'] == 'cancelled'
    assert not jobs.reservations


@pytest.fixture
def compiled():
    path = os.environ.get('HA_TEST_EXECUTION')
    if not path:
        pytest.skip('requires an actual built HA helper')
    assert Path(path).is_file(), 'Configured helper does not exist'
    return ExecutionClient([str(Path(path).resolve())])


def test_compiled_output(compiled, tmp_path):
    result = Jobs(runtime=lambda: compiled).run(
        'real', [sys.executable, '-c', 'print("native-helper-ok")'], tmp_path)
    assert result['status'] == 'completed'
    assert result['exit_code'] == 0
    assert result['output'].strip() == 'native-helper-ok'


def test_compiled_nonzero_exit(compiled, tmp_path):
    result = Jobs(runtime=lambda: compiled).run(
        'real', [sys.executable, '-c', 'raise SystemExit(7)'], tmp_path)
    assert result['status'] == 'completed'
    assert result['exit_code'] == 7


def test_compiled_timeout(compiled, tmp_path):
    result = Jobs(runtime=lambda: compiled).run(
        'real', [sys.executable, '-c', 'import time; time.sleep(30)'], tmp_path,
        timeout=0.5)
    assert result['status'] == 'timeout'
    assert result['elapsed'] < 10
