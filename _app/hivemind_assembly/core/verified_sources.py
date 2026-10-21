"""Host-verified source snapshots for rollback, kept for local and connected projects.

When a host comparison passes, the exact checked source files are retained as
content-addressed task artifacts. A worker can list them and restore a snapshot
through ordinary fenced ``write_file`` operations, so every restored file stays
individually reconcilable. Project compositions also keep the verified set of
recovered regions; the next project check reports a region from that set that no
longer passes as a regression and leaves it on original code.
"""

import hashlib
import json

from .common import ContractError, file_hash, scoped

CHECKED_TOOLS = (
    "validate_c_function",
    "compare_program",
    "compare_windows_program",
    "compare_linked_function",
    "compare_project",
)
KIND = "verified_source_snapshot"


def _normalized(raw):
    text = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(text.encode()).hexdigest()


class VerifiedSources:
    def __init__(self, store, artifacts):
        self.store = store
        self.artifacts = artifacts

    def retain(self, task, operation, tool, args, result, root):
        """Snapshot sources of a passing check; skip silently when they moved on."""
        if tool not in CHECKED_TOOLS or result.get("passed") is not True:
            return None
        expected = {}
        if tool == "validate_c_function":
            expected[args["candidate_path"]] = result.get("source_sha256")
        else:
            expected.update(result.get("source_hashes", result.get("sources", {})))
            if args.get("manifest_path"):
                expected[args["manifest_path"]] = None
        project = self.store.task(task)["project_id"]
        files = {}
        for name, digest in sorted(expected.items()):
            try:
                path = scoped(root, name)
                raw = path.read_bytes()
                if digest is not None and _normalized(raw) != digest:
                    raise ValueError
            except (OSError, UnicodeDecodeError, ValueError, ContractError):
                self.store.event(
                    task,
                    "verified_snapshot_skipped",
                    {"operation": operation, "path": name},
                )
                return None
            artifact = self.artifacts.add(raw, path.name, project)
            files[name] = {"sha256": hashlib.sha256(raw).hexdigest(), "artifact": artifact["id"]}
        if not files:
            return None
        snapshot = {"task": task, "tool": tool, "files": files}
        if tool == "compare_project":
            composition = result.get("composition", {})
            snapshot["composition"] = {
                "recovered": composition.get("recovered") or [],
                "fallback_count": len(composition.get("fallback") or []),
                "image_sha256": result.get("image_sha256"),
            }
        self.store.put(KIND, operation, snapshot)
        return snapshot

    def snapshots(self, task, limit=5):
        rows = self.store.rows(
            "SELECT id,payload FROM records WHERE kind=? ORDER BY rowid DESC", (KIND,)
        )
        found = []
        for row in rows:
            value = json.loads(row["payload"])
            if value.get("task") == task:
                found.append((row["id"], value))
                if len(found) >= limit:
                    break
        return found

    def last_composition(self, task):
        for _, value in self.snapshots(task, 50):
            if "composition" in value:
                return value["composition"]
        return None

    def listing(self, task, root, limit):
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ContractError("verified_sources limit must be 1–20")
        result = []
        for operation, value in self.snapshots(task, limit):
            files = {}
            for name, item in value["files"].items():
                path = scoped(root, name)
                files[name] = dict(item, current_sha256=file_hash(path) if path.exists() else None)
            entry = {
                "validation": operation,
                "tool": value["tool"],
                "files": files,
                "current": all(f["current_sha256"] == f["sha256"] for f in files.values()),
            }
            if "composition" in value:
                entry["composition"] = value["composition"]
            result.append(entry)
        return {
            "snapshots": result,
            "restore": "write_file each path with its artifact and its current_sha256 as expected_hash",
        }
