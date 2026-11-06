"""Stitch pinned public GitHub source-tree inventory pages into one strict manifest.

Input envelopes must preserve *both* the input cursor supplied to
GitHubPublicSourceInventory.page() and its untouched response. This protects
against accidental skipped, duplicated and out-of-order pages; it does not
authenticate untrusted JSON or replace a GitHub source/tree SHA verification.
No network, donor code, binary, credential or model execution occurs here.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SHA1 = re.compile(r"[0-9a-f]{40}\Z")
MAX_PAGES = 4096
MAX_ENTRIES = 100000
MAX_REQUESTS = 50000


class InvalidPageSequence(ValueError):
    """Cannot claim a complete, single-source public Git-tree inventory."""


def _exact(value, keys, where):
    if type(value) is not dict or set(value) != set(keys):
        raise InvalidPageSequence(f"{where}: invalid fields")
    return value


def _sha(value):
    return type(value) is str and SHA1.fullmatch(value) is not None


def _path(value, allow_root=False):
    if allow_root and value == "":
        return True
    return (type(value) is str and 1 <= len(value) <= 1024
            and not value.startswith("/") and "\\" not in value and ":" not in value
            and all(p not in ("", ".", "..") for p in value.split("/"))
            and not any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in value))


def _cursor(value, commit, root):
    _exact(value, ("commit_sha", "root_tree_sha", "frames"), "cursor")
    if value["commit_sha"] != commit or value["root_tree_sha"] != root:
        raise InvalidPageSequence("cursor: source revision drift")
    frames = value["frames"]
    if type(frames) is not list or not 1 <= len(frames) <= 40:
        raise InvalidPageSequence("cursor: invalid depth")
    for index, frame in enumerate(frames):
        _exact(frame, ("path", "sha", "index"), "cursor frame")
        if not _sha(frame["sha"]) or type(frame["index"]) is not int or not 0 <= frame["index"] <= 10000:
            raise InvalidPageSequence("cursor: invalid object/index")
        if not _path(frame["path"], allow_root=index == 0):
            raise InvalidPageSequence("cursor: unsafe frame path")
        if index == 0 and (frame["path"] != "" or frame["sha"] != root):
            raise InvalidPageSequence("cursor: root is not pinned")
        if index > 0 and not frame["path"].startswith(frames[index - 1]["path"] + "/" if index > 1 else ""):
            raise InvalidPageSequence("cursor: non-nested frame path")


def stitch_complete_pages(candidate, envelopes):
    """Return an inventory compatible with donor_cache_gate.verify_complete_inventory.

    Caller must retain request_cursor=cursor used for each page() invocation.
    Every response/entry must be unmodified from a trusted pinned GitHub read;
    no JSON-only tool can independently establish this external provenance.
    """
    if type(candidate) is not dict:
        raise InvalidPageSequence("candidate: invalid metadata")
    repo, commit, root = (candidate.get(k) for k in ("repository", "commit_sha", "root_tree_sha"))
    if (type(repo) is not str or repo.count("/") != 1
            or any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", x) for x in repo.split("/"))
            or not _sha(commit) or not _sha(root)):
        raise InvalidPageSequence("candidate: source identity is not pinned")
    if type(envelopes) is not list or not 1 <= len(envelopes) <= MAX_PAGES:
        raise InvalidPageSequence("pages: empty or excessive sequence")
    expected_cursor, entries, seen, total_requests = None, [], set(), 0
    for i, page in enumerate(envelopes):
        _exact(page, ("request_cursor", "response"), f"page {i}")
        if page["request_cursor"] != expected_cursor:
            raise InvalidPageSequence(f"page {i}: missing, duplicated or out-of-order cursor")
        response = _exact(page["response"], (
            "repository", "commit_sha", "root_tree_sha", "entries", "complete",
            "next_cursor", "requests"), f"page {i} response")
        if (response["repository"] != repo or response["commit_sha"] != commit
                or response["root_tree_sha"] != root):
            raise InvalidPageSequence(f"page {i}: source revision drift")
        next_cursor = response["next_cursor"]
        if type(response["complete"]) is not bool or response["complete"] != (next_cursor is None):
            raise InvalidPageSequence(f"page {i}: inconsistent completion claim")
        if i != len(envelopes) - 1 and next_cursor is None:
            raise InvalidPageSequence(f"page {i}: sequence continues after completion")
        if next_cursor is not None:
            _cursor(next_cursor, commit, root)
        if type(response["requests"]) is not int or not 1 <= response["requests"] <= 32:
            raise InvalidPageSequence(f"page {i}: invalid request count")
        total_requests += response["requests"]
        if total_requests > MAX_REQUESTS:
            raise InvalidPageSequence("pages: excessive total requests")
        batch = response["entries"]
        if type(batch) is not list or len(batch) > 500 or len(entries) + len(batch) > MAX_ENTRIES:
            raise InvalidPageSequence(f"page {i}: invalid entry count")
        for item in batch:
            _exact(item, ("path", "sha", "kind", "mode", "size", "submodule", "symlink"), "entry")
            path = item["path"]
            if not _path(path) or not _sha(item["sha"]):
                raise InvalidPageSequence("entry: unsafe path or noncanonical SHA")
            if (item["kind"], item["mode"]) not in (("tree", "040000"), ("blob", "100644"), ("blob", "100755")):
                raise InvalidPageSequence("entry: unsupported gitlink, symlink or mode")
            if type(item["submodule"]) is not bool or type(item["symlink"]) is not bool or item["submodule"] or item["symlink"]:
                raise InvalidPageSequence("entry: unresolved source type")
            if item["size"] is not None and (type(item["size"]) is not int or item["size"] < 0):
                raise InvalidPageSequence("entry: invalid size")
            folded = path.casefold()
            if folded in seen:
                raise InvalidPageSequence("entry: duplicate or Windows-case-colliding source path")
            seen.add(folded)
            entries.append(item)
        expected_cursor = next_cursor
    if expected_cursor is not None or not entries:
        raise InvalidPageSequence("pages: no complete populated inventory")
    return {"repository": repo, "commit_sha": commit, "root_tree_sha": root,
            "entries": entries, "complete": True, "next_cursor": None,
            "requests": total_requests}


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        raise SystemExit("usage: donor_inventory_pages.py CANDIDATE.json PAGE_ENVELOPES.json")
    with Path(args[0]).open(encoding="utf-8") as stream:
        candidate = json.load(stream)
    with Path(args[1]).open(encoding="utf-8") as stream:
        envelopes = json.load(stream)
    inventory = stitch_complete_pages(candidate, envelopes)
    # Reuse the existing stricter source/LICENSE blob checker. This gate can
    # assemble pages, but cannot approve licenses, vendor builds or CI.
    from donor_cache_gate import verify_complete_inventory
    result = verify_complete_inventory(candidate, inventory)
    print(json.dumps({**result, "source_pages_verified": len(envelopes),
                      "source_requests_verified": inventory["requests"]}, sort_keys=True))


if __name__ == "__main__":
    main()
