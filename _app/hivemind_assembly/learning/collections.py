"""Import a whole folder, or a whole GitHub repository, as reference material.

Automation, not AI. Markdown, Word, PDF, HTML, text and source files are imported;
everything else is listed as skipped with its reason (archives, programs and other
binary data, pictures no document uses, old Office formats). Nothing is skipped
silently. Each file's categories come from its Markdown front matter (tags), or else
from the names of the folders it is in; the collection's own name is a category too,
so the whole collection can be given to a project at once.

Importing again replaces the previous copies: changed files are read again, unchanged
ones are left as they are, and copies of files that are gone from the folder or
repository are removed (the folder and the repository themselves are never changed).
A GitHub repository is downloaded with Git through HA's GitHub connection, so
private repositories work too; "Update from GitHub" and an optional schedule fetch
the latest version.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path, PurePosixPath
from posixpath import normpath
from urllib.parse import unquote

from hivemind_assembly.core.common import Blocked, Conflict, ContractError, atomic_write, canonical, uid

from . import documents
from .knowledge import Knowledge, kind_of
from .scopes import KnowledgeScopes

SCHEDULES = (0, 1440, 10080)  # minutes: off, every day, every week
OWNER = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}")
NAME = re.compile(r"[A-Za-z0-9_.-]{1,100}")
SKIP_DIRS = {
    ".git": "Git's own records",
    "node_modules": "installed packages",
    "__pycache__": "Python's cache",
    ".venv": "installed packages",
    "venv": "installed packages",
    ".tox": "test cache",
    ".mypy_cache": "type-check cache",
    ".pytest_cache": "test cache",
}
ARCHIVES = {".zip", ".7z", ".rar", ".tar", ".gz", ".tgz", ".bz2", ".tbz2", ".xz", ".txz", ".zst", ".cab", ".jar",
            ".apk", ".whl", ".nupkg", ".msi", ".dmg", ".iso", ".lz", ".lzma", ".z"}
IMAGES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".ico", ".tif", ".tiff", ".emf", ".wmf"}
OLD_OFFICE = {".doc": "Word", ".xls": "Excel", ".ppt": "PowerPoint", ".rtf": "Rich Text"}
OTHER_OFFICE = {".pptx", ".odt", ".ods", ".odp", ".pages", ".numbers", ".key"}
SECRETS = re.compile(
    r"(^\.env(\..*)?$|^\.netrc$|^\.npmrc$|^\.pypirc$|^id_(rsa|dsa|ecdsa|ed25519)(\.pub)?$"
    r"|\.(pem|key|pfx|p12|keystore|jks|kdbx|ppk)$|^credentials(\.json)?$)",
    re.I,
)
MAX_TEXT = 20 * 1024 * 1024
MAX_DOCUMENT = 300 * 1024 * 1024
PACKED = ("word", "pdf", "spreadsheet")  # Compressed formats get the larger limit.
RECEIVING = re.compile(r"Receiving objects:\s+(\d+)%")


def _flags():
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def looks_like_text(head):
    """The first 8 KiB of a file without a known extension: UTF-8 or UTF-16 text?
    (A character cut off at the end of the sample doesn't count against it.)"""
    import codecs

    if not head.strip():
        return False
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):
        return True
    if b"\0" in head:
        return False
    try:
        codecs.getincrementaldecoder("utf-8")().decode(head, final=False)
        return True
    except UnicodeDecodeError:
        return False


def picture_path(target, folder, images):
    """The imported file a Markdown or HTML picture link points to, if it's in the folder:
    relative to the document, or from the top of the folder or repository when it
    starts with /, with %20-style escapes and either kind of slash."""
    clean = unquote(target.split("#")[0].split("?")[0]).strip().replace("\\", "/")
    if not clean or re.match(r"[a-z][a-z0-9+.-]*:", clean, re.I):
        return None
    if clean.startswith("/"):
        joined = normpath(clean.lstrip("/"))
    else:
        joined = normpath((folder + "/" if folder != "." else "") + clean)
    if joined in images:
        return joined
    # Windows and macOS don't mind letter case in a link; match it the same way.
    wanted = joined.lower()
    return next((k for k in images if k.lower() == wanted), None)


