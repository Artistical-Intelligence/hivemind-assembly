# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
import re
from typing import Any, Optional
_SKILL_INVOCATION_PREFIX = '[IMPORTANT: The user has invoked the '
_SINGLE_SKILL_MARKER = 'The full skill content is loaded below.]'
_SINGLE_SKILL_INSTRUCTION = 'The user has provided the following instruction alongside the skill invocation: '
_RUNTIME_NOTE = '\n\n[Runtime note:'
_BUNDLE_MARKER = ' skill bundle,'
_BUNDLE_USER_INSTRUCTION = '\nUser instruction: '
_BUNDLE_FIRST_SKILL_BLOCK = '\n\n[Loaded as part of the '
_SKILL_NAME_RE = re.compile(re.escape(_SKILL_INVOCATION_PREFIX) + '"([^"]*)"')
_AUTO_LOAD_PREFIX = '[IMPORTANT: The "'
_SKILL_DIR_NOTE_END = 'then run them with the terminal tool using the absolute path.'
SKILL_SCAFFOLD_SQL_LIKE = _SKILL_INVOCATION_PREFIX + '%'
AUTO_LOAD_SCAFFOLD_SQL_LIKE = _AUTO_LOAD_PREFIX + '%'
SKILL_EXCERPT_JOINT = '\x1e'

def extract_user_instruction_from_skill_message(content: Any) -> Optional[str]:
    """Recover the user's instruction from a slash-skill-expanded turn: the
    string unchanged when it is NOT scaffolding, the extracted instruction when
    the scaffolding carried one, or ``None`` for a bare ``/skill`` invocation."""
    if not isinstance(content, str):
        return None
    if not content.startswith(_SKILL_INVOCATION_PREFIX):
        return content
    if _BUNDLE_MARKER in content:
        return _cut_after(content, _BUNDLE_USER_INSTRUCTION, _BUNDLE_FIRST_SKILL_BLOCK, content.find)
    if _SINGLE_SKILL_MARKER in content:
        return _cut_after(content, _SINGLE_SKILL_INSTRUCTION, _RUNTIME_NOTE, content.rfind)
    return None

def _describe_auto_loaded_skill_turn(content: str) -> Optional[str]:
    """``[IMPORTANT: The "X" skill is auto-loaded. …]`` + payload(s) + typed text
    -> the typed text.

    ``_hmwa_auto_load_skills`` builds each payload with ``_build_skill_message``
    (activation header, body, then the skill-directory footer note) and appends the
    user's text as the final block. The footer's closing sentence is the reliable
    payload-end marker: the user's text is what follows the LAST footer. A header
    quoted inside a body (a skill embedding the scaffold in an example) carries no
    footer, so it cannot end the payload early. ``/<skill>`` renders when no user
    text follows, matching the single-skill describer's bare-invocation shape."""
    if not content.startswith(_AUTO_LOAD_PREFIX):
        return None
    name_match = re.match(re.escape(_AUTO_LOAD_PREFIX) + '([^"]*)"', content)
    name = name_match.group(1) if name_match else ''
    footer_end = content.rfind(_SKILL_DIR_NOTE_END)
    if footer_end == -1:
        return f'/{name}' if name else None
    tail = content[footer_end + len(_SKILL_DIR_NOTE_END):].lstrip()
    while (block_end := next((end for start, end in _TRAILING_BLOCK_ENDS if tail.startswith(start)), None)):
        cut = tail.find(block_end)
        tail = tail[cut + len(block_end):].lstrip() if cut >= 0 else ''
    if not tail.strip():
        return f'/{name}' if name else None
    return ' '.join(tail.split()) or None

def describe_skill_invocation(content: Any, separator: str=' — ') -> Optional[str]:
    """Render a slash-skill-expanded turn the way the user typed it:
    ``"/work — fix the title leak"``, ``"/work"`` for a bare invocation, or
    ``None`` when *content* is not scaffolding. ``separator=" "`` gives the
    literal invocation as typed (chat transcripts).

    A gateway auto-load scaffold (channel-bound skill on a new session) is also
    scaffolding: the typed request follows the skill payload, so it renders as
    that request — the header/body never reaches a preview or a title (#48359).
    """
    if not isinstance(content, str):
        return None
    if content.startswith(_AUTO_LOAD_PREFIX):
        return _describe_auto_loaded_skill_turn(content)
    if not content.startswith(_SKILL_INVOCATION_PREFIX):
        return None
    match = _SKILL_NAME_RE.match(content)
    name = (match.group(1) if match else '').strip()
    label = name if name.startswith('/') else f'/{name}'
    instruction = extract_user_instruction_from_skill_message(content)
    if instruction and instruction is not content:
        instruction = ' '.join(instruction.split(SKILL_EXCERPT_JOINT)[0].split())
        if instruction:
            return f'{label}{separator}{instruction}' if name else instruction
    return label if name else None

def _cut_after(message: str, marker: str, stop_marker: str, find) -> Optional[str]:
    """Text between *marker* (located with ``find``) and *stop_marker*, stripped; None if absent/empty."""
    marker_idx = find(marker)
    if marker_idx < 0:
        return None
    return message[marker_idx + len(marker):].split(stop_marker, 1)[0].strip() or None
_SUPPORTING_FILES_END = '/scripts/foo.js`).'
_TRAILING_BLOCK_ENDS = (('[Skill config (', '\n]'), ('[Skill setup note: ', ']\n\n'), ('[This skill has supporting files', _SUPPORTING_FILES_END))
