# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
from __future__ import annotations
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Mapping, Sequence
IS_WINDOWS = sys.platform == 'win32'
_CREATE_NO_WINDOW = 134217728

def windows_hide_flags() -> int:
    """Win32 creationflags hiding the child's console without detaching it; 0 elsewhere.

    For short-lived synchronous helpers (``taskkill``, ``where``, version probes): no flash, but the
    child stays in the parent's process group and job so Ctrl+C and job teardown still propagate.
    Stdio is inherited, so ``capture_output=True`` works.
    """
    return _CREATE_NO_WINDOW if IS_WINDOWS else 0
_GIT_CONFIG_INJECT_PREFIXES = ('GIT_CONFIG_KEY_', 'GIT_CONFIG_VALUE_')
_GIT_CONFIG_OVERRIDES = {'credential.helper': '', 'core.askPass': '', 'core.fsmonitor': 'false', 'core.untrackedCache': 'false', 'core.hooksPath': os.devnull, 'core.pager': 'cat', 'core.editor': 'true', 'sequence.editor': 'true', 'diff.external': '', 'core.sshCommand': 'ssh -o BatchMode=yes'}

def _safe_directory_cache_key(env: Mapping[str, str]) -> tuple:
    """Everything that decides which files ``git config --system/--global`` reads, plus the
    global candidates' mtimes so an edit to ``~/.gitconfig`` is picked up without a restart."""
    home = env.get('HOME', '')
    xdg = env.get('XDG_CONFIG_HOME') or os.path.join(home, '.config')
    candidates = (env.get('GIT_CONFIG_SYSTEM') or '/etc/gitconfig', env.get('GIT_CONFIG_GLOBAL') or os.path.join(home, '.gitconfig'), os.path.join(xdg, 'git', 'config'))
    stamps = []
    for path in candidates:
        try:
            stamps.append(os.stat(path).st_mtime_ns)
        except OSError:
            stamps.append(None)
    return (env.get('GIT_CONFIG_GLOBAL'), env.get('GIT_CONFIG_SYSTEM'), env.get('GIT_CONFIG_NOSYSTEM'), home, env.get('XDG_CONFIG_HOME'), env.get('PATH'), *stamps)
_safe_directory_cache: dict[tuple, list[str]] = {}

