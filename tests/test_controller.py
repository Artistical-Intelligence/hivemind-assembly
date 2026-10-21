import json
from concurrent.futures import ThreadPoolExecutor
import pytest
from workbench.common import Conflict, Blocked, ContractError
from workbench.controller import Controller
from workbench.broker import Broker
from workbench.store import Store


def req(t, e, tool="read_file", args=None):
    return {
        "id": "op1",
        "task_id": t["id"],
        "owner": "worker.opus",
        "epoch": e,
        "revision": 0,
        "tool": tool,
        "args": args or {},
    }


def test_idempotent(ready):
    c, t, e = ready
    r = req(t, e)
    a, new = c.begin(r, {"read_file"})
    assert new
    c.finish("op1", {"value": 4})
    a, new = c.begin(r, {"read_file"})
    assert not new and json.loads(a["result"])["value"] == 4
    r["args"] = {"different": True}
    with pytest.raises(Conflict):
        c.begin(r, {"read_file"})


def test_stale_writer(ready):
    c, t, e = ready
    c.transfer(t["id"], "worker.astra", "test")
    with pytest.raises(Conflict):
        c.begin(req(t, e), {"read_file"})


def test_no_transfer_pending(ready):
    c, t, e = ready
    c.begin(req(t, e), {"read_file"})
    with pytest.raises(Blocked):
        c.transfer(t["id"], "worker.astra", "test")


def test_revision_and_brief_invalidation(ready):
    c, t, e = ready
    c.begin(req(t, e), {"read_file"})
    c.finish("op1", {}, True)
    assert c.store.task(t["id"])["brief_id"] is None
    r = req(t, e)
    r["id"] = "op2"
    with pytest.raises(Conflict):
        c.begin(r, {"read_file"})
    r["revision"] = 1
    with pytest.raises(Blocked):
        c.begin(r, {"read_file"})


def test_no_brief(store):
    c = Controller(store)
    t = store.create_project("a", "b")
    e = c.acquire(t["id"], "worker.opus")
    with pytest.raises(Blocked):
        c.begin(req(t, e), {"read_file"})


def test_permission(ready):
    c, t, e = ready
    with pytest.raises(Blocked):
        c.begin(req(t, e, "shell"), {"read_file"})


def test_expired(ready):
    c, t, e = ready
    with c.store.tx() as db:
        db.execute("UPDATE tasks SET lease_until=0")
    with pytest.raises(Conflict):
        c.begin(req(t, e), {"read_file"})


def test_restart_marks_uncertain(ready):
    c, t, e = ready
    c.begin(req(t, e), {"read_file"})
    m = c.prepare_message(t["id"], "worker.opus", "chat", {"x": 1})
    c.message_state(m["id"], "dispatching")
    c.recover()
    assert c.store.one("SELECT state FROM operations")["state"] == "uncertain"
    assert c.store.one("SELECT state FROM messages")["state"] == "delivery_uncertain"
    with pytest.raises(Blocked):
        c.acquire(t["id"], "worker.astra")


def test_message_identity(ready):
    c, t, e = ready
    c.prepare_message(t["id"], "worker.opus", "chat", {"x": 1}, "m")
    assert c.prepare_message(t["id"], "worker.opus", "chat", {"x": 1}, "m")["id"] == "m"
    with pytest.raises(Conflict):
        c.prepare_message(t["id"], "worker.opus", "other", {"x": 1}, "m")


def test_no_critical_gap_brief(ready):
    c, t, e = ready
    with pytest.raises(Blocked):
        c.brief(
            t["id"],
            {"revision": 0},
            {"procedure": "x", "acceptance": "y"},
            {"critical_gaps": ["missing"]},
            [],
        )


def test_atomic_file_and_replay(ready):
    c, t, e = ready
    b = Broker(c, {"foundations": {}})
    r = req(
        t,
        e,
        "write_file",
        {"path": "main.c", "expected_hash": None, "text": "int main(){return 0;}"},
    )
    x = b.execute(r)
    assert x["status"] == "saved"
    assert b.execute(r) == x
    assert c.store.project(t["project_id"])["revision"] == 1
    assert (b.workspace(t["id"]) / "main.c").read_text() == "int main(){return 0;}"


