"""Compute one file's text patch with the owned engine; never write project files.

The broker keeps authorization, before/after artifacts and reconciliation. A
multi-file change remains several independently fenced write_file operations.
"""
from __future__ import annotations

from contextlib import suppress
import json
import os
from pathlib import PurePosixPath
import queue
import re
import subprocess
import threading
import time

from .common import Blocked, ContractError
from .execution import kill_tree

FILE_LIMIT = 2_000_000
REPLY_LIMIT = 16 * 1024 * 1024


def patch_path(name):
    if (not isinstance(name, str) or not 1 <= len(name) <= 500
            or any(ord(c) < 32 or c in '\\:<>"|?*' for c in name)):
        raise ContractError('Patch needs one ordinary relative project file')
    path = PurePosixPath(name)
    if (path.is_absolute() or str(path) != name or not path.parts
            or any(p in ('.', '..') or p.lower() == '.git' or p.endswith((' ', '.'))
                   or re.fullmatch(r'(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?', p)
                   for p in path.parts)):
        raise ContractError('Patch needs one ordinary relative project file')
    return name


def patch_target(root, name):
    """Do not let an alias, junction or symbolic link redirect an editing request."""
    target = root.resolve()
    for part in patch_path(name).split('/'):
        target = target / part
        if target.is_symlink() or (hasattr(target, 'is_junction') and target.is_junction()):
            raise Blocked('Linked paths cannot be patched')
    return target


def plan_file_patch(engine, name, patch, original, cwd, cancel=None, timeout=20):
    name = patch_path(name)
    if not isinstance(patch, str) or not patch or len(patch.encode('utf-8')) > FILE_LIMIT:
        raise ContractError('Patch must be bounded UTF-8 text')
    if original is not None and (not isinstance(original, str) or '\0' in original
                                 or len(original.encode('utf-8')) > FILE_LIMIT):
        raise ContractError('Patch requires a bounded original text file')
    command = getattr(engine, 'command', None)
    if (not isinstance(command, (tuple, list)) or not command
            or not all(isinstance(x, str) and x and '\0' not in x for x in command)):
        raise Blocked('HA internal editing capability is not prepared')
    request = json.dumps({'action': 'plan_patch', 'patch': patch, 'files': {name: original}},
                         ensure_ascii=False, allow_nan=False).encode('utf-8') + b'\n'
    if len(request) > 8 * 1024 * 1024:
        raise ContractError('Patch request is too large')
    if cancel is not None and cancel.is_set():
        raise Blocked('Patch cancelled before planning')
    # This operation has no reason to inherit account tokens, HOME or browser data.
    env = {k: v for k, v in os.environ.items() if k.upper() in ('SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP')}
    env['ORT_DISABLE_TELEMETRY'] = '1'
    flags = ({'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt'
             else {'start_new_session': True})
    process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, **flags)
    results = queue.Queue(maxsize=2)
    failure = 'HA could not plan this patch; project files were not changed'

    def read():
        try:
            results.put_nowait(process.stdout.read(REPLY_LIMIT + 1))
        except (OSError, ValueError):
            with suppress(queue.Full):
                results.put_nowait(None)

    def write():
        try:
            process.stdin.write(request)
            process.stdin.flush()
            process.stdin.close()
        except (OSError, ValueError):
            with suppress(queue.Full):
                results.put_nowait(None)

    reader = threading.Thread(target=read, daemon=True)
    writer = threading.Thread(target=write, daemon=True)
    reader.start()
    writer.start()
    deadline = time.monotonic() + timeout
    try:
        while True:
            if (cancel is not None and cancel.is_set()) or time.monotonic() > deadline:
                raise Blocked(failure)
            try:
                raw = results.get(timeout=0.05)
                break
            except queue.Empty:
                continue
        if raw is None or len(raw) > REPLY_LIMIT:
            raise Blocked(failure)
        try:
            code = process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            raise Blocked(failure) from None
        if code != 0:
            raise Blocked(failure)
        def unique(pairs):
            output = {}
            for key, value in pairs:
                if key in output:
                    raise ValueError('duplicate field')
                output[key] = value
            return output
        try:
            result = json.loads(raw, object_pairs_hook=unique)
        except (ValueError, UnicodeError):
            raise Blocked(failure) from None
        kind = 'add' if original is None else 'update'
        if (not isinstance(result, dict) or result.get('ok') is not True
                or result.get('filesystem_modified') is not False
                or result.get('paths') != [{'path': name, 'destination': None, 'kind': kind}]):
            raise Blocked('Use one add/update patch for exactly the requested file; no rename or deletion')
        changes = result.get('changes')
        if not isinstance(changes, list) or len(changes) != 1 or not isinstance(changes[0], dict):
            raise Blocked(failure)
        change = changes[0]
        content = change.get('content')
        if (change.get('path') != name or change.get('kind') != kind
                or change.get('destination') is not None or not isinstance(content, str)
                or '\0' in content or len(content.encode('utf-8')) > FILE_LIMIT):
            raise Blocked(failure)
        return content
    finally:
        kill_tree(process)
        with suppress(subprocess.TimeoutExpired):
            process.wait(timeout=5)
        reader.join(timeout=1)
        writer.join(timeout=1)
        for stream in (process.stdin, process.stdout):
            with suppress(OSError, ValueError):
                stream.close()
