"""Owner file access with project-wide writer guards and retained prior versions."""

import os
import hashlib
from contextlib import contextmanager
import re
import tempfile
from pathlib import Path, PurePosixPath
from hivemind_assembly.core.common import Blocked, Conflict, ContractError, file_hash

TEXT_LIMIT = 512 * 1024
UPLOAD_LIMIT = 256 * 1024 * 1024


class Workspace:
    def __init__(self, broker):
        self.broker, self.store = broker, broker.store

    def path(self, task_id, name):
        if (
            not isinstance(name, str)
            or not name
            or len(name) > 500
            or "\\" in name
            or ":" in name
            or any(ord(c) < 32 for c in name)
        ):
            raise ContractError("Use a relative project path with forward slashes")
        parts = PurePosixPath(name).parts
        if (
            name.startswith("/")
            or any(
                p.lower() in (".", "..", ".git")
                or p.endswith((" ", "."))
                or re.fullmatch(
                    r"(?i)(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", p
                )
                or any(c in p for c in '<>"|?*')
                for p in parts
            )
            or "/".join(parts) != name
        ):
            raise ContractError("Invalid project path")
        root = self.broker.workspace(task_id)
        path = root
        for part in parts:
            path = path / part
            if path.is_symlink() or (
                hasattr(path, "is_junction") and path.is_junction()
            ):
                raise Blocked("Linked paths are not editable through the dashboard")
        if not path.resolve().is_relative_to(root.resolve()):
            raise Blocked("Path leaves the project workspace")
        return path

    def guard(self, task_id):
        task = self.store.task(task_id)
        preparing = (
            task["status"] == "waiting_setup"
            and not task["step"]
            and not self.store.rows(
                "SELECT id FROM records WHERE kind='acceptance_contract' AND id=?",
                (task_id,),
            )
        )
        if (task["status"] != "paused" and not preparing) or task["owner"]:
            raise Blocked("Pause the task before changing project files")
        if self.store.rows(
            "SELECT id FROM tasks WHERE project_id=? AND owner IS NOT NULL",
            (task["project_id"],),
        ):
            raise Blocked("Another task owns this project; pause it before editing")
        if self.store.rows(
            "SELECT o.id FROM operations o JOIN tasks t ON t.id=o.task_id WHERE t.project_id=? AND o.state IN ('running','uncertain','applied')",
            (task["project_id"],),
        ):
            raise Blocked("Reconcile unfinished project operations before editing")
        return task

    def listing(self, task_id):
        from hivemind_assembly.core.acceptance import Acceptance

        task = self.store.task(task_id)
        root = self.broker.workspace(task_id)
        rows = []
        truncated = False
        for folder, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = sorted(
                d
                for d in dirs
                if d != ".git"
                and not (Path(folder) / d).is_symlink()
                and not (
                    hasattr(Path(folder) / d, "is_junction")
                    and (Path(folder) / d).is_junction()
                )
            )
            for name in sorted(files):
                relative = (Path(folder) / name).relative_to(root).as_posix()
                try:
                    path = self.path(task_id, relative)
                    rows.append({"path": relative, "size": path.stat().st_size})
                except (OSError, ContractError):
                    continue
                if len(rows) >= 2000:
                    truncated = True
                    break
            if truncated:
                break
        try:
            self.guard(task_id)
            reason = ""
        except Blocked as error:
            reason = str(error)
        return {
            "task": task_id,
            "root": str(root),
            "revision": self.store.project(task["project_id"])["revision"],
            "files": rows,
            "truncated": truncated,
            "editable": not reason,
            "preparing": task["status"] == "waiting_setup",
            "reason": reason,
            "acceptance": Acceptance(self.broker.controller, self.broker).describe(
                task_id
            ),
        }

    def read(self, task_id, name):
        path = self.path(task_id, name)
        if not path.is_file():
            raise ContractError("Project file does not exist")
        size = path.stat().st_size
        digest = file_hash(path)
        result = {"path": name, "size": size, "sha256": digest, "text": None}
        with path.open("rb") as f:
            data = f.read(TEXT_LIMIT + 1)
        if size <= TEXT_LIMIT and b"\0" not in data:
            try:
                result["text"] = data.decode("utf-8")
            except UnicodeDecodeError:
                pass
        if result["text"] is None:
            result["preview_hex"] = data[:256].hex(" ")
        if file_hash(path) != digest:
            raise Conflict("File changed while it was read; reload it")
        return result

    @contextmanager
    def download(self, task_id, name, expected_sha):
        if not isinstance(expected_sha, str) or not re.fullmatch(
            "[0-9a-f]{64}", expected_sha
        ):
            raise ContractError("Open the file before downloading it")
        source = self.path(task_id, name)
        if not source.is_file() or source.stat().st_size > UPLOAD_LIMIT:
            raise ContractError("Dashboard downloads support files up to 256 MiB")
        # Send a stable snapshot. A concurrent edit cannot change bytes after
        # the response headers or produce a partial mixture of file versions.
        with tempfile.TemporaryDirectory(prefix="ha-download-") as folder:
            stage = Path(folder) / "content"
            digest, size = hashlib.sha256(), 0
            with source.open("rb") as inp, stage.open("wb") as out:
                while chunk := inp.read(1024 * 1024):
                    size += len(chunk)
                    if size > UPLOAD_LIMIT:
                        raise Conflict("File grew beyond the dashboard download limit")
                    digest.update(chunk)
                    out.write(chunk)
            if digest.hexdigest() != expected_sha:
                raise Conflict(
                    "File changed since it was opened. Reload before downloading."
                )
            yield stage

    def install(self, task_id, name, stage, expected_sha=None):
        if expected_sha is not None and (
            not isinstance(expected_sha, str)
            or not re.fullmatch("[0-9a-f]{64}", expected_sha)
        ):
            raise ContractError(
                "Expected file hash must be SHA-256 or null for a new file"
            )
        stage = Path(stage)
        if stage.stat().st_size > UPLOAD_LIMIT:
            raise ContractError(
                "Upload exceeds 256 MiB; use local target import for larger files"
            )
        incoming = file_hash(stage)
        with self.store.lock:
            task = self.guard(task_id)
            target = self.path(task_id, name)
            if target.exists() and not target.is_file():
                raise Conflict("A folder already has this name")
            current = file_hash(target) if target.exists() else None
            if current == incoming:
                return {"path": name, "sha256": incoming, "unchanged": True}
            if current != expected_sha:
                raise Conflict(
                    "This file changed since it was opened. Reload it before saving; your draft has not been applied."
                )
            # Preserve every uploaded version, and every overwritten version,
            # outside the worker-visible workspace before changing the file.
            prior = (
                self.broker.artifacts.add_file(target, name, task["project_id"], "task")
                if target.exists()
                else None
            )
            retained = self.broker.artifacts.add_file(
                stage, name, task["project_id"], "task"
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, temp = tempfile.mkstemp(prefix=".ha-save-", dir=target.parent)
            try:
                with os.fdopen(fd, "wb") as out, stage.open("rb") as source:
                    while chunk := source.read(1024 * 1024):
                        out.write(chunk)
                    out.flush()
                    os.fsync(out.fileno())
                with self.store.tx() as db:
                    self.guard(task_id)
                    if (file_hash(target) if target.exists() else None) != current:
                        raise Conflict("File changed during save")
                    db.execute(
                        "UPDATE projects SET revision=revision+1 WHERE id=?",
                        (task["project_id"],),
                    )
                    self.store.event(
                        task_id,
                        "owner_file_prepared",
                        {
                            "path": name,
                            "sha256": incoming,
                            "artifact": retained["id"],
                            "previous_artifact": prior["id"] if prior else None,
                        },
                        db,
                    )
                # Advance the revision durably before replacing bytes, so a crash
                # cannot leave new file contents associated with an old revision.
                os.replace(temp, target)
                self.store.event(
                    task_id, "owner_file_saved", {"path": name, "sha256": incoming}
                )
            finally:
                Path(temp).unlink(missing_ok=True)
        return {
            "path": name,
            "sha256": incoming,
            "size": stage.stat().st_size,
            "unchanged": False,
        }

    def write(self, task_id, name, text, expected_sha=None):
        if not isinstance(text, str) or len(text.encode("utf-8")) > TEXT_LIMIT:
            raise ContractError("Text editor supports UTF-8 files up to 512 KiB")
        with tempfile.TemporaryDirectory(prefix="ha-edit-") as folder:
            stage = Path(folder) / "content"
            stage.write_bytes(text.encode("utf-8"))
            return self.install(task_id, name, stage, expected_sha)
