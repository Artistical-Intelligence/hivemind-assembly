# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
import contextlib
import os
import re
import sys
from collections.abc import Callable, Mapping
from contextvars import ContextVar, Token
from pathlib import Path
_profile_fallback_warned: bool = False
_UNSET = object()
_HERMES_HOME_OVERRIDE: ContextVar[str | object] = ContextVar('_HERMES_HOME_OVERRIDE', default=_UNSET)

def set_hermes_home_override(path: str | Path | None) -> Token:
    """Set a context-local Hermes home override and return its reset token.

    Deliberately does not mutate ``os.environ`` (shared by every thread in the process).
    """
    value: str | object = _UNSET if path is None else str(path)
    return _HERMES_HOME_OVERRIDE.set(value)

def reset_hermes_home_override(token: Token) -> None:
    """Restore the previous context-local Hermes home override."""
    _HERMES_HOME_OVERRIDE.reset(token)

def get_hermes_home_override() -> str | None:
    """Return the active context-local Hermes home override, if any."""
    override = _HERMES_HOME_OVERRIDE.get()
    return str(override) if override is not _UNSET and override else None

def _expand_hermes_home(path: str) -> Path:
    """Expand environment and user-home syntax in a Hermes home path."""
    return Path(os.path.expanduser(os.path.expandvars(path)))

def _platform_default_hermes_home(environ: Mapping[str, str], user_home: Callable[[], Path]) -> Path:
    """The platform default that *environ* names, with the literal data-directory suffix."""
    suffix = environ.get('HERMES_DATA_DIR_SUFFIX', '')
    if sys.platform == 'win32':
        local_appdata = environ.get('LOCALAPPDATA', '').strip()
        base = Path(local_appdata) if local_appdata else user_home() / 'AppData' / 'Local'
        return base / ('hermes' + suffix)
    return user_home() / ('.hermes' + suffix)

def _get_platform_default_hermes_home() -> Path:
    """Return the platform default with the literal data-directory suffix."""
    return _platform_default_hermes_home(os.environ, Path.home)

def _hermes_root_of(native_home: Path, env_path: Path | None) -> Path:
    """The root that holds *env_path*: the native home, a custom root, or *env_path* itself."""
    if env_path is None:
        return native_home
    try:
        env_path.resolve().relative_to(native_home.resolve())
    except ValueError:
        return env_path.parent.parent if env_path.parent.name == 'profiles' else env_path
    return native_home

def _warn_profile_fallback_once() -> None:
    """Warn once when HERMES_HOME is unset but a non-default profile is sticky-active (wrong fallback)."""
    global _profile_fallback_warned
    if _profile_fallback_warned:
        return
    _profile_fallback_warned = True
    try:
        fallback_home = _get_platform_default_hermes_home()
        active_path = fallback_home / 'active_profile'
        active = active_path.read_text(encoding='utf-8').strip() if active_path.exists() else ''
    except (UnicodeDecodeError, OSError):
        active = ''
    if active and active != 'default':
        msg = f'[HERMES_HOME fallback] HERMES_HOME is unset but active profile is {active!r}. Falling back to {fallback_home}, which is the DEFAULT profile — not {active!r}. Any data this process writes will land in the wrong profile. The subprocess spawner should pass HERMES_HOME explicitly (see issue #18594).'
        with contextlib.suppress(Exception):
            sys.stderr.write(msg + '\n')
            sys.stderr.flush()

def get_hermes_home() -> Path:
    """Hermes home: context-local override → ``HERMES_HOME`` env var → platform default."""
    override = get_hermes_home_override()
    if override:
        return _expand_hermes_home(override)
    if not os.environ.get('HERMES_HOME', '').strip():
        _warn_profile_fallback_once()
    return get_process_hermes_home()

def get_process_hermes_home() -> Path:
    """Hermes home of the running process, ignoring task overrides.

    For process-level assets (theme YAML, dashboard plugin manifests) that must stay visible while a
    request is scoped to another profile (e.g. embedded ``/chat`` under ``--open-profile``). Follows
    ``HERMES_HOME`` live on purpose: routed-profile DECISIONS compare against
    :func:`get_routing_process_hermes_home` instead (#119242).
    """
    val = os.environ.get('HERMES_HOME', '').strip()
    return _expand_hermes_home(val) if val else _get_platform_default_hermes_home()
_default_hermes_root_memo: tuple[str, str, Path] | None = None

