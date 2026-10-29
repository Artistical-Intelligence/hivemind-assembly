"""Resume trusts current evidence, not an old pass or a missing marker."""

import asyncio
import hashlib

import pytest

from test_checks_workflow import Checker, ROUTES, project, team_for, write  # noqa: F401
from hivemind_assembly.core.acceptance import Acceptance
from hivemind_assembly.core.checks import LEDGER, MARK, STATUS
from hivemind_assembly.core.common import Blocked


def checked_file(project):
    c, t, epoch, remote, broker = project
    write(broker, t, epoch, "src/a.c", "int a = 1;\n", "w1")
    team = team_for(c, broker, Checker({}, ROUTES))
    outcome = asyncio.run(team.independent.run(t["project_id"]))
    assert outcome["passed"] == ["src/a.c"]
    return c, t, epoch, remote, broker, team


def test_checked_local_drift_reopens_and_checks_local_not_old_remote(project):
    c, t, _, remote, broker, team = checked_file(project)
    root = broker.workspace(t["id"])
    before = c.store.project(t["project_id"])["revision"]
    (root / "src/a.c").write_bytes(b"int a = 2;\n")
    result = broker.drafts.reconcile(t["project_id"])
    assert result["changed"] == ["src/a.c"]
    assert c.store.project(t["project_id"])["revision"] == before + 1
    assert c.store.task(t["id"])["brief_id"] is None
    pending = broker.drafts.checks.pending(t["project_id"])[0]
    assert not pending.get("outside")
    assert MARK in (root / "src/STATUS.md").read_text(encoding="utf-8")
    assert "int a = 1" in remote.tree()["src/a.c"]  # Do not publish an external edit automatically.
    checker = Checker({}, ROUTES)
    team.sessions.checker = checker
    asyncio.run(team.independent.run(t["project_id"]))
    assert checker.calls[0][1]["files"][0]["text"] == "int a = 2;\n"


def test_only_newest_checked_hash_counts_and_unchanged_resume_is_idempotent(project):
    c, t, _, _, broker, _ = checked_file(project)
    checks = broker.drafts.checks
    state = checks.state(t["project_id"])
    state["checked"].append({**state["checked"][0], "sha256": "obsolete"})
    checks.save(t["project_id"], state)
    revision = c.store.project(t["project_id"])["revision"]
    assert broker.drafts.reconcile(t["project_id"])["pending"] == 0
    assert broker.drafts.reconcile(t["project_id"])["pending"] == 0
    assert c.store.project(t["project_id"])["revision"] == revision


def test_missing_checked_file_stays_pending_without_repeated_revision_bumps(project):
    c, t, _, _, broker, team = checked_file(project)
    (broker.workspace(t["id"]) / "src/a.c").unlink()
    result = broker.drafts.reconcile(t["project_id"])
    assert result["changed"] == ["src/a.c"]
    revision = c.store.project(t["project_id"])["revision"]
    assert broker.drafts.reconcile(t["project_id"])["changed"] == []
    assert c.store.project(t["project_id"])["revision"] == revision
    outcome = asyncio.run(team.independent.run(t["project_id"]))
    assert outcome["left"] == ["src/a.c"] and not outcome["passed"]


def test_local_markers_are_adopted_before_rewrite(project):
    _, t, _, _, broker = project
    root = broker.workspace(t["id"])
    (root / "outside.txt").write_text("local draft", encoding="utf-8")
    (root / STATUS).write_text(f"{MARK} outside.txt — owner requests review\n", encoding="utf-8")
    result = broker.drafts.reconcile(t["project_id"])
    assert result["pending"] == 1
    item = broker.drafts.checks.pending(t["project_id"])[0]
    assert item["path"] == "outside.txt" and not item.get("outside")
    assert "outside.txt" in (root / LEDGER).read_text(encoding="utf-8")


def test_missing_report_reopens_without_erasing_history(project):
    _, t, _, _, broker, _ = checked_file(project)
    checks = broker.drafts.checks
    report = checks.state(t["project_id"])["checked"][0]["report"]
    (broker.workspace(t["id"]) / report).unlink()
    result = broker.drafts.reconcile(t["project_id"])
    assert result["pending"] == 1
    assert checks.state(t["project_id"])["checked"][0]["report"] == report
    assert "report is missing" in checks.pending(t["project_id"])[0]["note"]


