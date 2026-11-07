"""Reconstruct Git tree objects from a complete public donor inventory, offline.

No donor code, binaries, network access or third-party imports. The digest binds
an inventory to its declared root Git tree *if the root was independently pinned*;
this does not authenticate a GitHub commit or determine license compatibility.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys

_SHA1 = re.compile(r"[0-9a-f]{40}\Z")
_ALLOWED = {("blob", "100644"), ("blob", "100755"), ("tree", "040000")}


class InvalidTreeDigest(ValueError):
    """Malformed or inconsistent Git tree inventory."""


def _hash_tree(children):
    """Hash one Git tree using Git's ordering and wire format (not JSON order)."""
    def order(item):
        name, kind, _mode, _sha = item
        return name.encode("utf-8") + (b"/" if kind == "tree" else b"")

    body = bytearray()
    for name, kind, mode, sha in sorted(children, key=order):
        wire_name = name.encode("utf-8")
        if not wire_name or b"/" in wire_name or b"\x00" in wire_name:
            raise InvalidTreeDigest("invalid Git tree entry name")
        if (kind, mode) not in _ALLOWED or not _SHA1.fullmatch(sha):
            raise InvalidTreeDigest("invalid Git mode or object SHA")
        wire_mode = b"40000" if kind == "tree" else mode.encode("ascii")
        body.extend(wire_mode + b" " + wire_name + b"\0" + bytes.fromhex(sha))
    return hashlib.sha1(b"tree " + str(len(body)).encode("ascii") + b"\0" + body).hexdigest()


def reconstruct_tree_digest(entries):
    """Return root SHA and verified tree count; reject incomplete/contradictory trees.

    All entries must be from the *complete* inventory, excluding the implicit
    root. Git's tree ordering treats a directory name as if it ended in '/'.
    Call the existing donor_cache_gate.verify_complete_inventory first for
    pinned-source, portability, and manifest-completeness validation.
    """
    if type(entries) is not list or not entries or len(entries) > 100000:
        raise InvalidTreeDigest("inventory entries missing or excessive")
    by_path = {}
    children = {}
    for entry in entries:
        if type(entry) is not dict or set(entry) != {
            "path", "sha", "kind", "mode", "size", "submodule", "symlink"
        }:
            raise InvalidTreeDigest("unexpected entry fields")
        path, kind, mode, sha = (entry[k] for k in ("path", "kind", "mode", "sha"))
        if (type(path) is not str or not path or "\\" in path
                or any(p in ("", ".", "..") for p in path.split("/"))
                or type(kind) is not str or type(mode) is not str
                or type(sha) is not str or (kind, mode) not in _ALLOWED
                or not _SHA1.fullmatch(sha)):
            raise InvalidTreeDigest("invalid Git source entry")
        if path in by_path:
            raise InvalidTreeDigest("duplicate Git tree path")
        by_path[path] = entry
        parent, _, name = path.rpartition("/")
        children.setdefault(parent, []).append((name, kind, mode, sha))
    for path, entry in sorted(by_path.items(), key=lambda item: item[0].count("/"), reverse=True):
        if entry["kind"] != "tree":
            continue
        calculated = _hash_tree(children.get(path, []))
        if calculated != entry["sha"]:
            raise InvalidTreeDigest("subtree SHA does not match declared entries")
    for path in by_path:
        if "/" in path:
            parent = path.rpartition("/")[0]
            if parent not in by_path or by_path[parent]["kind"] != "tree":
                raise InvalidTreeDigest("missing parent directory")
    root_sha = _hash_tree(children.get("", []))
    return {"root_tree_sha": root_sha,
            "tree_objects_checked": 1 + sum(e["kind"] == "tree" for e in entries)}


def verified_tree_cache_key(candidate, build, inventory):
    """Require both the existing gate and bit-exact Git root-tree reconstruction."""
    from donor_cache_gate import cache_key_with_inventory, InvalidIntake

    key = cache_key_with_inventory(candidate, build, inventory)
    digest = reconstruct_tree_digest(inventory["entries"])
    if digest["root_tree_sha"] != candidate["root_tree_sha"]:
        raise InvalidIntake("inventory: reconstructed Git root SHA mismatch")
    return key, digest


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 3:
        raise SystemExit("usage: donor_tree_digest.py CANDIDATE.json BUILD.json INVENTORY.json")
    from donor_cache_gate import _load_json

    candidate, build, inventory = (_load_json(p) for p in args)
    key, digest = verified_tree_cache_key(candidate, build, inventory)
    print(json.dumps({"cache_key": key, **digest,
                      "root_tree_reconstructed": True,
                      "remote_source_authenticated": False,
                      "license_approved": False,
                      "runtime_tested": False}, sort_keys=True))


if __name__ == "__main__":
    main()
