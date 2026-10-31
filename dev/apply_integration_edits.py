"""Apply explicit, hash-fenced source edits without executing their contents.

Existing files require an exact SHA-256 or Git blob identity. Each replacement
must have one exact anchor. Optional expected output SHA-256 permits independent
byte-for-byte reproduction. Receipts retain the resulting hashes in either mode.
This publisher is not a reviewer and never removes pending review markers.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

ROOT = Path(__file__).resolve().parents[1]
PROTECTED = {'dev/apply_integration_edits.py', 'dev/integration_edits.json'}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def blob(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def safe_path(value):
    if not isinstance(value, str) or any(c in value for c in ('\\', ':', '\x00')):
        raise ValueError('Invalid edit path')
    rel = PurePosixPath(value)
    if not rel.parts or rel.is_absolute() or str(rel) != value or '..' in rel.parts:
        raise ValueError('Invalid edit path')
    if value in PROTECTED or not value.startswith(('_app/', 'tests/', 'dev/')):
        raise ValueError('Edit outside the integration implementation scope')
    target = ROOT / value
    if any(part.is_symlink() for part in (target, *target.parents) if part != ROOT.parent):
        raise ValueError('Refusing redirected edit path')
    if not target.resolve().is_relative_to(ROOT):
        raise ValueError('Edit escaped repository')
    return target


def apply(manifest_path):
    manifest = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    if manifest.get('schema') != 1 or not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', manifest.get('id', '')):
        raise ValueError('Invalid integration manifest')
    edits = manifest.get('edits')
    if not isinstance(edits, list) or not 1 <= len(edits) <= 30:
        raise ValueError('An edit manifest needs 1–30 exact files')
    planned, seen, results = [], set(), []
    for edit in edits:
        target = safe_path(edit['path'])
        if edit['path'].casefold() in seen:
            raise ValueError('Duplicate edit path')
        seen.add(edit['path'].casefold())
        expected = edit.get('after_sha256')
        if expected is not None and (not isinstance(expected, str) or not re.fullmatch(r'[a-f0-9]{64}', expected)):
            raise ValueError('Invalid output digest')
        if target.exists() and (not target.is_file() or target.stat().st_size > 2 * 1024**2):
            raise ValueError('Edit target is not a bounded file')
        before = target.read_bytes() if target.exists() else None
        if before is not None and expected is not None and sha(before) == expected:
            results.append({'path': edit['path'], 'sha256': expected, 'state': 'already_present'})
            continue
        if 'before_git_blob' in edit:
            wanted = edit['before_git_blob']
            if not isinstance(wanted, str) or not re.fullmatch(r'[a-f0-9]{40}', wanted) or before is None or blob(before) != wanted:
                raise ValueError('Concurrent edit conflict; original preserved: ' + edit['path'])
        elif 'before_sha256' not in edit or (sha(before) if before is not None else None) != edit['before_sha256']:
            raise ValueError('Concurrent edit conflict; original preserved: ' + edit['path'])
        if before is None:
            if expected is None:
                raise ValueError('New files require the expected output digest')
            after = edit['new_content'].encode('utf-8')
        else:
            text = before.decode('utf-8')
            replacements = edit['replacements']
            if not isinstance(replacements, list) or not 1 <= len(replacements) <= 100:
                raise ValueError('Missing bounded exact replacements')
            for change in replacements:
                if not isinstance(change['old'], str) or not change['old'] or text.count(change['old']) != 1:
                    raise ValueError('Edit anchor is missing or ambiguous: ' + edit['path'])
                if not isinstance(change['new'], str):
                    raise ValueError('Replacement must be text')
                text = text.replace(change['old'], change['new'], 1)
            after = text.encode('utf-8')
        if len(after) > 2 * 1024**2 or (expected is not None and sha(after) != expected):
            raise ValueError('Edit does not reproduce its expected bytes: ' + edit['path'])
        planned.append((target, after))
        results.append({'path': edit['path'], 'before_sha256': sha(before) if before is not None else None,
                        'sha256': sha(after), 'git_blob': blob(after), 'state': 'applied'})
    for target, after in planned:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(after)
    return {'id': manifest['id'], 'files': [p.relative_to(ROOT).as_posix() for p, _ in planned],
            'results': results, 'independent_review': False, 'release_approved': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args()
    receipt = apply(args.manifest)
    if args.receipt:
        args.receipt.write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(receipt))
