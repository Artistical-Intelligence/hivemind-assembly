# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
from __future__ import annotations
import functools
import logging
import os
import stat
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
log = logging.getLogger(__name__)
_TOKEN_QUERY = 8
_TOKEN_ELEVATION = 20
FILE_ATTRIBUTE_DIRECTORY = 16
FILE_ATTRIBUTE_REPARSE_POINT = 1024
_READ_CONTROL = 131072
_WRITE_DAC = 262144
_FILE_SHARE_ALL = 7
_OPEN_EXISTING = 3
_FILE_FLAG_BACKUP_SEMANTICS = 33554432
_FILE_FLAG_OPEN_REPARSE_POINT = 2097152

class ReparsePointRefused(OSError):
    """The grant target is (or became) a junction, symlink, other reparse point or hard link."""

def is_reparse_point(path: str | Path) -> bool:
    """True when *path* itself is a symlink, junction or other reparse point (never followed), or
    cannot be lstat-ed at all; the safe answer for "may an elevated grant act on this path"."""
    try:
        st = os.lstat(path)
    except OSError:
        return True
    if stat.S_ISLNK(st.st_mode) or getattr(st, 'st_file_attributes', 0) & FILE_ATTRIBUTE_REPARSE_POINT:
        return True
    isjunction = getattr(os.path, 'isjunction', None)
    return bool(isjunction and isjunction(path))
_PROCESS_QUERY_LIMITED_INFORMATION = 4096

def process_elevation(pid: int | None=None) -> bool | None:
    """``TokenElevation`` of *pid*'s token (default: this process). The ONE elevation probe: the
    grants below, the refused-owner naming in ``gateway.runtime_bootstrap_windows`` and the
    Windows service installer all read it. None when the process or its token cannot be opened
    (across an elevation boundary that refusal is itself an answer the caller interprets)."""
    import ctypes
    from ctypes import wintypes
    advapi = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    own = pid is None
    process = kernel.GetCurrentProcess() if own else kernel.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not process:
        return None
    token = wintypes.HANDLE()
    try:
        if not advapi.OpenProcessToken(process, _TOKEN_QUERY, ctypes.byref(token)):
            return None
        elevated, size = (wintypes.DWORD(), wintypes.DWORD())
        if not advapi.GetTokenInformation(token, _TOKEN_ELEVATION, ctypes.byref(elevated), ctypes.sizeof(elevated), ctypes.byref(size)):
            return None
        return bool(elevated.value)
    finally:
        if token:
            kernel.CloseHandle(token)
        if not own:
            kernel.CloseHandle(process)

@functools.lru_cache(maxsize=1)
def process_is_elevated() -> bool:
    """True for an elevated (UAC full-token) Windows process; False elsewhere or on any error."""
    if sys.platform != 'win32':
        return False
    return bool(process_elevation())

def _strip_win32_prefix(path: str) -> str:
    if path.startswith('\\\\?\\UNC\\'):
        return '\\\\' + path[8:]
    return path.removeprefix('\\\\?\\')

