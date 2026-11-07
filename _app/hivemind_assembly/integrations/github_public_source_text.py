"""Explicit, hash-verified, bounded public-source text intake for donor review.

This does not mirror donor repositories or execute their code. It retrieves only
individually requested, inventory-pinned UTF-8 source files. Never use it for
private repositories, secrets, binaries, archives or automatic asset fetches.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
from urllib.parse import quote

from hivemind_assembly.core.common import Blocked, ContractError
from .github import GitHubHTTP
from .github_public_source_inventory import GitHubPublicSourceInventory


class GitHubPublicSourceText:
    """Review explicit source files at an inventory-pinned public Git revision."""

    MAX_FILE_BYTES = 256 * 1024
    MAX_BATCH_BYTES = 512 * 1024
    MAX_BATCH_FILES = 12
    SOURCE_SUFFIXES = frozenset({
        ".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx",
        ".rs", ".py", ".go", ".java", ".cs", ".zig", ".asm", ".s",
        ".js", ".ts", ".tsx", ".json", ".toml", ".yaml", ".yml",
        ".xml", ".md", ".txt", ".ini", ".cfg", ".cmake", ".sh",
        ".bat", ".cmd", ".ps1", ".gradle", ".m", ".mm", ".swift",
        ".patch", ".diff", ".rst", ".spdx", ".license", ".gitignore", ".gitattributes",
    })
    SOURCE_NAMES = frozenset({
        "license", "license.md", "license.txt", "license.mit", "copying",
        "copying.md", "copying.txt", "notice", "notice.md", "notice.txt",
        "readme", "makefile", "cmakelists.txt", "meson.build", "cargo.lock",
        ".gitmodules", "authors", "authors.md", "contributors", "contributors.md",
    })
    # Collect common extensionless/British-spelled license notices without
    # allowing arbitrary binary-looking LICENSE.* filenames as source text.
    _LICENSE_BARE_NAME = re.compile(
        r"^(?:license|licence|copying|notice|copyright|unlicense)"
        r"(?:-[a-z0-9][a-z0-9._-]{0,80})?$", re.IGNORECASE
    )
    FORBIDDEN_NAMES = frozenset({
        ".env", ".npmrc", ".pypirc", "id_rsa", "id_ed25519", "credentials",
        "credentials.json", "secrets.json", "secret.json", "config.private",
    })
    FORBIDDEN_SUFFIXES = (".key", ".pem", ".p12", ".pfx", ".keystore", ".jks", ".asc")

    def __init__(self, http=None):
        self.http = http or GitHubHTTP()

    @classmethod
    def _eligible(cls, entry):
        if not isinstance(entry, dict) or entry.get("kind") != "blob" or entry.get("mode") not in ("100644", "100755"):
            raise Blocked("Public source intake requires an ordinary pinned file blob")
        path = GitHubPublicSourceInventory._path(entry.get("path"))
        name = path.rsplit("/", 1)[-1].lower()
        if (any(name == bad or name.startswith(bad + ".") for bad in cls.FORBIDDEN_NAMES)
                or name.endswith(cls.FORBIDDEN_SUFFIXES)
                or any(segment.lower() in (".git", ".ssh", ".secrets") for segment in path.split("/"))
                or re.search(r"(?:^|[._-])(secret|password|token|credential|privatekey)(?:[._-]|$)", name)):
            raise Blocked("Source intake refuses credential or private-key material")
        if (name not in cls.SOURCE_NAMES
                and not any(name.endswith(s) for s in cls.SOURCE_SUFFIXES)
                and cls._LICENSE_BARE_NAME.fullmatch(name) is None):
            raise Blocked("Source intake refuses non-source, binary or archive filename")
        size = entry.get("size")
        if type(size) is not int or size < 0 or size > cls.MAX_FILE_BYTES:
            raise Blocked("Source intake requires known bounded source-file size")
        sha = entry.get("sha")
        if not GitHubPublicSourceInventory._sha(sha):
            raise Blocked("Source intake requires a valid pinned Git blob SHA")
        return path, sha.lower(), size

    @staticmethod
    def _pin(pin):
        if not isinstance(pin, dict):
            raise ContractError("Source text intake requires a public Git revision pin")
        repo = pin.get("repository")
        commit = pin.get("commit_sha")
        if not isinstance(repo, str) or repo.count("/") != 1 or not GitHubPublicSourceInventory._sha(commit):
            raise ContractError("Source text intake requires a pinned public repository commit")
        owner, name = (GitHubPublicSourceInventory._name(p) for p in repo.split("/"))
        return owner, name, commit.lower()

    def read(self, pin, entry):
        """Fetch one explicitly selected source file, validating path, size and Git SHA.

        Source and license candidates must be reviewed before downstream reuse.
        This does not follow submodule links, redirects or download URLs.
        """
        owner, repository, commit = self._pin(pin)
        path, expected_sha, expected_size = self._eligible(entry)
        escaped_path = "/".join(quote(s, safe="") for s in path.split("/"))
        payload = self.http.request(
            "GET", f"/repos/{owner}/{repository}/contents/{escaped_path}?ref={commit}", token=None
        )
        if (not isinstance(payload, dict) or payload.get("type") != "file"
                or payload.get("path") != path or not isinstance(payload.get("sha"), str)
                or payload["sha"].lower() != expected_sha
                or type(payload.get("size")) is not int or payload["size"] != expected_size
                or payload.get("encoding") != "base64"):
            raise Blocked("Public source response differs from the pinned Git object")
        encoded = payload.get("content")
        if not isinstance(encoded, str) or len(encoded) > ((expected_size + 2) // 3) * 4 + (expected_size // 48) * 2 + 16:
            raise Blocked("Public source response exceeds the encoded byte limit")
        try:
            raw = base64.b64decode(encoded.replace("\r", "").replace("\n", ""), validate=True)
        except (ValueError, binascii.Error):
            raise Blocked("Public source response has invalid base64 content") from None
        if len(raw) != expected_size:
            raise Blocked("Public source response has an inconsistent byte count")
        git_sha = hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()
        if git_sha != expected_sha:
            raise Blocked("Public source bytes do not match the pinned Git blob")
        try:
            source = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            raise Blocked("Public source file is not UTF-8 text") from None
        if any(ord(ch) == 0 or (ord(ch) < 32 and ch not in "\t\n\r") or ord(ch) == 127 for ch in source):
            raise Blocked("Public source content contains binary control characters")
        return {
            "repository": f"{owner}/{repository}", "commit_sha": commit,
            "path": path, "blob_sha": expected_sha, "sha256": hashlib.sha256(raw).hexdigest(),
            "size": len(raw), "text": source,
            "source_url": f"https://github.com/{owner}/{repository}/blob/{commit}/{escaped_path}",
            "license_review_required": True,
        }

    def selected_page(self, pin, entries, *, cursor=None, limit=4, byte_budget=256 * 1024):
        """Resumable selected page with an immutable selection/cursor fingerprint.

        Reusing a cursor with a different path, revision, order or size is
        rejected before any network calls. Entries are explicitly selected by
        the caller; no implicit file traversal, archive or submodule download.
        """
        owner, repository, commit = self._pin(pin)
        if (not isinstance(entries, (tuple, list)) or len(entries) > 512
                or type(limit) is not int or not 1 <= limit <= self.MAX_BATCH_FILES
                or type(byte_budget) is not int or not 1 <= byte_budget <= self.MAX_BATCH_BYTES):
            raise ContractError("Invalid bounded public source page parameters")
        selected = []
        seen = set()
        for entry in entries:
            path, blob_sha, size = self._eligible(entry)
            if path in seen:
                raise Blocked("Public source selection contains duplicate file paths")
            seen.add(path)
            selected.append((path, blob_sha, size))
        canonical = "\n".join(f"{path}\0{sha}\0{size}" for path, sha, size in selected)
        fingerprint = hashlib.sha256(
            (f"{owner}/{repository}\0{commit}\n" + canonical).encode("utf-8")
        ).hexdigest()
        if cursor is None:
            index = 0
        else:
            if (not isinstance(cursor, dict) or cursor.get("fingerprint") != fingerprint
                    or type(cursor.get("index")) is not int
                    or not 0 <= cursor["index"] <= len(entries)):
                raise Blocked("Public source resume cursor does not match selected revision and files")
            index = cursor["index"]
        result, used, offset = [], 0, index
        while offset < len(entries) and len(result) < limit:
            size = selected[offset][2]
            if size > byte_budget:
                raise Blocked("Selected source file exceeds the byte budget; select a larger bounded budget")
            if used + size > byte_budget:
                break
            result.append(self.read(pin, entries[offset]))
            used += size
            offset += 1
        return {"records": result, "next_cursor": (
                    {"index": offset, "fingerprint": fingerprint} if offset < len(entries) else None
                ), "selection_sha256": fingerprint,
                "complete": offset == len(entries), "bytes": used}

    def submodule_pins(self, pin, gitmodules_entry, gitlinks):
        """Map Gitlinks to HTTPS public GitHub remotes without cloning anything.

        The Gitlink SHA, not the mutable branch hint, is the revision to pin.
        Submodule content/license and nested dependencies remain unverified.
        """
        from configparser import ConfigParser, Error as ConfigError
        from urllib.parse import urlsplit

        owner, repository, commit = self._pin(pin)
        if not isinstance(gitlinks, (list, tuple)) or len(gitlinks) > 128:
            raise ContractError("Invalid bounded public Gitlink selection")
        indexed = {}
        for entry in gitlinks:
            if (not isinstance(entry, dict) or entry.get("kind") != "commit"
                    or entry.get("mode") != "160000"
                    or not GitHubPublicSourceInventory._sha(entry.get("sha"))):
                raise Blocked("Malformed public Git submodule gitlink")
            path = GitHubPublicSourceInventory._path(entry.get("path"))
            if path in indexed:
                raise Blocked("Duplicate public Git submodule gitlink")
            indexed[path] = entry["sha"].lower()
        if not indexed and gitmodules_entry is None:
            return {"repository": f"{owner}/{repository}", "commit_sha": commit,
                    "submodules": [], "complete_mapping": True, "content_verified": False}
        if gitmodules_entry is None or self._eligible(gitmodules_entry)[0] != ".gitmodules":
            raise Blocked("Public Gitlinks require pinned .gitmodules source text")
        source = self.read(pin, gitmodules_entry)
        if len(source["text"]) > 65536:
            raise Blocked("Public .gitmodules file exceeds parsing limits")
        config = ConfigParser(interpolation=None, strict=True)
        try:
            config.read_string(source["text"])
        except ConfigError:
            raise Blocked("Malformed public .gitmodules declaration") from None
        if len(config.sections()) > 128:
            raise Blocked("Public .gitmodules contains too many sections")
        resolved = []
        seen = set()
        for section in config.sections():
            if re.fullmatch(r'submodule "[^"\r\n]+"', section) is None:
                raise Blocked("Unrecognized public .gitmodules section")
            if not config.has_option(section, "path") or not config.has_option(section, "url"):
                raise Blocked("Incomplete public .gitmodules section")
            path = GitHubPublicSourceInventory._path(config.get(section, "path"))
            if path not in indexed or path in seen:
                raise Blocked("Public .gitmodules path does not match the pinned gitlinks")
            seen.add(path)
            url = config.get(section, "url")
            try:
                parsed = urlsplit(url)
                if (parsed.scheme != "https" or parsed.netloc != "github.com"
                        or parsed.query or parsed.fragment or parsed.username or parsed.password
                        or parsed.port is not None):
                    raise ValueError()
                parts = parsed.path.strip("/").split("/")
                if len(parts) != 2 or parsed.path.count("/") > 3:
                    raise ValueError()
                remote_owner = GitHubPublicSourceInventory._name(parts[0])
                remote_repo = GitHubPublicSourceInventory._name(
                    parts[1][:-4] if parts[1].endswith(".git") else parts[1]
                )
            except (ValueError, ContractError):
                raise Blocked("Public submodule URL is not an approved GitHub HTTPS repository") from None
            resolved.append({
                "path": path, "repository": f"{remote_owner}/{remote_repo}",
                "commit_sha": indexed[path], "source_url":
                    f"https://github.com/{remote_owner}/{remote_repo}/tree/{indexed[path]}",
                "content_verified": False, "license_review_required": True,
            })
        if seen != set(indexed):
            raise Blocked("Public gitlinks and .gitmodules are not a complete matching set")
        return {"repository": f"{owner}/{repository}", "commit_sha": commit,
                "gitmodules_sha256": source["sha256"], "submodules": resolved,
                "complete_mapping": True, "content_verified": False}
