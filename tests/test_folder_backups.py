"""Folder backups to GitHub, against a local Git remote standing in for GitHub."""

import asyncio
import subprocess
from concurrent.futures import Future

import pytest

from hivemind_assembly.core.common import Blocked, Conflict, ContractError
from hivemind_assembly.integrations import github_folders
from hivemind_assembly.integrations.github import GitHubError
from hivemind_assembly.integrations.github_folders import FolderBackups


def git(*args, cwd=None):
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.fixture
def world(tmp_path):
    folder = tmp_path / "Project"
    (folder / "docs").mkdir(parents=True)
    (folder / "docs" / "guide.md").write_text("# Guide\n")
    (folder / "data.bin").write_bytes(bytes(range(256)) * 4)
    (folder / "odd name [v2]*.txt").write_text("literal name\n")
    (folder / ".env").write_text("TOKEN=secret\n")
    (folder / "vendored" / ".git").mkdir(parents=True)
    (folder / "vendored" / "lib.c").write_text("int x;\n")
    remotes = tmp_path / "github"
    remotes.mkdir()
    config = {"github": {"allow_repository_creation": True}}
    backups = FolderBackups(
        tmp_path / "state",
        None,
        config,
        remote_url=lambda owner, name: str(remotes / owner / (name + ".git")),
        token=lambda: (None, None),  # No GitHub sign-in unless a test gives one.
    )
    return folder, remotes, backups, config


def bare(remotes, owner="owner", name="backup"):
    path = remotes / owner / (name + ".git")
    path.parent.mkdir(parents=True, exist_ok=True)
    git("init", "--bare", "-q", str(path))
    return path


def run(backups, **request):
    entry = backups.add(
        {"folder": request.pop("folder"), "action": "existing", "owner": "owner", "name": "backup", **request}
    )
    backups.running[entry["id"]].join(60)
    return backups._load()[entry["id"]]


def upload(backups, key):
    backups.start(key)
    backups.running[key].join(60)
    return backups._load()[key]


def tree(remote):
    return set(git("--git-dir", str(remote), "ls-tree", "-r", "--name-only", "main").split("\n")) - {""}


def test_first_upload_leaves_out_secrets_and_nested_history_but_not_large_files(world, monkeypatch):
    folder, remotes, backups, config = world
    monkeypatch.setattr(github_folders, "GITHUB_FILE_LIMIT", 5000)
    (folder / "huge.iso").write_bytes(b"x" * 6000)
    remote = bare(remotes)
    entry = run(backups, folder=str(folder))
    # Without a GitHub sign-in for release assets, the large file waits and says so.
    assert entry["state"] == "waiting", entry["message"]
    assert "waiting: connect GitHub" in entry["message"]
    assert {"docs/guide.md", "data.bin", "odd name [v2]*.txt"} <= tree(remote)
    assert "huge.iso" not in tree(remote)
    reasons = {x["path"]: x["reason"] for x in entry["excluded"]}
    assert set(reasons) == {".env", "vendored/"}
    assert [(f["path"], f["status"], f["message"]) for f in entry["large_files"]] == [
        ("huge.iso", "waiting", "Waiting: connect GitHub to upload this file")
    ]
    # The nested Git folder can be backed up on its own.
    nested = next(x for x in entry["excluded"] if x["path"] == "vendored/")
    assert nested["separate"] == str(folder / "vendored")
    # The folder itself is never turned into a Git repository or given HA's files.
    assert not (folder / ".git").exists() and not (folder / "LARGE_FILES.json").exists()
    author = git("--git-dir", str(remote), "log", "-1", "--format=%an <%ae>", "main")
    assert author.strip() == "Hivemind Assembly <owner@users.noreply.github.com>"


def test_later_uploads_send_changes_and_keep_deletions_unless_asked(world):
    folder, remotes, backups, config = world
    remote = bare(remotes)
    entry = run(backups, folder=str(folder))
    first = entry["last_commit"]
    assert upload(backups, entry["id"])["message"].startswith("Up to date")
    (folder / "docs" / "guide.md").write_text("# Guide, edited\n")
    (folder / "new.txt").write_text("new\n")
    (folder / "data.bin").unlink()
    entry = upload(backups, entry["id"])
    assert entry["state"] == "done" and entry["last_commit"] != first
    assert {"new.txt", "data.bin"} <= tree(remote)  # Deleted here, kept on GitHub.
    assert git("--git-dir", str(remote), "show", "main:docs/guide.md") == "# Guide, edited\n"
    backups.settings(entry["id"], {"include_deletions": True})
    entry = upload(backups, entry["id"])
    assert "data.bin" not in tree(remote) and "removed 1" in entry["message"]


def test_changes_made_on_github_are_kept_never_force_pushed(world, tmp_path):
    folder, remotes, backups, config = world
    remote = bare(remotes)
    entry = run(backups, folder=str(folder))
    elsewhere = tmp_path / "elsewhere"
    git("clone", "-q", "-b", "main", str(remote), str(elsewhere))
    (elsewhere / "README.md").write_text("Edited on GitHub\n")
    git("add", "README.md", cwd=elsewhere)
    git("-c", "user.name=x", "-c", "user.email=x@example.com", "commit", "-qm", "web edit", cwd=elsewhere)
    git("push", "-q", "origin", "HEAD:main", cwd=elsewhere)
    (folder / "docs" / "guide.md").write_text("# Local change\n")
    entry = upload(backups, entry["id"])
    assert entry["state"] == "done", entry["message"]
    assert {"README.md", "docs/guide.md"} <= tree(remote)
    history = git("--git-dir", str(remote), "log", "--format=%s", "main").splitlines()
    assert history[1] == "web edit" and len(history) == 3