def _grant_with_pywin32(path: Path, is_dir: bool, expected: str | None=None) -> bool:
    """Write the ACE on the handle; True when it was written (False: already present). The write
    does NOT propagate (``SetKernelObjectSecurity``), so a written dir's existing children are owed."""
    import ntsecuritycon
    import win32api
    import win32file
    import win32security
    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32security.TOKEN_QUERY)
    user_sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    handle = win32file.CreateFile(str(path), _READ_CONTROL | _WRITE_DAC, _FILE_SHARE_ALL, None, _OPEN_EXISTING, _FILE_FLAG_BACKUP_SEMANTICS | _FILE_FLAG_OPEN_REPARSE_POINT, None)
    try:
        if expected is not None:
            final = _strip_win32_prefix(win32file.GetFinalPathNameByHandle(handle, 0))
            if os.path.normcase(final.rstrip('\\')) != os.path.normcase(expected.rstrip('\\')):
                raise ReparsePointRefused(f'{path} resolves to {final}, not {expected}')
        info = win32file.GetFileInformationByHandle(handle)
        attributes, links = (info[0], info[7])
        if attributes & FILE_ATTRIBUTE_REPARSE_POINT:
            raise ReparsePointRefused(f'{path} is a junction, symlink or other reparse point')
        if not attributes & FILE_ATTRIBUTE_DIRECTORY and links > 1:
            raise ReparsePointRefused(f'{path} is a hard link ({links} names); its other names may be outside')
        is_dir = bool(attributes & FILE_ATTRIBUTE_DIRECTORY)
        descriptor = win32security.GetKernelObjectSecurity(handle, win32security.DACL_SECURITY_INFORMATION)
        dacl = descriptor.GetSecurityDescriptorDacl()
        inherit = win32security.OBJECT_INHERIT_ACE | win32security.CONTAINER_INHERIT_ACE if is_dir else 0
        if dacl is not None:
            for index in range(dacl.GetAceCount()):
                (ace_type, flags, *_), mask, sid = dacl.GetAce(index)[:3]
                if ace_type == win32security.ACCESS_ALLOWED_ACE_TYPE and sid == user_sid and (mask & ntsecuritycon.FILE_ALL_ACCESS == ntsecuritycon.FILE_ALL_ACCESS) and (flags & inherit == inherit) and (not flags & win32security.INHERIT_ONLY_ACE):
                    return False
        else:
            dacl = win32security.ACL()
        dacl.AddAccessAllowedAceEx(win32security.ACL_REVISION_DS, inherit, ntsecuritycon.FILE_ALL_ACCESS, user_sid)
        descriptor.SetSecurityDescriptorDacl(True, dacl, False)
        win32security.SetKernelObjectSecurity(handle, win32security.DACL_SECURITY_INFORMATION, descriptor)
        return True
    finally:
        handle.Close()

@functools.lru_cache(maxsize=1)
def _whoami_sid() -> str:
    whoami = subprocess.run(['whoami', '/user', '/fo', 'csv', '/nh'], capture_output=True, text=True, check=True, encoding='utf-8', errors='replace', timeout=30)
    sid = whoami.stdout.strip().rsplit(',', 1)[-1].strip().strip('"')
    if not sid.upper().startswith('S-1-'):
        raise OSError(f'could not resolve the current user SID from whoami: {whoami.stdout!r}')
    return sid

def _grant_with_icacls(path: Path, is_dir: bool, expected: str | None=None, subtree_has_link: bool | None=None) -> None:
    """*subtree_has_link*: the caller's own walk already answered it (None: walk here)."""
    if expected is None:
        raise ReparsePointRefused(f'{path} has no trusted root to check (icacls fallback, no pywin32)')
    if is_dir and subtree_has_link:
        raise ReparsePointRefused(f'{path} holds a junction, symlink or hard link (icacls fallback)')
    if is_dir and subtree_has_link is None:
        nested: list[Path] = []
        linked = [entry for entry, entry_is_dir in iter_tree_without_reparse_points(path, nested) if not entry_is_dir and _hard_linked_file(entry)]
        if nested or linked:
            raise ReparsePointRefused(f'{(nested + linked)[0]} under {path} is a junction, symlink or hard link (icacls fallback)')
    ace = f'*{_whoami_sid()}:(OI)(CI)F' if is_dir else f'*{_whoami_sid()}:F'
    subprocess.run(['icacls', str(path), '/grant', ace, '/Q', '/L'], capture_output=True, check=True, timeout=60)

def _hard_linked_file(path: Path) -> bool:
    try:
        st = os.lstat(path)
    except OSError:
        return True
    return not stat.S_ISDIR(st.st_mode) and st.st_nlink > 1