def test_path_escape(ready):
    c, t, e = ready
    b = Broker(c, {"foundations": {}})
    with pytest.raises(ContractError):
        b.execute(req(t, e, "write_file", {"path": "../../secrets", "text": "x"}))


def test_symlink_escape(ready, tmp_path):
    c, t, e = ready
    b = Broker(c, {"foundations": {}})
    outside = tmp_path / "outside"
    outside.write_text("private")
    try:
        (b.workspace(t["id"]) / "link").symlink_to(outside)
    except OSError:
        pytest.skip("symlink unavailable")
    with pytest.raises(ContractError):
        b.execute(req(t, e, "read_file", {"path": "link"}))


def test_reconcile_lost_save(ready, monkeypatch):
    c, t, e = ready
    b = Broker(c, {"foundations": {}})
    monkeypatch.setattr(
        c,
        "finish",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("process interrupted")),
    )
    with pytest.raises(RuntimeError):
        b.execute(
            req(
                t,
                e,
                "write_file",
                {"path": "file", "expected_hash": None, "text": "retained"},
            )
        )
    c.recover()
    assert b.reconcile_file("op1")["reconciled"]
    assert c.store.project(t["project_id"])["revision"] == 1
    with pytest.raises(ContractError):
        b.reconcile_file("op1")


def test_competing_writers(store):
    t = store.create_project("a", "b")
    c = Controller(store)

    def get(owner):
        try:
            c.acquire(t["id"], owner)
            return True
        except Conflict:
            return False

    with ThreadPoolExecutor(2) as pool:
        assert sum(pool.map(get, ["worker.opus", "worker.astra"])) == 1


def test_backup_restore(ready, tmp_path):
    c, t, e = ready
    p = tmp_path / "backup"
    c.store.backup(p)
    restored = tmp_path / "restored"
    restored.mkdir()
    p.rename(restored / "controller.sqlite3")
    s = Store(restored)
    try:
        assert s.task(t["id"])["epoch"] == e
    finally:
        s.close()


def _crafted_backup(path, files):
    import hashlib
    import json
    import zipfile

    manifest = {"format": 1, "created": 0, "excluded": [], "files": {}}
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
            manifest["files"][name] = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
        archive.writestr("backup-manifest.json", json.dumps(manifest))
    return path


@pytest.mark.parametrize(
    "files",
    [
        {"foundations/ghidra/support/analyzeHeadless": b"#!/bin/sh\n"},
        {"private/endpoint.json": b"{}"},
        {"settings.json": b"{}", "Settings.json": b"{}"},
    ],
)
def test_restore_accepts_only_owned_workspace_data(tmp_path, files):
    from hivemind_assembly.core.backups import restore
    from hivemind_assembly.core.common import ContractError

    archive = _crafted_backup(tmp_path / "crafted.zip", files)
    target = tmp_path / "restored"
    with pytest.raises(ContractError):
        restore(archive, target)
    assert not target.exists() or [p.name for p in target.iterdir()] in ([], ["host.lock"])


def test_failed_restore_leaves_no_partial_workspace(tmp_path, monkeypatch):
    from hivemind_assembly.core import backups

    archive = _crafted_backup(
        tmp_path / "ok.zip",
        {"settings.json": b"{}", "projects/p/workspace/a.c": b"int a;", "projects/p/workspace/b.c": b"int b;"},
    )
    target = tmp_path / "restored"
    real = backups.Path.replace
    calls = []

    def flaky(self, other):
        calls.append(self)
        if len(calls) == 2:
            raise OSError("disk failure")
        return real(self, other)

    monkeypatch.setattr(backups.Path, "replace", flaky)
    with pytest.raises(OSError):
        backups.restore(archive, target)
    assert [p.name for p in target.iterdir()] in ([], ["host.lock"])
