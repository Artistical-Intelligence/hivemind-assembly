#!/usr/bin/env python3
"""Put back the large files that Hivemind Assembly (HA) backed up as release assets.

GitHub refuses files over 100 MiB in a repository, so HA uploads them as assets of
this repository's release named in LARGE_FILES.json (usually "large-files"). Files
of 2 GiB or more are split into numbered parts. This script reads LARGE_FILES.json,
downloads each file's assets, joins the parts back into the file at its original
path and checks its SHA-256. A file that is already there with the right SHA-256 is
left alone. Nothing else is changed.

Usage, from a copy of this repository:
    python restore_large_files.py
    python restore_large_files.py --destination "D:\\Restored copy"
    python restore_large_files.py --only "videos/intro.mp4"

A private repository needs a GitHub token: --token, the GITHUB_TOKEN or GH_TOKEN
environment variable, or a signed-in GitHub CLI (gh). Needs only Python 3.8 or later.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CHUNK = 1024 * 1024


class NoAuthRedirect(urllib.request.HTTPRedirectHandler):
    """Follow GitHub's redirect to the file's storage without sending the token there."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urllib.parse.urlsplit(newurl).netloc != urllib.parse.urlsplit(req.full_url).netloc:
            new.remove_header("Authorization")
        return new


OPENER = urllib.request.build_opener(NoAuthRedirect)


def gh_token():
    program = shutil.which("gh")
    if not program:
        return ""
    try:
        done = subprocess.run([program, "auth", "token"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def request(url, token, accept="application/vnd.github+json"):
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": "Hivemind-Assembly-restore"})
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        return OPENER.open(req, timeout=120)
    except urllib.error.HTTPError as error:
        if error.code in (401, 403, 404) and not token:
            sys.exit("GitHub didn't allow the download. For a private repository, pass --token or sign in with gh.")
        sys.exit(f"GitHub answered HTTP {error.code} for {url}")
    except (urllib.error.URLError, OSError) as error:
        sys.exit(f"Couldn't reach GitHub ({getattr(error, 'reason', error)}). Check the internet connection and try again.")


def get_json(url, token):
    with request(url, token) as response:
        return json.loads(response.read().decode("utf-8"))


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(CHUNK)
            if not block:
                return digest.hexdigest()
            digest.update(block)


def target_path(destination, relative, windows=None):
    """Where a file from the manifest goes: always inside the destination. A path that
    could lead anywhere else (absolute, a drive, '..', a backslash on Windows, or a
    link inside the destination pointing out of it) stops the restore."""
    windows = os.name == "nt" if windows is None else windows
    text = str(relative)
    parts = text.replace("\\", "/").split("/") if windows else text.split("/")
    unsafe = (
        not text
        or text.startswith(("/", "\\"))
        or any(part in ("", ".", "..") for part in parts)
        or (windows and any(":" in part for part in parts))
    )
    root = Path(destination).resolve()
    target = root.joinpath(*parts) if not unsafe else None
    if target is not None:
        try:
            target.resolve().relative_to(root)
        except ValueError:
            unsafe = True
    if unsafe:
        sys.exit(f"Refusing an unsafe path in the manifest: {relative!r}")
    return target


def main(argv=None):
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Put back the large files HA backed up as release assets.")
    parser.add_argument("--destination", default=str(here), help="folder to restore into (default: this repository's folder)")
    parser.add_argument("--manifest", default=str(here / "LARGE_FILES.json"), help="the LARGE_FILES.json to read")
    parser.add_argument("--token", default="", help="GitHub token for a private repository")
    parser.add_argument("--api", default=os.environ.get("HA_GITHUB_API", "https://api.github.com"), help=argparse.SUPPRESS)
    parser.add_argument("--only", action="append", default=[], help="restore only this path (can be repeated)")
    args = parser.parse_args(argv)

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    owner, name = manifest["repository"].split("/", 1)
    token = args.token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or gh_token()
    api = args.api.rstrip("/")
    destination = Path(args.destination)
    files = [f for f in manifest.get("files", []) if not args.only or f["path"] in args.only]
    if not files:
        print("Nothing to restore.")
        return 0
    # Every path is checked before anything is downloaded or written.
    targets = {item["path"]: target_path(destination, item["path"]) for item in files}

    release = get_json(f"{api}/repos/{owner}/{name}/releases/tags/{urllib.parse.quote(manifest['release'])}", token)
    assets, page = {}, 1
    while True:
        batch = get_json(f"{api}/repos/{owner}/{name}/releases/{release['id']}/assets?per_page=100&page={page}", token)
        for asset in batch:
            assets[asset["name"]] = asset
        if len(batch) < 100:
            break
        page += 1

    failed = 0
    for item in files:
        target = targets[item["path"]]
        if target.is_file() and target.stat().st_size == item["size"] and sha256(target) == item["sha256"]:
            print(f"Already there: {item['path']}")
            continue
        missing = [p["name"] for p in item["parts"] if p["name"] not in assets]
        if missing:
            print(f"Can't restore {item['path']}: the release has no asset {missing[0]}.")
            failed += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".restoring")
        done = 0
        with open(partial, "wb") as out:
            for number, part in enumerate(item["parts"], 1):
                asset = assets[part["name"]]
                url = f"{api}/repos/{owner}/{name}/releases/assets/{asset['id']}"
                with request(url, token, accept="application/octet-stream") as response:
                    while True:
                        block = response.read(CHUNK)
                        if not block:
                            break
                        out.write(block)
                        done += len(block)
                        print(f"\r{item['path']}: part {number} of {len(item['parts'])}, {done * 100 // max(1, item['size'])}%", end="", flush=True)
        print()
        if partial.stat().st_size != item["size"] or sha256(partial) != item["sha256"]:
            partial.unlink()
            print(f"Can't restore {item['path']}: the downloaded file doesn't match its SHA-256.")
            failed += 1
            continue
        os.replace(partial, target)
        print(f"Restored: {item['path']}")
    if failed:
        print(f"{failed} file(s) couldn't be restored.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
