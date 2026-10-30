# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
def _dashboard_subcommand_index(argv: list[str]) -> int | None:
    return next((i for i, tok in enumerate(argv) if tok in ('serve', 'dashboard')), None)

def _is_ephemeral_port_zero_backend(argv: list[str]) -> bool:
    """True for Desktop-style ``serve|dashboard --port 0`` backends — replaying them after
    ``hermes update`` multiplies listening backends because ``--port 0`` binds a fresh port.

    See #78821.
    """
    if _dashboard_subcommand_index(argv) is None:
        return False
    return any((tok == '--port' and i + 1 < len(argv) and (str(argv[i + 1]) == '0') or (tok.startswith('--port=') and tok.split('=', 1)[1].strip() == '0') for i, tok in enumerate(argv)))
