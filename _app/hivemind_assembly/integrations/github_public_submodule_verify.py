"""Bounded, immutable public Gitlink commit verification without source downloads.

Consume a complete mapping from GitHubPublicSourceText.submodule_pins(). The
mapping is not itself evidence that any remote commit still exists or is public.
This adapter verifies that identity against the public GitHub commit API. It
never fetches blob contents, executes donor code or follows archive redirects.
"""

from __future__ import annotations

import hashlib
import re

from hivemind_assembly.core.common import Blocked, ContractError
from .github_public_source_inventory import GitHubPublicSourceInventory
from .github_public_source_text import GitHubPublicSourceText


class GitHubPublicSubmoduleVerify:
    """Resumable public Gitlink verification; metadata only, no model/API keys."""

    MAX_SUBMODULES = 128
    MAX_PAGE = 8

    def __init__(self, http=None):
        self.inventory = GitHubPublicSourceInventory(http=http)

    @staticmethod
    def _mapping(mapping):
        if (not isinstance(mapping, dict)
                or mapping.get("complete_mapping") is not True
                or mapping.get("content_verified") is not False):
            raise ContractError("Submodule verification requires a complete unverified Gitlink mapping")
        parent = mapping.get("repository")
        parent_commit = mapping.get("commit_sha")
        if (not isinstance(parent, str) or parent.count("/") != 1
                or not GitHubPublicSourceInventory._sha(parent_commit)):
            raise ContractError("Submodule verification requires a pinned parent revision")
        parent_owner, parent_repo = (
            GitHubPublicSourceInventory._name(part) for part in parent.split("/")
        )
        gitmodules_sha256 = mapping.get("gitmodules_sha256")
        records = mapping.get("submodules")
        if not isinstance(records, list) or len(records) > GitHubPublicSubmoduleVerify.MAX_SUBMODULES:
            raise ContractError("Submodule verification requires a bounded Gitlink selection")
        if records and (not isinstance(gitmodules_sha256, str)
                        or re.fullmatch(r"[a-fA-F0-9]{64}", gitmodules_sha256) is None):
            raise Blocked("Submodule mapping lacks a verified .gitmodules digest")
        if not records and gitmodules_sha256 is not None and (
                not isinstance(gitmodules_sha256, str)
                or re.fullmatch(r"[a-fA-F0-9]{64}", gitmodules_sha256) is None):
            raise Blocked("Submodule mapping has an invalid .gitmodules digest")
        selected = []
        seen_paths = set()
        for item in records:
            if not isinstance(item, dict) or item.get("content_verified") is not False:
                raise Blocked("Public Gitlink mapping contains an unverified or malformed entry")
            path = GitHubPublicSourceInventory._path(item.get("path"))
            repo = item.get("repository")
            sha = item.get("commit_sha")
            if (not isinstance(repo, str) or repo.count("/") != 1
                    or not GitHubPublicSourceInventory._sha(sha)):
                raise Blocked("Public Gitlink mapping has an invalid remote or revision")
            remote_owner, remote_repo = (
                GitHubPublicSourceInventory._name(part) for part in repo.split("/")
            )
            remote = f"{remote_owner}/{remote_repo}"
            commit = sha.lower()
            expected_url = f"https://github.com/{remote}/tree/{commit}"
            if (path in seen_paths or item.get("source_url") != expected_url):
                raise Blocked("Public Gitlink mapping has duplicate paths or conflicting source URL")
            seen_paths.add(path)
            selected.append((path, remote, commit))
        canonical = "\n".join(f"{path}\0{repo}\0{sha}" for path, repo, sha in selected)
        fingerprint = hashlib.sha256(
            (f"{parent_owner}/{parent_repo}\0{parent_commit.lower()}\0{gitmodules_sha256 or ''}\n" + canonical).encode("utf-8")
        ).hexdigest()
        return f"{parent_owner}/{parent_repo}", parent_commit.lower(), selected, fingerprint

    def _verify_parent_mapping(self, mapping, parent, parent_sha, selected):
        """Bind the supplied Gitlinks and URLs to the actual pinned parent tree.

        The one explicitly allowed source-text read is pinned `.gitmodules`;
        all other operations read public Git commit/tree metadata only.
        """
        owner, repository = parent.split("/")
        pin = self.inventory.pin(owner, repository, ref=parent_sha)
        if pin.get("commit_sha") != parent_sha:
            raise Blocked("Parent public commit differs from the pinned mapping")
        manifest = self.inventory.fast_manifest(pin)
        if manifest.get("complete") is not True:
            raise Blocked("Public parent Git tree inventory is incomplete")
        records = manifest.get("entries")
        if not isinstance(records, list):
            raise Blocked("Public parent Git tree is malformed")
        gitlinks = [item for item in records if item.get("submodule") is True]
        gitmodules = [item for item in records if item.get("path") == ".gitmodules"]
        if len(gitmodules) > 1 or len(gitlinks) > self.MAX_SUBMODULES:
            raise Blocked("Public parent Git tree contains inconsistent submodule metadata")
        module_entry = gitmodules[0] if gitmodules else None
        canonical = GitHubPublicSourceText(http=self.inventory.http).submodule_pins(
            pin, module_entry, gitlinks
        )
        expected = {(p, r, s) for p, r, s in selected}
        actual = {(item["path"], item["repository"], item["commit_sha"])
                  for item in canonical["submodules"]}
        if (len(expected) != len(selected) or expected != actual
                or canonical.get("gitmodules_sha256") != mapping.get("gitmodules_sha256")):
            raise Blocked("Public Gitlink mapping does not match the pinned parent source")
        return canonical.get("gitmodules_sha256")

    def page(self, mapping, *, cursor=None, limit=4):
        """Verify at most eight mapped public commit identities per invocation.

        gitlink_commit_verified means the remote public commit and its root
        Git tree were read at the exact Gitlink SHA. No blob bytes, recursive
        submodules, upstream license text or runtime behavior are verified.
        """
        parent, parent_commit, selected, fingerprint = self._mapping(mapping)
        if type(limit) is not int or not 1 <= limit <= self.MAX_PAGE:
            raise ContractError("Public submodule verification page limit must be 1..8")
        if cursor is None:
            offset = 0
        elif (isinstance(cursor, dict) and cursor.get("fingerprint") == fingerprint
              and type(cursor.get("index")) is int
              and 0 <= cursor["index"] <= len(selected)):
            offset = cursor["index"]
        else:
            raise Blocked("Submodule verification cursor is stale or inconsistent")
        parent_gitmodules_sha = self._verify_parent_mapping(
            mapping, parent, parent_commit, selected
        )
        verified = []
        for path, remote, sha in selected[offset:offset + limit]:
            owner, repo = remote.split("/")
            pinned = self.inventory.pin(owner, repo, ref=sha)
            if pinned.get("commit_sha") != sha or not GitHubPublicSourceInventory._sha(pinned.get("root_tree_sha")):
                raise Blocked("Public submodule commit differs from the pinned Gitlink")
            verified.append({
                "gitlink_path": path,
                "repository": remote,
                "commit_sha": sha,
                "root_tree_sha": pinned["root_tree_sha"],
                "source_url": f"https://github.com/{remote}/tree/{sha}",
                "license_spdx_metadata": pinned.get("license_spdx_metadata"),
                "gitlink_commit_verified": True,
                "parent_gitlink_mapping_verified": True,
                "source_bytes_verified": False,
                "full_tree_inventory_verified": False,
                "nested_submodules_verified": False,
                "license_text_verified": False,
            })
        next_index = offset + len(verified)
        return {
            "parent_repository": parent,
            "parent_commit_sha": parent_commit,
            "selection_sha256": fingerprint,
            "records": verified,
            "complete": next_index == len(selected),
            "next_cursor": (None if next_index == len(selected)
                            else {"index": next_index, "fingerprint": fingerprint}),
            "verified_count": len(verified),
            "parent_gitmodules_sha256": parent_gitmodules_sha,
            "parent_gitmodules_text_verified": parent_gitmodules_sha is not None,
            "max_public_requests": 4 + 2 * len(verified),
            "donor_binary_or_archive_fetched": False,
        }
