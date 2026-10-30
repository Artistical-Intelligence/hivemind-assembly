# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
from __future__ import annotations
import logging
import math
from datetime import datetime
from typing import Any, Optional
logger = logging.getLogger(__name__)
EPOCH_MIN = 0.0
EPOCH_MAX = 4200000000.0

def coerce_epoch(value: Any, *, session_id: Optional[str]=None, field: str='timestamp') -> Optional[float]:
    """A stored timestamp cell as float epoch seconds, or ``None`` when it cannot be trusted.

    Numbers, numeric strings and ``datetime`` are accepted; anything else, non-finite values and
    values outside ``EPOCH_MIN..EPOCH_MAX`` return ``None`` after a WARNING naming the session so
    the corrupt row can be found. ``None``/``""`` mean "unset" and stay silent. Every reader that
    renders a row timestamp goes through here (a bad row degrades to one ``?`` cell, never a dead
    command) and every writer uses it to refuse persisting a new bad row.
    """
    if value is None or value == '':
        return None
    try:
        ts = float(value.timestamp()) if isinstance(value, datetime) else float(value)
    except (TypeError, ValueError):
        ts = math.nan
    if not EPOCH_MIN <= ts <= EPOCH_MAX:
        logger.warning('Ignoring corrupt %s %r%s', field, value, f' on session {session_id}' if session_id else '')
        return None
    return ts
