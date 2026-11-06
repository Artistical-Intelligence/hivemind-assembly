"""Fence each awaited inspection before a native HA browser element action.

An element identity check alone is insufficient: visibility, enablement and
metadata evaluation also await remote browser work. Revocation or navigation
between these awaits must stop further DOM inspection and prevent dispatch.
This helper is pure transport validation: no browser, provider or login starts.
"""


# Metadata joins page-controlled labels and attributes independently of the
# bounded snapshot/control summaries. Never pass an unbounded DOM string to
# the caller's sensitive-control classifier or use it to authorize dispatch.
MAX_ACTION_METADATA_CHARS = 8192


class ActionInspectionError(RuntimeError):
    """The selected element is no longer an unambiguous actionable control."""


async def inspect_action_target(element, expected, identity_script, metadata_script,
                                session, check_authority):
    """Return (identity, metadata) only if every awaited read stays authorized.

    ``check_authority`` must validate BOTH the live page origin and the current
    profile/route policy. Its original exception propagates unchanged. The
    caller must not await between this return and the final dispatch fence.
    """
    check_authority(session)
    identity = await element.evaluate(identity_script)
    check_authority(session)
    if not isinstance(identity, dict) or not identity.get('connected') or identity != expected:
        raise ActionInspectionError('The selected element changed; no action was performed')

    visible = await element.is_visible()
    check_authority(session)
    if visible is not True:
        raise ActionInspectionError('The selected element is not currently actionable')

    enabled = await element.is_enabled()
    check_authority(session)
    if enabled is not True:
        raise ActionInspectionError('The selected element is not currently actionable')

    metadata = await element.evaluate(metadata_script)
    check_authority(session)
    if (not isinstance(metadata, str) or len(metadata) > MAX_ACTION_METADATA_CHARS
            or '\x00' in metadata):
        raise ActionInspectionError('The selected element returned invalid or excessive metadata')
    return identity, metadata
