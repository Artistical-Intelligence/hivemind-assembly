"""Files over GitHub's 100 MiB file limit, backed up as release assets (no AI).

A repository can't hold a file over 100 MiB, but a release asset can be up to just
under 2 GiB, and a release has no limit on its total size or bandwidth (up to 1,000
assets). Folder backups therefore upload each large file as an asset of one release
in the same repository, tag "large-files", titled "Large files backed up by HA".
Files of 2 GiB or more go up in numbered parts of about 1.9 GiB; nothing extra is
needed to split or join them.

LARGE_FILES.json in the repository records each file's path, size, SHA-256 and the
asset names of its parts. Two restore scripts in the repository, PowerShell for
Windows and Python, download the assets, join the parts back into each file at its
original path and check its SHA-256.

Older versions are never overwritten or deleted. Each asset name carries the first
12 characters of the file's SHA-256 (video.mp4.3fa9c1d2e4b7.part01), so a changed
file gets new assets and the manifest points at them; the old assets stay as the
file's history. An asset is uploaded again only when it is missing, or when an
interrupted upload left one with the wrong size.

Uploading assets needs a GitHub sign-in that Git's own window can't provide: HA's
GitHub connection, or else the GitHub CLI (gh) when it is signed in. Without either,
each large file waits, says so, and is tried again on the next upload.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath

import httpx

from hivemind_assembly.core.common import Blocked
from hivemind_assembly.integrations.github import GitHubError

RELEASE_TAG = "large-files"
RELEASE_TITLE = "Large files backed up by HA"
RELEASE_NOTES = (
    "Files too large for the repository itself (over GitHub's 100 MiB file limit), backed up "
    "by Hivemind Assembly. LARGE_FILES.json in the repository lists them. To put them back, "
    "run restore-large-files.ps1 (Windows PowerShell) or restore_large_files.py from a copy "
    "of the repository. Older versions stay here as each file's history."
)
ASSET_LIMIT = 2 * 1024**3  # A release asset must be under 2 GiB.
PART_BYTES = int(1.9 * 1024**3)  # Larger files go up in parts of about 1.9 GiB.
LFS_LIMIT = 2 * 1000**3  # Git LFS on GitHub Free stores files up to 2 GB.
MANIFEST = "LARGE_FILES.json"
SCRIPTS = ("restore-large-files.ps1", "restore_large_files.py")
MANAGED = (MANIFEST, *SCRIPTS)
WAITING = "Waiting: connect GitHub to upload this file"
API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"


def _flags():
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def script(name):
    """A restore script, exactly as committed to the repository."""
    return (Path(__file__).parent / "restore" / name).read_bytes()


def asset_base(path):
    """A file name GitHub keeps unchanged: letters, digits, dots, underscores, hyphens."""
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", PurePosixPath(path).name)
    name = re.sub(r"-*\.-*", ".", re.sub(r"-{2,}", "-", name))
    name = name.strip(".-")[:100].strip(".-")
    return name or "file"


def plan(path, size, sha256):
    """The assets for one version of a file: one under 2 GiB, else numbered parts."""
    base = f"{asset_base(path)}.{sha256[:12]}"
    if size < ASSET_LIMIT:
        return [{"name": base, "offset": 0, "size": size}]
    count = -(-size // PART_BYTES)
    width = max(2, len(str(count)))
    return [
        {
            "name": f"{base}.part{n + 1:0{width}d}",
            "offset": n * PART_BYTES,
            "size": min(PART_BYTES, size - n * PART_BYTES),
        }
        for n in range(count)
    ]


def file_sha256(path, progress=None):
    digest, done = hashlib.sha256(), 0
    with open(path, "rb") as f:
        while True:
            block = f.read(4 * 1024 * 1024)
            if not block:
                return digest.hexdigest()
            digest.update(block)
            done += len(block)
            if progress:
                progress(done)


def github_token(auth, gh=None, run=subprocess.run):
    """A GitHub token for the REST API: HA's connection first, else a signed-in GitHub CLI.

    The token is used for this upload only and never saved. Returns (token, how) or
    (None, None) when neither is available."""
    if auth is not None:
        try:
            return auth.credentials()["access_token"], "connection"
        except Exception:
            pass
    program = gh or shutil.which("gh")
    if program:
        try:
            done = run(
                [program, "auth", "token", "--hostname", "github.com"],
                capture_output=True, text=True, timeout=30, creationflags=_flags(),
            )
        except (OSError, subprocess.SubprocessError):
            return None, None
        token = (done.stdout or "").strip()
        if done.returncode == 0 and token and "\n" not in token:
            return token, "gh"
    return None, None


class ReleaseAssets:
    """The "large-files" release of one repository: find or create it, list, upload."""

    def __init__(self, token, owner, name, api=API, uploads=UPLOADS):
        self.owner, self.name = owner, name
        self.api, self.uploads = api.rstrip("/"), uploads.rstrip("/")
        self.headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Hivemind-Assembly",
            "Authorization": "Bearer " + token,
        }
        # Generous read time: GitHub may take a while to confirm a 1.9 GiB part.
        self.http = httpx.Client(timeout=httpx.Timeout(60, read=900), follow_redirects=False)

    def close(self):
        self.http.close()

    def _call(self, method, url, *, headers=None, **kw):
        try:
            response = self.http.request(method, url, headers={**self.headers, **(headers or {})}, **kw)
        except Blocked:
            raise
        except httpx.HTTPError:
            # Never show raw errors: they can carry request headers.
            raise Blocked("The connection to GitHub was interrupted. Upload now tries again.") from None
        if not 200 <= response.status_code < 300:
            raise GitHubError(response.status_code)
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            raise Blocked("GitHub returned an answer HA couldn't read. Upload now tries again.") from None

    def _repo(self, rest=""):
        return f"{self.api}/repos/{self.owner}/{self.name}{rest}"

    def repository(self):
        return self._call("GET", self._repo())

    def release(self, branch):
        """The large-files release, created the first time (not marked as Latest)."""
        try:
            return self._call("GET", self._repo(f"/releases/tags/{RELEASE_TAG}"))
        except GitHubError as error:
            if error.status != 404:
                raise
        return self._call(
            "POST",
            self._repo("/releases"),
            json={
                "tag_name": RELEASE_TAG,
                "target_commitish": branch,
                "name": RELEASE_TITLE,
                "body": RELEASE_NOTES,
                "draft": False,
                "prerelease": False,
                "make_latest": "false",
            },
        )

    def assets(self, release):
        found, page = {}, 1
        while True:
            batch = self._call(
                "GET", self._repo(f"/releases/{release['id']}/assets"), params={"per_page": 100, "page": page}
            )
            for asset in batch:
                found[asset["name"]] = asset
            if len(batch) < 100:
                return found
            page += 1

    def upload(self, release, name, path, offset, size, progress=None):
        def body():
            sent = 0
            with open(path, "rb") as f:
                f.seek(offset)
                while sent < size:
                    block = f.read(min(1024 * 1024, size - sent))
                    if not block:
                        raise Blocked("The file got shorter while uploading. Upload now tries again.")
                    sent += len(block)
                    if progress:
                        progress(sent)
                    yield block

        try:
            return self._call(
                "POST",
                f"{self.uploads}/repos/{self.owner}/{self.name}/releases/{release['id']}/assets",
                params={"name": name},
                headers={"Content-Type": "application/octet-stream", "Content-Length": str(size)},
                content=body(),
            )
        except GitHubError as error:
            if error.status == 422:
                raise Blocked(
                    f"GitHub refused {name}: the release may already hold 1,000 assets, or another upload of it is unfinished."
                ) from None
            raise

    def delete(self, asset):
        """Only for an interrupted upload's broken leftover with the same name."""
        self._call("DELETE", self._repo(f"/releases/assets/{asset['id']}"))