def _user_safe_directories(base_env: Mapping[str, str]) -> list[str]:
    """The user's configured ``safe.directory`` values, in git's own effective order.

    Read with ``git config -z --get-all`` under *base_env* (the caller's untouched environment) so
    an explicit ``GIT_CONFIG_GLOBAL``/``GIT_CONFIG_SYSTEM`` still points at the file the user means.
    Best-effort: any failure (git missing, malformed config, timeout) yields no entries and leaves
    the caller exactly as it behaved before. Memoised per process on the inputs that select the
    config files (and the global file's mtime): ``noninteractive_git_env()`` runs on every internal
    git call, including the startup banner probe, and two ``git config`` children per call is
    ~10 ms against ~0.2 ms for the rest of the function.

    ``safe.directory`` is an *ordered* multi-valued setting and an empty value resets every entry
    seen so far, so a user can revoke a system-wide ``safe.directory=*`` and then name only the
    repositories they actually trust. Order and empty resets are therefore policy, not formatting:
    scopes are read lowest-precedence first (system, then global) and every value is preserved
    verbatim -- no de-duplication (it is a sequence, not a set) and no dropping of the reset
    marker, either of which would resurrect a revoked wildcard and widen trust. ``-z`` keeps a
    value containing whitespace or a newline as the single entry git reads it as.
    """
    cache_key = _safe_directory_cache_key(base_env)
    cached = _safe_directory_cache.get(cache_key)
    if cached is not None:
        return list(cached)
    env = dict(base_env)
    for key in list(env):
        if key == 'GIT_CONFIG_PARAMETERS' or key.startswith(_GIT_CONFIG_INJECT_PREFIXES):
            env.pop(key, None)
    env.pop('GIT_CONFIG_COUNT', None)
    env['GIT_TERMINAL_PROMPT'] = '0'
    values: list[str] = []
    for scope in ('--system', '--global'):
        try:
            proc = subprocess.run(['git', 'config', scope, '-z', '--get-all', 'safe.directory'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=5, stdin=subprocess.DEVNULL, env=env, check=False, creationflags=windows_hide_flags())
        except (OSError, subprocess.SubprocessError):
            continue
        if proc.returncode != 0:
            continue
        records = proc.stdout.split('\x00')
        if records and records[-1] == '':
            records.pop()
        values.extend(records)
    _safe_directory_cache[cache_key] = list(values)
    return values

def noninteractive_git_env(base: Mapping[str, str] | None=None) -> dict[str, str]:
    """Environment for *internal* git invocations that must never prompt.

    Copy of ``base`` (default ``os.environ``) with ``GIT_TERMINAL_PROMPT=0`` (fail instead of
    prompting), ``GCM_INTERACTIVE=Never`` (no Git Credential Manager dialog), and isolated git
    config: inherited ``GIT_CONFIG_*`` injection, global/system config, pagers, editors, fsmonitor,
    external diff and hooks are all disabled so a user's repo/global config cannot hang or mutate
    Hermes's plumbing calls. ``core.sshCommand`` is pinned to ``ssh -o BatchMode=yes`` so the ssh
    child of a fetch/ls-remote fails instead of prompting — ssh bypasses ``stdin=DEVNULL`` and
    opens ``/dev/tty`` directly (#104591); an agent-authenticated ssh still succeeds, and an
    explicit user ``GIT_SSH_COMMAND`` env var still takes precedence over this config-layer pin.
    ``GIT_ASKPASS``/``SSH_ASKPASS`` env vars are left alone, but OpenSSH BatchMode disables
    passphrase/password prompts, including SSH askpass. Usable keys and ssh-agent authentication
    still work; Git's own working askpass helper is unaffected. Pair with
    ``stdin=subprocess.DEVNULL``. Internal plumbing only — the agent-facing terminal tool has its
    own policy layer and visible PTY.

    Hermes shells out to git from many non-interactive contexts — MCP catalog installs, plugin
    install/update, profile distribution staging, worktree base fetches, desktop review-pane fetch/push.
    When the remote is private, misconfigured, or requires auth, git's default behavior is to prompt on the
    inherited terminal (or via an askpass helper), which silently hangs the operation until its timeout — or
    forever at call sites without one. Ported from openai/codex#34540 / #34612 ("detach non-interactive
    subprocesses from stdin"): a background tool invocation must fail fast with a readable error, not wait
    for input nobody can type.
    """
    env = dict(base if base is not None else os.environ)
    safe_directories = _user_safe_directories(base if base is not None else os.environ)
    env['GIT_TERMINAL_PROMPT'] = '0'
    env['GCM_INTERACTIVE'] = 'Never'
    for key in list(env):
        if key == 'GIT_CONFIG_PARAMETERS' or key.startswith(_GIT_CONFIG_INJECT_PREFIXES):
            env.pop(key, None)
    env.pop('GIT_CONFIG_COUNT', None)
    env['GIT_CONFIG_GLOBAL'] = os.devnull
    env['GIT_CONFIG_SYSTEM'] = os.devnull
    env['GIT_CONFIG_NOSYSTEM'] = '1'
    env['GIT_PAGER'] = 'cat'
    env['PAGER'] = 'cat'
    env['GIT_EDITOR'] = 'true'
    overrides = list(_GIT_CONFIG_OVERRIDES.items())
    overrides.extend((('safe.directory', value) for value in safe_directories))
    env['GIT_CONFIG_COUNT'] = str(len(overrides))
    for idx, (key, value) in enumerate(overrides):
        env[f'GIT_CONFIG_KEY_{idx}'] = key
        env[f'GIT_CONFIG_VALUE_{idx}'] = value
    return env
_FILTER_COMMAND_KEY = re.compile('^filter\\..+\\.(?:clean|smudge|process)$', re.IGNORECASE)
_INCLUDE_IF_KEY = re.compile('^includeif\\..*\\.path$', re.IGNORECASE)
_INCLUDE_KEY = re.compile('^include(?:if\\..*)?\\.path$', re.IGNORECASE)
_DISCOVERY_KEYS_REGEXP = '^(filter\\..*\\.(clean|smudge|process)|include\\.path|includeif\\..*\\.path)$'
_MAX_INCLUDE_TARGETS = 16
_MAX_FILTER_KEYS = 256
FILTER_DISCOVERY_FAILED = 'git filter discovery failed'

def noninteractive_repo_git_env(cwd: str | os.PathLike[str], base: Mapping[str, str] | None=None) -> dict[str, str] | None:
    """Harden internal git for one repository, including named clean/smudge/process filters.

    The static environment can pin fixed config keys such as core.fsmonitor and
    core.hooksPath, but a repository chooses filter driver names through .gitattributes.
    Discover the effective filter command keys for this checkout and append empty command
    overrides plus required=false to the already-isolated config block. Discovery is
    bounded and fail-closed: if filter discovery cannot be trusted, callers skip the
    automatic git operation instead of running with only partial hardening.
    """
    env = noninteractive_git_env(base)
    proc = bounded_probe_run(['git', '-C', str(cwd), 'config', '--includes', '--show-origin', '-z', '--get-regexp', _DISCOVERY_KEYS_REGEXP], timeout=2, env=env)
    if proc is None or proc.returncode not in (0, 1):
        return None
    names: list[str] = []
    targets: set[Path] = set()
    toplevel: Path | None = None
    fields = proc.stdout.split('\x00')
    for origin, entry in zip(fields[0::2], fields[1::2]):
        key, _, value = entry.partition('\n')
        if not _INCLUDE_IF_KEY.fullmatch(key):
            names.append(key)
            continue
        if not origin.startswith('file:'):
            return None
        origin_path = Path(origin[len('file:'):])
        if not origin_path.is_absolute():
            if env.get('GIT_DIR') or env.get('GIT_WORK_TREE'):
                return None
            if toplevel is None:
                top = bounded_probe_run(['git', '-C', str(cwd), 'rev-parse', '--show-toplevel'], timeout=2, env=env)
                if top is None or top.returncode != 0:
                    return None
                toplevel = Path(top.stdout.rstrip('\r\n'))
            origin_path = toplevel / origin_path
        target = (origin_path.parent / os.path.expanduser(value)).resolve()
        if target in targets or not target.exists():
            continue
        if not target.is_file() or len(targets) >= _MAX_INCLUDE_TARGETS:
            return None
        targets.add(target)
        probe = bounded_probe_run(['git', 'config', '--file', str(target), '--name-only', '-z', '--get-regexp', _DISCOVERY_KEYS_REGEXP], timeout=2, env=env)
        if probe is None or probe.returncode not in (0, 1):
            return None
        found = probe.stdout.split('\x00')
        if any((_INCLUDE_KEY.fullmatch(name) for name in found)):
            return None
        names.extend(found)
    keys: list[str] = []
    required: list[str] = []
    seen: set[str] = set()
    for raw in names:
        key = raw.strip()
        if not key or key in seen or (not _FILTER_COMMAND_KEY.fullmatch(key)):
            continue
        seen.add(key)
        keys.append(key)
        if len(keys) > _MAX_FILTER_KEYS:
            return None
        required_key = key.rsplit('.', 1)[0] + '.required'
        if required_key not in seen:
            seen.add(required_key)
            required.append(required_key)
    start = int(env['GIT_CONFIG_COUNT'])
    overrides = [(key, '') for key in keys] + [(key, 'false') for key in required]
    for offset, (key, value) in enumerate(overrides):
        env[f'GIT_CONFIG_KEY_{start + offset}'] = key
        env[f'GIT_CONFIG_VALUE_{start + offset}'] = value
    env['GIT_CONFIG_COUNT'] = str(start + len(overrides))
    return env

def posix_is_zombie(pid: int) -> bool:
    """Zombie via ``/proc/<pid>/stat`` field 3, or ``ps -o state=`` without /proc (macOS/BSD)."""
    try:
        with open(f'/proc/{pid}/stat', encoding='utf-8') as fh:
            stat_fields = fh.read().split()
        return len(stat_fields) > 2 and stat_fields[2] == 'Z'
    except FileNotFoundError:
        try:
            r = subprocess.run(['ps', '-o', 'state=', '-p', str(pid)], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=5, check=False)
            return r.returncode == 0 and r.stdout.strip().startswith('Z')
        except Exception:
            pass
    except (IndexError, PermissionError, OSError):
        pass
    return False

def win32_pid_exists(pid: int) -> bool:
    """psutil-free Windows liveness probe via OpenProcess/WaitForSingleObject."""
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.WaitForSingleObject.restype = ctypes.c_uint
        kernel32.GetLastError.restype = ctypes.c_uint
        PROCESS_QUERY_LIMITED_INFORMATION, SYNCHRONIZE = (4096, 1048576)
        WAIT_TIMEOUT, ERROR_ACCESS_DENIED = (258, 5)
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid)
        if not handle:
            return kernel32.GetLastError() == ERROR_ACCESS_DENIED
        try:
            return kernel32.WaitForSingleObject(handle, 0) == WAIT_TIMEOUT
        finally:
            kernel32.CloseHandle(handle)
    except (OSError, AttributeError):
        return False

