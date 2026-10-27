"""Large files in folder backups: release assets, LARGE_FILES.json, restore scripts and Git LFS.

GitHub's release API is played by a local stand-in server (api and uploads), and
GitHub's Git side by a local bare repository. Sizes are scaled down: files over
5000 bytes count as large, assets must be under 20000 bytes, parts are 8000 bytes.
"""

import json
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from hivemind_assembly.integrations import github_folders, large_files
from hivemind_assembly.integrations.github_folders import FolderBackups

TOKEN = "test-token"


def git(*args, cwd=None):
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout


class ReleaseAPI:
    """A stand-in for GitHub's repository, release and asset endpoints."""

    def __init__(self, remote, owner="owner", name="backup"):
        self.remote, self.owner, self.name = remote, owner, name
        self.private = True
        self.releases, self.assets = {}, {}
        self.uploads, self.deleted, self.created = [], [], []
        self.next = 1
        api = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status, body=None, headers=None):
                data = b"" if body is None else json.dumps(body).encode()
                self.send_response(status)
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                if body is not None:
                    self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def route(self, method):
                parts = urlsplit(self.path)
                path, query = parts.path, parse_qs(parts.query)
                if path.startswith("/storage/"):
                    # Like real storage: a token sent here is an error.
                    if self.headers.get("Authorization"):
                        return self.reply(400, {"message": "Only one auth mechanism allowed"})
                    asset = api.assets[int(path.rsplit("/", 1)[1])]
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(asset["data"])))
                    self.end_headers()
                    self.wfile.write(asset["data"])
                    return None
                if self.headers.get("Authorization") != "Bearer " + TOKEN:
                    return self.reply(401, {"message": "Bad credentials"})
                base = f"/repos/{api.owner}/{api.name}"
                if method == "GET" and path == base:
                    return self.reply(200, {"full_name": f"{api.owner}/{api.name}", "private": api.private})
                if method == "GET" and path == base + "/releases/tags/large-files":
                    found = [r for r in api.releases.values() if r["tag_name"] == "large-files"]
                    return self.reply(200, found[0]) if found else self.reply(404, {"message": "Not Found"})
                if method == "POST" and path == base + "/releases":
                    body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                    if not git("--git-dir", str(api.remote), "for-each-ref", "refs/heads").strip():
                        return self.reply(422, {"message": "Repository is empty."})
                    release = {"id": api.next, **body}
                    api.next += 1
                    api.releases[release["id"]] = release
                    api.created.append(body)
                    return self.reply(201, release)
                if method == "GET" and path.startswith(base + "/releases/") and path.endswith("/assets"):
                    release = int(path.split("/")[-2])
                    listed = [
                        {k: v for k, v in a.items() if k != "data"}
                        for a in api.assets.values()
                        if a["release"] == release
                    ]
                    page, per = int(query.get("page", ["1"])[0]), int(query.get("per_page", ["30"])[0])
                    return self.reply(200, listed[(page - 1) * per : page * per])
                if method == "POST" and path.startswith(base + "/releases/") and path.endswith("/assets"):
                    release, name = int(path.split("/")[-2]), query["name"][0]
                    data = self.rfile.read(int(self.headers["Content-Length"]))
                    if any(a["name"] == name and a["release"] == release for a in api.assets.values()):
                        return self.reply(422, {"message": "already_exists"})
                    asset = {"id": api.next, "name": name, "size": len(data), "state": "uploaded",
                             "release": release, "data": data}
                    api.next += 1
                    api.assets[asset["id"]] = asset
                    api.uploads.append(name)
                    return self.reply(201, {k: v for k, v in asset.items() if k != "data"})
                if path.startswith(base + "/releases/assets/"):
                    key = int(path.rsplit("/", 1)[1])
                    if method == "DELETE":
                        api.deleted.append(api.assets.pop(key)["name"])
                        return self.reply(204)
                    if key not in api.assets:
                        return self.reply(404, {"message": "Not Found"})
                    # Downloads go to storage on another host, as GitHub's do.
                    host = "localhost" if self.headers["Host"].startswith("127.0.0.1") else "127.0.0.1"
                    port = self.server.server_address[1]
                    return self.reply(302, headers={"Location": f"http://{host}:{port}/storage/{key}"})
                return self.reply(404, {"message": "Not Found"})

            def do_GET(self):
                self.route("GET")

            def do_POST(self):
                self.route("POST")

            def do_DELETE(self):
                self.route("DELETE")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def names(self):
        return sorted(a["name"] for a in self.assets.values())

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(github_folders, "GITHUB_FILE_LIMIT", 5000)
    monkeypatch.setattr(large_files, "ASSET_LIMIT", 20000)
    monkeypatch.setattr(large_files, "PART_BYTES", 8000)
    folder = tmp_path / "Project"
    (folder / "media").mkdir(parents=True)
    (folder / "notes.md").write_text("# Notes\n")
    (folder / "media" / "video.mp4").write_bytes(bytes(range(256)) * 24)  # 6144 bytes: one asset
    (folder / "disk image.iso").write_bytes(bytes((n * 7) % 251 for n in range(30000)))  # 4 parts
    remote = tmp_path / "github" / "owner" / "backup.git"
    remote.parent.mkdir(parents=True)
    git("init", "--bare", "-q", str(remote))
    api = ReleaseAPI(remote)
    signed_in = {"token": (TOKEN, "connection")}
    backups = FolderBackups(
        tmp_path / "state",
        None,
        {"github": {}},
        remote_url=lambda owner, name: str(remote),
        token=lambda: signed_in["token"],
        api=api.url,
        uploads=api.url,
    )
    yield folder, remote, api, backups, signed_in
    api.close()


