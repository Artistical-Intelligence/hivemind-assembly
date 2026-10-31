"""Owned, immutable HA runtime components and offline installation.

The catalogue is shipped as part of HA, not fetched from an upstream registry.
An imported bundle must match that catalogue before any of its files are made
active. Installations are content addressed and retained for explicit rollback.
This is an integrity/recovery boundary, not a sandbox against the local owner.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import secrets
import shutil
import stat
import tempfile
import threading
import zipfile

from hivemind_assembly.core.common import Blocked, ContractError, InstanceLock, atomic_write, canonical, file_hash
from hivemind_assembly.paths import APP_ROOT

SHA = re.compile(r"[0-9a-f]{64}\Z")
NAME = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")
RESERVED = re.compile(r"(?:con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\..*)?\Z", re.I)
MAX_FILES = 100_000
MAX_UNPACKED = 4 * 1024**3
MAX_FILE = 1024**3


def host_platform() -> str:
    arch = platform.machine().lower()
    arch = 'x64' if arch in ('amd64', 'x86_64') else 'arm64' if arch in ('aarch64', 'arm64') else arch
    system = 'windows' if os.name == 'nt' else 'macos' if platform.system() == 'Darwin' else 'linux'
    return system + '-' + arch


def relative_path(value: str) -> str:
    """A portable, unambiguous path; also reject Windows ADS/device spellings."""
    if not isinstance(value, str) or not value or len(value) > 1500 or any(c in value for c in ('\\', ':', '\x00')):
        raise ContractError('Invalid component path')
    path = PurePosixPath(value)
    if not path.parts or path.is_absolute() or str(path) != value or any(
        p in ('', '.', '..') or p.endswith((' ', '.')) or RESERVED.fullmatch(p)
        for p in path.parts
    ):
        raise ContractError('Invalid component path')
    return value


def _read_json(path: Path, limit: int = 16 * 1024 * 1024):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
        raise ContractError('Component metadata is not a bounded regular file')
    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ContractError('Duplicate component metadata key')
            result[key] = value
        return result
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ContractError('Invalid metadata number')))


def _active_state(state):
    if not isinstance(state, dict) or state.get('schema') != 1 or not isinstance(state.get('active'), dict):
        raise ContractError('Unsupported component state')
    for name, value in state['active'].items():
        if (not isinstance(name, str) or not NAME.fullmatch(name) or not isinstance(value, dict)
                or not isinstance(value.get('sha256'), str) or not SHA.fullmatch(value['sha256'])
                or not isinstance(value.get('version'), str) or not value['version']):
            raise ContractError('Invalid active component')
    return state['active']


@dataclass(frozen=True)
class Component:
    name: str
    version: str
    digest: str
    home: Path
    entrypoint: Path
    metadata: dict


class Components:
    """One local inventory for HA, with no updater, shell installer or network."""
    def __init__(self, root, bundle_root=None, *, platform_name=None):
        self.root = Path(root) / 'components'
        self.bundle = Path(bundle_root) if bundle_root is not None else APP_ROOT / 'components'
        self.platform = platform_name or host_platform()
        self.path = self.root / 'active.json'
        self.lock = threading.RLock()
        self.catalogue_error = None
        self.state_error = None
        self.entries = {}
        self.active = {}
        try:
            catalogue = self.bundle / 'catalogue.json'
            data = _read_json(catalogue) if catalogue.exists() else {'schema': 1, 'components': []}
            if not isinstance(data, dict) or data.get('schema') != 1 or not isinstance(data.get('components'), list):
                raise ContractError('Unsupported component catalogue')
            for entry in data['components']:
                if not isinstance(entry, dict) or not isinstance(entry.get('version'), str) or not entry['version']:
                    raise ContractError('Invalid component catalogue entry')
                name = entry['component']
                if not isinstance(name, str) or not NAME.fullmatch(name) or not SHA.fullmatch(entry['sha256']):
                    raise ContractError('Invalid component catalogue entry')
                relative_path(entry['file'])
                relative_path(entry['entrypoint'])
                if entry['platform'] not in (self.platform, 'any'):
                    continue
                if name in self.entries:
                    raise ContractError('Ambiguous component selection')
                self.entries[name] = entry
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.catalogue_error = 'HA component catalogue needs repair; no component was loaded.'
            self.entries = {}
        try:
            state = _read_json(self.path) if self.path.exists() else {'schema': 1, 'active': {}}
            self.active = _active_state(state)
        except (OSError, ValueError, KeyError, TypeError):
            self.state_error = 'HA component state needs repair. The original state and stored versions were preserved.'
            self.active = {}

    def _require_healthy(self):
        if self.catalogue_error or self.state_error:
            raise Blocked(self.catalogue_error or self.state_error)
        for path in (self.root, self.root / 'objects', self.root / 'archives', self.root / 'preserved'):
            if path.is_symlink() or (path.exists() and not path.is_dir()):
                raise Blocked('HA component storage must not be redirected or a symbolic link')

    def snapshot(self):
        """Passive status: no processes, downloads, repairs or repeated hashing."""
        items = []
        for name, entry in sorted(self.entries.items()):
            active = self.active.get(name)
            expected = entry['sha256']
            path = self.root / 'objects' / expected
            items.append({'id': name, 'label': entry.get('label', name.replace('-', ' ').title()),
                          'version': entry['version'], 'bundled': (self.bundle / entry['file']).is_file(),
                          'installed': bool(active and active['sha256'] == expected and path.is_dir()),
                          'retained_version': bool(active),
                          'state': 'installed' if active and active['sha256'] == expected and path.is_dir() else 'ready_to_prepare' if (self.bundle / entry['file']).is_file() else 'package_missing'})
        return {'components': items, 'error': self.catalogue_error or self.state_error,
                'network_required': False, 'platform': self.platform}

    def _manifest(self, folder: Path, name: str, expected: dict | None = None):
        metadata = _read_json(folder / 'component.json')
        if not isinstance(metadata, dict) or metadata.get('schema') != 1 or metadata.get('component') != name:
            raise ContractError('Component identity mismatch')
        if metadata.get('platform') not in (self.platform, 'any'):
            raise ContractError('Component belongs to another platform')
        files = metadata.get('files')
        if not isinstance(files, dict) or not 1 <= len(files) <= MAX_FILES:
            raise ContractError('Invalid component file inventory')
        folded = set()
        for rel, digest in files.items():
            relative_path(rel)
            if not isinstance(digest, str) or not SHA.fullmatch(digest) or rel.casefold() in folded:
                raise ContractError('Invalid or ambiguous component file inventory')
            folded.add(rel.casefold())
        entry = relative_path(metadata['entrypoint'])
        if entry not in files:
            raise ContractError('Component entrypoint is not in its file inventory')
        if expected and (metadata.get('version') != expected['version'] or entry != expected['entrypoint']):
            raise ContractError('Component does not match the approved catalogue')
        return metadata

    def _verify(self, folder: Path, name: str, expected: dict):
        if folder.is_symlink() or not folder.is_dir():
            raise Blocked('HA runtime component is missing or redirected')
        metadata = self._manifest(folder, name, expected)
        # The inventory itself is authenticated by the retained archive. A local
        # edit to both payload and inventory must not redefine the trusted hash.
        retained = self.root / 'archives' / (expected['sha256'] + '.zip')
        if not retained.is_file() or retained.is_symlink() or file_hash(retained) != expected['sha256']:
            raise Blocked('The retained HA component archive did not pass its integrity check')
        with zipfile.ZipFile(retained) as z:
            if z.read('component.json') != (folder / 'component.json').read_bytes():
                raise Blocked('The component inventory was changed')
        payload = folder / 'payload'
        if payload.is_symlink() or not payload.is_dir():
            raise Blocked('The component payload is missing or redirected')
        observed = set()
        for path in payload.rglob('*'):
            if path.is_symlink():
                raise Blocked('A component contains a symbolic link')
            if path.is_file():
                rel = path.relative_to(payload).as_posix()
                if rel not in metadata['files'] or file_hash(path) != metadata['files'][rel]:
                    raise Blocked('HA component files changed; use Repair without overwriting the altered copy')
                observed.add(rel)
        if observed != set(metadata['files']):
            raise Blocked('HA component files are missing')
        return Component(name, metadata['version'], expected['sha256'], payload,
                         payload / metadata['entrypoint'], metadata)

    def resolve(self, name: str) -> Component:
        with self.lock:
            self._require_healthy()
            entry = self.entries.get(name)
            if entry is None:
                raise Blocked('This HA build does not contain the requested runtime component')
            active = self.active.get(name)
            if not active or active['sha256'] != entry['sha256']:
                raise Blocked('Prepare the built-in capabilities from HA Settings first')
            return self._verify(self.root / 'objects' / entry['sha256'], name, entry)

    def prepare(self, names=None, *, repair=False):
        """Install only trusted bundled bytes; retain altered/older copies."""
        with self.lock:
            if repair and self.state_error:
                self._recover_state()
            self._require_healthy()
            selected = list(self.entries) if names is None else list(names)
            if not selected or any(name not in self.entries for name in selected):
                raise Blocked('The required built-in package is not included in this HA build')
            self.root.mkdir(parents=True, exist_ok=True)
            owner = InstanceLock(self.root)
            try:
                # Re-read under the process lock so another completed preparation
                # cannot be lost by an older Components instance.
                if self.path.exists():
                    state = _read_json(self.path)
                    self.active = _active_state(state)
                completed = []
                for name in selected:
                    entry = self.entries[name]
                    target = self.root / 'objects' / entry['sha256']
                    if target.exists() or target.is_symlink():
                        try:
                            self._verify(target, name, entry)
                        except (OSError, ValueError, KeyError, zipfile.BadZipFile):
                            if not repair:
                                raise Blocked('The installed component changed. Use Repair to preserve it and rebuild from the retained package.') from None
                            quarantine = self.root / 'preserved'
                            quarantine.mkdir(exist_ok=True)
                            target.rename(quarantine / (entry['sha256'] + '-' + secrets.token_hex(8)))
                    if not target.exists():
                        self._install(name, entry, target)
                    self.active[name] = {'sha256': entry['sha256'], 'version': entry['version']}
                    atomic_write(self.path, canonical({'schema': 1, 'active': self.active}))
                    completed.append({'id': name, 'version': entry['version'], 'state': 'prepared'})
                return {'state': 'prepared', 'items': completed, 'network_used': False}
            finally:
                owner.close()

    def _install(self, name, entry, target):
        archive = self.bundle / entry['file']
        retained = self.root / 'archives' / (entry['sha256'] + '.zip')
        if retained.is_file() and not retained.is_symlink() and file_hash(retained) == entry['sha256']:
            archive = retained
        if not archive.is_file() or archive.is_symlink() or file_hash(archive) != entry['sha256']:
            raise Blocked('The built-in runtime package is missing or failed its integrity check. No download was substituted.')
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.preparing-', dir=target.parent) as temporary:
            stage = Path(temporary)
            with zipfile.ZipFile(archive) as z:
                members = z.infolist()
                if len(members) > MAX_FILES + 2 or sum(m.file_size for m in members) > MAX_UNPACKED:
                    raise ContractError('Runtime archive exceeds installation limits')
                names = set()
                for item in members:
                    if item.is_dir():
                        raise ContractError('Runtime archives must contain only inventoried regular files')
                    path = relative_path(item.filename)
                    if path.casefold() in names or item.file_size > MAX_FILE:
                        raise ContractError('Duplicate or oversized archive member')
                    names.add(path.casefold())
                    mode = item.external_attr >> 16
                    if mode and stat.S_IFMT(mode) not in (0, stat.S_IFREG):
                        raise ContractError('Runtime archive contains a non-regular file')
                if 'component.json' not in names or z.getinfo('component.json').file_size > 16 * 1024 * 1024:
                    raise ContractError('Runtime archive has no bounded inventory')
                (stage / 'component.json').write_bytes(z.read('component.json'))
                metadata = self._manifest(stage, name, entry)
                expected_names = {'component.json', *('payload/' + p for p in metadata['files'])}
                if {item.filename for item in members} != expected_names:
                    raise ContractError('Runtime archive and inventory disagree')
                for rel, expected in metadata['files'].items():
                    output = stage / 'payload' / rel
                    output.parent.mkdir(parents=True, exist_ok=True)
                    digest = hashlib.sha256()
                    with z.open('payload/' + rel) as source, output.open('xb') as stream:
                        for block in iter(lambda: source.read(1024 * 1024), b''):
                            digest.update(block)
                            stream.write(block)
                    if digest.hexdigest() != expected:
                        raise ContractError('Runtime archive file failed its integrity check')
                    mode = z.getinfo('payload/' + rel).external_attr >> 16
                    output.chmod(0o755 if mode & 0o111 else 0o644)
            retained.parent.mkdir(parents=True, exist_ok=True)
            if archive != retained:
                if retained.exists():
                    preserved = self.root / 'preserved'
                    preserved.mkdir(exist_ok=True)
                    retained.rename(preserved / (retained.name + '-' + secrets.token_hex(8)))
                with tempfile.NamedTemporaryFile(prefix='.archive-', dir=retained.parent, delete=False) as output:
                    pending = Path(output.name)
                    try:
                        with archive.open('rb') as source:
                            shutil.copyfileobj(source, output, 1024 * 1024)
                        output.flush()
                        os.fsync(output.fileno())
                    except BaseException:
                        pending.unlink(missing_ok=True)
                        raise
                if file_hash(pending) != entry['sha256']:
                    pending.unlink(missing_ok=True)
                    raise Blocked('Runtime archive changed during installation')
                pending.replace(retained)
            stage.rename(target)
        self._verify(target, name, entry)

    def _recover_state(self):
        """Explicit repair preserves damaged metadata and authenticates retained objects."""
        if self.catalogue_error:
            raise Blocked(self.catalogue_error)
        for path in (self.root, self.root / 'objects', self.root / 'archives', self.root / 'preserved'):
            if path.is_symlink() or (path.exists() and not path.is_dir()):
                raise Blocked('HA component storage must not be redirected')
        self.root.mkdir(parents=True, exist_ok=True)
        owner = InstanceLock(self.root)
        try:
            try:
                current = _active_state(_read_json(self.path))
            except (OSError, ValueError, TypeError, KeyError):
                current = None
            if current is None:
                if self.path.exists() or self.path.is_symlink():
                    preserved = self.root / 'preserved'
                    preserved.mkdir(exist_ok=True)
                    self.path.rename(preserved / ('active-' + secrets.token_hex(12) + '.json'))
                current = {}
                for name, entry in self.entries.items():
                    try:
                        self._verify(self.root / 'objects' / entry['sha256'], name, entry)
                    except (OSError, ValueError, KeyError, zipfile.BadZipFile):
                        continue
                    current[name] = {'sha256': entry['sha256'], 'version': entry['version']}
                atomic_write(self.path, canonical({'schema': 1, 'active': current}))
            self.active = current
            self.state_error = None
        finally:
            owner.close()

    def effective_foundations(self, original):
        self._require_healthy()
        result = dict(original)
        mapping = {'analysis': 'rea_home', 'node': 'node_executable', 'jdk': 'java_home', 'ghidra': 'ghidra_home', 'compiler': 'c_compiler'}
        for name, setting in mapping.items():
            if name not in self.active or name not in self.entries:
                value = result.get(setting)
                if isinstance(value, str) and value and Path(value).resolve().is_relative_to(self.root.resolve()):
                    raise Blocked('A configured owned runtime has no approved active package')
                continue
            component = self.resolve(name)
            result[setting] = str(component.entrypoint if name in ('node', 'compiler') else component.home)
        return result
