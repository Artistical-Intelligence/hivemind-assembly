"""Finalize a browser read without leaking handles on late authorization loss.

Element collection transfers Playwright handles to the caller before the final
profile/route/origin check. A failed last check must dispose those provisional
handles rather than leaving them outside the session's ownership. This helper
never opens a browser or retries an external operation.
"""

from .control_summaries import ControlSummaryError, bounded_control_summaries
from .element_refs import MAX_SNAPSHOT_CHARS


async def publish_authorized_snapshot(session, handles, text, check_authority,
                                      redact, new_snapshot_id):
    """Return (snapshot_id, safe_text, controls) after an atomic in-memory handoff.

    No await occurs between the last authorization check and installation of
    the handles. Until installation succeeds, every handle is provisionally
    owned by this function and best-effort disposed on any failure, including
    permission revocation, malformed output, or cancellation. Errors propagate
    to the caller's existing uncertain/non-replayable receipt journal.
    """
    installed = False
    try:
        controls = bounded_control_summaries(handles, redact)
        check_authority(session)
        safe_text = redact(text)
        if not isinstance(safe_text, str) or len(safe_text) > MAX_SNAPSHOT_CHARS:
            raise ControlSummaryError('The page returned invalid or oversized redacted text')
        snapshot_id = new_snapshot_id()
        if not isinstance(snapshot_id, str) or not snapshot_id:
            raise ControlSummaryError('The page snapshot identifier is invalid')
        session.update(snapshot=snapshot_id, handles=handles)
        installed = True
        return snapshot_id, safe_text, controls
    finally:
        if not installed and isinstance(handles, dict):
            for item in handles.values():
                if not isinstance(item, tuple) or not item:
                    continue
                try:
                    await item[0].dispose()
                except Exception:
                    # Cleanup cannot erase the original authorization failure.
                    pass
