"""Bounded, public, immutable license/notice source evidence for donor intake.

This reads explicit UTF-8 text at pinned Git blob SHAs, never clones a repository,
fetches donor binaries, or grants a license to copy/reuse third-party source.
License text identity is distinct from a legal/provenance assessment.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import quote

from hivemind_assembly.core.common import Blocked, ContractError
from .github_public_complete_inventory import GitHubPublicCompleteInventory
from .github_public_source_inventory import GitHubPublicSourceInventory
from .github_public_source_text import GitHubPublicSourceText


class GitHubPublicLicenseEvidence:
    """Inventory and read back explicitly selected pinned donor license text."""

    MAX_CANDIDATES = 2048
    MAX_SELECTED = 12
    MAX_TOTAL_BYTES = 512 * 1024
    _LICENSE_NAME = re.compile(
        r"^(license|licence|copying|notice|third[-_.]?party[-_.]?(?:licenses?|notices?))"
        r"(?:[._-](?:[a-z0-9][a-z0-9._-]{0,80}))?$", re.IGNORECASE
    )

    def __init__(self, *, inventory=None, source=None, complete=None):
        self.inventory = inventory if inventory is not None else GitHubPublicSourceInventory()
        self.source = source if source is not None else GitHubPublicSourceText(http=self.inventory.http)
        self.complete = complete if complete is not None else GitHubPublicCompleteInventory(self.inventory)

    def _manifest(self, pin):
        """Reconfirm a caller-supplied commit/tree pin against public GitHub."""
        if not isinstance(pin, dict):
            raise ContractError("License evidence requires an immutable public Git pin")
        repository, commit, root = (pin.get(k) for k in ("repository", "commit_sha", "root_tree_sha"))
        if (not isinstance(repository, str) or repository.count("/") != 1
                or not GitHubPublicSourceInventory._sha(commit)
                or not GitHubPublicSourceInventory._sha(root)):
            raise ContractError("License evidence requires pinned public commit/tree identities")
        owner, name = (GitHubPublicSourceInventory._name(s) for s in repository.split("/"))
        canonical_repo = f"{owner}/{name}"
        verified = self.inventory.pin(owner, name, ref=commit.lower())
        if (verified.get("repository") != canonical_repo
                or verified.get("commit_sha") != commit.lower()
                or verified.get("root_tree_sha") != root.lower()):
            raise Blocked("Donor license evidence pin differs from public GitHub commit")
        canonical_pin = {**verified, "commit_sha": commit.lower(), "root_tree_sha": root.lower()}
        manifest = self.complete.manifest(canonical_pin)
        if (manifest.get("complete") is not True
                or manifest.get("repository") != canonical_repo
                or manifest.get("commit_sha") != commit.lower()
                or manifest.get("root_tree_sha") != root.lower()):
            raise Blocked("Donor license evidence has an incomplete or inconsistent Git inventory")
        entries = manifest.get("entries")
        GitHubPublicCompleteInventory._validate(canonical_pin, entries)
        return canonical_pin, entries

    @classmethod
    def _candidates(cls, entries):
        result = []
        for entry in entries:
            if entry.get("kind") != "blob" or entry.get("mode") not in ("100644", "100755"):
                continue
            path = entry["path"]
            basename = path.rsplit("/", 1)[-1]
            if cls._LICENSE_NAME.fullmatch(basename) is None:
                continue
            try:
                GitHubPublicSourceText._eligible(entry)
            except Blocked:
                # A license-looking binary, secret or giant blob is not fetched.
                continue
            result.append({"path": path, "sha": entry["sha"], "size": entry["size"],
                           "scope": "repository_root" if "/" not in path else "nested_dependency"})
            if len(result) > cls.MAX_CANDIDATES:
                raise Blocked("Public donor license candidates exceed the bounded inventory")
        return sorted(result, key=lambda item: item["path"])

    def candidates(self, pin):
        """Metadata only. Missing files do not establish absence of obligations."""
        verified, entries = self._manifest(pin)
        candidates = self._candidates(entries)
        return {"repository": verified["repository"], "commit_sha": verified["commit_sha"],
                "root_tree_sha": verified["root_tree_sha"], "candidates": candidates,
                "candidate_count": len(candidates), "complete_git_tree_metadata": True,
                "license_text_verified": False, "reuse_permission_established": False}

    def attest(self, pin, selected_paths, *, byte_budget=MAX_TOTAL_BYTES):
        """Return selected inline text and pinned SHA-256 receipts for human review.

        Every selection must appear in a newly verified complete source inventory.
        This is byte identity verification, not SPDX identification or legal approval.
        """
        if (not isinstance(selected_paths, (list, tuple))
                or not 1 <= len(selected_paths) <= self.MAX_SELECTED
                or type(byte_budget) is not int or not 1 <= byte_budget <= self.MAX_TOTAL_BYTES):
            raise ContractError("License evidence requires a bounded explicit text selection")
        verified, entries = self._manifest(pin)
        candidates = {item["path"]: item for item in self._candidates(entries)}
        files = {entry["path"]: entry for entry in entries}
        seen, wanted = set(), []
        size_total = 0
        for path in selected_paths:
            if not isinstance(path, str) or path not in candidates or path in seen:
                raise Blocked("License evidence selection is duplicate or not a verified text candidate")
            seen.add(path)
            entry = files[path]
            size_total += entry["size"]
            if size_total > byte_budget:
                raise Blocked("License evidence selection exceeds byte budget before source reads")
            wanted.append(entry)
        records = []
        for entry in wanted:
            read = self.source.read(verified, entry)
            text = read.get("text") if isinstance(read, dict) else None
            if not isinstance(text, str):
                raise Blocked("License source reader did not produce inline UTF-8 text")
            raw = text.encode("utf-8")
            path = entry["path"]
            escaped = "/".join(quote(s, safe="") for s in path.split("/"))
            expected_url = (f"https://github.com/{verified['repository']}/blob/"
                            f"{verified['commit_sha']}/{escaped}")
            if (read.get("repository") != verified["repository"]
                    or read.get("commit_sha") != verified["commit_sha"]
                    or read.get("path") != path or read.get("blob_sha") != entry["sha"]
                    or read.get("source_url") != expected_url
                    or read.get("size") != len(raw) or len(raw) != entry["size"]
                    or read.get("sha256") != hashlib.sha256(raw).hexdigest()):
                raise Blocked("License text receipt differs from pinned Git content")
            records.append({"path": path, "blob_sha": entry["sha"],
                            "sha256": read["sha256"], "size": len(raw),
                            "source_url": expected_url, "text": text,
                            "license_text_byte_verified": True,
                            "license_terms_reviewed": False})
        return {"repository": verified["repository"], "commit_sha": verified["commit_sha"],
                "root_tree_sha": verified["root_tree_sha"], "candidate_count": len(candidates),
                "selected_count": len(records), "remaining_candidates": len(candidates) - len(records),
                "records": records, "bytes": size_total, "reuse_permission_established": False,
                "nested_submodules_verified": False, "runtime_verified": False}
