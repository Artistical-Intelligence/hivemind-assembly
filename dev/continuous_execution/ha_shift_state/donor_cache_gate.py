"""HA public donor *source identity* and build-cache receipt gate.

Metadata-only: no network, donor execution, binaries, credentials, dependency
installation, approval decisions, or third-party code import. A matching cache
receipt proves bytes/inputs identity, NOT license compatibility or runtime parity.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

SCHEMA = "ha-public-donor-cache/v1"
SHA1 = re.compile(r"[0-9a-f]{40}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
OPT = re.compile(r"[A-Z][A-Z0-9_]*\Z")
# Win32 device basenames resolve specially even when given a file extension.
WINDEV = re.compile(r"(?:CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[1-9¹²³]|LPT[1-9¹²³])\Z", re.IGNORECASE)
MAX_OBJECTS = 4096


class InvalidIntake(ValueError):
    """Unpinned, ambiguous or potentially unsafe donor-cache metadata."""


def _record(value, where, allowed):
    if type(value) is not dict or set(value) != set(allowed):
        raise InvalidIntake(f"{where}: expected exact fields {','.join(sorted(allowed))}")
    return value


def _text(value, where, max_len=512):
    if (type(value) is not str or not 1 <= len(value) <= max_len
            or any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in value)):
        raise InvalidIntake(f"{where}: invalid text")
    return value


def _hex(value, pattern, where):
    if type(value) is not str or not pattern.fullmatch(value):
        raise InvalidIntake(f"{where}: requires lowercase immutable hash")
    return value


def _path(value, where):
    value = _text(value, where, 1024)
    parts = value.split("/")
    if ("\\" in value or ":" in value or value.startswith("/")
            or any(part in ("", ".", "..") for part in parts)):
        raise InvalidIntake(f"{where}: unsafe relative path")
    # Avoid divergent cache/source identities across Linux and Windows hosts:
    # Win32 collapses trailing dot/space and reserves device names.
    if any(part.endswith((" ", ".")) or WINDEV.fullmatch(part.split(".", 1)[0])
           or any(c in '<>"|?*' for c in part) or part.casefold() == ".git"
           or len(part.encode("utf-16-le")) > 510 for part in parts):
        raise InvalidIntake(f"{where}: nonportable Windows source path")
    return value


def checked_candidate(candidate):
    """Validate *evidence* only. Root LICENSE != every source/dependency license."""
    x = _record(candidate, "candidate", [
        "schema", "repository", "commit_sha", "root_tree_sha", "license",
        "source_objects", "runtime_seam", "integration_status",
    ])
    if x["schema"] != SCHEMA or not REPO.fullmatch(str(x["repository"])):
        raise InvalidIntake("candidate: unrecognized schema or repository")
    _hex(x["commit_sha"], SHA1, "commit_sha")
    _hex(x["root_tree_sha"], SHA1, "root_tree_sha")
    lic = _record(x["license"], "license", ["path", "blob_sha", "spdx", "review"])
    _path(lic["path"], "license.path")
    _hex(lic["blob_sha"], SHA1, "license.blob_sha")
    _text(lic["spdx"], "license.spdx", 100)
    if lic["review"] != "PENDING":
        raise InvalidIntake("license.review: this gate cannot grant approval")
    if x["integration_status"] != "SOURCE_ONLY_NOT_BUILT":
        raise InvalidIntake("integration_status: cannot claim executed runtime")
    _text(x["runtime_seam"], "runtime_seam", 240)
    objects = x["source_objects"]
    if type(objects) is not list or not 1 <= len(objects) <= MAX_OBJECTS:
        raise InvalidIntake("source_objects: invalid count")
    paths = {lic["path"].casefold()}
    for obj in objects:
        _record(obj, "source_object", ["path", "blob_sha"])
        name = _path(obj["path"], "source_object.path")
        _hex(obj["blob_sha"], SHA1, "source_object.blob_sha")
        if name.casefold() in paths:
            raise InvalidIntake("source_objects: case-folding path collision")
        paths.add(name.casefold())
    return x


def checked_build(build):
    """Full build inputs must be pinned before a reusable key is possible."""
    x = _record(build, "build", [
        "host", "target", "compiler", "compiler_version", "compiler_sha256",
        "generator", "cmake_version", "options", "dependency_pins",
        "patchset_sha256", "source_tree_complete",
    ])
    for field in ("host", "target", "compiler", "compiler_version", "generator", "cmake_version"):
        _text(x[field], f"build.{field}", 100)
    _hex(x["compiler_sha256"], SHA256, "build.compiler_sha256")
    _hex(x["patchset_sha256"], SHA256, "build.patchset_sha256")
    if x["source_tree_complete"] is not True:
        raise InvalidIntake("build.source_tree_complete: cannot cache partial tree")
    options = x["options"]
    if type(options) is not dict or len(options) > 128:
        raise InvalidIntake("build.options: invalid options")
    for key, value in options.items():
        if type(key) is not str or not OPT.fullmatch(key):
            raise InvalidIntake("build.options: invalid flag name")
        _text(value, f"build.options.{key}", 250)
    deps = x["dependency_pins"]
    if type(deps) is not list or len(deps) > 2048:
        raise InvalidIntake("build.dependency_pins: invalid list")
    names = set()
    for dep in deps:
        _record(dep, "dependency_pin", ["repository", "commit_sha", "tree_sha"])
        if not REPO.fullmatch(str(dep["repository"])):
            raise InvalidIntake("dependency_pin: invalid repository")
        _hex(dep["commit_sha"], SHA1, "dependency.commit_sha")
        _hex(dep["tree_sha"], SHA1, "dependency.tree_sha")
        name = dep["repository"].casefold()
        if name in names:
            raise InvalidIntake("dependency_pin: duplicate dependency")
        names.add(name)
    return x



def verify_complete_inventory(candidate, inventory):
    """Consume HA GitHubPublicSourceInventory.fast_manifest output, offline.

    A partial page is not an inventory. Symlinks/gitlinks need their own
    provenance and review, so this conservative gate fails closed on either.
    """
    c = checked_candidate(candidate)
    _record(inventory, "inventory", [
        "repository", "commit_sha", "root_tree_sha", "entries",
        "complete", "next_cursor", "requests",
    ])
    if (inventory["repository"] != c["repository"] or
            inventory["commit_sha"] != c["commit_sha"] or
            inventory["root_tree_sha"] != c["root_tree_sha"] or
            inventory["complete"] is not True or inventory["next_cursor"] is not None or
            type(inventory["requests"]) is not int or inventory["requests"] < 1):
        raise InvalidIntake("inventory: incomplete or not pinned to candidate")
    entries = inventory["entries"]
    if type(entries) is not list or not 1 <= len(entries) <= 100000:
        raise InvalidIntake("inventory: missing or excessive source entries")
    required = {obj["path"]: obj["blob_sha"] for obj in c["source_objects"]}
    required[c["license"]["path"]] = c["license"]["blob_sha"]
    found, seen, by_path = set(), set(), {}
    for entry in entries:
        _record(entry, "inventory.entry", [
            "path", "sha", "kind", "mode", "size", "submodule", "symlink",
        ])
        path = _path(entry["path"], "inventory.path")
        _hex(entry["sha"], SHA1, "inventory.entry.sha")
        if type(entry["submodule"]) is not bool or type(entry["symlink"]) is not bool:
            raise InvalidIntake("inventory: source flags must be Boolean")
        lowered = path.casefold()
        if lowered in seen:
            raise InvalidIntake("inventory: duplicate/case-colliding source paths")
        seen.add(lowered)
        by_path[path] = (entry["kind"], entry["mode"])
        if entry["kind"] == "commit" or entry["mode"] in ("160000", "120000") or entry["submodule"] is True or entry["symlink"] is True:
            raise InvalidIntake("inventory: unresolved submodule or symlink source")
        if entry["kind"] not in ("tree", "blob") or entry["mode"] not in ("040000", "100644", "100755"):
            raise InvalidIntake("inventory: unsupported source object kind/mode")
        if entry["kind"] == "tree" and entry["mode"] != "040000":
            raise InvalidIntake("inventory: inconsistent tree mode")
        if entry["kind"] == "blob" and entry["mode"] == "040000":
            raise InvalidIntake("inventory: inconsistent blob mode")
        if entry["size"] is not None and (type(entry["size"]) is not int or entry["size"] < 0):
            raise InvalidIntake("inventory: invalid source object size")
        if entry["kind"] == "tree" and entry["size"] is not None:
            raise InvalidIntake("inventory: tree entry must not declare a blob size")
        if path in required:
            if entry["kind"] != "blob" or entry["sha"] != required[path]:
                raise InvalidIntake("inventory: pinned source blob mismatch")
            found.add(path)
    # A complete Git tree listing must contain the tree entries for every
    # nested source path. Reject orphaned blobs and a file posing as a parent.
    for path in by_path:
        parts = path.split("/")
        for depth in range(1, len(parts)):
            if by_path.get("/".join(parts[:depth])) != ("tree", "040000"):
                raise InvalidIntake("inventory: missing or non-tree source parent")
    if len(found) != len(required):
        raise InvalidIntake("inventory: missing required public source objects")
    return {"source_paths_verified": len(found), "complete_inventory": True,
            "license_approved": False, "runtime_tested": False}

def cache_key_with_inventory(candidate, build, inventory):
    """Cache identity only after a structurally complete pinned source inventory.

    Caller must independently establish the inventory came from trusted GitHub
    reads: matching JSON alone does not authenticate upstream source or license.
    """
    verify_complete_inventory(candidate, inventory)
    return cache_key(candidate, build)


def cache_key(candidate, build):
    """Stable across JSON key order, sensitive to source/toolchain/flag/dep drift."""
    c, b = checked_candidate(candidate), checked_build(build)
    # Sorting collections prevents accidental cache misses from enumeration order.
    normalized = {
        "schema": SCHEMA,
        "source": {k: c[k] for k in ("repository", "commit_sha", "root_tree_sha")},
        "objects": sorted(c["source_objects"], key=lambda x: x["path"]),
        "license_identity": {k: c["license"][k] for k in ("path", "blob_sha", "spdx")},
        "build": {**b, "dependency_pins": sorted(b["dependency_pins"], key=lambda x: x["repository"])},
    }
    wire = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return hashlib.sha256(b"HA-DONOR-REUSE-CACHE-V1\x00" + wire).hexdigest()


def verify_artifact(candidate, build, receipt, artifact_path):
    """Opt-in local file SHA-256 verification only. Never executes an artifact."""
    _record(receipt, "receipt", ["cache_key", "artifact_sha256", "artifact_size"])
    expected_key = cache_key(candidate, build)
    if receipt["cache_key"] != expected_key:
        raise InvalidIntake("receipt: source/build cache key mismatch")
    _hex(receipt["artifact_sha256"], SHA256, "receipt.artifact_sha256")
    if type(receipt["artifact_size"]) is not int or receipt["artifact_size"] < 0:
        raise InvalidIntake("receipt: invalid artifact size")
    path = Path(artifact_path)
    if path.is_symlink() or not path.is_file():
        raise InvalidIntake("receipt: artifact absent or symlink")
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > receipt["artifact_size"]:
                raise InvalidIntake("receipt: artifact larger than declared")
            digest.update(chunk)
    if size != receipt["artifact_size"] or digest.hexdigest() != receipt["artifact_sha256"]:
        raise InvalidIntake("receipt: actual artifact bytes differ")
    return {"artifact_identity_verified": True, "runtime_tested": False,
            "license_approved": False, "independently_accepted": False}


def verify_artifact_with_inventory(candidate, build, inventory, receipt, artifact_path):
    """Verify exact cached artifact bytes only after pinned source-tree validation.

    This performs offline structural checks, not remote GitHub attestation,
    independent license review, donor execution or runtime parity testing.
    The legacy verify command remains metadata-only for compatibility.
    """
    verify_complete_inventory(candidate, inventory)
    return verify_artifact(candidate, build, receipt, artifact_path)


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    arity = {"validate": 2, "inventory": 3, "key": 3, "verified-key": 4, "verify": 5, "verified-verify": 6}
    if not args or args[0] not in arity or len(args) != arity[args[0]]:
        raise SystemExit("usage: donor_cache_gate.py validate CANDIDATE.json | inventory CANDIDATE.json INVENTORY.json | key CANDIDATE.json BUILD.json | verified-key CANDIDATE.json BUILD.json INVENTORY.json | verify CANDIDATE.json BUILD.json RECEIPT.json ARTIFACT | verified-verify CANDIDATE.json BUILD.json INVENTORY.json RECEIPT.json ARTIFACT")
    with open(args[1], encoding="utf-8") as f:
        c = json.load(f)
    if args[0] == "validate":
        checked_candidate(c)
        print("PINNED_METADATA_VALID; NOT_BUILT; LICENSE_REVIEW_PENDING")
        return
    with open(args[2], encoding="utf-8") as f:
        b = json.load(f)
    if args[0] == "inventory":
        print(json.dumps(verify_complete_inventory(c, b), sort_keys=True))
        return
    if args[0] == "key":
        print(cache_key(c, b))
        return
    if args[0] == "verified-key":
        with open(args[3], encoding="utf-8") as stream:
            inventory = json.load(stream)
        print(cache_key_with_inventory(c, b, inventory))
        return
    if args[0] == "verified-verify":
        with open(args[3], encoding="utf-8") as stream:
            inventory = json.load(stream)
        with open(args[4], encoding="utf-8") as stream:
            receipt = json.load(stream)
        print(json.dumps(verify_artifact_with_inventory(c, b, inventory, receipt, args[5]), sort_keys=True))
        return
    with open(args[3], encoding="utf-8") as f:
        receipt = json.load(f)
    print(json.dumps(verify_artifact(c, b, receipt, args[4]), sort_keys=True))


if __name__ == "__main__":
    main()
