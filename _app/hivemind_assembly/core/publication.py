"""Incremental, verified source checkpoints in the project's private repository.

No repository is required for local execution. Published files come from a
host-recorded successful check, not a worker's claimed test result. No force push,
remote deletions, arbitrary paths, binaries or private runtime-state uploads.
"""

import base64
import hashlib
import json
import re
from pathlib import PurePosixPath
from urllib.parse import quote
from .common import Blocked, Conflict, ContractError, scoped, canonical, digest, uid


class Publications:
    def __init__(self, repositories):
        self.repositories = repositories
        self.store = repositories.store

    def enabled(self, project):
        return (
            self.repositories.config.get("github", {}).get(
                "automatic_checkpoints", True
            )
            and self.repositories.status(project).get("state") == "verified"
        )

    def record_checked_result(self, task, operation, tool, args, result, root):
        if tool == "test_programs" and result.get("passed") is True:
            files = {}
            for name, expected in result.get("candidate_hashes", {}).items():
                if PurePosixPath(name).suffix.lower() not in {
                    ".c",
                    ".h",
                    ".cc",
                    ".cpp",
                    ".cc",
                    ".rs",
                    ".cmake",
                    ".hpp",
                    ".py",
                    ".rs",
                    ".js",
                    ".ts",
                    ".json",
                    ".toml",
                    ".cmake",
                    ".txt",
                }:
                    continue
                raw = scoped(root, name).read_bytes()
                if hashlib.sha256(raw).hexdigest() != expected:
                    raise Conflict("Native-tested source changed before checkpoint")
                try:
                    self._safe_text(name, raw)
                except (Blocked, UnicodeDecodeError) as error:
                    self.store.event(
                        task,
                        "checkpoint_source_excluded",
                        {"operation": operation, "path": name, "reason": str(error)},
                    )
                    # Publication is optional. A valid local comparison remains
                    # valid even when its sources cannot leave this workspace.
                    # Skip the complete snapshot rather than publish a partial set.
                    return
                files[name] = expected
            self.retain_validation(task, operation, files)
            return
        if result.get("passed") is not True or tool not in (
            "validate_c_function",
            "compare_program",
            "compare_linked_function",
        ):
            return
        files = {}
        if tool == "validate_c_function":
            files[args["candidate_path"]] = result["source_sha256"]
        else:
            files.update(result.get("source_hashes", result.get("sources", {})))
            manifest_path = scoped(root, args["manifest_path"])
            if digest(json.loads(manifest_path.read_text())) != result.get(
                "manifest_sha256"
            ):
                raise Conflict("Build manifest changed after verification")
            files[args["manifest_path"]] = hashlib.sha256(
                manifest_path.read_text().encode()
            ).hexdigest()
        raw_hashes = {}
        for name, expected in files.items():
            path = scoped(root, name)
            raw = path.read_bytes()
            normalized = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
            if hashlib.sha256(normalized.encode()).hexdigest() != expected:
                raise Conflict("Checked source changed before checkpoint: " + name)
            raw_hashes[name] = hashlib.sha256(raw).hexdigest()
        self.retain_validation(task, operation, raw_hashes)

    def retain_validation(self, task, operation, files):
        if not files:
            return
        self.store.put(
            "publication_validation", operation, {"task": task, "files": files}
        )

    def _load(self, kind, key):
        rows = self.store.rows(
            "SELECT payload FROM records WHERE kind=? ORDER BY rowid DESC LIMIT 1",
            (kind + ":" + key,),
        )
        return json.loads(rows[0]["payload"]) if rows else None

    def _save(self, kind, key, value):
        self.store.put(kind + ":" + key, uid("state"), value)

    def status(self, project):
        return self._load("publication_head", project) or {"sha": None}

    def _safe_text(self, path, raw):
        p = PurePosixPath(path)
        forbidden = {
            "private",
            "protected",
            "restricted",
            "originals",
            "logs",
            "profiles",
            "node_modules",
            "__pycache__",
        }
        if (
            p.is_absolute()
            or any(x.startswith(".") or x.lower() in forbidden for x in p.parts)
            or "\\" in path
            or p.suffix.lower()
            not in {
                ".c",
                ".h",
                ".cpp",
                ".cc",
                ".rs",
                ".cmake",
                ".hpp",
                ".py",
                ".js",
                ".ts",
                ".json",
                ".md",
                ".txt",
                ".toml",
                ".yaml",
                ".yml",
            }
        ):
            raise Blocked(
                "Checkpoint path is outside publishable source files: " + path
            )
        if any(
            term in p.name.lower()
            for term in ("credential", "secret", "token", "settings")
        ):
            raise Blocked("Private configuration is not publishable")
        if len(raw) > 256000:
            raise Blocked("Checkpoint file exceeds 256 KB")
        if self.store.rows(
            "SELECT 1 FROM artifacts WHERE classification='protected' AND sha256=?",
            (hashlib.sha256(raw).hexdigest(),),
        ):
            raise Blocked("Protected evaluation data is not publishable")
        text = raw.decode("utf-8")
        if "\0" in text or re.search(
            r"gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|sk-(?:proj-|ant-)?[A-Za-z0-9_-]{40,}",
            text,
        ):
            raise Blocked(
                "Possible credential or binary data in checkpoint file: " + path
            )
        # Exact originals and substantial verbatim restricted source passages cannot
        # be laundered through a generated file. This is not semantic DLP.
        for row in self.store.rows(
            "SELECT revision,sections FROM sources WHERE external_allowed=0"
        ):
            if hashlib.sha256(raw).hexdigest() == row["revision"]:
                raise Blocked("Source lacks external-sharing permission")
            for section in json.loads(row["sections"]):
                part = section.get("text", "").strip()
                if len(part) >= 80 and part in text:
                    raise Blocked("Checkpoint contains a restricted source passage")
        return text

    def _snapshot(self, task, validation, root):
        evidence = self.store.get("publication_validation", validation)
        op = self.store.one(
            "SELECT state,task_id FROM operations WHERE id=?", (validation,)
        )
        if (
            evidence["task"] != task
            or op["task_id"] != task
            or op["state"] not in ("completed", "saved")
        ):
            raise Blocked("Checkpoint requires this task’s completed host validation")
        files = evidence["files"]
        if not 1 <= len(files) <= 100:
            raise ContractError("Checkpoint requires 1–100 checked source files")
        snapshot = []
        for name, expected in files.items():
            unresolved = root / name
            if any(
                p.is_symlink()
                for p in (unresolved, *unresolved.parents)
                if p != root.parent
            ):
                raise Blocked("Checkpoint symlinks are not supported")
            path = scoped(root, name)
            if path.is_symlink() or path.stat().st_size > 256000:
                raise Blocked("Checkpoint source must be a bounded regular file")
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != expected:
                raise Conflict("Source changed after validation: " + name)
            text = self._safe_text(name, raw)
            snapshot.append(
                {"path": name, "mode": "100644", "type": "blob", "content": text}
            )
        if len(canonical(snapshot)) > 2_000_000:
            raise Blocked("Checkpoint exceeds 2 MB")
        return snapshot

    def publish(self, task, operation, validation, root, cancel=None):
        project = self.store.task(task)["project_id"]
        if not self.enabled(project):
            return {
                "status": "disabled",
                "reason": "Local-only project or automatic checkpoints disabled",
            }
        with self.repositories.lock:
            if self._load("publication_intent", operation):
                return self.reconcile(project, operation)
            snapshot = self._snapshot(task, validation, root)
            row = self.repositories._row(project)
            self.repositories._identity(row)
            repo = self.repositories.client.lookup(row["owner"], row["name"])
            self.repositories._validate(row, repo)
            branch = repo.get("default_branch", "main")
            client = self.repositories.client
            head = client.head(row["owner"], row["name"], branch)
            if head is None and repo.get("size", 0) != 0:
                raise Blocked("Default branch is inaccessible in a nonempty repository")
            previous = self.status(project)
            if previous.get("sha") is not None and (
                previous["sha"] != head or previous.get("branch") != branch
            ):
                raise Conflict(
                    "Remote branch changed; reconcile remote work before publishing"
                )
            identity = digest(snapshot)
            if previous.get("snapshot") == identity:
                return {"status": "saved", "sha": head, "unchanged": True}
            if cancel is not None and cancel.is_set():
                raise Blocked("Checkpoint cancelled before publication")
            intent = {
                "project": project,
                "validation": validation,
                "branch": branch,
                "parent": head,
                "snapshot": snapshot,
                "snapshot_hash": identity,
                "stage": "prepared",
                "commit": None,
            }
            self._save("publication_intent", operation, intent)
            return self._advance(row, operation, intent)

    def _advance(self, row, operation, intent):
        client = self.repositories.client

        def call(method, endpoint, data=None):
            return client.git(row["owner"], row["name"], method, endpoint, data)

        def save():
            self._save("publication_intent", operation, intent)

        branch = quote(intent["branch"], safe="")
        # GitHub's Git database API rejects empty repositories. Initialize one
        # verified source file with Contents, retaining intent before the write.
        if intent["parent"] is None:
            first = intent["snapshot"][0]
            if intent["stage"] == "initializing":
                observed = client.head(row["owner"], row["name"], intent["branch"])
                if observed is None:
                    raise Blocked(
                        "Initial checkpoint write is uncertain; no duplicate initialization sent"
                    )
                info = call("GET", "commits/" + observed)
                changed = info.get("files", [])
                expected = hashlib.sha1(
                    b"blob "
                    + str(len(first["content"].encode())).encode()
                    + b"\0"
                    + first["content"].encode()
                ).hexdigest()
                if (
                    info.get("parents")
                    or len(changed) != 1
                    or changed[0].get("filename") != first["path"]
                    or changed[0].get("sha") != expected
                ):
                    raise Conflict(
                        "Repository initialization differs from the saved checkpoint"
                    )
                intent["parent"] = observed
                intent["stage"] = "prepared"
                save()
            else:
                intent["stage"] = "initializing"
                save()
                created = call(
                    "PUT",
                    "contents/" + quote(first["path"], safe="/"),
                    {
                        "message": "Initialize verified project source",
                        "content": base64.b64encode(first["content"].encode()).decode(),
                        "branch": intent["branch"],
                    },
                )
                intent["parent"] = created["commit"]["sha"]
                intent["stage"] = "prepared"
                save()
        if intent["commit"] is None:
            parent = call("GET", "git/commits/" + intent["parent"])
            tree = call(
                "POST",
                "git/trees",
                {"base_tree": parent["tree"]["sha"], "tree": intent["snapshot"]},
            )
            if tree["sha"] == parent["tree"]["sha"]:
                intent["commit"] = intent["parent"]
            else:
                created = call(
                    "POST",
                    "git/commits",
                    {
                        "message": "Verified reconstruction checkpoint",
                        "tree": tree["sha"],
                        "parents": [intent["parent"]],
                    },
                )
                intent["commit"] = created["sha"]
            intent["stage"] = "committed"
            save()
        head = client.head(row["owner"], row["name"], intent["branch"])
        if head != intent["commit"]:
            if head != intent["parent"]:
                raise Conflict(
                    "Remote advanced during checkpoint; no overwrite performed"
                )
            # A repeated update to this exact saved commit is idempotent. force:false
            # also rejects a concurrent sibling commit after the preceding read.
            intent["stage"] = "publishing"
            save()
            call(
                "PATCH",
                "git/refs/heads/" + branch,
                {"sha": intent["commit"], "force": False},
            )
        if client.head(row["owner"], row["name"], intent["branch"]) != intent["commit"]:
            raise Blocked("Checkpoint branch update requires reconciliation")
        intent["stage"] = "published"
        save()
        self._save(
            "publication_head",
            row["project_id"],
            {
                "sha": intent["commit"],
                "branch": intent["branch"],
                "snapshot": intent["snapshot_hash"],
            },
        )
        return {
            "status": "saved",
            "sha": intent["commit"],
            "branch": intent["branch"],
            "files": [x["path"] for x in intent["snapshot"]],
            "url": f"https://github.com/{row['owner']}/{row['name']}/commit/{intent['commit']}",
        }

    def uncertain(self, operation):
        return self._load("publication_intent", operation) is not None

    def reconcile(self, project, operation):
        with self.repositories.lock:
            intent = self._load("publication_intent", operation)
            if not intent:
                return {"status": "not_applied"}
            if intent["project"] != project:
                raise Conflict("Checkpoint project differs")
            row = self.repositories._row(project)
            self.repositories._identity(row)
            self.repositories._validate(
                row, self.repositories.client.lookup(row["owner"], row["name"])
            )
            if not self.enabled(project):
                observed = self.repositories.client.head(
                    row["owner"], row["name"], intent["branch"]
                )
                if not intent.get("commit") or observed != intent["commit"]:
                    raise Blocked(
                        "Checkpoint publication is disabled; retained writes will not be dispatched"
                    )
                return {
                    "status": "saved",
                    "sha": intent["commit"],
                    "branch": intent["branch"],
                    "reconciled": True,
                }
            # Recheck current sharing/credential restrictions before any retained upload.
            for item in intent["snapshot"]:
                self._safe_text(item["path"], item["content"].encode())
            return self._advance(row, operation, intent)
