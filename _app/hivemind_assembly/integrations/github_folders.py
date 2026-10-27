"""Back up a folder on this computer to a GitHub repository and keep it updated.

Automation, not AI: HA scans the folder, leaves out what GitHub should not hold, and
uploads the rest with Git. Later uploads send only what changed, by hand or on a
schedule. The folder itself is never changed: Git's records for it live in HA's data
folder, not in the folder being backed up.

Creating the repository uses HA's GitHub connection. When that is not connected,
or GitHub refuses the request, HA falls back to filling in github.com's New
repository page in its GitHub browser window (see github_web.py). Uploading then
uses Git's own GitHub sign-in (Git Credential Manager on Windows) instead of HA's.

Files over GitHub's 100 MiB file limit are backed up too, as assets of the
repository's "large-files" release, with LARGE_FILES.json and two restore scripts
in the repository (see large_files.py). With "Store large files with Git LFS
instead" they go up with Git LFS; files over Git LFS's 2 GB limit still go up as
release assets.

Safety rules:
- never force-push; changes made on GitHub in the meantime are kept, and a
  changed file from this folder becomes a new version on top of them;
- files deleted from the folder stay on GitHub unless the owner turns on
  "Also remove files I delete here", and even then they remain in GitHub's history;
- release assets are never overwritten or deleted: a changed large file gets new
  assets, and the old ones stay as its history;
- likely secrets (.env, private keys, password databases) and folders with their
  own Git history are left out and listed;
- a repository that already exists is never adopted by a Create request.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from hivemind_assembly.core.common import (
    Blocked,
    Conflict,
    ContractError,
    atomic_write,
    canonical,
    uid,
)
from hivemind_assembly.integrations import large_files
from hivemind_assembly.integrations.large_files import (
    API,
    MANAGED,
    MANIFEST,
    SCRIPTS,
    UPLOADS,
    WAITING,
    ReleaseAssets,
    file_sha256,
    github_token,
)

GITHUB_FILE_LIMIT = 100 * 1024 * 1024  # GitHub refuses larger files in a repository.
BATCH_BYTES = 512 * 1024 * 1024  # GitHub refuses pushes over 2 GiB; stay well below.
NAME = re.compile(r"[A-Za-z0-9_.-]{1,100}")
OWNER = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}")
SECRET_NAMES = re.compile(
    r"(^\.env(\..*)?$|^\.netrc$|^\.npmrc$|^\.pypirc$|^id_(rsa|dsa|ecdsa|ed25519)(\.pub)?$"
    r"|\.(pem|key|pfx|p12|keystore|jks|kdbx|ppk)$|^credentials(\.json)?$)",
    re.I,
)
PUSH_PROGRESS = re.compile(r"(?:Writing objects|Uploading LFS objects):\s+(\d+)%")
INTERVALS = (15, 60, 360, 1440)  # minutes: every 15 minutes, hour, 6 hours, day
LFS_BLOCK = "# Large files stored with Git LFS by Hivemind Assembly\n"


def _flags():
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def _ignore_line(path):
    """Exact-path Git ignore pattern for one relative POSIX path."""
    escaped = re.sub(r"([\\*?\[\]!#])", r"\\\1", path)
    if escaped.endswith(" "):
        escaped = escaped[:-1] + "\\ "
    return "/" + escaped


def _attribute_line(path):
    """Exact-path Git attributes line sending one file through Git LFS."""
    escaped = re.sub(r"([\\*?\[\]!#])", r"\\\1", path)
    # Whitespace ends a pattern in .gitattributes; [[:space:]] matches it (as git lfs track writes).
    escaped = re.sub(r"\s", "[[:space:]]", escaped)
    return "/" + escaped + " filter=lfs diff=lfs merge=lfs -text\n"


def _size(n):
    for unit, step in (("GiB", 1024**3), ("MiB", 1024**2), ("KiB", 1024)):
        if n >= step:
            return f"{n / step:.1f} {unit}"
    return f"{n} bytes"


class FolderBackups:
    def __init__(
        self, root, auth, config, web=None, submit=None, git=None, remote_url=None, clock=time.time,
        token=None, api=API, uploads=UPLOADS,
    ):
        self.dir = Path(root) / "folder-backups"
        self.path = self.dir / "backups.json"
        self.data_root = Path(root).resolve()
        self.auth, self.config, self.web, self.submit = auth, config, web, submit
        self.git_program = git
        self.remote_url = remote_url or (
            lambda owner, name: f"https://github.com/{owner}/{name}.git"
        )
        self.clock = clock
        # The GitHub sign-in for release assets: HA's connection, else a signed-in GitHub CLI.
        self.token_source = token or (lambda: github_token(self.auth))
        self.api_url, self.uploads_url = api, uploads
        self.lock = threading.RLock()
        self.running = {}
        self.monitor = None
        self.stopping = threading.Event()
        self.lfs_known = None
        self.shown = {}

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
        with self.lock:
            entries = self._load()
        shown = []
        for e in entries.values():
            item = {k: v for k, v in e.items() if k != "creating"}
            item["running"] = e["id"] in self.running and self.running[e["id"]].is_alive()
            shown.append(item)
        return sorted(shown, key=lambda e: e["created"])

    def lfs_available(self):
        """Whether Git LFS is installed, checked once (offered only when it is)."""
        if self.lfs_known is None:
            try:
                done = subprocess.run(
                    [self._git_path(), "lfs", "version"], capture_output=True, timeout=60,
                    creationflags=_flags(),
                )
                self.lfs_known = done.returncode == 0
            except Exception:
                self.lfs_known = False
        return self.lfs_known

    def _check_lfs(self, wanted):
        if wanted and not self.lfs_available():
            raise ContractError(
                "Git LFS isn't installed on this computer. Install it, or leave Store large files with Git LFS off."
            )
        return bool(wanted)

    # -------------------------------------------------------------- requests
    def add(self, data):
        if not isinstance(data, dict) or set(data) - {
            "folder", "action", "owner", "name", "description", "visibility",
            "automatic", "interval_minutes", "include_deletions", "lfs",
        }:
            raise ContractError("Unexpected folder backup settings.")
        folder = Path(str(data.get("folder", "")).strip().strip('"'))
        if not folder.is_absolute() or not folder.is_dir():
            raise ContractError("Choose a folder on this computer.")
        folder = folder.resolve()
        if folder == Path(folder.anchor):
            raise ContractError("Choose a folder, not a whole drive.")
        if folder == self.data_root or self.data_root in folder.parents:
            raise ContractError("HA's own data folder can't be backed up this way.")
        action = data.get("action", "create")
        if action not in ("create", "existing"):
            raise ContractError("Choose Create a new repository or Use an existing repository.")
        name, owner = data.get("name", ""), data.get("owner", "") or ""
        if not isinstance(name, str) or not NAME.fullmatch(name) or name in (".", ".."):
            raise ContractError("Repository name must contain 1–100 letters, numbers, dots, underscores or hyphens.")
        if not isinstance(owner, str) or owner and not OWNER.fullmatch(owner):
            raise ContractError("Invalid GitHub account or organization name.")
        description = data.get("description", "") or ""
        if not isinstance(description, str) or len(description) > 200 or any(ord(c) < 32 for c in description):
            raise ContractError("Description must be one line of at most 200 characters.")
        visibility = data.get("visibility", "private")
        if visibility not in ("private", "public"):
            raise ContractError("Visibility must be Private or Public.")
        interval = int(data.get("interval_minutes", 60) or 60)
        if interval not in INTERVALS:
            raise ContractError("Choose how often to upload changes.")
        lfs = self._check_lfs(data.get("lfs", False))
        with self.lock:
            entries = self._load()
            for e in entries.values():
                if Path(e["folder"]) == folder:
                    raise Conflict("This folder is already backed up. Use Upload now on it instead.")
                if (e["owner"] or "").lower() == owner.lower() and owner and e["name"].lower() == name.lower():
                    raise Conflict("Another folder already uploads to this repository.")
            entry = {
                "id": uid("backup"),
                "folder": str(folder),
                "action": action,
                "owner": owner,
                "name": name,
                "description": description,
                "visibility": visibility if action == "create" else "",
                "visibility_notice": "",
                "branch": "main",
                "automatic": bool(data.get("automatic", False)),
                "interval_minutes": interval,
                "include_deletions": bool(data.get("include_deletions", False)),
                "lfs": lfs,
                "repository_ready": False,
                "creating": False,
                "state": "waiting",
                "message": "Waiting to start.",
                "progress": None,
                "excluded": [],
                "large_files": [],
                "last_commit": "",
                "last_upload": 0,
                "last_check": 0,
                "created": self.clock(),
            }
            entries[entry["id"]] = entry
            self._save(entries)
        self.start(entry["id"])
        return entry

    def settings(self, key, data):
        allowed = {"automatic", "interval_minutes", "include_deletions", "lfs"}
        if not isinstance(data, dict) or set(data) - allowed:
            raise ContractError("Unexpected folder backup settings.")
        values = {}
        if "automatic" in data:
            values["automatic"] = bool(data["automatic"])
        if "include_deletions" in data:
            values["include_deletions"] = bool(data["include_deletions"])
        if "lfs" in data:
            values["lfs"] = self._check_lfs(data["lfs"])
        if "interval_minutes" in data:
            if int(data["interval_minutes"]) not in INTERVALS:
                raise ContractError("Choose how often to upload changes.")
            values["interval_minutes"] = int(data["interval_minutes"])
        entry = self._set(key, **values)
        if entry is None:
            raise ContractError("Unknown folder backup.")
        return entry

    def remove(self, key):
        """Forget a backup: GitHub's copy and the folder itself are left as they are."""
        with self.lock:
            if key in self.running and self.running[key].is_alive():
                raise Blocked("Wait for the upload in progress to finish first.")
            entries = self._load()
            if entries.pop(key, None) is None:
                raise ContractError("Unknown folder backup.")
            self._save(entries)
        shutil.rmtree(self.dir / (key + ".git"), ignore_errors=True)
        return {"removed": True}

    def start(self, key):
        with self.lock:
            if key not in self._load():
                raise ContractError("Unknown folder backup.")
            thread = self.running.get(key)
            if thread and thread.is_alive():
                return {"started": False, "message": "Already uploading."}
            thread = threading.Thread(target=self._run, args=(key,), daemon=True)
            self.running[key] = thread
            self._set(key, state="uploading", message="Starting…", progress={"percent": 0, "text": "Starting…"})
            thread.start()
        return {"started": True}

    def start_monitor(self, every=60):
        def loop():
            while not self.stopping.wait(every):
                try:
                    self.due()
                except Exception:
                    pass  # Shown on the backup itself when an upload fails.

        if self.monitor is None:
            self.monitor = threading.Thread(target=loop, daemon=True)
            self.monitor.start()

    def due(self):
        now = self.clock()
        started = []
        for e in self.view():
            if (
                e["automatic"]
                and e["repository_ready"]
                and not e["running"]
                and now - max(e["last_check"], e["last_upload"]) >= e["interval_minutes"] * 60
            ):
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
            if not entry["repository_ready"]:
                self._progress(key, 2, "Preparing the GitHub repository…")
                self._prepare_repository(entry)
                entry = self._load()[key]
            result = self._upload(entry)
            self._set(key, progress=None, last_check=self.clock(), **{"state": "done", **result})
        except Exception as error:
            message = str(error) or error.__class__.__name__
            self._set(key, state="failed", progress=None, message=message, last_check=self.clock())

    def _client(self):
        """HA's GitHub connection, or None when it isn't connected."""
        from hivemind_assembly.integrations.github import GitHubClient

        if self.auth is None:
            return None, None
        try:
            client = GitHubClient(self.auth)
            return client, client.identity()
        except Blocked:
            return None, None

    def _prepare_repository(self, e):
        client, user = self._client()
        github = self.config.get("github", {})
        if e["action"] == "create" and not github.get("allow_repository_creation", False):
            raise Blocked("Turn on Let HA create repositories under Settings, GitHub first.")
        if client:
            owner = e["owner"] or user["login"]
            allowed = {user["login"].lower(), *(o.lower() for o in github.get("allowed_organizations", []))}
            if owner.lower() not in allowed:
                raise Blocked("That owner isn't your account or an organization allowed under Settings, GitHub.")
            self._set(e["id"], owner=owner, login=user["login"])
            if e["action"] == "existing":
                repo = client.lookup(owner, e["name"])
                if repo is None:
                    raise Blocked(f"{owner}/{e['name']} wasn't found, or your GitHub connection can't see it.")
                if repo.get("permissions", {}).get("push") is not True or repo.get("archived"):
                    raise Blocked(f"HA can't add files to {owner}/{e['name']} with your GitHub connection.")
                visibility = "public" if repo.get("private") is False else "private"
                self._set(e["id"], repository_ready=True, visibility=visibility, created_with="existing")
                return
            if self._create_with_connection(e, client, user, owner):
                return
        elif e["action"] == "existing":
            # Without HA's connection, Git's own sign-in checks access when uploading.
            self._set(e["id"], repository_ready=True, created_with="existing")
            return
        self._create_with_browser(self._load()[e["id"]])

    def _create_with_connection(self, e, client, user, owner):
        from hivemind_assembly.integrations.github import GitHubError

        name, private = e["name"], e["visibility"] == "private"
        repo = client.lookup(owner, name)
        if repo is not None:
            if not e.get("creating"):
                raise Conflict(
                    f"{owner}/{name} already exists. Choose another name, or choose Use an existing repository."
                )
            return self._accept(e, repo, "github")  # Our earlier request did create it.
        self._set(e["id"], creating=True)
        try:
            repo = client.create(
                owner, name, e["description"],
                organization=owner.lower() != user["login"].lower(),
                private=private,
            )
        except GitHubError as error:
            if error.status in (401, 403, 404) and self.web is not None:
                self._set(e["id"], creating=False)
                return False  # Fall back to github.com's own page.
            if error.status == 422:
                self._set(e["id"], creating=False)
            raise
        except Exception:
            repo = client.lookup(owner, name)
            if repo is None:
                raise Blocked(
                    "GitHub's answer was lost. Upload now checks again before creating anything."
                ) from None
        return self._accept(e, repo, "github")

    def _accept(self, e, repo, how):
        wanted = e["visibility"] or "private"
        if not isinstance(repo, dict) or repo.get("private") is not (wanted == "private"):
            raise Conflict(f"GitHub didn't confirm a {wanted} repository; nothing was uploaded.")
        self._set(e["id"], repository_ready=True, creating=False, created_with=how)
        return True

    def _create_with_browser(self, e):
        if self.web is None or self.submit is None:
            raise Blocked("Connect GitHub under Settings, GitHub first.")
        self._progress(e["id"], 4, "Creating the repository on github.com in HA's GitHub window…")
        owner, name = e["owner"], e["name"]
        if e.get("creating") and owner and self.submit(self.web.exists(owner, name)).result(timeout=180):
            self._set(e["id"], repository_ready=True, creating=False, created_with="browser")
            return
        self._set(e["id"], creating=True)
        created = self.submit(
            self.web.create(owner, name, e["description"], e["visibility"] or "private")
        ).result(timeout=300)
        self._set(
            e["id"], owner=created["owner"], repository_ready=True, creating=False, created_with="browser"
        )

    # ------------------------------------------------------------------- Git
    def _git_path(self):
        program = self.git_program or shutil.which("git")
        if not program:
            raise Blocked("Git isn't installed. Use Install required tools under Settings first.")
        return program

    def _environment(self, e):
        env = {**os.environ, "LC_ALL": "C"}
        for name in [k for k in env if k.startswith("GIT_CONFIG_")]:
            env.pop(name)
        client, user = self._client()
        if client:
            # HA's connection signs Git in for this command only; nothing is saved.
            # Without it, Git's own sign-in (Git Credential Manager's window) is
            # used, so prompts stay allowed in that case.
            token = self.auth.credentials()["access_token"]
            basic = base64.b64encode(f"{user['login']}:{token}".encode()).decode()
            env.update({
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_CONFIG_COUNT": "2",
                "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
                "GIT_CONFIG_VALUE_0": "AUTHORIZATION: basic " + basic,
                "GIT_CONFIG_KEY_1": "credential.helper",
                "GIT_CONFIG_VALUE_1": "",
            })
        return env

    def _git(self, e, *args, env=None, check=True, input=None, timeout=3600, stderr_lines=None):
        gitdir = self.dir / (e["id"] + ".git")
        # Literal paths: a file named like a pattern (a*b.txt) is only that file.
        command = [self._git_path(), "--literal-pathspecs", "--git-dir", str(gitdir), "--work-tree", e["folder"], *args]
        if stderr_lines is None:
            result = subprocess.run(
                command, cwd=e["folder"], env=env, input=input, capture_output=True,
                timeout=timeout, creationflags=_flags(),
            )
            if check and result.returncode:
                raise Blocked(self._explain(result.stderr.decode("utf-8", "replace")))
            return result
        process = subprocess.Popen(
            command, cwd=e["folder"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            creationflags=_flags(),
        )
        text = []
        buffer = b""
        while True:
            chunk = process.stderr.read(256)
            if not chunk:
                break
            buffer += chunk
            *parts, buffer = re.split(rb"[\r\n]", buffer)
            for part in parts:
                line = part.decode("utf-8", "replace")
                text.append(line)
                stderr_lines(line)
        process.wait(timeout=timeout)
        if check and process.returncode:
            raise Blocked(self._explain("\n".join(text)))
        return process

    @staticmethod
    def _explain(stderr):
        lowered = stderr.lower()
        if "over its data quota" in lowered or "exceeded its lfs" in lowered or "lfs" in lowered and "budget" in lowered:
            return (
                "GitHub refused the Git LFS upload: this account's Git LFS storage or bandwidth for the month is used up. "
                "Turn off Store large files with Git LFS to back them up as release assets instead, or wait until next month."
            )
        if "authentication failed" in lowered or "could not read username" in lowered or "403" in lowered:
            return "GitHub didn't accept the sign-in for uploading. Connect GitHub under Settings, or sign in when Git asks, then Upload now."
        if "non-fast-forward" in lowered or "fetch first" in lowered:
            return "GitHub changed while uploading. Upload now again; HA keeps those changes."
        if "repository not found" in lowered:
            return "GitHub says the repository doesn't exist or this sign-in can't reach it."
        lines = [l for l in stderr.strip().splitlines() if l.strip()]
        return "Git: " + (lines[-1] if lines else "the command failed.")

    def _init(self, e, env):
        gitdir = self.dir / (e["id"] + ".git")
        if (gitdir / "HEAD").exists():
            return
        gitdir.parent.mkdir(parents=True, exist_ok=True)
        made = subprocess.run(
            [self._git_path(), "init", "--bare", "-q", str(gitdir)],
            env=env, capture_output=True, creationflags=_flags(),
        )
        if made.returncode:
            raise Blocked(self._explain(made.stderr.decode("utf-8", "replace")))
        for key, value in (
            ("core.bare", "false"),
            ("core.autocrlf", "false"),
            ("core.safecrlf", "false"),
            ("core.longpaths", "true"),
            ("core.quotepath", "false"),
            ("core.precomposeunicode", "true"),
        ):
            self._git(e, "config", key, value, env=env)

    def _scan(self, e):
        """Walk the folder; return what to leave out, the large files, and what's kept."""
        folder = Path(e["folder"])
        excluded, large, kept, files = [], [], 0, 0
        last = time.monotonic()
        for current, dirs, names in os.walk(folder):
            here = Path(current)
            rel_dir = here.relative_to(folder).as_posix()
            if rel_dir != "." and (here / ".git").exists():
                excluded.append({
                    "path": rel_dir + "/",
                    "reason": "has its own Git history; back it up separately",
                    "separate": str(here),
                })
                dirs[:] = []
                continue
            if here.resolve() == self.data_root:
                excluded.append({"path": rel_dir + "/", "reason": "HA's own data"})
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs if d != ".git"]
            for name in names:
                path = here / name
                rel = (path.relative_to(folder)).as_posix()
                try:
                    stat = path.lstat()
                except OSError:
                    excluded.append({"path": rel, "reason": "couldn't be read"})
                    continue
                if SECRET_NAMES.search(name):
                    excluded.append({"path": rel, "reason": "may hold a password or key"})
                elif stat.st_size > GITHUB_FILE_LIMIT and not path.is_symlink():
                    large.append({"path": rel, "size": stat.st_size, "mtime": stat.st_mtime_ns})
                else:
                    kept += stat.st_size
                    files += 1
            if time.monotonic() - last > 1:
                last = time.monotonic()
                self._progress(e["id"], 8, f"Looking through the folder: {files + len(large)} files so far…")
        return excluded, sorted(large, key=lambda f: f["path"]), kept, files

    def _tracked(self, e, env, path):
        return self._git(e, "ls-files", "--error-unmatch", "--", path, env=env, check=False).returncode == 0

    def _index_bytes(self, e, env, path):
        shown = self._git(e, "show", ":" + path, env=env, check=False)
        return shown.stdout if shown.returncode == 0 else None

    def _stage(self, e, env, path, data):
        """Put HA's own file (manifest, restore script, .gitattributes) in the next commit
        without writing it into the folder being backed up."""
        blob = self._git(e, "hash-object", "-w", "--stdin", env=env, input=data).stdout.decode().strip()
        listed = self._git(e, "ls-files", "-s", "--", path, env=env).stdout.decode().split()
        if len(listed) >= 2 and listed[1] == blob:
            return False
        self._git(e, "update-index", "--add", "--cacheinfo", f"100644,{blob},{path}", env=env)
        return True

    def _staged(self, e, env):
        return self._git(e, "diff", "--cached", "--quiet", env=env, check=False).returncode == 1

    def _push(self, e, env, branch, key, start, span, label=""):
        def show(line):
            found = PUSH_PROGRESS.search(line)
            if found:
                what = "Uploading large files with Git LFS" if "LFS" in line else "Uploading"
                self._progress(key, start + span * int(found.group(1)) / 100, f"{what}{label}: {found.group(1)}%")

        self._git(e, "push", "--progress", "origin", f"HEAD:refs/heads/{branch}", env=env, stderr_lines=show)

    def _lfs_setup(self, e, env, files):
        """Send the given large files through Git LFS; clones get them via .gitattributes."""
        gitdir = self.dir / (e["id"] + ".git")
        hook = gitdir / "hooks" / "pre-push"
        if not hook.exists() or "lfs" not in hook.read_text(encoding="utf-8", errors="replace"):
            self._git(e, "lfs", "install", "--local", "--force", env=env)
        lines = "".join(_attribute_line(f["path"]) for f in files)
        (gitdir / "info").mkdir(parents=True, exist_ok=True)
        (gitdir / "info" / "attributes").write_text(lines, encoding="utf-8")
        own = Path(e["folder"]) / ".gitattributes"
        mine = own.read_bytes() if own.is_file() else b""
        if mine and not mine.endswith(b"\n"):
            mine += b"\n"
        content = mine + ((LFS_BLOCK + lines).encode() if lines else b"")
        if content and self._stage(e, env, ".gitattributes", content):
            return True
        return False

    def _upload(self, e, retry=True):
        key = e["id"]
        env = self._environment(e)
        self._init(e, env)
        owner = e["owner"] or e.get("login") or ""
        if not owner:
            raise Blocked("Type the GitHub owner for this repository.")
        url = self.remote_url(owner, e["name"])
        remotes = self._git(e, "remote", env=env).stdout.decode().split()
        self._git(e, "remote", "set-url" if "origin" in remotes else "add", "origin", url, env=env)
        email = f"{owner}@users.noreply.github.com"  # Never the owner's own address.
        identity = ["-c", "user.name=Hivemind Assembly", "-c", f"user.email={email}"]
        folder = Path(e["folder"])

        self._progress(key, 5, "Looking through the folder…")
        excluded, large, kept_bytes, kept_files = self._scan(e)
        lfs = bool(e.get("lfs")) and self.lfs_available()
        notes = []
        if e.get("lfs") and not lfs:
            notes.append("Git LFS isn't installed, so large files went up as release assets.")
        lfs_files = [f for f in large if lfs and f["size"] <= large_files.LFS_LIMIT]
        asset_files = [f for f in large if f not in lfs_files]

        self._progress(key, 15, "Checking GitHub's copy…")
        branch = e["branch"]
        listed = self._git(e, "ls-remote", "origin", f"refs/heads/{branch}", env=env, timeout=600)
        remote = listed.stdout.decode().split()[0] if listed.stdout.strip() else ""
        ours = self._git(e, "rev-parse", "--verify", "-q", f"refs/heads/{branch}", env=env, check=False)
        ours = ours.stdout.decode().strip() if ours.returncode == 0 else ""
        if remote and remote != ours:
            # GitHub has commits HA doesn't: start from GitHub's latest version.
            self._git(e, "fetch", "-q", "--no-tags", "--depth=1", "origin",
                      f"+refs/heads/{branch}:refs/remotes/origin/{branch}", env=env)
            self._git(e, "update-ref", f"refs/heads/{branch}", remote, env=env)
            self._git(e, "read-tree", remote, env=env)
        elif not remote and ours:
            # GitHub's branch is gone or empty: upload everything again as a fresh start.
            self._git(e, "update-ref", "-d", f"refs/heads/{branch}", env=env)
            self._git(e, "read-tree", "--empty", env=env)
        self._git(e, "symbolic-ref", "HEAD", f"refs/heads/{branch}", env=env)

        # Release assets for large files come with HA's list of them and two restore scripts.
        managed = bool(asset_files) or self._tracked(e, env, MANIFEST)
        if managed:
            for name in MANAGED:
                if (folder / name).is_file():
                    excluded.append({
                        "path": name,
                        "reason": "HA keeps its list of large files under this name; rename yours to back it up",
                    })
        exclude_file = self.dir / (key + ".git") / "info" / "exclude"
        exclude_file.parent.mkdir(parents=True, exist_ok=True)
        exclude_file.write_text(
            "".join(_ignore_line(x["path"].rstrip("/")) + "\n" for x in excluded)
            + "".join(_ignore_line(f["path"]) + "\n" for f in asset_files),
            encoding="utf-8",
        )
        attributes = self.dir / (key + ".git") / "info" / "attributes"
        attributes_staged = False
        if lfs:
            attributes_staged = self._lfs_setup(e, env, lfs_files)
        elif attributes.exists():
            attributes.write_text("", encoding="utf-8")

        self._progress(key, 20, "Finding new and changed files…")
        status = self._git(e, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignore-submodules=all",
                           env=env).stdout.decode("utf-8", "surrogateescape")
        skip = set(MANAGED) if managed else set()
        if lfs:
            skip.add(".gitattributes")
        changed, deleted = [], []
        parts = status.split("\0")
        i = 0
        while i < len(parts):
            item = parts[i]
            i += 1
            if len(item) < 4:
                continue
            code, path = item[:2], item[3:]
            if code[0] == "R":
                i += 1  # Renames carry the old path next; not produced for untracked files.
            if path in skip:
                continue
            if "D" in code:
                deleted.append(path)
            else:
                changed.append(path)
        if not e["include_deletions"]:
            deleted = []
        end = 60 if asset_files else 100
        uploaded_any = False
        stamp = time.strftime("%Y-%m-%d %H:%M")
        if changed or deleted or attributes_staged:
            batches, current, size = [], [], 0
            for path in changed:
                try:
                    bytes_ = (folder / path).lstat().st_size
                except OSError:
                    bytes_ = 0
                if path in {f["path"] for f in lfs_files}:
                    bytes_ = 200  # Git sends a small pointer; Git LFS uploads the file itself.
                if current and size + bytes_ > BATCH_BYTES:
                    batches.append(current)
                    current, size = [], 0
                current.append(path)
                size += bytes_
            if current or deleted or not batches:
                batches.append(current)
            try:
                for n, batch in enumerate(batches, 1):
                    start = 25 + (end - 25) * (n - 1) / len(batches)
                    span = (end - 25) / len(batches)
                    label = f" (part {n} of {len(batches)})" if len(batches) > 1 else ""
                    self._progress(key, start, f"Preparing files{label}…")
                    if batch:
                        self._git(e, "add", "--pathspec-from-file=-", "--pathspec-file-nul", env=env,
                                  input=b"\0".join(p.encode("utf-8", "surrogateescape") for p in batch))
                    if n == len(batches) and deleted:
                        self._git(e, "rm", "-q", "--cached", "--ignore-unmatch", "--pathspec-from-file=-",
                                  "--pathspec-file-nul", env=env,
                                  input=b"\0".join(p.encode("utf-8", "surrogateescape") for p in deleted))
                    if not self._staged(e, env):
                        continue
                    message = f"Backup from {folder.name} on {stamp}{label}"
                    self._git(e, *identity, "commit", "-q", "--no-verify", "-m", message, env=env)
                    self._push(e, env, branch, key, start, span, label)
                    uploaded_any = True
            except Blocked as error:
                if retry and "changed while uploading" in str(error):
                    return self._upload(self._load()[key], retry=False)
                raise
        statuses = [
            {"path": f["path"], "size": f["size"], "mtime": f["mtime"], "status": "lfs",
             "percent": 100, "message": "Stored with Git LFS"}
            for f in lfs_files
        ]
        manifest_pushed = False
        if managed:
            try:
                asset_statuses, manifest_pushed = self._large_assets(
                    e, env, identity, owner, branch, asset_files, bool(remote) or uploaded_any, key, end
                )
            except Blocked as error:
                if retry and "changed while uploading" in str(error):
                    return self._upload(self._load()[key], retry=False)
                raise
            statuses += asset_statuses
        visibility = self._record_visibility(e, owner)
        waiting = [s for s in statuses if s["status"] == "waiting"]
        failed = [s for s in statuses if s["status"] == "failed"]
        uploaded = [s for s in statuses if s.get("uploaded_now")]
        removed = f", removed {len(deleted)}" if deleted else ""
        if changed or deleted:
            message = f"Uploaded {len(changed)} new or changed files{removed}."
        elif uploaded or manifest_pushed:
            message = "Uploaded large files."
        else:
            message = "Up to date: nothing new to upload."
        if uploaded:
            message += f" {len(uploaded)} large file{'s' if len(uploaded) > 1 else ''} uploaded as release assets."
        if waiting:
            message += f" {len(waiting)} large file{'s are' if len(waiting) > 1 else ' is'} waiting: connect GitHub under Settings to upload {'them' if len(waiting) > 1 else 'it'}."
        if failed:
            message += f" {len(failed)} large file{'s' if len(failed) > 1 else ''} couldn't be uploaded; see Large files."
        message = " ".join([message, *notes, *([visibility] if visibility else [])])
        for s in statuses:
            s.pop("uploaded_now", None)
        head = self._git(e, "rev-parse", "--verify", "-q", "HEAD", env=env, check=False)
        result = {
            "state": "attention" if failed else "waiting" if waiting else "done",
            "message": message,
            "excluded": excluded,
            "large_files": statuses,
            "files": kept_files,
            "bytes": kept_bytes,
            "url": f"https://github.com/{owner}/{e['name']}",
        }
        if changed or deleted or uploaded or manifest_pushed:
            result["last_upload"] = self.clock()
        if head.returncode == 0:
            result["last_commit"] = head.stdout.decode().strip()
        return result

    # -------------------------------------------------------- large files
    def _show_large(self, key, statuses, percent, text, force=False):
        """Progress for the large files, written at most twice a second."""
        now = time.monotonic()
        if not force and now - self.shown.get(key, 0) < 0.5:
            return
        self.shown[key] = now
        self._set(
            key,
            large_files=[{k: v for k, v in s.items() if k != "uploaded_now"} for s in statuses],
            progress={"percent": max(0, min(100, int(percent))), "text": text},
            message=text,
        )

    def _large_assets(self, e, env, identity, owner, branch, files, remote_exists, key, start):
        """Upload large files as release assets and keep LARGE_FILES.json up to date."""
        folder = Path(e["folder"])
        previous = {s["path"]: s for s in e.get("large_files", [])}
        try:
            old = json.loads(self._index_bytes(e, env, MANIFEST) or b"{}")
        except ValueError:
            old = {}
        old_entries = {f["path"]: f for f in old.get("files", []) if isinstance(f, dict) and "path" in f}
        token, how = self.token_source() if files else (None, None)
        statuses = []
        for f in files:
            prior = previous.get(f["path"], {})
            same = prior.get("sha256") and prior.get("size") == f["size"] and prior.get("mtime") == f["mtime"]
            status = {
                "path": f["path"], "size": f["size"], "mtime": f["mtime"],
                "sha256": prior["sha256"] if same else "", "parts": prior.get("parts", 0) if same else 0,
                "status": "waiting", "percent": 0, "message": WAITING,
            }
            if not token and same and prior.get("status") == "uploaded":
                status.update(status="uploaded", percent=100, message=prior.get("message", "Uploaded"))
            statuses.append(status)
        versions = {}
        span = 97 - start
        if token:
            if not remote_exists:
                # A release needs a commit to point at: put the restore scripts up first.
                self._commit_manifest(e, env, identity, branch, key, old_entries, owner, start)
            api = ReleaseAssets(token, owner, e["name"], self.api_url, self.uploads_url)
            release, assets = None, None
            try:
                for n, (f, status) in enumerate(zip(files, statuses)):
                    share = span / max(1, len(files))
                    base = start + share * n
                    path = folder / f["path"]
                    try:
                        if not status["sha256"]:
                            status.update(status="checking", percent=0, message="Checking…")

                            def hashing(done, status=status, base=base, share=share, f=f):
                                status["percent"] = int(done * 100 / max(1, f["size"]))
                                self._show_large(key, statuses, base + share * 0.2 * done / max(1, f["size"]),
                                                 f"Checking large file {f['path']}: {status['percent']}%")

                            status["sha256"] = file_sha256(path, hashing)
                        planned = large_files.plan(f["path"], f["size"], status["sha256"])
                        status["parts"] = len(planned)
                        if release is None:
                            release = api.release(branch)
                            assets = api.assets(release)
                        sent_before = 0
                        for number, part in enumerate(planned, 1):
                            have = assets.get(part["name"])
                            if have and have.get("size") == part["size"] and have.get("state", "uploaded") == "uploaded":
                                sent_before += part["size"]
                                continue
                            if have:
                                api.delete(have)  # An interrupted upload's broken leftover, never an old version.
                            label = f"part {number} of {len(planned)}, " if len(planned) > 1 else ""

                            def sending(sent, status=status, base=base, share=share, f=f, label=label, before=sent_before):
                                done = before + sent
                                status["percent"] = int(done * 100 / max(1, f["size"]))
                                self._show_large(key, statuses, base + share * (0.2 + 0.8 * done / max(1, f["size"])),
                                                 f"Uploading large file {f['path']}: {label}{status['percent']}%")

                            status.update(status="uploading", message="Uploading…")
                            got = api.upload(release, part["name"], path, part["offset"], part["size"], sending)
                            if got.get("size") != part["size"]:
                                raise Blocked(f"GitHub kept {part['name']} with a different size. Upload now tries again.")
                            part["name"] = got.get("name") or part["name"]
                            assets[part["name"]] = got
                            sent_before += part["size"]
                            status["uploaded_now"] = True
                        now = path.stat()
                        if now.st_size != f["size"] or now.st_mtime_ns != f["mtime"]:
                            raise Blocked("The file changed while uploading. Upload now tries again.")
                        versions[f["path"]] = {
                            "path": f["path"], "size": f["size"], "sha256": status["sha256"],
                            "parts": [{"name": p["name"], "size": p["size"]} for p in planned],
                        }
                        status.update(
                            status="uploaded", percent=100,
                            message="Uploaded" if len(planned) == 1 else f"Uploaded in {len(planned)} parts",
                        )
                    except Exception as error:
                        status.update(status="failed", message=str(error) or error.__class__.__name__)
                    self._show_large(key, statuses, base + share, f"Large files: {n + 1} of {len(files)} done", force=True)
            finally:
                api.close()
        entries = self._manifest_entries(e, files, versions, old_entries)
        pushed = self._commit_manifest(e, env, identity, branch, key, entries, owner, 97)
        return statuses, pushed

    def _manifest_entries(self, e, files, versions, old_entries):
        """Each large file's current version; older versions are kept as its history."""
        folder = Path(e["folder"])
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.clock()))
        current = {f["path"] for f in files}
        entries = {}
        for path in sorted(current | set(old_entries)):
            old = old_entries.get(path)
            new = versions.get(path)
            if path in current:
                if new and old and old.get("sha256") != new["sha256"]:
                    earlier = {k: old[k] for k in ("sha256", "size", "parts", "uploaded") if k in old}
                    entries[path] = {**new, "uploaded": stamp, "previous": [earlier, *old.get("previous", [])]}
                elif new and old:
                    entries[path] = {**old, "parts": new["parts"]}
                elif new:
                    entries[path] = {**new, "uploaded": stamp}
                elif old:
                    entries[path] = old  # Waiting or failed: the earlier version stays restorable.
            elif old and not (folder / path).exists() and not e["include_deletions"]:
                entries[path] = old  # Deleted here: kept, like Git keeps deleted files.
            # Otherwise it's no longer a large file here; its assets stay in the release.
        return entries

    def _commit_manifest(self, e, env, identity, branch, key, entries, owner, percent):
        """Stage LARGE_FILES.json and the restore scripts; commit and push when changed."""
        manifest = {
            "about": large_files.RELEASE_NOTES,
            "format": 1,
            "repository": f"{owner}/{e['name']}",
            "release": large_files.RELEASE_TAG,
            "restore": {"windows": SCRIPTS[0], "python": SCRIPTS[1]},
            "files": [entries[p] for p in sorted(entries)],
        }
        changed = self._stage(e, env, MANIFEST, (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode())
        for name in SCRIPTS:
            changed = self._stage(e, env, name, large_files.script(name)) or changed
        if not changed or not self._staged(e, env):
            return False
        self._progress(key, percent, "Saving the list of large files…")
        message = f"Large files list from {Path(e['folder']).name} on {time.strftime('%Y-%m-%d %H:%M')}"
        self._git(e, *identity, "commit", "-q", "--no-verify", "-m", message, env=env)
        self._push(e, env, branch, key, percent, 99 - percent)
        return True

    def _record_visibility(self, e, owner):
        """Record the visibility GitHub shows on each upload; say so when it changed."""
        token, how = self.token_source()
        if not token:
            return ""
        api = ReleaseAssets(token, owner, e["name"], self.api_url, self.uploads_url)
        try:
            repo = api.repository()
        except Exception:
            return ""
        finally:
            api.close()
        if repo.get("private") not in (True, False):
            return ""
        seen = "private" if repo["private"] else "public"
        before = e.get("visibility") or ""
        notice = ""
        if before and before != seen:
            notice = f"This repository is now {seen} on GitHub."
        self._set(
            e["id"], visibility=seen, visibility_checked=self.clock(),
            **({"visibility_notice": notice} if notice else {}),
        )
        return notice
