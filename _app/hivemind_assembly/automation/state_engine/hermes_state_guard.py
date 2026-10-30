# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
import os
import sys
import threading
import weakref
from pathlib import Path
from typing import Any, Optional
try:
    import psutil
except ImportError:
    psutil = None
_STATE_DB_GUARD_BYPASS_ENV = 'HERMES_STATE_DB_GUARD_BYPASS'

def _real_platform_state_root() -> Optional[Path]:
    """The REAL platform-default Hermes root. Avoids ``Path.home()`` /
    ``hermes_constants`` (tests monkeypatch Path.home to a tempdir); ``expanduser``
    reads HOME/passwd, which the conftest never rewrites."""
    try:
        home = Path(os.path.expanduser('~'))
        if sys.platform == 'win32':
            base = os.environ.get('LOCALAPPDATA', '').strip()
            root = Path(base) / 'hermes' if base else home / 'AppData' / 'Local' / 'hermes'
        else:
            root = home / '.hermes'
        return root.resolve()
    except Exception:
        return None
_TEST_ISOLATION_MARKER_ENV = 'HERMES_TEST_ISOLATION'

def _running_under_pytest() -> bool:
    """True when this process (or a parent test process) is a pytest run."""
    return bool(os.environ.get('PYTEST_CURRENT_TEST') or os.environ.get('PYTEST_VERSION') or os.environ.get(_TEST_ISOLATION_MARKER_ENV))
_PYTEST_LAUNCHER_NAMES = frozenset({'pytest', 'py.test', 'pytest.exe', 'py.test.exe'})
_PYTEST_ANCESTOR: Optional[bool] = None

def _process_looks_like_pytest(proc: Any) -> bool:
    """True when *proc*'s command line is a pytest invocation. Unreadable cmdline
    => not pytest: guessing the other way would refuse production opens."""
    try:
        cmdline = proc.cmdline() or []
    except Exception:
        return False
    for arg in cmdline:
        try:
            name = str(arg).strip('"').strip("'").replace('\\', '/').rsplit('/', 1)[-1].lower()
        except Exception:
            continue
        if name in _PYTEST_LAUNCHER_NAMES:
            return True
    return False

def _has_pytest_ancestor() -> bool:
    """True when an ancestor process is a pytest run: a child spawned with a
    rebuilt env loses PYTEST_* and the HERMES_HOME redirect together, ancestry
    survives that. Fails open without psutil / on walk errors.

    ``_running_under_pytest`` reads ``PYTEST_*`` env vars, which a child spawned with a rebuilt environment
    loses at the same moment it loses the ``HERMES_HOME`` redirect: that child aims at the production DB
    *and* disarms the guard in one step (#82770). Ancestry is the one test-context signal that survives an
    env rebuild, so it backs the env check up.
    """
    global _PYTEST_ANCESTOR
    if _PYTEST_ANCESTOR is not None:
        return _PYTEST_ANCESTOR
    found = False
    if psutil is not None:
        try:
            found = any((_process_looks_like_pytest(p) for p in psutil.Process().parents()))
        except Exception:
            found = False
    _PYTEST_ANCESTOR = found
    return found

def _in_test_context() -> bool:
    """Test run by environment or ancestry (memoised; env checked first)."""
    return _running_under_pytest() or _has_pytest_ancestor()

def _is_production_state_db(resolved: Path, root: Path) -> bool:
    """*resolved* is ``<root>/state.db`` or ``<root>/profiles/<name>/state.db``;
    deeper scratch paths (repo worktrees) are deliberately NOT matched."""
    if resolved.parent == root:
        return True
    try:
        parts = resolved.relative_to(root).parts
    except ValueError:
        return False
    return len(parts) == 3 and parts[0] == 'profiles'
_test_instance_registry: weakref.WeakSet[Any] = weakref.WeakSet()

def _register_test_instance(db: Any) -> None:
    """Track *db* for suite-level teardown closing (test-isolation runs only)."""
    if os.environ.get(_TEST_ISOLATION_MARKER_ENV):
        try:
            _test_instance_registry.add(db)
        except Exception:
            pass
_last_init_error_lock = threading.Lock()

def _set_last_init_error(msg: Optional[str]) -> None:
    """Record (or clear with None) the most recent init failure. __init__ never
    clears on success: a concurrent open would erase the cause another thread's
    /resume is about to format."""
    global _last_init_error
    with _last_init_error_lock:
        _last_init_error = msg