def get_default_hermes_root(*, home: str | Path | None=None) -> Path:
    """Root of an explicit home, or the process home when none is supplied."""
    global _default_hermes_root_memo
    native_home = _get_platform_default_hermes_home()
    env_home = str(home).strip() if home is not None else os.environ.get('HERMES_HOME', '').strip()
    env_path = _expand_hermes_home(env_home) if env_home else None
    memo_key = (str(native_home), str(env_path) if env_path is not None else '')
    memo = _default_hermes_root_memo
    if memo is not None and memo[:2] == memo_key:
        return memo[2]
    result = _hermes_root_of(native_home, env_path)
    _default_hermes_root_memo = (*memo_key, result)
    return result
_DELETED_PROFILES_DIR = '.deleted'
_HERMES_HOME_MARKERS = ('config.yaml', '.env', 'state.db')

def _is_hermes_profiles_root(profiles_dir: Path) -> bool:
    """True when *profiles_dir* is provably ``<hermes-home>/profiles``.

    Accepts the classic ``~/.hermes`` layout, a root carrying Hermes-home marker files, a
    ``profiles/.deleted`` tombstone dir (only ``profile delete`` creates it), or the default root.
    """
    root = profiles_dir.parent
    if root.name == '.hermes':
        return True
    try:
        if (profiles_dir / _DELETED_PROFILES_DIR).is_dir() or any(((root / marker).exists() for marker in _HERMES_HOME_MARKERS)):
            return True
    except OSError:
        pass
    try:
        return root.resolve(strict=False) == get_default_hermes_root().resolve(strict=False)
    except OSError:
        return False

def named_profile_home(path: str | Path) -> Path | None:
    """Return ``<root>/profiles/<name>`` when *path* is that home or under it.

    Requires ``<name>`` not to start with ``.`` and the ``profiles`` parent to be a real Hermes home;
    a default home whose path merely contains a ``profiles`` segment is not a named profile.
    """
    current = Path(path)
    for candidate in (current, *current.parents):
        if candidate.parent.name == 'profiles' and (not candidate.name.startswith('.')) and _is_hermes_profiles_root(candidate.parent):
            return candidate
        if candidate.name == '.hermes':
            return None
    return None

def profile_name_for_home(path: str | Path | None) -> str | None:
    """Return the canonical profile id owning *path*, or ``None`` when it is not a profile home.

    The default home is the Hermes root itself, so its basename is an installation detail (``.hermes``
    on POSIX and commonly ``hermes`` on Windows), not the profile id ``default``.
    """
    if path is None or not str(path).strip():
        return None
    current = Path(path).expanduser()
    try:
        default_root = get_default_hermes_root()
        for candidate in (current, current.resolve(strict=False)):
            if candidate == default_root or candidate == default_root.resolve(strict=False):
                return 'default'
            named = named_profile_home(candidate)
            if named is not None:
                return named.name
            if candidate.parent.name == 'profiles' and (not candidate.name.startswith('.')):
                return candidate.name
    except (OSError, RuntimeError, ValueError):
        return None
    return None

def profile_tombstone_path(profile_home: Path) -> Path:
    return profile_home.parent / _DELETED_PROFILES_DIR / profile_home.name

def named_profile_is_deleted(profile_home: str | Path) -> bool:
    return profile_tombstone_path(Path(profile_home)).exists()
PROFILE_ID_RE = re.compile('^[a-z0-9][a-z0-9_-]{0,63}$')

def assert_named_profile_home_live(path: str | Path) -> None:
    """Refuse missing or tombstoned named profile homes."""
    home = named_profile_home(path)
    if home is not None and (named_profile_is_deleted(home) or not home.exists()):
        raise FileNotFoundError(f'Named profile home does not exist: {home}. Create the profile explicitly before using it.')

def mkdir_under_hermes_home(path: str | Path) -> Path:
    """Create *path*, but never materialize a deleted/missing named profile."""
    target = Path(path)
    assert_named_profile_home_live(target)
    from hivemind_assembly.automation.state_engine.hermes_dir_acl import make_user_dir
    make_user_dir(target, parents=True, exist_ok=True)
    return target

def profile_cli_selector() -> str:
    """``-p <name> `` (trailing space) pinning copy-pasteable ``hermes ...`` guidance to the
    active NAMED profile, else ``""``: a bare ``hermes`` follows the sticky ``active_profile``
    file, which can name a different database than the one that failed (#105887). A custom
    home outside the profile tree has no selector (only HERMES_HOME names it)."""
    name = profile_name_for_home(get_hermes_home())
    return f'-p {name} ' if name and name != 'default' else ''
VALID_REASONING_EFFORTS = ('minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra')
