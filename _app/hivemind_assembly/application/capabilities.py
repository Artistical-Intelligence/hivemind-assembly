"""One HA-owned preparation, validation and recovery surface.

A component being present is not a successful live test. Passive dashboard
status never launches a process, installs a package, or retries an operation.
"""
from __future__ import annotations
import json
from pathlib import Path
import threading
import time
from hivemind_assembly.core.common import Blocked, ContractError, atomic_write, canonical
from .components import Components


class BuiltinCapabilities:
    def __init__(self, root, config_path, config, *, bundle_root=None):
        self.root = Path(root)
        self.config_path = Path(config_path)
        self.config = config
        self.bundle_root = bundle_root
        self.components = Components(root, bundle_root)
        self.path = self.root / 'private/setup/capability-status.json'
        self.lock = threading.Lock()
        self.state = {'state': 'not_checked', 'checks': {}, 'steps': []}
        self.state_error = False
        if self.path.exists():
            try:
                if self.path.is_symlink() or self.path.stat().st_size > 2 * 1024 * 1024:
                    raise ValueError('Invalid setup status')
                saved = json.loads(self.path.read_text(encoding='utf-8'))
                if not isinstance(saved, dict) or saved.get('state') not in {
                    'not_checked', 'preparing', 'checking', 'repairing', 'interrupted',
                    'ready', 'needs_attention', 'failed',
                } or not isinstance(saved.get('checks'), dict):
                    raise ValueError('Invalid setup state')
                self.state = saved
                if saved['state'] in ('preparing', 'checking', 'repairing'):
                    self.state = {**saved, 'state': 'interrupted',
                                  'message': 'HA stopped during setup. Prepared files were retained; resume from this screen.'}
            except (OSError, ValueError, TypeError):
                self.state_error = True
                self.state = {'state': 'needs_attention', 'checks': {}, 'steps': [],
                              'message': 'The previous setup status is damaged and was preserved. Component integrity can still be checked.'}

    def _save(self):
        if self.state_error:
            raise Blocked('The setup status needs explicit repair before saving new results')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(self.path, canonical(self.state))

    def snapshot(self):
        return {**self.state, 'packages': self.components.snapshot(),
                'busy': self.lock.locked(), 'local_first': True,
                'built_in': {'sessions': True, 'browser_automation': True},
                'retained_originals': True}

    def activate(self):
        """Authenticate already-installed components once at application start."""
        try:
            self.config.setdefault('foundations', {}).update(
                self.components.effective_foundations(self.config.get('foundations', {})))
        except (OSError, ValueError, KeyError):
            owned = (self.root / 'components').resolve()
            for key, value in list(self.config.get('foundations', {}).items()):
                if isinstance(value, str) and value:
                    try:
                        if Path(value).resolve().is_relative_to(owned):
                            self.config['foundations'][key] = ''
                    except (OSError, ValueError):
                        pass
            self.state = {**self.state, 'state': 'needs_attention',
                          'message': 'A built-in package failed verification. Use Repair; other HA functions remain available.'}

    def run(self, action, publish=None):
        if action not in ('prepare', 'check', 'repair'):
            raise ContractError('Unknown built-in capability action')
        if not self.lock.acquire(blocking=False):
            raise Blocked('HA is already preparing or checking these capabilities')
        try:
            if self.state_error:
                if action != 'repair':
                    raise Blocked('Use Repair to preserve the damaged setup status and check the owned packages')
                preserved = self.path.with_name('capability-status-preserved-' + str(time.time_ns()) + '.json')
                self.path.rename(preserved)
                self.state_error = False
            self.state = {'state': {'prepare': 'preparing', 'check': 'checking', 'repair': 'repairing'}[action],
                          'checks': {}, 'steps': [], 'operation': action, 'started': time.time()}
            self._save()
            self.components = Components(self.root, self.bundle_root)
            if action in ('prepare', 'repair'):
                from .setup import SetupProgress
                progress = SetupProgress(publish)
                required = ('node', 'jdk', 'analysis', 'ghidra')
                if any(name not in self.components.entries for name in required):
                    raise Blocked('This HA copy is missing its complete built-in package. Restore the full HA installation; no external installer was substituted.')
                selected = list(self.components.entries)
                for name in selected:
                    progress.expect('Preparing ' + self.components.entries[name].get('label', name), 20)
                for name in selected:
                    label = self.components.entries[name].get('label', name)
                    progress.begin('Preparing ' + label, 20)
                    self.components.prepare([name], repair=action == 'repair')
                    self.state['steps'].append({'capability': name, 'state': 'prepared'})
                    self._save()
                self.config['foundations'] = self.components.effective_foundations(self.config.get('foundations', {}))
                previous = self.path.parent / 'before-owned-components.json'
                if not previous.exists():
                    saved = json.loads(self.config_path.read_text())
                    atomic_write(previous, canonical({'foundations': saved.get('foundations', {})}))
                saved = json.loads(self.config_path.read_text())
                saved['foundations'] = self.config['foundations']
                atomic_write(self.config_path, canonical(saved))
                progress.finish()
            checked = {}
            for name in self.components.active:
                if name not in self.components.entries:
                    continue
                try:
                    component = self.components.resolve(name)
                    checked[name] = {'passed': True, 'version': component.version, 'kind': 'file_integrity'}
                except (OSError, ValueError, KeyError):
                    checked[name] = {'passed': False, 'kind': 'file_integrity', 'reason': 'Stored runtime needs repair'}
            self.state.update(state='checking', checks=checked)
            self._save()
            from .verification import verify_foundations
            result = verify_foundations(self.root / 'private/verification', self.config.get('foundations', {}))
            summary = {name: {'passed': value.get('passed') is True,
                              **({'reason': str(value['reason'])[:500]} if value.get('reason') else {})}
                       for name, value in result.get('checks', {}).items()}
            passed = bool(result.get('passed')) and all(value['passed'] for value in checked.values())
            self.state.update(state='ready' if passed else 'needs_attention',
                              checks={**checked, **summary}, finished=time.time(),
                              message='Built-in checks passed.' if passed else 'HA is usable; the listed capabilities need attention.')
            self._save()
            return {'state': self.state['state'], 'checks': self.state['checks'],
                    'network_required': False, 'live_account_acceptance': False,
                    'evidence_directory': result.get('evidence_directory')}
        except BaseException as error:
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                raise
            self.state.update(state='failed', message=str(error)[:1000], finished=time.time())
            if not self.state_error:
                self._save()
            raise
        finally:
            self.lock.release()
