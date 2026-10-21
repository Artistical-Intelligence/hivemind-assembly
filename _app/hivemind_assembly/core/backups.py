"""Consistent portable workspace snapshots; browser sessions/OS credentials excluded."""

import json
import tempfile
import time
import zipfile
from pathlib import Path

from .common import Blocked, ContractError, canonical, file_hash


def snapshot(store, destination):
    with store.lock:
        return _snapshot(store, destination)


def _snapshot(store, destination):
    destination = Path(destination).resolve()
    root = store.root
    # Caller stops writers. Reject an active controller lease or uncertain external mutation.
    if store.rows("SELECT id FROM tasks WHERE owner IS NOT NULL AND status='running'"):
        raise Blocked(
            "Pause tasks and wait for active work to finish before backing up"
        )
    if store.rows(
        "SELECT id FROM operations WHERE state IN ('running','uncertain','applied')"
    ):
        raise Blocked("Reconcile pending operations before backing up")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ha-backup-") as tmp:
        stage = Path(tmp)
        store.backup(stage / "controller.sqlite3")
        files = [stage / "controller.sqlite3"]
        # Complete owned data, never installed software, caches, lock files or credentials.
        for name in ("projects", "artifacts", "sources", "knowledge", "exports"):
            source = root / name
            if source.exists():
                for path in source.rglob("*"):
                    if path.is_symlink():
                        raise Blocked(
                            "Backup contains a symbolic link; inspect it before retrying"
                        )
                    if path.is_file():
                        files.append(path)
        if (root / "settings.json").exists():
            files.append(root / "settings.json")
        # Hermes SQLite uses its own WAL; take a SQLite snapshot, never copy a live DB.
        import sqlite3

        for source in root.glob("hermes*.sqlite3"):
            with sqlite3.connect(source) as db, sqlite3.connect(
                stage / source.name
            ) as target:
                db.backup(target)
            files.append(stage / source.name)
        manifest = {
            "format": 1,
            "created": time.time(),
            "excluded": ["browser sessions", "OS credentials", "installed foundations"],
            "files": {},
        }
        pending = destination.with_suffix(".partial")
        try:
            with zipfile.ZipFile(pending, "w", zipfile.ZIP_DEFLATED) as archive:
                for path in files:
                    name = str(
                        path.relative_to(stage if path.is_relative_to(stage) else root)
                    ).replace("\\", "/")
                    manifest["files"][name] = {
                        "sha256": file_hash(path),
                        "size": path.stat().st_size,
                    }
                    archive.write(path, name)
                    if file_hash(path) != manifest["files"][name]["sha256"]:
                        raise Blocked(
                            "Workspace changed during backup; retry after writers stop"
                        )
                archive.writestr("backup-manifest.json", canonical(manifest))
            verify(pending)
            pending.replace(destination)
        finally:
            pending.unlink(missing_ok=True)
    return {
        "name": destination.name,
        "files": len(files),
        "sha256": file_hash(destination),
        "scope": "Projects, originals, native project data, artifacts, sources, learning state, transcripts and settings. Browser sessions and OS credentials require reconnecting.",
    }


DATA_PREFIXES = ("projects/", "artifacts/", "sources/", "knowledge/", "exports/")
TOP_LEVEL = {"controller.sqlite3", "settings.json"}
MAX_TOTAL = 16 * 1024**3  # Bounded restore size; larger workspaces need a manual move.
MAX_MANIFEST = 64 * 1024**2


def allowed_name(name):
    """Only what snapshot() writes: owned data, never software, sessions or secrets."""
    if name in TOP_LEVEL or name.startswith(DATA_PREFIXES):
        return True
    return "/" not in name and name.startswith("hermes") and name.endswith(".sqlite3")


def verify(path):
    import hashlib

    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ContractError("Duplicate backup entries")
        if archive.getinfo("backup-manifest.json").file_size > MAX_MANIFEST:
            raise ContractError("Backup manifest exceeds bounds")
        manifest = json.loads(archive.read("backup-manifest.json"))
        if manifest.get("format") != 1 or set(names) != {
            *manifest["files"],
            "backup-manifest.json",
        }:
            raise ContractError("Backup manifest mismatch")
        folded = [n.casefold() for n in manifest["files"]]
        if len(folded) != len(set(folded)):
            raise ContractError("Backup entries collide on case-insensitive filesystems")
        if sum(archive.getinfo(n).file_size for n in manifest["files"]) > MAX_TOTAL:
            raise ContractError("Backup exceeds the restore size limit")
        for name, evidence in manifest["files"].items():
            if not allowed_name(name):
                raise ContractError("Backup contains a file outside owned workspace data: " + name)
            if (
                "\\" in name
                or name.startswith("/")
                or any(p in ("", "..", ".") for p in name.split("/"))
                or ":" in name
            ):
                raise ContractError("Invalid backup path")
            info = archive.getinfo(name)
            if info.file_size != evidence["size"]:
                raise ContractError("Backup size mismatch")
            h = hashlib.sha256()
            with archive.open(name) as stream:
                for chunk in iter(lambda: stream.read(1048576), b""):
                    h.update(chunk)
            if h.hexdigest() != evidence["sha256"]:
                raise ContractError("Backup integrity failure")
        return manifest


def restore(path, destination):
    """Offline restoration into an empty directory. Never overwrite live work."""
    destination = Path(destination)
    if destination.exists() and any(destination.iterdir()):
        raise Blocked("Restore requires an empty data directory")
    manifest = verify(path)
    destination.mkdir(parents=True, exist_ok=True)
    from .common import InstanceLock
    import hashlib

    import shutil

    lock = InstanceLock(destination)
    restored = []
    try:
        # Refuse a race with another process creating a workspace before the lock.
        if any(p.name != "host.lock" for p in destination.iterdir()):
            raise Blocked("Restore destination changed before the lock was acquired")
        if shutil.disk_usage(destination).free < sum(e["size"] for e in manifest["files"].values()):
            raise Blocked("Not enough free space to restore this backup")
        with zipfile.ZipFile(path) as archive:
            if set(archive.namelist()) != {*manifest["files"], "backup-manifest.json"}:
                raise ContractError("Backup changed before restoration")
            for name, evidence in manifest["files"].items():
                target = destination / name
                target.parent.mkdir(parents=True, exist_ok=True)
                pending = target.with_name(target.name + ".restore-partial")
                try:
                    h = hashlib.sha256()
                    size = 0
                    with archive.open(name) as src, pending.open("xb") as dst:
                        for chunk in iter(lambda: src.read(1048576), b""):
                            dst.write(chunk)
                            h.update(chunk)
                            size += len(chunk)
                    if size != evidence["size"] or h.hexdigest() != evidence["sha256"]:
                        raise ContractError("Backup changed during restoration")
                    pending.replace(target)
                    restored.append(target)
                finally:
                    pending.unlink(missing_ok=True)
    except BaseException:
        # Never leave a partly restored directory that could open as live data.
        for item in destination.iterdir():
            if item.name == "host.lock":
                continue
            if item.is_dir() and not item.is_symlink():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink(missing_ok=True)
        raise
    finally:
        lock.close()
    return {"restored": str(destination)}