def remove_tree(path):
    """Delete one of HA's own copies, including the read-only files Git leaves on Windows."""

    def retry(func, name, _):
        try:
            os.chmod(name, stat.S_IWRITE)
            func(name)
        except OSError:
            pass

    if Path(path).exists():
        shutil.rmtree(path, **({"onexc": retry} if sys.version_info >= (3, 12) else {"onerror": retry}))


def tag_id(label):
    """A category ID from a folder name or front-matter tag."""
    key = re.sub(r"[^a-z0-9_-]+", "-", label.lower()).strip("-_")[:64].strip("-_")
    if not key:
        import hashlib

        key = "tag-" + hashlib.sha256(label.encode()).hexdigest()[:8]
    return key


class KnowledgeCollections:
    def __init__(self, store, auth=None, git=None, remote_url=None, clock=time.time):
        self.store = store
        self.dir = Path(store.root) / "knowledge"
        self.path = self.dir / "collections.json"
        self.auth, self.git_program, self.clock = auth, git, clock
        self.remote_url = remote_url or (lambda owner, name: f"https://github.com/{owner}/{name}.git")
        self.lock = threading.RLock()
        self.running = {}
        self.permission = {}  # The owner's latest choice, read by an import already running.
        self.monitor = None
        self.stopping = threading.Event()

    # ---------------------------------------------------------------- records
    def _load(self):
        if not self.path.exists():
            return {}
        return {e["id"]: e for e in json.loads(self.path.read_text(encoding="utf-8"))}

    def _save(self, entries):
        atomic_write(self.path, canonical(sorted(entries.values(), key=lambda e: e["created"])))

    def _set(self, key, **values):
        with self.lock:
            entries = self._load()
            if key not in entries:
                return None
            entries[key].update(values)
            self._save(entries)
            return entries[key]

    def view(self):
        """Collections for the dashboard; long skipped lists are summarized (see report())."""
        with self.lock:
            entries = self._load()
        shown = []
        for e in sorted(entries.values(), key=lambda e: e["created"]):
            item = {**e, "running": e["id"] in self.running and self.running[e["id"]].is_alive()}
            report = e.get("report")
            if report:
                reasons = {}
                for x in report["skipped"]:
                    kind = re.sub(r" \(.*?\)|;.*$|\d+ MiB.*", "", x["reason"]).strip()
                    reasons[kind] = reasons.get(kind, 0) + 1
                item["report"] = {
                    **{k: v for k, v in report.items() if k != "skipped"},
                    "skipped_count": len(report["skipped"]),
                    "skipped_reasons": reasons,
                    "skipped_sample": report["skipped"][:100],
                }
            shown.append(item)
        return shown

    def report(self, key):
        """The full import report, with every skipped file and why."""
        entry = self._load().get(key)
        if entry is None:
            raise ContractError("Unknown imported collection.")
        return entry.get("report") or {}

    # -------------------------------------------------------------- requests
    def add(self, data):
        if not isinstance(data, dict) or set(data) - {
            "kind", "folder", "repository", "branch", "external_allowed", "tags", "schedule_minutes",
        }:
            raise ContractError("Unexpected import settings.")
        kind = data.get("kind")
        tags = KnowledgeScopes(self.store).validate_tags(data.get("tags") or [], allow_empty=True)
        if "unclassified" in tags:
            raise ContractError("Choose real categories, or none.")
        # Every day unless the owner chooses otherwise (0 = only when Update is selected).
        schedule = 1440 if data.get("schedule_minutes") in (None, "") else int(data["schedule_minutes"])
        if schedule not in SCHEDULES:
            raise ContractError("Choose how often to update: off, every day or every week.")
        entry = {
            "id": uid("collection"),
            "kind": kind,
            "external_allowed": bool(data.get("external_allowed", False)),
            "tags": tags,
            "schedule_minutes": schedule,
            "state": "waiting",
            "message": "Waiting to start.",
            "progress": None,
            "report": None,
            "last_import": 0,
            "last_check": 0,
            "commit": "",
            "created": self.clock(),
        }
        if kind == "folder":
            folder = Path(str(data.get("folder", "")).strip().strip('"'))
            if not folder.is_absolute() or not folder.is_dir():
                raise ContractError("Choose a folder on this computer.")
            folder = folder.resolve()
            if folder == Path(folder.anchor):
                raise ContractError("Choose a folder, not a whole drive.")
            if folder == Path(self.store.root).resolve() or Path(self.store.root).resolve() in folder.parents:
                raise ContractError("HA's own data folder can't be imported.")
            entry.update(folder=str(folder), name=folder.name)
        elif kind == "github":
            repository = str(data.get("repository", "")).strip().removeprefix("https://github.com/").removesuffix(".git").strip("/")
            owner, _, name = repository.partition("/")
            if not OWNER.fullmatch(owner) or not NAME.fullmatch(name) or name in (".", ".."):
                raise ContractError("Type the repository as owner/name, for example your-name/research-notes.")
            branch = str(data.get("branch", "") or "")
            if branch and (len(branch) > 200 or branch.startswith("-") or ".." in branch or re.search(r"[\s~^:?*\[\\]", branch)):
                raise ContractError("That isn't a branch name.")
            entry.update(owner=owner, repository=name, branch=branch, name=name)
        else:
            raise ContractError("Choose a folder or a GitHub repository.")
        with self.lock:
            entries = self._load()
            for e in entries.values():
                same = (
                    e.get("folder") == entry.get("folder") if kind == "folder"
                    else (e.get("owner", "").lower(), e.get("repository", "").lower())
                    == (entry["owner"].lower(), entry["repository"].lower())
                )
                if e["kind"] == kind and same:
                    raise Conflict("This is already imported. Use its Update button instead.")
            entries[entry["id"]] = entry
            self._save(entries)
        self.start(entry["id"])
        return entry

    def settings(self, key, data):
        if not isinstance(data, dict) or set(data) - {"schedule_minutes", "external_allowed"}:
            raise ContractError("Unexpected import settings.")
        values = {}
        if "schedule_minutes" in data:
            if int(data["schedule_minutes"]) not in SCHEDULES:
                raise ContractError("Choose how often to update: off, every day or every week.")
            values["schedule_minutes"] = int(data["schedule_minutes"])
        if "external_allowed" in data:
            values["external_allowed"] = bool(data["external_allowed"])
        entry = self._set(key, **values)
        if entry is None:
            raise ContractError("Unknown imported collection.")
        if "external_allowed" in values:
            # Applies to every copy at once, even while the folder or GitHub can't be
            # reached; an import already running uses it from its next file on.
            self.permission[key] = values["external_allowed"]
            self._apply_permission(key, values["external_allowed"], announce=True)
            entry = self._set(key, imported_with=values["external_allowed"])
        return entry

    def _apply_permission(self, key, allowed, announce=False):
        copies = sorted(set(self._copies(key).values()))
        with self.store.tx() as db:
            db.executemany("UPDATE sources SET external_allowed=? WHERE id=?", [(int(allowed), s) for s in copies])
            if announce:
                name = (self._load().get(key) or {}).get("name", "This material")
                self.store.event(key, "knowledge_collection_permission", {
                    "allowed": bool(allowed), "copies": len(copies),
                    "message": f"{name}: the assistants {'may now' if allowed else 'may no longer'} read its {len(copies)} documents.",
                }, db)

    def remove(self, key):
        """Forget a collection and HA's copies of its files (the originals stay)."""
        with self.lock:
            if key in self.running and self.running[key].is_alive():
                raise Blocked("Wait for the import in progress to finish first.")
            entries = self._load()
            entry = entries.pop(key, None)
            if entry is None:
                raise ContractError("Unknown imported collection.")
            self._save(entries)
        knowledge = Knowledge(self.store)
        removed = 0
        for source in self._copies(key).values():
            knowledge.remove(source)
            removed += 1
        remove_tree(self.dir / "repos" / key)
        self.permission.pop(key, None)
        return {"removed": True, "copies_removed": removed}

    def start(self, key):
        with self.lock:
            if key not in self._load():
                raise ContractError("Unknown imported collection.")
            thread = self.running.get(key)
            if thread and thread.is_alive():
                return {"started": False, "message": "Already importing."}
            thread = threading.Thread(target=self._run, args=(key,), daemon=True)
            self.running[key] = thread
            self._set(key, state="importing", message="Starting…", progress={"percent": 0, "text": "Starting…"})
            thread.start()
        return {"started": True}

    def start_monitor(self, every=60):
        def loop():
            while not self.stopping.wait(every):
                try:
                    self.due()
                except Exception:
                    pass  # Shown on the collection when an import fails.

        if self.monitor is None:
            self.monitor = threading.Thread(target=loop, daemon=True)
            self.monitor.start()

    def due(self):
        now, started = self.clock(), []
        for e in self.view():
            if e["schedule_minutes"] and not e["running"] and now - max(e["last_check"], e["last_import"]) >= e["schedule_minutes"] * 60:
                self.start(e["id"])
                started.append(e["id"])
        return started

    def close(self):
        self.stopping.set()

    # -------------------------------------------------------------- the work
    def _progress(self, key, percent, text):
        self._set(key, progress={"percent": max(0, min(100, int(percent))), "text": text}, message=text)

    def _run(self, key):
        try:
            entry = self._load()[key]
            result = self._import(entry)
            self._set(key, state="done", progress=None, last_check=self.clock(), **result)
            index = getattr(self.store, "knowledge_vectors", None)
            if index is not None:
                index.poke()  # Read the new and changed documents for meaning search now.
        except Exception as error:
            self._set(key, state="failed", progress=None, message=str(error) or error.__class__.__name__,
                      last_check=self.clock())

    def _git_path(self):
        program = self.git_program or shutil.which("git")
        if not program:
            raise Blocked("Git isn't installed. Use Install required tools under Settings first.")
        return program

    def _environment(self):
        env = {**os.environ, "LC_ALL": "C"}
        for name in [k for k in env if k.startswith("GIT_CONFIG_")]:
            env.pop(name)
        token = None
        if self.auth is not None:
            try:
                token = self.auth.credentials()["access_token"]
            except Exception:
                token = None
        if token:
            # HA's GitHub connection signs Git in for this download only; nothing is saved.
            basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
            env.update({
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_CONFIG_COUNT": "2",
                "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
                "GIT_CONFIG_VALUE_0": "AUTHORIZATION: basic " + basic,
                "GIT_CONFIG_KEY_1": "credential.helper",
                "GIT_CONFIG_VALUE_1": "",
            })
        return env

    def _git(self, *args, cwd=None, env=None, progress=None, timeout=3600):
        process = subprocess.Popen(
            [self._git_path(), *args], cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=_flags(),
        )
        lines, buffer = [], b""
        while True:
            chunk = process.stderr.read(256)
            if not chunk:
                break
            buffer += chunk
            *parts, buffer = re.split(rb"[\r\n]", buffer)
            for part in parts:
                line = part.decode("utf-8", "replace")
                lines.append(line)
                if progress:
                    progress(line)
        out = process.stdout.read().decode("utf-8", "replace")
        process.wait(timeout=timeout)
        if process.returncode:
            text = "\n".join(lines).lower()
            if "authentication failed" in text or "could not read username" in text or "not found" in text or "403" in text:
                raise Blocked(
                    "GitHub didn't let HA download this repository. Check the name; for a private repository, connect GitHub under Settings."
                )
            last = [l for l in lines if l.strip()]
            raise Blocked("Git: " + (last[-1] if last else "the download failed."))
        return out

    def _checkout(self, entry):
        """HA's own copy of the repository, at its latest version."""
        target = self.dir / "repos" / entry["id"]
        env = self._environment()
        url = self.remote_url(entry["owner"], entry["repository"])
        key = entry["id"]

        def show(line):
            found = RECEIVING.search(line)
            if found:
                self._progress(key, 2 + int(found.group(1)) * 0.18, f"Downloading the repository: {found.group(1)}%")

        self._progress(key, 2, "Downloading the repository…")
        if not (target / ".git").exists():
            remove_tree(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            branch = ["--branch", entry["branch"]] if entry.get("branch") else []
            # Long paths: deep repositories check out on Windows too.
            self._git("clone", "--progress", "--depth", "1", "--no-tags", "--single-branch", "-c", "core.longpaths=true",
                      *branch, url, str(target), env=env, progress=show)
        else:
            self._git("config", "core.longpaths", "true", cwd=target, env=env)
            self._git("remote", "set-url", "origin", url, cwd=target, env=env)
            self._git("fetch", "--progress", "--depth", "1", "--no-tags", "origin", entry.get("branch") or "HEAD",
                      cwd=target, env=env, progress=show)
            self._git("reset", "-q", "--hard", "FETCH_HEAD", cwd=target, env=env)
            self._git("clean", "-qfdx", cwd=target, env=env)
        return target, self._git("rev-parse", "HEAD", cwd=target, env=env).strip()

    def _copies(self, key):
        """path -> source of the copies this collection made earlier."""
        copies = {}
        for row in self.store.rows("SELECT origin,source FROM knowledge_origins"):
            origin = json.loads(row["origin"])
            if origin.get("kind") == "collection" and origin.get("collection") == key:
                copies[origin["path"]] = row["source"]
        return copies

    def _walk(self, root):
        """Every file to look at, and what's skipped without being opened. Links are
        never followed (they could lead outside the folder), and HA's own data folder
        (settings, sign-ins) is never imported."""
        files, skipped = [], []
        root = Path(root)
        data = Path(self.store.root).resolve()
        junction = getattr(os.path, "isjunction", lambda _: False)

        def rel_of(path):
            try:
                rel = Path(path).relative_to(root).as_posix()
            except ValueError:
                rel = str(path)
            return "" if rel == "." else rel

        def unreadable(error):
            where = getattr(error, "filename", None)
            skipped.append({"path": ((rel_of(where) if where else "") or ".") + "/", "reason": "couldn't be read"})

        for current, dirs, names in os.walk(root, onerror=unreadable):
            here = Path(current)
            rel_dir = rel_of(here)
            kept = []
            for d in sorted(dirs):
                full = here / d
                rel = (rel_dir + "/" if rel_dir else "") + d + "/"
                if d in SKIP_DIRS:
                    skipped.append({"path": rel, "reason": SKIP_DIRS[d]})
                elif full.is_symlink() or junction(full):
                    skipped.append({"path": rel, "reason": "a link to another folder; links aren't followed"})
                elif full.resolve() == data:
                    skipped.append({"path": rel, "reason": "HA's own data"})
                else:
                    kept.append(d)
            dirs[:] = kept
            for name in sorted(names):
                path = here / name
                rel = (rel_dir + "/" if rel_dir else "") + name
                if path.is_symlink():
                    skipped.append({"path": rel, "reason": "a link to another file; links aren't followed"})
                else:
                    files.append((rel, path))
        return files, skipped

    def _tags(self, entry, rel, front):
        scopes = KnowledgeScopes(self.store)
        known = {t["id"] for t in scopes.catalog()["tags"]}
        labels = front if front else list(PurePosixPath(rel).parts[:-1][:2])
        labels = [entry["name"], *labels]
        result, missing = list(entry["tags"]), []
        for label in labels:
            key = tag_id(label)
            if key == "unclassified":
                continue
            if key not in known:
                try:
                    scopes.create_tag(key, label[:100])
                    known.add(key)
                except (Blocked, Conflict, ContractError):
                    missing.append(label)
                    continue
            if key not in result:
                result.append(key)
        return (result[:32] or ["unclassified"]), missing

    def _import(self, entry):
        key = entry["id"]
        commit = ""
        if entry["kind"] == "github":
            root, commit = self._checkout(entry)
        else:
            root = Path(entry["folder"])
            if not root.is_dir():
                raise Blocked("The folder isn't there any more. Check that its drive is connected.")
        self._progress(key, 20, "Looking through the files…")
        files, skipped = self._walk(root)
        documents_, images = [], {}
        for rel, path in files:
            name = path.name
            suffix = path.suffix.lower()
            try:
                size = path.stat().st_size
            except OSError:
                skipped.append({"path": rel, "reason": "couldn't be read"})
                continue
            if SECRETS.search(name):
                skipped.append({"path": rel, "reason": "may hold a password or key"})
            elif suffix in ARCHIVES or name.lower().endswith((".tar.gz", ".tar.bz2", ".tar.xz")):
                skipped.append({"path": rel, "reason": f"archive ({suffix}); unpack it to import what's inside"})
            elif suffix in IMAGES:
                images[rel] = path
            elif suffix in OLD_OFFICE:
                skipped.append({"path": rel, "reason": f"old {OLD_OFFICE[suffix]} format; save it as {'.xlsx' if suffix == '.xls' else '.docx'} to import it"})
            elif suffix in OTHER_OFFICE:
                skipped.append({"path": rel, "reason": "slides and other office formats aren't imported; save spreadsheets as .xlsx"})
            else:
                kind = kind_of(name)
                if kind is None:
                    with open(path, "rb") as f:
                        head = f.read(8192)
                    kind = "text" if looks_like_text(head) else None
                if kind is None:
                    skipped.append({"path": rel, "reason": f"binary data ({suffix or 'no extension'}), not text"})
                elif kind in PACKED and size > MAX_DOCUMENT or kind not in PACKED and size > MAX_TEXT:
                    limit = MAX_DOCUMENT if kind in PACKED else MAX_TEXT
                    skipped.append({"path": rel, "reason": f"too large ({size // 1048576} MiB; the limit is {limit // 1048576} MiB)"})
                else:
                    documents_.append((rel, path, kind))
        # Push early, check later: files their own markers say aren't checked yet are
        # imported (so they can be found) but flagged, and listed in the report.
        from hivemind_assembly.core.checks import LEDGER, waiting_in

        waiting = waiting_in(root, [rel for rel, _, _ in documents_])
        if any(rel == LEDGER for rel, _, _ in documents_):
            documents_ = [d for d in documents_ if d[0] != LEDGER]
            skipped.append({"path": LEDGER, "reason": "the list of files waiting for a check; those files are flagged"})
        if (commit and commit == entry.get("commit") and entry.get("report")
                and not entry["report"].get("failed") and entry.get("imported_with") == entry["external_allowed"]
                and not Knowledge(self.store).waiting_for_ocr(set(self._copies(key).values()))):
            return {"message": "Already up to date with GitHub."}
        knowledge = Knowledge(self.store)
        before = self._copies(key)
        used, failed, missing_tags = set(), [], set()
        counts = {"imported": 0, "updated": 0, "unchanged": 0, "removed": 0, "pictures": 0,
                  "pictures_not_described": 0, "tables": 0, "sections": 0}
        last = 0.0
        for n, (rel, path, kind) in enumerate(documents_, 1):
            if time.monotonic() - last > 0.5:
                last = time.monotonic()
                self._progress(key, 20 + 75 * n / max(1, len(documents_)), f"Importing {n} of {len(documents_)}: {rel}")
            front = None
            if kind in ("markdown", "html"):
                with open(path, "rb") as f:
                    text = documents.decode(f.read()) or ""
                fields, _ = documents.front_matter(text.replace("\r\n", "\n"))
                front = [t for k in ("tags", "tag", "categories", "category") for t in documents.as_list(fields.get(k))]
            origin = {"kind": "collection", "collection": key, "path": rel}
            earlier = knowledge.origin_source(origin)
            given = knowledge.assigned_tags(earlier) if earlier else None
            current = knowledge.scopes.tags("source", earlier) if earlier else None
            if earlier and (given is None or sorted(current) != sorted(given)):
                tags = current  # The owner (or the adviser) changed its categories; theirs stay.
            else:
                tags, lost = self._tags(entry, rel, front)
                missing_tags.update(lost)
            folder = PurePosixPath(rel).parent.as_posix()

            def image(target, folder=folder):
                found = picture_path(target, folder, images)
                if found:
                    used.add(found)
                    return images[found].read_bytes(), PurePosixPath(found).name
                return None

            allowed = self.permission.get(key, entry["external_allowed"])
            try:
                result = knowledge.ingest(path, allowed, tags, origin=origin, kind=kind, image=image, display=rel)
            except Exception as error:
                failed.append({"path": rel, "reason": str(error) or error.__class__.__name__})
                continue
            knowledge.mark_checks_pending(result["id"], rel in waiting)
            if self.permission.get(key, allowed) != allowed:
                # The owner changed the permission while this file was being read.
                with self.store.tx() as db:
                    db.execute("UPDATE sources SET external_allowed=? WHERE id=?",
                               (int(self.permission[key]), result["id"]))
            if result.get("unchanged"):
                counts["unchanged"] += 1
                if kind in ("markdown", "html"):
                    used.update(self._pictures_used(rel, folder, images, path))
            elif result.get("replaced"):
                counts["updated"] += 1
            else:
                counts["imported"] += 1
            info = result.get("counts", {})
            counts["pictures"] += info.get("pictures", 0)
            counts["pictures_not_described"] += info.get("pictures_not_described", 0)
            counts["tables"] += info.get("tables", 0)
            counts["sections"] += info.get("sections", 0)
        present = {rel for rel, _, _ in documents_} - {f["path"] for f in failed}
        for rel, source in before.items():
            if rel not in present and not any(f["path"] == rel for f in failed):
                knowledge.remove(source)
                counts["removed"] += 1
        for rel in sorted(set(images) - used):
            skipped.append({"path": rel, "reason": "picture no imported document shows"})
        # Whatever the owner chose last applies to every copy, including any read before the change.
        allowed = self.permission.get(key, entry["external_allowed"])
        self._apply_permission(key, allowed)
        skipped.sort(key=lambda x: x["path"])
        report = {
            **counts,
            "documents": len(present),
            "failed": failed,
            "skipped": skipped,
            "categories_full": sorted(missing_tags),
            "checks_pending": sorted(waiting)[:200],
            "commit": commit,
            "finished": self.clock(),
        }
        parts = [f"{len(present)} documents: {counts['imported']} new, {counts['updated']} updated, {counts['unchanged']} unchanged"]
        if counts["removed"]:
            parts.append(f"{counts['removed']} removed (gone from the {'repository' if commit else 'folder'})")
        parts.append(f"{len(skipped)} skipped")
        if failed:
            parts.append(f"{len(failed)} couldn't be read")
        message = "Imported " + "; ".join(parts) + "."
        if missing_tags:
            message += " The category list is full, so some folder names didn't become categories."
        if waiting:
            message += (f" {len(waiting)} document{'s are' if len(waiting) != 1 else ' is'} still marked “checks pending” "
                        "there; the assistants are told they're unchecked drafts.")
        return {"message": message, "report": report, "commit": commit, "last_import": self.clock(),
                "imported_with": allowed}

    def _pictures_used(self, rel, folder, images, path):
        """Pictures an unchanged Markdown file shows (so they aren't listed as unused)."""
        try:
            text = documents.decode(path.read_bytes()) or ""
        except OSError:
            return set()
        found = set()
        for bang, _, target in documents.LINK.findall(text):
            if bang:
                joined = picture_path(target, folder, images)
                if joined:
                    found.add(joined)
        return found
