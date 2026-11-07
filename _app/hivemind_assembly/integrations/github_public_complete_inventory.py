"""Bounded complete metadata inventory for pinned public Git repositories.

Fast recursive listings are accepted only when GitHub confirms completeness.
A truncated listing is rebuilt from immutable non-recursive Git trees with a
page/entry/request ceiling. No source bytes, archives or submodules are fetched.
"""

from __future__ import annotations

from hivemind_assembly.core.common import Blocked, ContractError
from .github_public_source_inventory import GitHubPublicSourceInventory


class GitHubPublicCompleteInventory:
    """Verify a complete, bounded Git-object listing, not source-file acquisition."""

    MAX_PAGES = 64
    MAX_ENTRIES = 30000
    _INCOMPLETE = "Recursive public source listing is incomplete; use pinned paginated traversal"
    _TYPES = {
        ("tree", "040000"), ("blob", "100644"), ("blob", "100755"),
        ("blob", "120000"), ("commit", "160000"),
    }

    def __init__(self, inventory=None):
        self.inventory = inventory if inventory is not None else GitHubPublicSourceInventory()

    @classmethod
    def _validate(cls, pin, entries):
        if not isinstance(pin, dict) or not isinstance(entries, list) or len(entries) > cls.MAX_ENTRIES:
            raise Blocked("Complete public inventory has invalid pin or entry count")
        paths = {}
        for item in entries:
            if not isinstance(item, dict):
                raise Blocked("Complete public inventory has malformed object")
            path = GitHubPublicSourceInventory._path(item.get("path"))
            if path in paths or not GitHubPublicSourceInventory._sha(item.get("sha")):
                raise Blocked("Complete public inventory has duplicate path or invalid Git object")
            kind, mode = item.get("kind"), item.get("mode")
            if ((kind, mode) not in cls._TYPES
                    or item.get("submodule") is not (kind == "commit")
                    or item.get("symlink") is not (mode == "120000")):
                raise Blocked("Complete public inventory has contradictory Git object metadata")
            size = item.get("size")
            if size is not None and (type(size) is not int or size < 0):
                raise Blocked("Complete public inventory has invalid object size")
            paths[path] = kind
        for path in paths:
            parent = path.rpartition("/")[0]
            if parent and paths.get(parent) != "tree":
                raise Blocked("Complete public inventory has missing or non-tree ancestor")

    def manifest(self, pin, *, max_pages=64, max_entries=30000, page_limit=500, max_requests=48):
        """Complete only if fast Git tree or all bounded pinned DFS pages agree.

        The caller must separately review source bytes, gitlinks and licensing.
        A page ceiling fails closed; it never returns a partial inventory marked
        complete. The returned request count includes the initial fast attempt.
        """
        if (type(max_pages) is not int or not 1 <= max_pages <= self.MAX_PAGES
                or type(max_entries) is not int or not 1 <= max_entries <= self.MAX_ENTRIES
                or type(page_limit) is not int or not 1 <= page_limit <= 500
                or type(max_requests) is not int or not 1 <= max_requests <= 48):
            raise ContractError("Invalid bounded complete public inventory parameters")
        fast_requests = 1
        try:
            fast = self.inventory.fast_manifest(pin)
        except Blocked as error:
            if str(error) != self._INCOMPLETE:
                raise
        else:
            if (fast.get("complete") is not True or fast.get("next_cursor") is not None
                    or fast.get("repository") != pin.get("repository")
                    or fast.get("commit_sha") != pin.get("commit_sha")
                    or fast.get("root_tree_sha") != pin.get("root_tree_sha")):
                raise Blocked("Fast public source inventory pin or completeness mismatch")
            entries = fast.get("entries")
            self._validate(pin, entries)
            if len(entries) > max_entries:
                raise Blocked("Complete public inventory exceeds entry budget")
            return {**fast, "method": "verified_recursive_tree", "requests": fast_requests,
                    "source_bytes_verified": False, "submodule_bytes_verified": False}

        cursor = None
        entries = []
        requests = fast_requests
        for _ in range(max_pages):
            page = self.inventory.page(pin, cursor, limit=page_limit, max_requests=max_requests)
            if (not isinstance(page, dict)
                    or page.get("repository") != pin.get("repository")
                    or page.get("commit_sha") != pin.get("commit_sha")
                    or page.get("root_tree_sha") != pin.get("root_tree_sha")
                    or type(page.get("requests")) is not int
                    or not 0 <= page["requests"] <= max_requests
                    or not isinstance(page.get("entries"), list)
                    or len(page["entries"]) > page_limit):
                raise Blocked("Paginated public source listing has inconsistent identity or bounds")
            requests += page["requests"]
            entries.extend(page["entries"])
            if len(entries) > max_entries:
                raise Blocked("Complete public inventory exceeds entry budget")
            complete = page.get("complete")
            successor = page.get("next_cursor")
            if type(complete) is not bool or (complete is True) != (successor is None):
                raise Blocked("Paginated public source listing has contradictory completion state")
            if complete:
                self._validate(pin, entries)
                return {
                    "repository": pin["repository"], "commit_sha": pin["commit_sha"],
                    "root_tree_sha": pin["root_tree_sha"], "entries": entries,
                    "complete": True, "next_cursor": None, "requests": requests,
                    "method": "verified_pinned_tree_pages", "source_bytes_verified": False,
                    "submodule_bytes_verified": False,
                }
            if not isinstance(successor, dict) or successor == cursor or not page["entries"]:
                raise Blocked("Paginated public source listing made no verifiable progress")
            cursor = successor
        raise Blocked("Complete public source traversal exceeds the page budget")
