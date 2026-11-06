"""Bound the separate browser-control list before returning a DOM read.

The DOM snapshot has its own size limit, but Playwright identity metadata
comes from additional page attributes and must be bounded and redacted too.
This helper neither opens a browser nor authorizes an external effect.
"""

import re

MAX_CONTROL_FIELD_CHARS = 512
MAX_CONTROL_LABEL_CHARS = 65_536
MAX_CONTROL_ENTRIES = 1024
_FIELDS = ('tag', 'type', 'id', 'name', 'label', 'text')
_REF = re.compile(r'[0-9]{1,5}\Z')


class ControlSummaryError(RuntimeError):
    """A page exposed malformed or excessive control metadata."""


def bounded_control_summaries(refs, redact):
    """Return redacted controls, or refuse the entire ambiguous read.

    Every identity must have the expected fields produced by HA's pinned
    identity script. Page-provided attributes are not trusted for result size
    or privacy; a caller-owned redactor is mandatory. Call before assigning
    any handles/snapshot to a session, disposing returned handles on failure.
    """
    if not isinstance(refs, dict) or len(refs) > MAX_CONTROL_ENTRIES or not callable(redact):
        raise ControlSummaryError('The page returned invalid control metadata')
    result = []
    aggregate = 0
    for ref, item in refs.items():
        if (not isinstance(ref, str) or not _REF.fullmatch(ref)
                or not isinstance(item, tuple) or len(item) != 2
                or not isinstance(item[1], dict)):
            raise ControlSummaryError('The page returned invalid control metadata')
        identity = item[1]
        if identity.get('connected') is not True:
            raise ControlSummaryError('The page changed during control inspection')
        for field in _FIELDS:
            value = identity.get(field)
            if not isinstance(value, str) or len(value) > MAX_CONTROL_FIELD_CHARS:
                raise ControlSummaryError('The page returned oversized or invalid control metadata')
        if not identity['tag']:
            raise ControlSummaryError('The page returned invalid control metadata')
        label = (identity['label'] or identity['name'] or identity['text']
                 or identity['id'] or identity['tag'])
        safe_label = redact(label)
        if not isinstance(safe_label, str) or len(safe_label) > MAX_CONTROL_FIELD_CHARS:
            raise ControlSummaryError('The page returned oversized or invalid control metadata')
        aggregate += len(safe_label)
        if aggregate > MAX_CONTROL_LABEL_CHARS:
            raise ControlSummaryError('The page returned too much control metadata')
        result.append({'ref': ref, 'tag': identity['tag'], 'label': safe_label})
    return result
