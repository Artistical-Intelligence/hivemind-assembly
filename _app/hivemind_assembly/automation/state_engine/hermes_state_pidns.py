# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
from __future__ import annotations
import os
import re
import sys
from typing import NamedTuple, Optional
_PIDNS_TOKEN_RE = re.compile('(?:^|:)pidns=(\\d+)(?::|$)')

class LocalPidNamespace(NamedTuple):
    """What this process knows about its own PID namespace.

    Three states, and the ``checkable`` predicates treat each differently:
    ``supported`` False — the platform has no namespace identity at all;
    ``supported`` True with an ``id`` — resolved; ``supported`` True with an
    ``id`` of None — resolution failed, see the module docstring.
    """
    id: Optional[str]
    supported: bool
_UNSUPPORTED = LocalPidNamespace(None, False)
_LOCAL_PID_NS: Optional[LocalPidNamespace] = None

def _resolve_local_pid_namespace() -> LocalPidNamespace:
    if sys.platform != 'linux':
        return _UNSUPPORTED
    try:
        link = os.readlink('/proc/self/ns/pid')
    except OSError:
        return LocalPidNamespace(None, True)
    match = re.search('\\[(\\d+)\\]', link)
    return LocalPidNamespace(match.group(1) if match else None, True)

def _local_pid_namespace() -> LocalPidNamespace:
    """This process' PID-namespace identity (see :class:`LocalPidNamespace`)."""
    global _LOCAL_PID_NS
    if _LOCAL_PID_NS is None:
        local = _resolve_local_pid_namespace()
        if local.id is not None or not local.supported:
            _LOCAL_PID_NS = local
        return local
    return _LOCAL_PID_NS

def pid_namespace_id() -> Optional[str]:
    """What a holder records: the ``/proc/self/ns/pid`` inode on Linux, ``None``
    where there is no namespace identity or the lookup failed.  A holder never
    asserts a namespace it cannot prove."""
    return _local_pid_namespace().id

def _recorded_namespace(holder: str) -> Optional[str]:
    """The ``pidns=`` stamp from a holder string, or None when it carries none."""
    match = _PIDNS_TOKEN_RE.search(holder or '')
    return match.group(1) if match else None

def _qualify(recorded: Optional[str], *, unstamped_checkable: bool) -> bool:
    """The shared matrix; *unstamped_checkable* is the policy for a record that
    carries no namespace (see the module docstring for why there are two)."""
    local = _local_pid_namespace()
    if not local.supported:
        return True
    if recorded is None:
        return unstamped_checkable
    if local.id is None:
        return False
    return recorded == local.id

def holder_pid_checkable(holder: str) -> bool:
    """STRICT: may a structured holder string's ``pid=`` be probed here?

    The policy for TTL-bounded rows (compression locks, session turn leases):
    a foreign-namespace or unstamped holder is never probed — it defers to the
    row's own expiry instead (at most the remaining TTL; a false defer
    self-heals, a false reclaim ends a live turn).
    """
    return _qualify(_recorded_namespace(holder), unstamped_checkable=False)

def persistent_record_pidns_checkable(recorded: Optional[str]) -> bool:
    """LEGACY ROLLOUT: may a persistent record (no expiry) be probed here?

    The policy for the flock holder records: a foreign-namespace record is
    never probed, while an unstamped one keeps main's behavior — those records
    never expire, so refusing to probe them would permanently disable
    orphaned-lock cleanup (see the module docstring).
    """
    return _qualify(recorded, unstamped_checkable=True)
