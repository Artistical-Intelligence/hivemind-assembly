"""Retained parser integration, with HA's existing writer and recovery safeguards."""
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from hivemind_assembly.core.broker import Broker
from hivemind_assembly.core.common import Blocked, Conflict, ContractError, file_hash
from hivemind_assembly.core import patching
from test_controller import req

ADD = '*** Begin Patch\n*** Add File: file.txt\n+hello\n*** End Patch'
UPDATE = '*** Begin Patch\n*** Update File: file.txt\n@@\n-hello\n+goodbye\n*** End Patch'


@pytest.fixture
def engine():
    path = os.environ.get('HA_TEST_EXECUTION')
    if not path:
        pytest.skip('requires the actual built internal editing helper')
    assert Path(path).is_file()
    return SimpleNamespace(command=(str(Path(path).resolve()),))


def test_real_planner_does_not_write_files(engine, tmp_path):
    text = patching.plan_file_patch(engine, 'file.txt', ADD, None, tmp_path)
    assert text == 'hello\n'
    assert not list(tmp_path.iterdir())


def test_real_planner_retains_original_line_endings(engine, tmp_path):
    text = patching.plan_file_patch(engine, 'file.txt', UPDATE, 'hello\r\nsecond\r\n', tmp_path)
    assert text == 'goodbye\r\nsecond\r\n'


@pytest.mark.parametrize('patch', [
    '*** Begin Patch\n*** Delete File: file.txt\n*** End Patch',
    '*** Begin Patch\n*** Update File: file.txt\n*** Move to: another.txt\n@@\n-hello\n+new\n*** End Patch',
    '*** Begin Patch\n*** Add File: other.txt\n+x\n*** End Patch',
    '*** Begin Patch\n*** Update File: file.txt\n@@\n-hello\n+new\n*** Add File: other.txt\n+x\n*** End Patch',
])
def test_real_planner_cannot_expand_the_write_scope(engine, tmp_path, patch):
    with pytest.raises(Blocked):
        patching.plan_file_patch(engine, 'file.txt', patch, 'hello\n', tmp_path)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('name', ['../x', '/x', 'a/../x', '.git/config', 'x\\a', 'C:x',
                                  'nul.txt', 'A//x', './x', 'x.', 'x '])
def test_invalid_patch_targets(name):
    with pytest.raises(ContractError):
        patching.patch_path(name)


def test_linked_paths_are_not_patch_targets(tmp_path):
    target = tmp_path / 'target'
    target.write_text('private')
    try:
        (tmp_path / 'link').symlink_to(target)
    except OSError:
        pytest.skip('symbolic links unavailable')
    with pytest.raises(Blocked, match='Linked'):
        patching.patch_target(tmp_path, 'link')


def test_unprepared_engine_is_not_replaced_by_another_runner(tmp_path):
    with pytest.raises(Blocked, match='not prepared'):
        patching.plan_file_patch(None, 'file.txt', ADD, None, tmp_path)


def test_hung_planner_is_bounded(tmp_path):
    fake = SimpleNamespace(command=(sys.executable, '-c', 'import time; time.sleep(30)'))
    with pytest.raises(Blocked, match='not changed'):
        patching.plan_file_patch(fake, 'file.txt', ADD, None, tmp_path, timeout=0.1)


@pytest.mark.parametrize('output', ['not-json', '{"ok":true,"ok":false}',
                                   '{"ok":true,"filesystem_modified":true}', '[]'])
def test_untrusted_planner_replies_are_rejected(tmp_path, output):
    script = 'import sys; sys.stdin.readline(); print(' + repr(output) + ')'
    fake = SimpleNamespace(command=(sys.executable, '-c', script))
    with pytest.raises(Blocked):
        patching.plan_file_patch(fake, 'file.txt', ADD, None, tmp_path)


def test_broker_applies_and_replays_the_original_receipt(ready, engine):
    controller, task, epoch = ready
    broker = Broker(controller, {'foundations': {}})
    broker.jobs.runtime = lambda: engine
    request = req(task, epoch, 'write_file', {'path':'file.txt','expected_hash':None,'patch':ADD})
    result = broker.execute(request)
    assert result['status'] == 'saved'
    assert (broker.workspace(task['id']) / 'file.txt').read_text() == 'hello\n'
    broker.jobs.runtime = lambda: pytest.fail('duplicate delivery must not recompute')
    assert broker.execute(request) == result
    assert controller.store.project(task['project_id'])['revision'] == 1


def test_broker_updates_with_exact_old_hash_and_retained_intent(ready, engine):
    controller, task, epoch = ready
    broker = Broker(controller, {'foundations': {}})
    broker.jobs.runtime = lambda: engine
    path = broker.workspace(task['id']) / 'file.txt'
    path.write_bytes(b'hello\r\n')
    old = file_hash(path)
    result = broker.execute(req(task, epoch, 'write_file',
                               {'path':'file.txt','expected_hash':old,'patch':UPDATE}))
    assert path.read_bytes() == b'goodbye\r\n'
    intent = controller.store.get('file_intent', 'op1')
    assert intent['before'] == old and intent['after'] == result['sha256']


def test_missing_runtime_does_not_silently_rewrite(ready):
    controller, task, epoch = ready
    broker = Broker(controller, {'foundations': {}})
    with pytest.raises(Blocked, match='not prepared'):
        broker.execute(req(task, epoch, 'write_file', {'path':'file.txt','patch':ADD,'expected_hash':None}))
    assert not (broker.workspace(task['id']) / 'file.txt').exists()


@pytest.mark.parametrize('change', ['file', 'lease', 'cancel'])
def test_state_changed_during_planning_prevents_write(ready, monkeypatch, change):
    controller, task, epoch = ready
    broker = Broker(controller, {'foundations': {}})
    path = broker.workspace(task['id']) / 'file.txt'
    def plan(*args):
        if change == 'file':
            path.write_text('external-edit')
        elif change == 'lease':
            with controller.store.tx() as connection:
                connection.execute('UPDATE tasks SET lease_until=0')
        else:
            broker.cancel[task['id']].set()
        return 'planned-content'
    monkeypatch.setattr(patching, 'plan_file_patch', plan)
    with pytest.raises((Conflict, Blocked)):
        broker.execute(req(task, epoch, 'write_file', {'path':'file.txt','patch':ADD,'expected_hash':None}))
    assert (path.read_text() if path.exists() else None) == ('external-edit' if change == 'file' else None)
    assert controller.store.one('SELECT state FROM operations')['state'] == 'failed'


def test_patch_keeps_uncertain_write_reconciliation(ready, engine, monkeypatch):
    controller, task, epoch = ready
    broker = Broker(controller, {'foundations': {}})
    broker.jobs.runtime = lambda: engine
    monkeypatch.setattr(controller, 'finish', lambda *a: (_ for _ in ()).throw(RuntimeError('interrupted')))
    with pytest.raises(RuntimeError):
        broker.execute(req(task, epoch, 'write_file', {'path':'file.txt','patch':ADD,'expected_hash':None}))
    controller.recover()
    assert broker.reconcile_file('op1')['reconciled']
    assert controller.store.project(task['project_id'])['revision'] == 1


def test_patch_and_text_are_mutually_exclusive(ready):
    controller, task, epoch = ready
    broker = Broker(controller, {'foundations': {}})
    with pytest.raises(ContractError, match='exactly one'):
        broker.execute(req(task, epoch, 'write_file', {'path':'file.txt','patch':ADD,'text':'x','expected_hash':None}))
