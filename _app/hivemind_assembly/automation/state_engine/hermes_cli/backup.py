# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
from pathlib import Path

def is_zeroed_sqlite_file(path: Path, *, probe_bytes: int=100, force: bool=False) -> bool:
    """True when *path* looks like the #68474 zeroed-state.db signature.

    Only regular files qualify: probing a FIFO/device/socket could block indefinitely.

    Signature: no ``SQLite format 3`` header and no data — either empty (size 0, the total-loss case,
    #97568) or first *probe_bytes* all NUL. Used at SessionDB open and for snapshot diagnostics so a silent
    all-zero file becomes a guided recovery instead of a generic failure.
    """
    try:
        if not path.is_file():
            return False
    except OSError:
        return False
    from hivemind_assembly.automation.state_engine.hermes_cli.sqlite_safe_read import has_live_connection, read_header_bytes_preopen
    if not force and has_live_connection(path):
        return False
    head = read_header_bytes_preopen(path, length=max(16, probe_bytes), force=force)
    return head is not None and (not head.startswith(b'SQLite format 3')) and (not any(head))