def backup(backups, folder, **extra):
    entry = backups.add({"folder": str(folder), "action": "existing", "owner": "owner", "name": "backup", **extra})
    backups.running[entry["id"]].join(120)
    return backups._load()[entry["id"]]


def upload(backups, key):
    backups.start(key)
    backups.running[key].join(120)
    return backups._load()[key]


def tree(remote):
    return set(git("--git-dir", str(remote), "ls-tree", "-r", "--name-only", "main").split("\n")) - {""}


def manifest(remote):
    return json.loads(git("--git-dir", str(remote), "show", "main:LARGE_FILES.json"))


def checkout(remote, where):
    """What someone gets from GitHub: the repository's files, without the large ones."""
    git("clone", "-q", "-b", "main", str(remote), str(where))
    return where


def test_large_files_go_up_as_release_assets_and_restore_byte_identical(world, tmp_path):
    folder, remote, api, backups, signed_in = world
    entry = backup(backups, folder)
    assert entry["state"] == "done", entry["message"]
    statuses = {f["path"]: (f["status"], f["message"]) for f in entry["large_files"]}
    assert statuses == {
        "disk image.iso": ("uploaded", "Uploaded in 4 parts"),
        "media/video.mp4": ("uploaded", "Uploaded"),
    }
    # One release, not marked Latest; asset names carry the first 12 characters of the SHA-256.
    assert len(api.created) == 1
    assert api.created[0]["tag_name"] == "large-files" and api.created[0]["name"] == "Large files backed up by HA"
    assert api.created[0]["make_latest"] == "false"
    listed = manifest(remote)
    files = {f["path"]: f for f in listed["files"]}
    video, iso = files["media/video.mp4"], files["disk image.iso"]
    assert video["size"] == 6144 and [p["name"] for p in video["parts"]] == ["video.mp4." + video["sha256"][:12]]
    assert [p["name"] for p in iso["parts"]] == [f"disk-image.iso.{iso['sha256'][:12]}.part{n:02d}" for n in (1, 2, 3, 4)]
    assert [p["size"] for p in iso["parts"]] == [8000, 8000, 8000, 6000]
    assert api.names() == sorted(p["name"] for f in files.values() for p in f["parts"])
    # The repository has the list and both restore scripts, but not the large files.
    assert {"notes.md", "LARGE_FILES.json", "restore-large-files.ps1", "restore_large_files.py"} <= tree(remote)
    assert not {"media/video.mp4", "disk image.iso"} & tree(remote)
    assert not (folder / "LARGE_FILES.json").exists()  # The folder itself is untouched.
    # The restore script rebuilds each file exactly, sending the token only to GitHub.
    copy = checkout(remote, tmp_path / "copy")
    done = subprocess.run(
        [sys.executable, str(copy / "restore_large_files.py"), "--api", api.url, "--token", TOKEN],
        capture_output=True, text=True, timeout=120,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    for path in ("media/video.mp4", "disk image.iso"):
        assert (copy / path).read_bytes() == (folder / path).read_bytes()
    again = subprocess.run(
        [sys.executable, str(copy / "restore_large_files.py"), "--api", api.url, "--token", TOKEN],
        capture_output=True, text=True, timeout=120,
    )
    assert again.stdout.count("Already there") == 2
    # Nothing changed: nothing is uploaded again.
    before = list(api.uploads)
    assert upload(backups, entry["id"])["message"].startswith("Up to date")
    assert api.uploads == before


def test_changed_large_file_gets_new_assets_and_keeps_the_old_ones(world, tmp_path):
    folder, remote, api, backups, signed_in = world
    entry = backup(backups, folder)
    old = {f["path"]: f for f in manifest(remote)["files"]}["media/video.mp4"]
    (folder / "media" / "video.mp4").write_bytes(bytes(range(255, -1, -1)) * 30)
    entry = upload(backups, entry["id"])
    assert entry["state"] == "done", entry["message"]
    new = {f["path"]: f for f in manifest(remote)["files"]}["media/video.mp4"]
    assert new["sha256"] != old["sha256"] and new["parts"][0]["name"] == "video.mp4." + new["sha256"][:12]
    # The old asset is kept as the file's history, and the list says where it is.
    assert old["parts"][0]["name"] in api.names() and not api.deleted
    assert new["previous"][0]["sha256"] == old["sha256"]
    assert new["previous"][0]["parts"] == old["parts"]
    copy = checkout(remote, tmp_path / "copy")
    subprocess.run(
        [sys.executable, str(copy / "restore_large_files.py"), "--api", api.url, "--token", TOKEN, "--only", "media/video.mp4"],
        check=True, capture_output=True, timeout=120,
    )
    assert (copy / "media" / "video.mp4").read_bytes() == (folder / "media" / "video.mp4").read_bytes()


def test_missing_or_broken_assets_are_uploaded_again_and_nothing_else(world):
    folder, remote, api, backups, signed_in = world
    entry = backup(backups, folder)
    names = {a["name"]: key for key, a in api.assets.items()}
    part2 = next(n for n in names if n.endswith(".part02"))
    part3 = next(n for n in names if n.endswith(".part03"))
    # An interrupted upload left part 2 short; part 3 went missing.
    api.assets[names[part2]]["size"] = 10
    del api.assets[names[part3]]
    api.uploads.clear()
    entry = upload(backups, entry["id"])
    assert entry["state"] == "done", entry["message"]
    assert sorted(api.uploads) == sorted([part2, part3]) and api.deleted == [part2]


def test_without_a_sign_in_large_files_wait_and_are_tried_again(world):
    folder, remote, api, backups, signed_in = world
    signed_in["token"] = (None, None)
    entry = backup(backups, folder)
    assert entry["state"] == "waiting"
    assert "2 large files are waiting: connect GitHub under Settings" in entry["message"]
    assert {(f["status"], f["message"]) for f in entry["large_files"]} == {
        ("waiting", "Waiting: connect GitHub to upload this file")
    }
    assert api.assets == {} and "notes.md" in tree(remote)
    signed_in["token"] = (TOKEN, "gh")
    entry = upload(backups, entry["id"])
    assert entry["state"] == "done", entry["message"]
    assert {f["status"] for f in entry["large_files"]} == {"uploaded"}
    assert len(manifest(remote)["files"]) == 2


def test_only_large_files_still_get_a_release(tmp_path, world):
    folder, remote, api, backups, signed_in = world
    (folder / "notes.md").unlink()  # Nothing small to push first.
    entry = backup(backups, folder)
    assert entry["state"] == "done", entry["message"]
    assert tree(remote) == {"LARGE_FILES.json", "restore-large-files.ps1", "restore_large_files.py"}
    assert len(manifest(remote)["files"]) == 2


def test_visibility_seen_on_each_upload_is_recorded_and_announced(world):
    folder, remote, api, backups, signed_in = world
    entry = backup(backups, folder)
    assert entry["visibility"] == "private" and not entry["visibility_notice"]
    api.private = False
    entry = upload(backups, entry["id"])
    assert entry["visibility"] == "public"
    assert entry["visibility_notice"] == "This repository is now public on GitHub."
    assert "now public on GitHub" in entry["message"]


def test_deleted_large_files_stay_listed_unless_deletions_are_on(world):
    folder, remote, api, backups, signed_in = world
    entry = backup(backups, folder)
    (folder / "disk image.iso").unlink()
    upload(backups, entry["id"])
    assert "disk image.iso" in {f["path"] for f in manifest(remote)["files"]}
    backups.settings(entry["id"], {"include_deletions": True})
    upload(backups, entry["id"])
    assert "disk image.iso" not in {f["path"] for f in manifest(remote)["files"]}
    assert any(n.startswith("disk-image.iso.") for n in api.names())  # Its assets stay as history.


@pytest.mark.skipif(
    subprocess.run(["git", "lfs", "version"], capture_output=True).returncode != 0,
    reason="Git LFS isn't installed",
)
def test_git_lfs_instead(world, tmp_path):
    folder, remote, api, backups, signed_in = world
    backups.remote_url = lambda owner, name: remote.as_uri()
    entry = backup(backups, folder, lfs=True)
    assert entry["state"] == "done", entry["message"]
    assert {f["path"]: f["status"] for f in entry["large_files"]} == {
        "media/video.mp4": "lfs", "disk image.iso": "lfs",
    }
    pointer = git("--git-dir", str(remote), "show", "main:media/video.mp4")
    assert pointer.startswith("version https://git-lfs.github.com/spec/v1")
    attributes = git("--git-dir", str(remote), "show", "main:.gitattributes")
    assert "/disk[[:space:]]image.iso filter=lfs" in attributes
    assert list((remote / "lfs" / "objects").rglob("*")) and api.assets == {}
    assert "LARGE_FILES.json" not in tree(remote)


def test_lfs_is_offered_only_when_installed(world):
    folder, remote, api, backups, signed_in = world
    backups.lfs_known = False
    with pytest.raises(Exception, match="Git LFS isn't installed"):
        backups.add({"folder": str(folder), "action": "existing", "owner": "owner", "name": "backup", "lfs": True})


@pytest.mark.skipif(not (shutil.which("powershell") or shutil.which("pwsh")), reason="PowerShell isn't installed")
def test_powershell_restore_script_rebuilds_files(world, tmp_path):
    folder, remote, api, backups, signed_in = world
    backup(backups, folder)
    copy = checkout(remote, tmp_path / "copy")
    shell = shutil.which("powershell") or shutil.which("pwsh")
    done = subprocess.run(
        [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(copy / "restore-large-files.ps1"),
         "-Api", api.url, "-Token", TOKEN],
        capture_output=True, text=True, timeout=300,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    for path in ("media/video.mp4", "disk image.iso"):
        assert (copy / path).read_bytes() == (folder / path).read_bytes()


def test_a_file_that_grows_past_the_limit_leaves_the_repository(world):
    folder, remote, api, backups, signed_in = world
    (folder / "log.txt").write_bytes(b"small\n" * 10)
    entry = backup(backups, folder)
    assert "log.txt" in tree(remote)
    (folder / "log.txt").write_bytes(b"x" * 6000)  # Now over the (lowered) 5000-byte limit.
    later = upload(backups, entry["id"])
    assert later["state"] == "done", later["message"]
    # It goes up as a release asset instead of into the repository, which GitHub would refuse.
    assert "log.txt" not in tree(remote)
    assert {f["path"]: f["status"] for f in later["large_files"]}["log.txt"] == "uploaded"
    assert "log.txt" in {f["path"] for f in manifest(remote)["files"]}
    # The earlier, small version stays in the repository's history.
    first = git("--git-dir", str(remote), "log", "--format=%H", "main", "--", "log.txt").split()[-1]
    assert git("--git-dir", str(remote), "show", f"{first}:log.txt") == "small\n" * 10
    assert upload(backups, entry["id"])["message"].startswith("Up to date")


@pytest.mark.skipif(
    subprocess.run(["git", "lfs", "version"], capture_output=True).returncode != 0,
    reason="Git LFS isn't installed",
)
def test_turning_git_lfs_off_moves_large_files_to_release_assets(world):
    folder, remote, api, backups, signed_in = world
    backups.remote_url = lambda owner, name: remote.as_uri()
    (folder / ".gitattributes").write_text("*.txt text\n")
    entry = backup(backups, folder, lfs=True)
    assert {f["status"] for f in entry["large_files"]} == {"lfs"}
    backups.settings(entry["id"], {"lfs": False})
    later = upload(backups, entry["id"])
    assert later["state"] == "done", later["message"]
    assert not {"media/video.mp4", "disk image.iso"} & tree(remote)
    assert {f["path"]: f["status"] for f in later["large_files"]} == {
        "media/video.mp4": "uploaded", "disk image.iso": "uploaded",
    }
    assert git("--git-dir", str(remote), "show", "main:.gitattributes") == "*.txt text\n"


UNSAFE = ["../outside.bin", "/etc/outside.bin", "a//b.bin", "./a.bin"]


@pytest.mark.parametrize("unsafe", UNSAFE)
def test_restore_refuses_paths_outside_the_folder(tmp_path, unsafe):
    script = Path(github_folders.__file__).parent / "restore" / "restore_large_files.py"
    copy = tmp_path / "copy"
    copy.mkdir()
    (copy / "LARGE_FILES.json").write_text(json.dumps({
        "repository": "owner/backup", "release": "large-files",
        "files": [{"path": unsafe, "size": 1, "sha256": "0" * 64, "parts": [{"name": "x", "size": 1}]}],
    }))
    done = subprocess.run(
        [sys.executable, str(script), "--destination", str(copy), "--manifest", str(copy / "LARGE_FILES.json"),
         "--api", "http://127.0.0.1:9", "--token", TOKEN],
        capture_output=True, text=True, timeout=60,
    )
    assert done.returncode != 0 and "Refusing an unsafe path" in done.stderr
    assert not (tmp_path / "outside.bin").exists()


def test_restore_refuses_windows_paths_and_links_outside_the_folder(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "restore_large_files", Path(github_folders.__file__).parent / "restore" / "restore_large_files.py")
    restore = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(restore)
    for unsafe in ("..\\..\\x", "\\Windows\\System32\\x", "ok/D:x", "C:x", "a\\..\\..\\x"):
        with pytest.raises(SystemExit):
            restore.target_path(tmp_path, unsafe, windows=True)
    assert restore.target_path(tmp_path, "media\\clip.mp4", windows=True) == tmp_path.resolve() / "media" / "clip.mp4"
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (tmp_path / "copy").mkdir()
        (tmp_path / "copy" / "linked").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("This computer doesn't allow creating links")
    with pytest.raises(SystemExit):
        restore.target_path(tmp_path / "copy", "linked/file.bin")


@pytest.mark.skipif(not (shutil.which("powershell") or shutil.which("pwsh")), reason="PowerShell isn't installed")
def test_powershell_restore_refuses_paths_outside_the_folder(tmp_path):
    script = Path(github_folders.__file__).parent / "restore" / "restore-large-files.ps1"
    shell = shutil.which("powershell") or shutil.which("pwsh")
    copy = tmp_path / "copy"
    copy.mkdir()
    unsafe = ["../outside.bin", "a//b.bin"] + (["..\\..\\outside.bin", "ok/D:x"] if sys.platform == "win32" else [])
    for path in unsafe:
        (copy / "LARGE_FILES.json").write_text(json.dumps({
            "repository": "owner/backup", "release": "large-files",
            "files": [{"path": path, "size": 1, "sha256": "0" * 64, "parts": [{"name": "x", "size": 1}]}],
        }))
        done = subprocess.run(
            [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Destination", str(copy),
             "-Manifest", str(copy / "LARGE_FILES.json"), "-Api", "http://127.0.0.1:9", "-Token", TOKEN],
            capture_output=True, text=True, timeout=300,
        )
        assert done.returncode != 0 and "Refusing an unsafe path" in done.stdout + done.stderr, path
    assert not (tmp_path / "outside.bin").exists()
