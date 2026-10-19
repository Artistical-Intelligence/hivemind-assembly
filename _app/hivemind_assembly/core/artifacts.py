from __future__ import annotations
import hashlib, re, time, zipfile
from pathlib import Path
from hivemind_assembly.core.common import (
    atomic_write,
    file_hash,
    uid,
    ContractError,
    Blocked,
    scoped,
)


class Artifacts:
    def __init__(self, store):
        self.store = store
        self.root = store.root / "artifacts"

    def add(self, data, name, project=None, classification="task"):
        if classification not in ("task", "shared", "restricted", "protected"):
            raise ContractError("Unknown artifact classification")
        if isinstance(data, str):
            data = data.encode()
        h = hashlib.sha256(data).hexdigest()
        path = self.root / h[:2] / h
        if not path.exists():
            atomic_write(path, data)
        key = uid("artifact")
        with self.store.tx() as c:
            c.execute(
                "INSERT INTO artifacts VALUES(?,?,?,?,?,?,?)",
                (
                    key,
                    h,
                    len(data),
                    classification,
                    project,
                    Path(name).name,
                    time.time(),
                ),
            )
        return self.store.one("SELECT * FROM artifacts WHERE id=?", (key,))

    def read(self, key, role, project=None):
        row = self.store.one("SELECT * FROM artifacts WHERE id=?", (key,))
        cls = row["classification"]
        if cls == "protected" and role != "evaluator":
            raise Blocked("Protected evaluator artifact")
        if cls == "restricted" and role not in ("adviser", "ingestion", "controller"):
            raise Blocked("Restricted artifact")
        if cls == "task" and row["project_id"] != project and role != "controller":
            raise Blocked("Artifact belongs to another project")
        p = self.root / row["sha256"][:2] / row["sha256"]
        if file_hash(p) != row["sha256"]:
            raise ContractError("Artifact content hash mismatch")
        return p.read_bytes()


FORBIDDEN_NAMES = {
    "cookies",
    "credentials",
    "browser",
    "profile",
    "auth",
    "controller.sqlite3",
    ".env",
    ".git",
    "restricted",
    "protected",
}
SECRET_PATTERNS = [
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r'(?i)(api[_-]?key|authorization|password|access[_-]?token)\s*[:=]\s*["\']?[^\s"\']{8,}',
    r"\b(?:ghp|github_pat|sk)-?[A-Za-z0-9_]{20,}",
    r"(?i)[A-Z]:\\Users\\",
    r"/home/[^/\s]+/",
    r"/Users/[^/\s]+/",
    r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
]


def export_package(root, paths, destination):
    """Strict text-only public export. No directory recursion or binary metadata leaks."""
    selected = []
    for name in paths:
        p = scoped(root, name)
        if any(
            any(f in part.lower() for f in FORBIDDEN_NAMES) for part in Path(name).parts
        ):
            raise Blocked("Private path in export")
        if p.suffix.lower() not in (
            ".py",
            ".java",
            ".js",
            ".ts",
            ".json",
            ".md",
            ".txt",
            ".c",
            ".h",
            ".toml",
            ".yaml",
            ".yml",
        ):
            raise Blocked("Binary/unknown export requires a separate review")
        if p.stat().st_size > 4_000_000:
            raise Blocked("Oversized export")
        data = p.read_text("utf-8")
        if any(re.search(pattern, data) for pattern in SECRET_PATTERNS):
            raise Blocked(
                "Private metadata or possible secret found; export quarantined"
            )
        selected.append((name, data))
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in selected:
            z.writestr(name, data)
    return {
        "files": len(selected),
        "sha256": file_hash(destination),
        "publication": "not_published",
    }