def pid_exists_stdlib(pid: int) -> bool:
    """Stdlib-only "is this PID alive" check that never signals the target (zombies report dead).

    For code that must run without the dependency environment: the detached gateway restart
    watcher is started by whatever interpreter the updater runs on (the bare store Python after
    the package-manager handoff), so it cannot import ``gateway.status`` (``utils`` pulls in
    ``ruamel``). ``gateway.status._pid_exists`` prefers psutil and falls back to this.
    """
    pid = int(pid)
    if IS_WINDOWS:
        return win32_pid_exists(pid)
    if posix_is_zombie(pid):
        return False
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True

def kill_process_tree(proc: subprocess.Popen) -> None:
    """Best-effort terminate *proc* and its descendants on both platforms; never raises.

    ``proc.kill()`` alone only terminates the direct child. This is cleanup on an already-failing
    path whose contract is to fail open, so every failure (access denied, already reaped) is
    swallowed rather than escaping the caller's ``except``.

    On Windows a suspended descendant (e.g. ``git.exe``) can survive holding duplicates of the captured pipe
    handles, which keeps the pipes from reaching EOF and leaks two reader threads + the process per fired
    timeout — ``taskkill /T /F`` takes the whole tree down so the bounded drain that follows can actually
    reach EOF. On POSIX the same class exists: killing the launcher leaves descendants (credential helpers,
    ``git-remote-https``, hook children) running and holding the pipe write ends. Callers spawn the child in
    its own process group (``process_group=0``, Python ≥3.11), so when — and only when — the child leads its
    own group (``pgid == pid``), the entire group is signalled with ``os.killpg``. The ownership check means
    a fallback spawn that shares our group can never cause us to kill unrelated processes. Ported from
    openai/codex#36793 ("Terminate timed-out Git process trees"); generalized for the shell-hook runner via
    openai/codex#37527 ("Terminate timed-out hook process trees").
    """
    try:
        from hivemind_assembly.automation.state_engine.agent.deadline import kill_process_tree as _deadline_kill_tree
        _deadline_kill_tree(proc.pid)
    except Exception:
        _legacy_kill_process_tree(proc)
        return
    try:
        proc.kill()
    except OSError:
        pass

