# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
from __future__ import annotations

class SessionTelegramTopicsMixin:
    """Telegram DM topic-mode tables, bindings and lookups. Read paths tolerate absent
    tables (nobody ran ``/topic``) by returning their empty value and never create them;
    pre-v3 tables left by an upgrade are self-healed on read."""
