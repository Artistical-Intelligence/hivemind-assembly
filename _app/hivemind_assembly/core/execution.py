"""Bounded stdio client for HA's owned execution engine.

The caller authenticates the component and authorizes the operation. This is a
process transport, not a sandbox or a source of permissions. A broken transport
never causes replay through another runner: the outcome may already have effects.
"""
from __future__ import annotations

import base64
import binascii
import json
import math
import os
from pathlib import Path
import queue
import signal
import subprocess
import threading
import time

from .common import Blocked, ContractError

OUTPUT_LIMIT = 32 * 1024 * 1024
OUTPUT_TAIL = 2_000_000
FRAME_LIMIT = 1024 * 1024
REQUEST_LIMIT = 8 * 1024 * 1024


def kill_tree(proc):
    """Last-resort cleanup, never an authorization to repeat the operation."""
    if proc.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                       capture_output=True, timeout=10)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


class ExecutionClient:
    def __init__(self, command):
        # Only application composition supplies this command, never a tool payload.
        if not command or not all(isinstance(x, str) and x and '\x00' not in x for x in command):
            raise ContractError('Invalid internal runtime command')
        self.command = tuple(command)

    def run(self, key, argv, cwd, timeout, cancel, environment):
        if not math.isfinite(timeout) or not 0 < timeout <= 3600:
            raise ContractError('Execution timeout must be between zero and one hour')
        request = {'action': 'run', 'id': key, 'argv': list(argv),
                   'cwd': str(Path(cwd).resolve()), 'environment': environment,
                   'timeout': math.ceil(timeout), 'pty': False, 'output_limit': OUTPUT_LIMIT}
        encoded = json.dumps(request, ensure_ascii=True, allow_nan=False).encode() + b'\n'
        if len(encoded) > REQUEST_LIMIT:
            raise ContractError('Execution request is too large')
        if cancel is not None and cancel.is_set():
            return {'status': 'cancelled', 'exit_code': -1, 'elapsed': 0.0,
                    'output': '', 'output_truncated': False}
        started = time.monotonic()
        flags = ({'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt'
                 else {'start_new_session': True})
        proc = subprocess.Popen(self.command, cwd=cwd, env=environment,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, **flags)
        incoming, outgoing = queue.Queue(maxsize=16), queue.Queue(maxsize=4)
        closed = threading.Event()

        def deliver(kind, value=None):
            while not closed.is_set():
                try:
                    incoming.put((kind, value), timeout=0.1)
                    return
                except queue.Full:
                    continue

        def read():
            try:
                while not closed.is_set():
                    line = proc.stdout.readline(FRAME_LIMIT + 1)
                    if not line:
                        deliver('eof')
                        return
                    if len(line) > FRAME_LIMIT or not line.endswith(b'\n'):
                        deliver('error')
                        return
                    deliver('frame', line)
            except (OSError, ValueError):
                deliver('error')

        def write():
            try:
                proc.stdin.write(encoded)
                proc.stdin.flush()
                while not closed.is_set():
                    try:
                        value = outgoing.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    proc.stdin.write(value)
                    proc.stdin.flush()
            except (OSError, ValueError):
                deliver('write_error')

        reader = threading.Thread(target=read, daemon=True, name='ha-runtime-output')
        writer = threading.Thread(target=write, daemon=True, name='ha-runtime-control')
        reader.start()
        writer.start()
        seen_start, eof, final = False, False, None
        total, tail = 0, bytearray()
        forced, stop_at = None, None
        failure = 'HA execution channel was interrupted; reconcile the operation before retrying'
        try:
            while True:
                now = time.monotonic()
                if forced is None and final is None:
                    if cancel is not None and cancel.is_set():
                        forced = 'cancelled'
                    elif now - started >= timeout:
                        forced = 'timeout'
                    if forced:
                        stop_at = now + 4
                        outgoing.put_nowait(b'{"action":"terminate"}\n')
                if stop_at is not None and now > stop_at:
                    raise Blocked(failure)
                if final is not None and eof:
                    try:
                        code = proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        raise Blocked(failure) from None
                    if code != 0:
                        raise Blocked(failure)
                    return {'status': forced or final['status'], 'exit_code': final['exit_code'],
                            'elapsed': time.monotonic() - started,
                            'output': tail.decode('utf-8', errors='replace'),
                            'output_truncated': total > OUTPUT_TAIL or final['status'] == 'output_limit'}
                try:
                    kind, raw = incoming.get(timeout=0.05)
                except queue.Empty:
                    if eof or (proc.poll() is not None and not reader.is_alive()):
                        raise Blocked(failure)
                    continue
                if kind == 'eof':
                    eof = True
                    if final is None:
                        raise Blocked(failure)
                    continue
                if kind in ('error', 'write_error'):
                    raise Blocked(failure)
                if final is not None:
                    raise Blocked(failure)
                try:
                    message = json.loads(raw)
                except (ValueError, UnicodeError):
                    raise Blocked(failure) from None
                if not isinstance(message, dict) or message.get('id') != key:
                    raise Blocked(failure)
                kind = message.get('type')
                if kind == 'started':
                    if seen_start or message.get('pty') is not False:
                        raise Blocked(failure)
                    seen_start = True
                elif kind == 'output':
                    if (not seen_start or message.get('stream') not in ('stdout', 'stderr')
                            or type(message.get('offset')) is not int or message['offset'] != total
                            or not isinstance(message.get('data'), str)):
                        raise Blocked(failure)
                    try:
                        data = base64.b64decode(message['data'], validate=True)
                    except (binascii.Error, ValueError):
                        raise Blocked(failure) from None
                    total += len(data)
                    if total > OUTPUT_LIMIT:
                        raise Blocked(failure)
                    tail.extend(data)
                    if len(tail) > OUTPUT_TAIL:
                        del tail[:-OUTPUT_TAIL]
                elif kind == 'finished':
                    if (not seen_start or message.get('status') not in
                            ('completed', 'cancelled', 'timeout', 'output_limit')
                            or type(message.get('exit_code')) is not int
                            or type(message.get('bytes')) is not int or message['bytes'] != total):
                        raise Blocked(failure)
                    final = message
                    stop_at = now + 4
                else:
                    raise Blocked(failure)
        finally:
            # Ask the helper to terminate its owned child before terminating it.
            # This matters because PTY helpers may own a different process group.
            if proc.poll() is None:
                try:
                    outgoing.put_nowait(b'{"action":"terminate"}\n')
                    proc.wait(timeout=3)
                except (queue.Full, subprocess.TimeoutExpired):
                    kill_tree(proc)
            closed.set()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
            reader.join(timeout=1)
            writer.join(timeout=1)
            proc.stdout.close()
            proc.stdin.close()
