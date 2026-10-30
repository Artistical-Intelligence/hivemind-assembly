# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
from pathlib import Path
from hivemind_assembly.automation.state_engine.hermes_constants import PROFILE_ID_RE
_PROFILE_ID_RE = PROFILE_ID_RE

def _get_profiles_root() -> Path:
    """Named-profiles root, anchored to the hermes root (NOT the current HERMES_HOME, which
    may itself be a profile) so ``coder profile list`` sees all profiles."""
    return _get_default_hermes_home() / 'profiles'

def _get_default_hermes_home() -> Path:
    """Default (pre-profile) HERMES_HOME: ``~/.hermes``, or HERMES_HOME itself in
    Docker/custom deployments (e.g. ``/opt/data``)."""
    from hivemind_assembly.automation.state_engine.hermes_constants import get_default_hermes_root
    return get_default_hermes_root()

def normalize_profile_name(name: str) -> str:
    """Canonical profile id used on disk and in ``-p`` argv: lowercase, ``default`` matched
    case-insensitively. Dashboards/tools may pass title-cased labels — normalize before
    validation, assignment, and subprocess spawn.

    Named profiles are stored lowercase under ``profiles/<id>/``. The special
    alias ``default`` is matched case-insensitively (``Default`` → ``default``).
    Dashboards and tools may pass title-cased display labels; normalize before
    validation, assignment, and subprocess spawn (see issue #18498).

    Raises ``ValueError`` for non-string input: a numeric profile id (e.g. a
    DB row id or a falsy sentinel) silently coerced via ``str()`` becomes a
    real on-disk profile directory (``profiles/0/``, #88842). Callers that
    hold a numeric id must resolve it to an actual profile name first.
    """
    if not isinstance(name, str):
        raise ValueError(f'profile name must be a string, got {type(name).__name__}: {name!r}')
    stripped = name.strip()
    if not stripped:
        raise ValueError('profile name cannot be empty')
    if stripped.casefold() == 'default':
        return 'default'
    return stripped.lower()

def get_active_profile_name() -> str:
    """Profile name inferred from HERMES_HOME: ``"default"`` when unset or ``~/.hermes``, the
    name under ``~/.hermes/profiles/<name>``, ``"custom"`` for any other path."""
    from hivemind_assembly.automation.state_engine.hermes_constants import get_hermes_home
    resolved = get_hermes_home().resolve()
    if resolved == _get_default_hermes_home().resolve():
        return 'default'
    profiles_root = _get_profiles_root().resolve()
    try:
        parts = resolved.relative_to(profiles_root).parts
        if len(parts) == 1 and _PROFILE_ID_RE.match(parts[0]):
            return parts[0]
    except ValueError:
        pass
    return 'custom'
