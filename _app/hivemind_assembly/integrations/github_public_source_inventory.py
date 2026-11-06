"""Read-only pinned public GitHub source-tree inventory and provenance.

Never fetches file/blob bytes, runs donor code, or uses an authenticated
repository connection. All entries are evidence until independently reviewed;
Git submodule refs do not include submodule content or license grants.
"""

from __future__ import annotations

import re

from hivemind_assembly.core.common import Blocked, ContractError
from .github import GitHubHTTP


class GitHubPublicSourceInventory:
    """Read-only, pinned public Git tree inventory; never downloads file bytes.

    Each page contains Git object IDs and paths only. Save next_cursor and
    repeat with the same pin to resume. A page is not a complete inventory
    until complete is true. Submodule gitlinks are *references*, not content.
    """

    MAX_TREE_ITEMS = 10000
    MAX_PATH = 1024
    MAX_DEPTH = 40

    def __init__(self, http=None):
        self.http = http or GitHubHTTP()

    @staticmethod
    def _sha(value):
        return isinstance(value, str) and re.fullmatch(r"[a-fA-F0-9]{40}", value) is not None

    @staticmethod
    def _name(value, *, ref=False):
        if not isinstance(value, str) or not 1 <= len(value) <= (200 if ref else 100):
            raise ContractError("Invalid public GitHub repository/ref name")
        if not re.fullmatch(r"[A-Za-z0-9_.\-/]+" if ref else r"[A-Za-z0-9_.-]+", value):
            raise ContractError("Invalid public GitHub repository/ref name")
        if value.startswith((".", "-", "/")) or ".." in value or "//" in value or value.endswith(("/", ".")):
            raise ContractError("Invalid public GitHub repository/ref name")
        return value

    @classmethod
    def _path(cls, path):
        if (not isinstance(path, str) or not 1 <= len(path) <= cls.MAX_PATH
                or any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in path)
                or "\\" in path or any(p in ("", ".", "..") for p in path.split("/"))):
            raise Blocked("Public GitHub tree has malformed source path")
        return path

    def pin(self, owner, repository, ref=None):
        """Resolve the public donor ref once to immutable commit/tree SHAs."""
        from urllib.parse import quote

        owner = self._name(owner)
        repository = self._name(repository)
        base = f"/repos/{owner}/{repository}"
        metadata = self.http.request("GET", base, token=None)
        if metadata.get("private") is not False or metadata.get("visibility", "public") != "public":
            raise Blocked("Public source intake cannot inspect private repositories")
        branch = self._name(ref if ref is not None else metadata.get("default_branch"), ref=True)
        commit = self.http.request("GET", base + "/commits/" + quote(branch, safe=""), token=None)
        commit_sha = commit.get("sha")
        tree = commit.get("commit", {}).get("tree", {}).get("sha")
        if not self._sha(commit_sha) or not self._sha(tree):
            raise Blocked("Public GitHub revision has an invalid commit/tree identity")
        license_metadata = metadata.get("license")
        spdx = license_metadata.get("spdx_id") if isinstance(license_metadata, dict) else None
        return {
            "repository": f"{owner}/{repository}",
            "requested_ref": branch,
            "commit_sha": commit_sha.lower(),
            "root_tree_sha": tree.lower(),
            "license_spdx_metadata": spdx if isinstance(spdx, str) else None,
            "license_text_verified": False,
            "source_url": f"https://github.com/{owner}/{repository}/tree/{commit_sha.lower()}",
        }

    def fast_manifest(self, pin):
        """One-request complete inventory when GitHub confirms no truncation.

        If GitHub truncates the recursive view, refuse the completeness claim;
        use page() with the same pin to traverse individual Git trees instead.
        """
        if (not isinstance(pin, dict) or not self._sha(pin.get("commit_sha"))
                or not self._sha(pin.get("root_tree_sha"))):
            raise ContractError("Public source inventory requires a pinned commit and tree")
        repo = pin.get("repository")
        if not isinstance(repo, str) or repo.count("/") != 1:
            raise ContractError("Public source inventory requires a repository")
        owner, name = (self._name(part) for part in repo.split("/"))
        sha = pin["root_tree_sha"].lower()
        payload = self.http.request(
            "GET", f"/repos/{owner}/{name}/git/trees/{sha}?recursive=1", token=None
        )
        tree = payload.get("tree")
        if (payload.get("truncated") is not False or not self._sha(payload.get("sha"))
                or payload["sha"].lower() != sha or not isinstance(tree, list)
                or len(tree) > self.MAX_TREE_ITEMS):
            raise Blocked("Recursive public source listing is incomplete; use pinned paginated traversal")
        entries = []
        for item in tree:
            if not isinstance(item, dict) or not self._sha(item.get("sha")):
                raise Blocked("Public GitHub tree has invalid object identity")
            path = self._path(item.get("path"))
            kind, mode = item.get("type"), item.get("mode")
            if (kind, mode) not in {
                ("tree", "040000"), ("blob", "100644"), ("blob", "100755"),
                ("blob", "120000"), ("commit", "160000"),
            }:
                raise Blocked("Public GitHub tree has unexpected object type or mode")
            size = item.get("size")
            if size is not None and (type(size) is not int or size < 0):
                raise Blocked("Public GitHub tree has invalid blob size")
            entries.append({
                "path": path, "sha": item["sha"].lower(), "kind": kind,
                "mode": mode, "size": size, "submodule": kind == "commit",
                "symlink": mode == "120000",
            })
        return {
            "repository": f"{owner}/{name}", "commit_sha": pin["commit_sha"].lower(),
            "root_tree_sha": sha, "entries": entries, "complete": True,
            "next_cursor": None, "requests": 1,
        }

    @classmethod
    def _validate_cursor_chain(cls, frames, cache):
        """Verify resumed DFS ancestry against actual pinned parent Git trees.

        The client-controlled cursor cannot invent a child tree SHA or path.
        Indexes still describe a caller-provided traversal offset, not an
        independently certified full-inventory receipt.
        """
        for depth, parent in enumerate(frames[:-1]):
            children = cache[parent["sha"]]
            previous_index = parent["index"] - 1
            if previous_index < 0 or previous_index >= len(children):
                raise Blocked("Public source inventory cursor has invalid parent offset")
            record = children[previous_index]
            child = frames[depth + 1]
            if not isinstance(record, dict):
                raise Blocked("Public source inventory cursor has malformed ancestor")
            part = record.get("path")
            if not isinstance(part, str) or "/" in part:
                raise Blocked("Public source inventory cursor has malformed ancestor")
            expected_path = cls._path(parent["path"] + "/" + part if parent["path"] else part)
            if (record.get("type") != "tree" or record.get("mode") != "040000"
                    or not isinstance(record.get("sha"), str)
                    or record["sha"].lower() != child["sha"]
                    or expected_path != child["path"]):
                raise Blocked("Public source inventory cursor ancestry differs from pinned tree")

    def page(self, pin, cursor=None, *, limit=200, max_requests=12):
        """Enumerate a deterministic bounded DFS page of pinned Git objects.

        Non-recursive trees avoid GitHub's silent truncation of recursive trees.
        Unknown modes, truncated API responses, invalid paths and identity drift
        are fatal rather than grounds to declare the source completely acquired.
        """
        from urllib.parse import quote

        if type(limit) is not int or not 1 <= limit <= 500:
            raise ContractError("Public source inventory page limit must be 1..500")
        if type(max_requests) is not int or not 1 <= max_requests <= 48:
            raise ContractError("Public source inventory request limit must be 1..48")
        if not isinstance(pin, dict) or not self._sha(pin.get("commit_sha")) or not self._sha(pin.get("root_tree_sha")):
            raise ContractError("Public source inventory requires a pinned commit and tree")
        repo = pin.get("repository")
        if not isinstance(repo, str) or repo.count("/") != 1:
            raise ContractError("Public source inventory requires a repository")
        owner, name = (self._name(part) for part in repo.split("/"))
        root = pin["root_tree_sha"].lower()
        commit = pin["commit_sha"].lower()
        if cursor is None:
            frames = [{"path": "", "sha": root, "index": 0}]
        else:
            if (not isinstance(cursor, dict) or cursor.get("commit_sha") != commit
                    or cursor.get("root_tree_sha") != root):
                raise Blocked("Public source inventory cursor does not match the pinned revision")
            raw = cursor.get("frames")
            if not isinstance(raw, list) or not 1 <= len(raw) <= self.MAX_DEPTH:
                raise Blocked("Public source inventory has an invalid resume cursor")
            frames = []
            for item in raw:
                if (not isinstance(item, dict) or not self._sha(item.get("sha"))
                        or type(item.get("index")) is not int or not 0 <= item["index"] <= self.MAX_TREE_ITEMS
                        or not isinstance(item.get("path"), str)):
                    raise Blocked("Public source inventory has an invalid resume cursor")
                if item["path"]:
                    self._path(item["path"])
                frames.append({"path": item["path"], "sha": item["sha"].lower(), "index": item["index"]})
            if frames[0]["path"] != "" or frames[0]["sha"] != root:
                raise Blocked("Public source inventory cursor root differs from the pin")
        entries = []
        cache = {}
        requests = 0
        if cursor is not None and len(frames) > 1:
            # Check the full ancestor chain before emitting records. A forged
            # cursor may name a valid but unrelated tree in the same repository.
            # This bounded revalidation consumes request budget on resume.
            if len(frames) > max_requests:
                raise Blocked("Public source inventory cursor ancestry exceeds the request budget; raise max_requests")
            for ancestor in frames[:-1]:
                sha = ancestor["sha"]
                if sha in cache:
                    continue
                payload = self.http.request(
                    "GET", f"/repos/{owner}/{name}/git/trees/{quote(sha, safe='')}", token=None
                )
                requests += 1
                tree = payload.get("tree")
                if (payload.get("truncated") is not False or not self._sha(payload.get("sha"))
                        or payload["sha"].lower() != sha or not isinstance(tree, list)
                        or len(tree) > self.MAX_TREE_ITEMS):
                    raise Blocked("Public GitHub ancestor tree is truncated or inconsistent")
                cache[sha] = tree
            self._validate_cursor_chain(frames, cache)
        while frames and len(entries) < limit:
            frame = frames[-1]
            sha = frame["sha"]
            if sha not in cache:
                if requests == max_requests:
                    break
                payload = self.http.request(
                    "GET", f"/repos/{owner}/{name}/git/trees/{quote(sha, safe='')}", token=None
                )
                requests += 1
                tree = payload.get("tree")
                if (payload.get("truncated") is not False or not self._sha(payload.get("sha"))
                        or payload["sha"].lower() != sha or not isinstance(tree, list)
                        or len(tree) > self.MAX_TREE_ITEMS):
                    raise Blocked("Public GitHub tree response is truncated or inconsistent")
                cache[sha] = tree
            tree = cache[sha]
            if frame["index"] >= len(tree):
                if frame["index"] != len(tree):
                    raise Blocked("Public source inventory cursor exceeds the tree")
                frames.pop()
                continue
            record = tree[frame["index"]]
            frame["index"] += 1
            if not isinstance(record, dict) or not self._sha(record.get("sha")):
                raise Blocked("Public GitHub tree has invalid object identity")
            part = record.get("path")
            if not isinstance(part, str) or "/" in part:
                raise Blocked("Public GitHub tree has malformed source path")
            path = self._path(frame["path"] + "/" + part if frame["path"] else part)
            kind, mode = record.get("type"), record.get("mode")
            if (kind, mode) not in {
                ("tree", "040000"), ("blob", "100644"), ("blob", "100755"),
                ("blob", "120000"), ("commit", "160000"),
            }:
                raise Blocked("Public GitHub tree has unexpected object type or mode")
            if kind == "tree" and len(frames) >= self.MAX_DEPTH:
                raise Blocked("Public GitHub source tree exceeds the traversal depth limit")
            size = record.get("size")
            if size is not None and (type(size) is not int or size < 0):
                raise Blocked("Public GitHub tree has invalid blob size")
            entries.append({
                "path": path, "sha": record["sha"].lower(), "kind": kind,
                "mode": mode, "size": size,
                "submodule": kind == "commit", "symlink": mode == "120000",
            })
            if kind == "tree":
                frames.append({"path": path, "sha": record["sha"].lower(), "index": 0})
        next_cursor = ({"commit_sha": commit, "root_tree_sha": root, "frames": frames}
                       if frames else None)
        return {
            "repository": f"{owner}/{name}", "commit_sha": commit,
            "root_tree_sha": root, "entries": entries,
            "complete": next_cursor is None,
            "next_cursor": next_cursor, "requests": requests,
        }
