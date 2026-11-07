"""Pure offline, read-only HA branch-consolidation preflight.

Input is externally captured GitHub metadata JSON; never executes GitHub operations,
actions, donor code, merges, deletions, or approval changes. This is a fail-closed
triage helper, NOT an independent review or merge authorization.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import PurePosixPath

SHA = re.compile(r"[0-9a-f]{40}\Z")
EXPECTED = (
    "automation/ha-workplace-browser-transport-20261105",
    "beta/0.38.0-beta.1-source",
    "experiment/chatmode-scheduled-github-20261104",
    "fix/browser-mcp-setup-2026-11-01",
)


def _sha(value, key):
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise ValueError(f"invalid {key}: expected full Git commit SHA")
    return value


def _path(value):
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError("invalid changed file path")
    parts = PurePosixPath(value).parts
    if value.startswith("/") or any(p in (".", "..") for p in value.split("/")) or not parts:
        raise ValueError("unsafe changed file path")
    return value


def classify(snapshot):
    """Return deterministic, non-authoritative dispositions from SHA-pinned metadata."""
    if not isinstance(snapshot, dict):
        raise ValueError("snapshot must be a JSON object")
    main = _sha(snapshot.get("main_sha"), "main_sha")
    rows = snapshot.get("branches")
    if not isinstance(rows, list) or len(rows) != len(EXPECTED):
        raise ValueError("exactly four known branch receipts required")
    if {r.get("name") for r in rows if isinstance(r, dict)} != set(EXPECTED):
        raise ValueError("missing/duplicate/unexpected branch name")
    out = []
    for r in rows:
        name = r["name"]
        head = _sha(r.get("head_sha"), "head_sha")
        base = _sha(r.get("compared_main_sha"), "compared_main_sha")
        if base != main or r.get("too_large") is not False:
            raise ValueError(f"stale/incomplete compare for {name}")
        ahead, behind = r.get("ahead_by"), r.get("behind_by")
        if (type(ahead) is not int or type(behind) is not int
                or min(ahead, behind) < 0):
            raise ValueError("invalid ahead/behind counts")
        files = r.get("files")
        if not isinstance(files, list):
            raise ValueError("missing complete file list")
        seen = set()
        changed = []
        for f in files:
            if not isinstance(f, dict) or f.get("status") not in ("added", "modified", "removed", "renamed"):
                raise ValueError("invalid file change entry")
            p = _path(f.get("filename"))
            if p in seen:
                raise ValueError("duplicate changed file path")
            seen.add(p)
            changed.append(p)
        if ahead == 0 and changed:
            raise ValueError("behind/equal branch cannot have ahead-only file differences")
        if ahead > 0 and not changed:
            raise ValueError("ahead branch requires reviewed diff, empty or truncated compare")
        code = [p for p in changed if p.startswith(("_app/", "tests/", ".github/"))]
        if ahead == 0:
            state = "NO_UNIQUE_COMMITS_DO_NOT_MERGE"
        elif not code and all(p.startswith("experiments/") for p in changed):
            state = "HISTORICAL_EVIDENCE_ONLY_NEEDS_OWNER_DISPOSITION"
        else:
            state = "UNMERGED_UNREVIEWED_SOURCE_DO_NOT_MERGE"
        # Note: even independently reviewed source needs owner mediation and
        # fresh-source checks; this helper intentionally NEVER yields MERGE_OK.
        out.append({"branch": name, "head_sha": head, "main_sha": main,
                    "ahead_by": ahead, "behind_by": behind,
                    "changed_files": len(changed), "code_or_test_files": len(code),
                    "disposition": state, "merge_authorized": False})
    return {"main_sha": main, "source": "untrusted metadata snapshot; verify against GitHub",
            "merges_performed": 0, "branches_deleted": 0,
            "acceptance": "CHECKS PENDING / AWAITING CI AND QUALIFIED REVIEW",
            "branches": out}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", help="local JSON of SHA-pinned compare metadata")
    args = parser.parse_args()
    def reject_constant(value):
        raise ValueError("non-JSON numeric constant " + value)
    with open(args.snapshot, "r", encoding="utf-8") as fp:
        data = json.load(fp, parse_constant=reject_constant)
    print(json.dumps(classify(data), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
