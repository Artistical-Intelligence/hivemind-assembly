"""Fail-closed collection of browser element references during DOM inspection.

Each await can cross a navigation or permission-revocation boundary. The
caller supplies its live origin/profile validator. All new element handles are
best-effort disposed if validation fails; only validated handles transfer into
the session snapshot. No browser or provider is opened by this helper.
"""

import re


class ElementInspectionError(RuntimeError):
    """The current DOM cannot supply unambiguous authorized action refs."""


async def collect_authorized_refs(elements, session, check_authority, identity_script):
    """Collect unique numeric refs, fencing every awaited element inspection.

    ``elements`` is the complete batch returned by Playwright. On any failure,
    including cancellation, the batch is not transferred to the caller and
    every element is offered for disposal. A failed disposal never masks the
    original authorization failure. The caller must not await between this
    return and installing the validated references in its session.
    """
    refs = {}
    transferred = False
    try:
        check_authority(session)
        for element in elements:
            check_authority(session)
            ref = await element.get_attribute('data-ha-ref')
            check_authority(session)
            if not isinstance(ref, str) or not re.fullmatch(r'[0-9]{1,5}', ref):
                raise ElementInspectionError('The page returned an invalid action reference')
            if ref in refs:
                raise ElementInspectionError('The page contains ambiguous action references')
            identity = await element.evaluate(identity_script)
            check_authority(session)
            if not isinstance(identity, dict) or not identity.get('connected'):
                raise ElementInspectionError('The page changed during action reference inspection')
            refs[ref] = (element, identity)
        check_authority(session)
        transferred = True
        return refs
    finally:
        if not transferred:
            for element in elements:
                try:
                    await element.dispose()
                except Exception:
                    # Preserve the original failure; disposal is best effort.
                    pass
