# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
class RuntimeStoreError(ValueError):
    """A refusal by the state authority. ``reason`` is the bounded wire code (callers compare it as a
    string); ``field`` and ``detail`` name the check that fired and why, so a client and the gateway
    log can tell the reasons' many checks apart instead of reporting the bare code."""

    def __init__(self, reason: str, *, field: str | None=None, detail: str | None=None):
        self.reason = reason
        self.field = _one_line(field, 80)
        self.detail = _one_line(detail, 160)
        super().__init__(reason)

def _one_line(value, limit):
    """A refusal's ``field``/``detail`` as the log line and the client frame carry it: either may hold
    client text, so whitespace collapses to single spaces, other non-printables drop (no forged log
    lines), and the length is bounded below the client's frame limit."""
    if value is None:
        return None
    text = ''.join((ch for ch in ' '.join(str(value).split()) if ch.isprintable()))
    return text[:limit] or None
