# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
from __future__ import annotations

class SessionCoverageMixin:
    """Coverage helpers for SessionDB; relies on SessionMessagesMixin's codec/identity helpers."""