def test_external_edit_during_check_cannot_pass_old_bytes(project):
    c, t, epoch, _, broker = project
    write(broker, t, epoch, "a.c", "int a = 1;\n", "w1")
    checker = Checker({}, ROUTES)
    original = checker.exchange

    async def changed(route, message):
        (broker.workspace(t["id"]) / "a.c").write_bytes(b"int a = 2;\n")
        return await original(route, message)

    checker.exchange = changed
    outcome = asyncio.run(team_for(c, broker, checker).independent.run(t["project_id"]))
    assert outcome["left"] == ["a.c"] and not outcome["passed"]
    assert broker.drafts.checks.pending(t["project_id"])[0]["sha256"] == hashlib.sha256(b"int a = 2;\n").hexdigest()


def test_legacy_remote_check_history_remains_remote_after_upgrade(project):
    c, t, epoch, remote, broker = project
    remote.edit("docs/remote.md", "Remote-only source\n")
    remote.edit(LEDGER, "| Item | Folder | Waiting for |\n| --- | --- | --- |\n"
                "| docs/remote.md | docs | review |\n")
    write(broker, t, epoch, "local.c", "int a;\n", "w1")
    team = team_for(c, broker, Checker({}, ROUTES))
    outcome = asyncio.run(team.independent.run(t["project_id"]))
    assert "docs/remote.md" in outcome["passed"]
    checks = broker.drafts.checks
    state = checks.state(t["project_id"])
    for entry in state["checked"]:
        entry.pop("outside", None)  # Exact legacy shape, before provenance was saved.
    checks.save(t["project_id"], state)
    revision = c.store.project(t["project_id"])["revision"]
    assert broker.drafts.reconcile(t["project_id"])["pending"] == 0
    assert c.store.project(t["project_id"])["revision"] == revision
    # Legacy local evidence still detects deletion instead of assuming remote origin.
    (broker.workspace(t["id"]) / "local.c").unlink()
    assert broker.drafts.reconcile(t["project_id"])["changed"] == ["local.c"]


def test_checked_local_discovery_does_not_become_remote_history(project):
    c, t, _, _, broker = project
    root = broker.workspace(t["id"])
    (root / "local.txt").write_text("first", encoding="utf-8")
    (root / STATUS).write_text(f"{MARK} local.txt — review\n", encoding="utf-8")
    broker.drafts.reconcile(t["project_id"])
    team = team_for(c, broker, Checker({}, ROUTES))
    assert asyncio.run(team.independent.run(t["project_id"]))["passed"] == ["local.txt"]
    (root / "local.txt").write_text("second", encoding="utf-8")
    assert broker.drafts.reconcile(t["project_id"])["changed"] == ["local.txt"]


def test_direct_acceptance_rechecks_changed_file_even_without_scheduler(project):
    c, t, _, _, broker, _ = checked_file(project)
    (broker.workspace(t["id"]) / "src/a.c").write_text("int a = 3;\n", encoding="utf-8")
    with pytest.raises(Blocked, match="independent check"):
        Acceptance(c, broker).evaluate(c.store.task(t["id"]), {"result_operations": ["w1"]})
    assert broker.drafts.checks.pending(t["project_id"])[0]["path"] == "src/a.c"
    assert not c.store.rows("SELECT id FROM records WHERE kind='acceptance_result'")


def test_fixture_approval_persists_evidence_and_does_not_reopen_on_reconcile(project):
    from native_fixtures import pass_checks
    from hivemind_assembly.core.checks import parse_ledger

    c, t, epoch, remote, broker = project
    write(broker, t, epoch, "src/fixture.c", "int fixture = 1;\n", "fixture-write")
    root = broker.workspace(t["id"])
    assert MARK in (root / "src" / STATUS).read_text(encoding="utf-8")
    outcome = pass_checks(broker, t["project_id"])
    assert outcome == {"passed": ["src/fixture.c"], "failed": [], "left": []}
    report = broker.drafts.checks.state(t["project_id"])["checked"][0]["report"]
    assert (root / report).is_file()
    assert "not live provider evidence" in (root / report).read_text(encoding="utf-8")
    assert remote.tree()[report] == (root / report).read_text(encoding="utf-8")
    assert not (root / "src" / STATUS).exists()
    assert "src/STATUS.md" not in remote.tree()
    assert parse_ledger((root / LEDGER).read_text(encoding="utf-8")) == []
    assert parse_ledger(remote.tree()[LEDGER]) == []
    revision = c.store.project(t["project_id"])["revision"]
    for _ in range(2):
        result = broker.drafts.reconcile(t["project_id"])
        assert result["pending"] == 0 and result["changed"] == []
    assert c.store.project(t["project_id"])["revision"] == revision