def test_large_first_upload_goes_up_in_parts(world, monkeypatch):
    folder, remotes, backups, config = world
    monkeypatch.setattr(github_folders, "BATCH_BYTES", 600)
    remote = bare(remotes)
    entry = run(backups, folder=str(folder))
    assert entry["state"] == "done", entry["message"]
    history = git("--git-dir", str(remote), "log", "--format=%s", "main").splitlines()
    assert len(history) >= 2 and "(part" in history[0]
    assert tree(remote) == {"docs/guide.md", "data.bin", "odd name [v2]*.txt"}


def test_requests_are_checked_before_anything_runs(world, tmp_path):
    folder, remotes, backups, config = world
    for bad in (
        {"folder": "relative/path", "name": "x"},
        {"folder": str(folder), "name": "../x"},
        {"folder": str(folder), "name": "x", "visibility": "secret"},
        {"folder": str(folder), "name": "x", "token": "nope"},
        {"folder": str(tmp_path / "state"), "name": "x"},
    ):
        with pytest.raises(ContractError):
            backups.add(bad)
    bare(remotes)
    run(backups, folder=str(folder))
    with pytest.raises(Conflict, match="already backed up"):
        backups.add({"folder": str(folder), "name": "other", "action": "existing"})


class Client:
    def __init__(self):
        self.repos, self.creates, self.denied = {}, 0, False

    def lookup(self, owner, name):
        return self.repos.get((owner, name))

    def create(self, owner, name, description, organization=False, private=True):
        self.creates += 1
        if self.denied:
            raise GitHubError(403)
        repo = {"private": private, "permissions": {"push": True}}
        self.repos[owner, name] = repo
        return repo


class Web:
    def __init__(self):
        self.created = []

    async def exists(self, owner, name):
        return False

    async def create(self, owner, name, description, visibility):
        self.created.append((owner, name, visibility))
        return {"owner": owner or "owner", "name": name}


def submit(coroutine):
    future = Future()
    future.set_result(asyncio.run(coroutine))
    return future


def creating(world, monkeypatch, client):
    folder, remotes, backups, config = world
    backups.web, backups.submit = Web(), submit
    monkeypatch.setattr(
        backups, "_client", lambda: (client, {"login": "owner"}) if client else (None, None)
    )
    monkeypatch.setattr(backups, "_environment", lambda e: None)
    bare(remotes, name="fresh")
    return folder, remotes, backups, config


def add(backups, folder, **extra):
    entry = backups.add({"folder": str(folder), "name": "fresh", **extra})
    backups.running[entry["id"]].join(60)
    return backups._load()[entry["id"]]


def test_create_public_repository_with_the_connection(world, monkeypatch):
    client = Client()
    folder, remotes, backups, config = creating(world, monkeypatch, client)
    entry = add(backups, folder, visibility="public")
    assert entry["state"] == "done", entry["message"]
    assert client.repos["owner", "fresh"]["private"] is False
    assert entry["created_with"] == "github" and not backups.web.created


def test_existing_name_is_never_adopted_by_create(world, monkeypatch):
    client = Client()
    client.repos["owner", "fresh"] = {"private": True, "permissions": {"push": True}}
    folder, remotes, backups, config = creating(world, monkeypatch, client)
    entry = add(backups, folder)
    assert entry["state"] == "failed" and "already exists" in entry["message"]
    assert client.creates == 0


def test_refused_or_missing_connection_falls_back_to_github_page(world, monkeypatch):
    client = Client()
    client.denied = True
    folder, remotes, backups, config = creating(world, monkeypatch, client)
    entry = add(backups, folder, visibility="private")
    assert entry["state"] == "done", entry["message"]
    assert entry["created_with"] == "browser"
    assert backups.web.created == [("owner", "fresh", "private")]


def test_not_connected_uses_the_github_page(world, monkeypatch):
    folder, remotes, backups, config = creating(world, monkeypatch, None)
    entry = add(backups, folder, owner="owner")
    assert entry["created_with"] == "browser" and entry["state"] == "done", entry["message"]


def test_creation_needs_the_settings_permission(world, monkeypatch):
    folder, remotes, backups, config = creating(world, monkeypatch, Client())
    config["github"]["allow_repository_creation"] = False
    entry = add(backups, folder)
    assert entry["state"] == "failed" and "Let HA create repositories" in entry["message"]


def test_automatic_uploads_run_when_due(world):
    folder, remotes, backups, config = world
    remote = bare(remotes)
    now = [1000.0]
    backups.clock = lambda: now[0]
    entry = run(backups, folder=str(folder), automatic=True, interval_minutes=15)
    assert backups.due() == []
    (folder / "later.txt").write_text("later\n")
    now[0] += 15 * 60
    assert backups.due() == [entry["id"]]
    backups.running[entry["id"]].join(60)
    assert "later.txt" in tree(remote)


def test_remove_forgets_the_backup_but_not_the_folder_or_github(world):
    folder, remotes, backups, config = world
    remote = bare(remotes)
    entry = run(backups, folder=str(folder))
    backups.remove(entry["id"])
    assert backups.view() == [] and (folder / "docs" / "guide.md").exists()
    assert "docs/guide.md" in tree(remote)


def test_failed_upload_message_is_plain(world):
    folder, remotes, backups, config = world
    entry = run(backups, folder=str(folder))  # No remote repository exists.
    assert entry["state"] == "failed"
    assert entry["message"].startswith(("GitHub", "Git:"))