def _grant(path: Path, is_dir: bool=True, expected: str | None=None, subtree_has_link: bool | None=None) -> bool:
    """Grant the token's user full control on *path* itself; raise :class:`ReparsePointRefused`
    for a reparse point or hard-linked file (or, with *expected*, a handle that resolves anywhere
    else) and anything else on failure.

    Returns True when the existing children are still owed: the pywin32 write does not propagate,
    while the icacls fallback (``SetNamedSecurityInfo``) does, and refuses a dir holding a link."""
    if is_reparse_point(path) or _hard_linked_file(path):
        raise ReparsePointRefused(f'{path} is a junction, symlink, other reparse point or hard link')
    try:
        return _grant_with_pywin32(path, is_dir, expected) and is_dir
    except ImportError:
        _grant_with_icacls(path, is_dir, expected, subtree_has_link)
        return False

def _components_below_home(path: Path) -> list[Path]:
    """*path* and each ancestor of it strictly below the Hermes home (lexically), outermost first;
    empty when *path* is not under the home. The home itself (and above) is the user's own choice
    and may legitimately be a link; an entry INSIDE it is what same-user code can swap."""
    try:
        from hivemind_assembly.automation.state_engine.hermes_constants import get_hermes_home
        home = Path(os.path.abspath(get_hermes_home()))
        rel = Path(os.path.abspath(path)).relative_to(home)
    except (ImportError, ValueError, OSError):
        return []
    return [home.joinpath(*rel.parts[:i]) for i in range(1, len(rel.parts) + 1)]

def _expected_final(path: Path) -> str | None:
    """Where *path* must resolve when nothing below the home is a link: the home's real path plus
    the relative parts. None off-home (only the leaf's own open-reparse check applies there)."""
    components = _components_below_home(path)
    if not components:
        return None
    home = components[0].parent
    return os.path.join(os.path.realpath(home), *Path(os.path.abspath(path)).relative_to(home).parts)

def _warn_refused(path: Path, exc: BaseException) -> None:
    log.warning('Not granting the current user access to %s while elevated (%s): an elevated grant never follows a junction or link out of the Hermes home. If this is your own link, point HERMES_HOME (or the link) at the real directory.', path, exc)

def _elevated(elevated: bool | None) -> bool:
    """The host fact every grant decision takes: *elevated* as passed, else probed (an elevated
    Windows process; :func:`process_is_elevated` is False on every other host)."""
    return process_is_elevated() if elevated is None else elevated

def grant_user_access(path: str | Path, *, elevated: bool | None=None, repair_children: bool=False) -> bool:
    """Give the token's user an inheriting full-control ACE on *path* when this process is elevated.

    True when a grant was attempted and did not fail; False off Windows, when not elevated, when
    *path* is a junction/symlink/reparse point (refused, one warning), or when the grant failed
    (logged; the directory itself still exists). *elevated* defaults to the probed host fact.

    With *repair_children* (an existing dir an earlier elevated run may have filled), a write that
    does not propagate is followed by the same grant on everything already below *path*, never
    through a link; children are best-effort and never change the result."""
    if not _elevated(elevated):
        return False
    target = Path(path)
    try:
        for component in _components_below_home(target):
            if is_reparse_point(component):
                raise ReparsePointRefused(f'{component} is a junction, symlink or other reparse point')
        expected = _expected_final(target)
        children_owed = _grant(target, expected=expected)
    except ReparsePointRefused as exc:
        _warn_refused(target, exc)
        return False
    except Exception as exc:
        log.warning('Could not grant the current user access to %s created while elevated (%s); a non-elevated Hermes may not be able to use it. To repair, from an elevated prompt run: icacls "%s" /reset /t', target, exc, target)
        return False
    if repair_children and children_owed:
        real = expected or os.path.realpath(target)
        skipped: list[Path] = []
        entries = [(p, d) for p, d in iter_tree_without_reparse_points(target, skipped) if p != target]
        _, _, failed = _grant_entries(target, real, entries, skipped)
        if failed:
            log.debug('Granting the existing entries under %s failed for %d, e.g. %s: %s', target, len(failed), *failed[0])
    return True