def _legacy_kill_process_tree(proc: subprocess.Popen) -> None:
    """Local tree-kill fallback when agent.deadline is unavailable (partial install, cycle)."""
    if not IS_WINDOWS:
        try:
            import signal as _signal
            pgid = os.getpgid(proc.pid)
            if pgid == proc.pid:
                os.killpg(pgid, _signal.SIGKILL)
        except Exception:
            pass
    try:
        proc.kill()
    except OSError:
        pass
    if IS_WINDOWS:
        try:
            subprocess.run(['taskkill', '/T', '/F', '/PID', str(proc.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, timeout=2, check=False, creationflags=windows_hide_flags())
        except Exception:
            pass

def bounded_probe_run(argv: Sequence[str], *, timeout: float, errors: str='replace', env: Mapping[str, str] | None=None, cwd: str | os.PathLike[str] | None=None, raise_on_spawn_failure: bool=False, input: str | None=None) -> subprocess.CompletedProcess[str] | None:
    """Deadlock-safe ``subprocess.run(argv, capture_output=True, timeout=…)`` for fail-open probes.

    ``input`` is written to the child's stdin (closed afterwards); without it stdin is ``DEVNULL``.

    Returns a ``CompletedProcess`` when the child finished within *timeout* (any exit code), or
    ``None`` on spawn failure or timeout. With ``raise_on_spawn_failure=True`` the ``Popen``
    exception propagates instead, so callers that treat a *timeout* as a verdict can still tell
    "our own probe never started" apart from "the child hung".

    Why not ``subprocess.run``: on Windows, ``run()``'s post-timeout cleanup calls an *unbounded*
    ``communicate()`` after killing the direct child. Killing it can leave a descendant (``git.exe`` under a
    launcher shim, ``conhost.exe`` under wmic/powershell) holding duplicates of the captured stdout/stderr
    handles, so the pipes never reach EOF and the reader-thread join blocks forever. The wmic /
    ``Get-CimInstance Win32_Process`` gateway scan hit exactly this during ``hermes update`` on slow-WMI
    machines (#87134); the git probes hit it first (#68609 / #66037).
    """
    _popen_kwargs: dict = {'creationflags': windows_hide_flags()} if IS_WINDOWS else {'process_group': 0}
    job = None
    try:
        from hivemind_assembly.automation.state_engine.hermes_cli.local_runtime.processes import spawn_server
        proc, job = spawn_server(list(argv), stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL if input is None else subprocess.PIPE, text=True, encoding='utf-8', errors=errors, env=dict(env) if env is not None else None, cwd=cwd, **_popen_kwargs)
    except Exception:
        if raise_on_spawn_failure:
            raise
        return None
    try:
        stdout, stderr = proc.communicate(input=input, timeout=timeout)
    except Exception:
        _close_job(job)
        kill_and_drain(proc, 1)
        return None
    _close_job(job)
    return subprocess.CompletedProcess(list(argv), proc.returncode, stdout, stderr)

def kill_and_drain(proc: subprocess.Popen, seconds: float) -> tuple | None:
    """Tree-kill *proc* (:func:`kill_process_tree`), then read what its pipes still hold for at
    most *seconds*: ``(stdout, stderr)``, or ``None`` when a descendant the kill missed still
    holds them. Those pipes are left to ``communicate()``'s reader threads, never closed
    (closing a pipe a thread is reading blocks; a ``with Popen`` exit would close them)."""
    kill_process_tree(proc)
    try:
        return proc.communicate(timeout=seconds)
    except (OSError, ValueError, subprocess.SubprocessError):
        proc.stdin = proc.stdout = proc.stderr = None
        return None

def _close_job(job) -> None:
    if job is None:
        return
    try:
        job.close()
    except Exception:
        pass