def iter_tree_without_reparse_points(root: str | Path, skipped: list[Path]) -> Iterator[tuple[Path, bool]]:
    """Yield ``(path, is_dir)`` for *root* and everything under it, never entering or yielding a
    junction, symlink or other reparse point (each one is appended to *skipped* instead).

    ``os.walk`` is not enough: it follows directory junctions (``os.path.islink`` is False for one).
    Unreadable directories are skipped silently, like ``icacls /C``."""
    root = Path(root)
    if is_reparse_point(root):
        skipped.append(root)
        return
    stack = [root]
    while stack:
        directory = stack.pop()
        yield (directory, True)
        try:
            with os.scandir(directory) as entries:
                children = [Path(entry.path) for entry in entries]
        except OSError:
            continue
        for child in sorted(children):
            if is_reparse_point(child):
                skipped.append(child)
            elif child.is_dir():
                stack.append(child)
            else:
                yield (child, False)

def _grant_entries(root: Path, real_root: str, entries: list[tuple[Path, bool]], skipped: list[Path]) -> tuple[int, list[Path], list[tuple[Path, str]]]:
    """Grant each walked entry on its own (the pywin32 write does not propagate). The ONE walk
    that produced *entries* and *skipped* also decides which dirs hold a link, so the icacls
    fallback never re-walks a subtree per directory (it refuses exactly those dirs, as before)."""
    linked = {root, *skipped}
    linked.update((p for p, is_dir in entries if not is_dir and _hard_linked_file(p)))
    holds_link: set[Path] = set()
    for bad in linked - {root}:
        holds_link.update((parent for parent in bad.parents if parent == root or root in parent.parents))
    if root in skipped:
        holds_link.add(root)
    granted, failed = (0, [])
    for path, is_dir in entries:
        try:
            _grant(path, is_dir, os.path.join(real_root, *path.relative_to(root).parts), subtree_has_link=is_dir and path in holds_link)
        except ReparsePointRefused:
            skipped.append(path)
        except Exception as exc:
            failed.append((path, str(exc) or type(exc).__name__))
        else:
            granted += 1
    return (granted, skipped, failed)
_granted: set[tuple[Path, int, int]] = set()

def _identity(path: Path) -> tuple[Path, int, int] | None:
    try:
        st = os.lstat(path)
    except OSError:
        return None
    return (path, st.st_dev, st.st_ino)

def make_user_dir(path: str | Path, mode: int=511, *, parents: bool=False, exist_ok: bool=False, elevated: bool | None=None) -> Path:
    """``Path.mkdir`` (same arguments and defaults) that keeps an elevated Windows creation usable
    by the same user unelevated.

    Off Windows or unelevated this is ``Path.mkdir`` and nothing else. Elevated, every directory
    this call created (missing parents included) is granted the user's inheriting full-control ACE,
    and an existing leaf (the repair case) once per directory object per process, except that a
    component that is a junction/symlink/reparse point stops the grants with one warning. An
    existing leaf without ``exist_ok`` is still granted before the ``FileExistsError``. *elevated*
    is the host fact (default: probed); production passes nothing."""
    target = Path(path)
    if not _elevated(elevated):
        target.mkdir(mode=mode, parents=parents, exist_ok=exist_ok)
        return target
    created = []
    probe = target
    while not probe.exists() and probe.parent != probe:
        created.append(probe)
        probe = probe.parent
    try:
        target.mkdir(mode=mode, parents=parents, exist_ok=exist_ok)
    except FileExistsError:
        if target.is_dir() and (not is_reparse_point(target)):
            _grant_dirs(target, [target])
        raise
    _grant_dirs(target, list(reversed(created or [target])), fresh=set(created))
    return target

def _grant_dirs(target: Path, to_grant: list[Path], fresh: set[Path]=frozenset()) -> None:
    """Grant *to_grant*; a dir in *fresh* (this call created it) is always granted, an existing
    one once per verified object identity."""
    for component in dict.fromkeys([*_components_below_home(target), *to_grant]):
        if is_reparse_point(component):
            _warn_refused(component, ReparsePointRefused('junction, symlink or other reparse point'))
            return
    for directory in to_grant:
        key = _identity(directory)
        if key is None or (directory not in fresh and key in _granted):
            continue
        if grant_user_access(directory, elevated=True, repair_children=directory not in fresh):
            _granted.add(key)
