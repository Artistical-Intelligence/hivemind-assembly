"""Push early, check later: every file an assistant writes is pushed at once with its
"checks pending" markers; a different assistant checks it in its own conversation;
its report and the removal of the markers go up in one commit; nothing marked is
accepted or released; and the rules are in the repository for any assistant."""

import asyncio
import base64
import copy
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from test_publication import GitFixture
from hivemind_assembly.automation.checking import IndependentChecks
from hivemind_assembly.automation.team import NativeTeam
from hivemind_assembly.core.acceptance import Acceptance
from hivemind_assembly.core.broker import Broker
from hivemind_assembly.core.checks import (
    END, LEDGER, START, STATUS, Checks, blob_sha, parse_ledger, waiting_in,
)
from hivemind_assembly.core.common import Blocked
from hivemind_assembly.automation.policy import Availability, Window
from hivemind_assembly.core.repositories import Repositories
from hivemind_assembly.domains.reverse_engineering.domain import ReverseEngineeringDomain
from hivemind_assembly.integrations.github import GitHubError

ROUTES = {
    "worker.opus": {"provider": "claude"},
    "worker.extra": {"provider": "openai"},
    "reviewer.high": {"provider": "openai"},
}


class Remote(GitFixture):
    """GitHub with file reads and deletions, on top of the publication stand-in."""

    def tree(self, ref=None):
        return self.trees[self.commits[ref or self.current]["tree"]["sha"]]

    def git(self, owner, name, method, endpoint, data=None):
        if method == "GET" and endpoint.startswith("contents/"):
            path, ref = endpoint[len("contents/"):].split("?ref=")
            tree = self.tree(ref)
            if path not in tree:
                raise GitHubError(404)
            return {"type": "file", "encoding": "base64", "sha": blob_sha(tree[path]),
                    "content": base64.b64encode(tree[path].encode()).decode()}
        if method == "POST" and endpoint == "git/trees":
            tree = copy.deepcopy(self.trees[data["base_tree"]])
            for item in data["tree"]:
                if item.get("sha", "") is None:
                    tree.pop(item["path"], None)
                else:
                    tree[item["path"]] = item["content"]
            from test_publication import sha

            key = sha(tree)
            self.trees[key] = tree
            return {"sha": key}
        return super().git(owner, name, method, endpoint, data)

    def edit(self, path, text):
        """Someone changes a file on GitHub directly."""
        from test_publication import sha

        tree = dict(self.tree())
        tree[path] = text
        key = sha(tree)
        self.trees[key] = tree
        commit = sha({"edit": path, "parent": self.current})
        self.commits[commit] = {"tree": {"sha": key}, "parents": [{"sha": self.current}]}
        self.current = commit


@pytest.fixture
def project(ready):
    c, t, epoch = ready
    remote = Remote()
    remote.trees["base-tree"]["AGENTS.md"] = "# House rules\n\nUse tabs.\n"
    repos = Repositories(c.store, remote, {"github": {"allow_repository_creation": False}})
    assert repos.link(t["project_id"], "link", {"name": "existing"})["state"] == "verified"
    broker = Broker(c, {"foundations": {}, "routes": ROUTES}, ReverseEngineeringDomain(), repos)
    return c, t, epoch, remote, broker


def write(broker, t, epoch, path, text, op, owner="worker.opus", expected=None):
    revision = broker.store.project(t["project_id"])["revision"]
    broker.controller.brief(t["id"], {"revision": revision}, {"procedure": "write", "acceptance": "checked"},
                            {"critical_gaps": []}, [])
    return broker.execute({
        "id": op, "task_id": t["id"], "owner": owner, "epoch": epoch, "revision": revision,
        "tool": "write_file", "args": {"path": path, "text": text, "expected_hash": expected},
    })


def test_each_write_is_pushed_at_once_with_its_markers(project):
    c, t, epoch, remote, broker = project
    result = write(broker, t, epoch, "src/sum.c", "int sum(int a,int b){return a+b;}\n", "w1")
    assert result["checks"] == "pending: pushed before review"
    tree = remote.tree()
    assert tree["src/sum.c"].startswith("int sum")
    assert tree["src/STATUS.md"] == "CHECKS PENDING: sum.c — independent check by a different assistant\n"
    rows = parse_ledger(tree[LEDGER])
    assert rows == [{"item": "src/sum.c", "folder": "src",
                     "waiting": "independent check by a different assistant (written by Claude (worker.opus))"}]
    # The rules reach any assistant: added to the repository's own AGENTS.md, which keeps its content.
    assert tree["AGENTS.md"].startswith("# House rules\n\nUse tabs.\n") and START in tree["AGENTS.md"]
    assert START in tree["CLAUDE.md"] and "Read AGENTS.md first" in tree["CLAUDE.md"]
    assert "1. Pending checks" in tree["QUEUE.md"] and "src/sum.c" in tree["QUEUE.md"]
    assert "Verify a bounded region" in tree["QUEUE.md"]
    # The same markers are in the project's folder.
    root = broker.workspace(t["id"])
    assert (root / "src" / STATUS).read_text() == tree["src/STATUS.md"]
    # A second file in the same folder adds its own line; nothing else is touched.
    write(broker, t, epoch, "src/mul.c", "int mul(int a,int b){return a*b;}\n", "w2")
    assert remote.tree()["src/STATUS.md"].splitlines() == [
        "CHECKS PENDING: mul.c — independent check by a different assistant",
        "CHECKS PENDING: sum.c — independent check by a different assistant",
    ]
    assert remote.tree()["README.md"] == "Original readme"


def test_ha_files_are_not_marked(project):
    c, t, epoch, remote, broker = project
    for n, path in enumerate(("STATUS.md", "src/STATUS.md", "CHECKS_STATUS.md", "QUEUE.md", "checks/old.md")):
        write(broker, t, epoch, path, "x\n", f"w{n}")
    assert not broker.drafts.checks.pending(t["project_id"])


def test_markers_written_by_others_stay_and_their_rows_are_adopted(project):
    c, t, epoch, remote, broker = project
    remote.edit("src/STATUS.md", "Notes for this folder.\nCHECKS PENDING: asm.s — ChatGPT's draft\n")
    remote.edit(LEDGER, "| Item | Folder | Waiting for |\n| --- | --- | --- |\n| src/asm.s | src | ChatGPT's draft |\n")
    write(broker, t, epoch, "src/sum.c", "int sum;\n", "w1")
    status = remote.tree()["src/STATUS.md"]
    assert status.startswith("Notes for this folder.\nCHECKS PENDING: asm.s — ChatGPT's draft\n")
    assert "CHECKS PENDING: sum.c" in status
    pending = {i["path"]: i for i in broker.drafts.checks.pending(t["project_id"])}
    assert pending["src/asm.s"]["outside"] and pending["src/asm.s"]["writer"] == "outside"
    assert {r["item"] for r in parse_ledger(remote.tree()[LEDGER])} == {"src/asm.s", "src/sum.c"}


def test_a_file_changed_on_github_is_not_overwritten(project):
    c, t, epoch, remote, broker = project
    first = write(broker, t, epoch, "src/sum.c", "one\n", "w1")
    remote.edit("src/sum.c", "someone else's fix\n")
    second = write(broker, t, epoch, "src/sum.c", "two\n", "w2", expected=first and broker_hash(broker, t, "src/sum.c", "one\n"))
    assert remote.tree()["src/sum.c"] == "someone else's fix\n"
    state = broker.drafts.checks.state(t["project_id"])
    assert state["push"]["state"] == "conflict" and state["push"]["conflicts"] == ["src/sum.c"]
    assert "src/sum.c" in state["unpushed"] and second["checks"].startswith("pending: not pushed, because someone changed")


def broker_hash(broker, t, path, text):
    import hashlib

    return hashlib.sha256(text.encode()).hexdigest()


def test_without_github_the_markers_stay_in_the_folder(ready):
    c, t, epoch = ready
    broker = Broker(c, {"foundations": {}, "routes": ROUTES}, ReverseEngineeringDomain())
    result = write(broker, t, epoch, "a.c", "int a;\n", "w1")
    assert result["checks"].startswith("pending: saved in the project folder")
    root = broker.workspace(t["id"])
    assert (root / STATUS).read_text().startswith("CHECKS PENDING: a.c")
    assert parse_ledger((root / LEDGER).read_text())[0]["item"] == "a.c"


def test_markers_merge_and_disappear():
    checks = Checks.__new__(Checks)
    checks.providers = lambda route: None
    items = [{"path": "src/a.c", "folder": "src", "note": "independent check", "state": "pending"}]
    text = checks.status_text("Keep me\n", "src", items, {"src/a.c"})
    assert text == "Keep me\nCHECKS PENDING: a.c — independent check\n"
    assert checks.status_text(text, "src", [], {"src/a.c"}) == "Keep me\n"
    assert checks.status_text("CHECKS PENDING: a.c — x\n", "src", [], {"src/a.c"}) is None


class Checker:
    def __init__(self, verdicts, routes):
        self.verdicts, self.calls = verdicts, []
        self.config = {"routes": {r: {**v, "conversation_url": "https://example.invalid/" + r} for r, v in routes.items()}}

    async def exchange(self, route, message):
        body = json.loads(message["payload"])
        self.calls.append((route, body))
        if self.verdicts == "stop":
            raise ConnectionError("tab closed")
        return {"request_id": message["id"], "type": "check_report", "summary": "Looked at both.",
                "results": [{"path": f["path"], "verdict": self.verdicts.get(f["path"], "pass"),
                             "findings": "Returns a-b, not a+b." if self.verdicts.get(f["path"]) == "fail" else "Fine."}
                            for f in body["files"]]}


class Sessions:
    def __init__(self, checker):
        self.checker, self.isolated = checker, []

    async def isolated_browser(self, key, route, identity):
        self.isolated.append(identity)
        return self.checker

    async def release_isolated(self, identity):
        pass


def team_for(c, broker, checker, ready_routes=ROUTES):
    team = NativeTeam(c, broker, None, {"routes": {r: {**v, "conversation_url": "https://example.invalid/" + r}
                                                   for r, v in ROUTES.items()}, "foundations": {}})
    team.sessions = Sessions(checker)
    for route in ready_routes:
        team.observations[route] = Availability(route, True, True, False, time.time(), [Window("daily", 50)])
    return team


def test_a_different_assistant_checks_and_its_report_goes_up_with_the_marker_removal(project):
    c, t, epoch, remote, broker = project
    write(broker, t, epoch, "src/sum.c", "int sum(int a,int b){return a+b;}\n", "w1")
    write(broker, t, epoch, "src/sub.c", "int sub(int a,int b){return a-b;}\n", "w2")
    checker = Checker({"src/sub.c": "fail"}, ROUTES)
    team = team_for(c, broker, checker)
    before = remote.updates
    outcome = asyncio.run(team.independent.run(t["project_id"]))
    assert outcome["passed"] == ["src/sum.c"] and outcome["failed"] == ["src/sub.c"]
    route, body = checker.calls[0]
    assert ROUTES[route]["provider"] == "openai"  # Claude wrote it; ChatGPT checked it.
    assert set(body) == {"instruction", "files", "sources"}  # Only the files and their sources.
    assert {f["path"] for f in body["files"]} == {"src/sum.c", "src/sub.c"}
    assert team.sessions.isolated  # Its own conversation.
    tree = remote.tree()
    report = outcome["reports"][0]
    assert report.startswith("checks/") and "| src/sum.c |" in tree[report] and "Returns a-b" in tree[report]
    assert tree["src/STATUS.md"].startswith("CHECKS PENDING: sub.c — check failed: Returns a-b, not a+b.")
    assert [r["item"] for r in parse_ledger(tree[LEDGER])] == ["src/sub.c"]
    # The report and the removal of what passed are one commit.
    last = remote.commits[remote.current]
    parent_tree = remote.trees[remote.commits[last["parents"][0]["sha"]]["tree"]["sha"]]
    assert report not in parent_tree and "CHECKS PENDING: sum.c" in parent_tree["src/STATUS.md"]
    assert remote.updates > before
    # Fixing it and checking again clears the last marker; the empty STATUS.md goes.
    write(broker, t, epoch, "src/sub.c", "int sub(int a,int b){return a-b;}\n/* fixed */\n", "w3",
          expected=broker_hash(broker, t, "src/sub.c", "int sub(int a,int b){return a-b;}\n"))
    checker.verdicts = {}
    asyncio.run(team.independent.run(t["project_id"]))
    tree = remote.tree()
    assert "src/STATUS.md" not in tree and parse_ledger(tree[LEDGER]) == []
    assert "Nothing is waiting" in tree[LEDGER]
    assert broker.drafts.checks.summary(t["project_id"])["checked"] == 2


def test_an_interrupted_check_keeps_the_marker_and_says_so(project):
    c, t, epoch, remote, broker = project
    write(broker, t, epoch, "a.c", "int a;\n", "w1")
    team = team_for(c, broker, Checker("stop", ROUTES))
    with pytest.raises(ConnectionError):
        asyncio.run(team.independent.run(t["project_id"]))
    assert remote.tree()[STATUS].startswith("CHECKS PENDING: a.c — check stopped early (tab closed); run it again")


def test_a_file_changed_during_its_check_stays_pending(project):
    c, t, epoch, remote, broker = project
    write(broker, t, epoch, "a.c", "int a;\n", "w1")
    checker = Checker({}, ROUTES)
    team = team_for(c, broker, checker)
    original = checker.exchange

    async def edit_meanwhile(route, message):
        checks = broker.drafts.checks
        state = checks.state(t["project_id"])
        state["items"]["a.c"]["sha256"] = "changed"
        checks.save(t["project_id"], state)
        return await original(route, message)

    checker.exchange = edit_meanwhile
    outcome = asyncio.run(team.independent.run(t["project_id"]))
    assert outcome["left"] == ["a.c"] and broker.drafts.checks.pending(t["project_id"])


def test_the_checker_is_another_provider_when_one_is_ready(project):
    c, t, epoch, remote, broker = project
    team = team_for(c, broker, Checker({}, ROUTES))
    assert ROUTES[team.independent.choose("worker.opus")]["provider"] == "openai"
    assert team.independent.choose("worker.extra") == "worker.opus"
    only_openai = team_for(c, broker, Checker({}, ROUTES), ready_routes=["worker.extra", "reviewer.high"])
    assert only_openai.independent.choose("worker.extra") == "reviewer.high"  # Same provider, another assistant.
    nobody = team_for(c, broker, Checker({}, ROUTES), ready_routes=[])
    assert nobody.independent.choose("worker.opus") is None


def test_nothing_marked_is_accepted(project):
    c, t, epoch, remote, broker = project
    write(broker, t, epoch, "a.c", "int a;\n", "w1")
    with pytest.raises(Blocked, match="for an independent check"):
        Acceptance(c, broker).evaluate(c.store.task(t["id"]), {"result_operations": ["w1"]})


def test_reference_imports_flag_what_their_repository_marks_pending(store, tmp_path):
    from hivemind_assembly.learning.collections import KnowledgeCollections
    from hivemind_assembly.learning.knowledge import Knowledge

    root = tmp_path / "Book"
    (root / "chapters").mkdir(parents=True)
    (root / "chapters" / "one.md").write_text("# Relocations\n\nChecked text.\n")
    (root / "chapters" / "two.md").write_text("# Relocation drafts\n\nUnchecked text.\n")
    (root / "chapters" / STATUS).write_text("CHECKS PENDING: two.md — independent check\n")
    (root / LEDGER).write_text("| Item | Folder | Waiting for |\n| --- | --- | --- |\n| chapters/two.md | chapters | check |\n")
    assert waiting_in(root, ["chapters/one.md", "chapters/two.md", "chapters/STATUS.md"]) == {"chapters/two.md"}
    collections = KnowledgeCollections(store)
    entry = collections.add({"kind": "folder", "folder": str(root), "external_allowed": True})
    collections.running[entry["id"]].join(120)
    entry = collections._load()[entry["id"]]
    assert entry["report"]["checks_pending"] == ["chapters/two.md"]
    assert "still marked “checks pending”" in entry["message"]
    hits = {h["title"]: h for h in Knowledge(store).search("relocation", role="controller")}
    assert hits["Relocation drafts"].get("checks_pending") and not hits["Relocations"].get("checks_pending")


def test_release_gate_refuses_while_anything_is_pending(tmp_path):
    gate = Path(__file__).parents[1] / "dev" / "checks_gate.py"
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / STATUS).write_text("CHECKS PENDING: a.c — check\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    refused = subprocess.run([sys.executable, str(gate), str(tmp_path)], capture_output=True, text=True)
    assert refused.returncode == 1 and "src/STATUS.md" in refused.stdout
    (tmp_path / "src" / STATUS).write_text("Notes only.\n")
    (tmp_path / LEDGER).write_text("# Checks status\n\nNothing is waiting for a check.\n")
    assert subprocess.run([sys.executable, str(gate), str(tmp_path)], capture_output=True).returncode == 0


def test_the_projects_page_runs_a_check(tmp_path):
    from hivemind_assembly.application.app import Application

    app = Application(tmp_path / "state")
    try:
        task = app.store.create_project("Checks", "Rebuild a.c", paused=True)
        assert app.action("/api/checks/run", {"project": task["project_id"]})["message"] == "Nothing is waiting for a check."
        app.broker.drafts.checks.mark(task["project_id"], "a.c", "worker.opus", "x")
        status = app.status()["checks"][task["project_id"]]
        assert status["pending"] == 1 and status["items"][0]["path"] == "a.c"
        with pytest.raises(Blocked, match="No assistant has usage left"):
            app.action("/api/checks/run", {"project": task["project_id"]})
    finally:
        app.close()


def test_project_rules_reach_any_assistant():
    from hivemind_assembly.core.checks import RULES, section

    text = section("# Mine\n", START, END, RULES)
    assert text.startswith("# Mine\n\n" + START) and section(text, START, END, RULES) == text
    repo = Path(__file__).parents[1]
    assert RULES in (repo / "AGENTS.md").read_text() and "AGENTS.md" in (repo / "CLAUDE.md").read_text()


# ---------------------------------------------------------------- review findings
def test_a_binary_file_is_never_sent_as_a_removal(project):
    c, t, epoch, remote, broker = project
    remote.edit("assets/logo.txt", "the logo on GitHub\n")
    root = broker.workspace(t["id"])
    (root / "assets").mkdir(parents=True, exist_ok=True)
    (root / "assets" / "logo.txt").write_bytes(b"\x89PNG\xff\xfe binary")
    broker.drafts.checks.mark(t["project_id"], "assets/logo.txt", "worker.opus", "x")
    broker.drafts.sync(t["project_id"], changed=["assets/logo.txt"])
    assert remote.tree()["assets/logo.txt"] == "the logo on GitHub\n"
    state = broker.drafts.checks.state(t["project_id"])
    assert "not a text file" in state["push"]["skipped"]["assets/logo.txt"]


def test_a_different_file_already_on_github_is_not_overwritten_by_a_first_push(project):
    c, t, epoch, remote, broker = project
    result = write(broker, t, epoch, "README.md", "An assistant's readme\n", "w1")
    assert remote.tree()["README.md"] == "Original readme"
    assert result["checks"].startswith("pending: not pushed, because someone changed")
    # Editing the version GitHub has is fine: it's replaced.
    root = broker.workspace(t["id"])
    (root / "notes.md").write_text("v1\n")
    remote.edit("notes.md", "v1\n")
    import hashlib

    write(broker, t, epoch, "notes.md", "v2\n", "w2", expected=hashlib.sha256(b"v1\n").hexdigest())
    assert remote.tree()["notes.md"] == "v2\n"


def test_a_pass_does_not_clear_a_file_github_has_another_version_of(project):
    c, t, epoch, remote, broker = project
    write(broker, t, epoch, "src/sum.c", "one\n", "w1")
    remote.edit("src/sum.c", "someone else's fix\n")
    write(broker, t, epoch, "src/sum.c", "two\n", "w2", expected=broker_hash(broker, t, "src/sum.c", "one\n"))
    team = team_for(c, broker, Checker({}, ROUTES))
    outcome = asyncio.run(team.independent.run(t["project_id"]))
    assert outcome["left"] == ["src/sum.c"] and not outcome["passed"]
    assert "GitHub has a different version" in remote.tree()["src/STATUS.md"]
    assert [r["item"] for r in parse_ledger(remote.tree()[LEDGER])] == ["src/sum.c"]


def test_a_bad_row_written_elsewhere_is_ignored_and_pushing_goes_on(project):
    c, t, epoch, remote, broker = project
    remote.edit(LEDGER, "| Item | Folder | Waiting for |\n| --- | --- | --- |\n"
                        "| ../../evil.md | ../../evil | x |\n| `docs/x.md` | `docs` | y |\n")
    write(broker, t, epoch, "a.c", "int a;\n", "w1")
    write(broker, t, epoch, "b.c", "int b;\n", "w2")
    assert remote.tree()["b.c"] == "int b;\n"
    pending = {i["path"]: i for i in broker.drafts.checks.pending(t["project_id"])}
    assert "../../evil.md" not in pending and pending["docs/x.md"]["folder"] == "docs"


def test_files_written_outside_ha_are_checked_from_github(project):
    c, t, epoch, remote, broker = project
    remote.edit("docs/x.md", "# Notes\n\nWritten in ChatGPT.\n")
    remote.edit(LEDGER, "| Item | Folder | Waiting for |\n| --- | --- | --- |\n| docs/x.md | docs | check |\n")
    write(broker, t, epoch, "a.c", "int a;\n", "w1")
    checker = Checker({}, ROUTES)
    team = team_for(c, broker, checker)
    assert team.independent.who(t["project_id"])
    outcome = asyncio.run(team.independent.run(t["project_id"]))
    assert set(outcome["passed"]) == {"a.c", "docs/x.md"}
    assert any(f["text"].startswith("# Notes") for _, body in checker.calls for f in body["files"])
    assert parse_ledger(remote.tree()[LEDGER]) == []


def test_what_no_assistant_can_check_the_owner_can_mark_checked(project):
    c, t, epoch, remote, broker = project
    write(broker, t, epoch, "big.txt", "x" * 100_001, "w1")
    team = team_for(c, broker, Checker({}, ROUTES))
    outcome = asyncio.run(team.independent.run(t["project_id"]))
    assert outcome["left"] == ["big.txt"]
    assert "mark it checked on the Projects page" in broker.drafts.checks.pending(t["project_id"])[0]["note"]
    done = broker.drafts.owner_checked(t["project_id"], ["big.txt"], "Read it all.")
    assert done["passed"] == ["big.txt"] and "Read it all." in remote.tree()[done["report"]]
    assert not broker.drafts.checks.pending(t["project_id"])


def test_a_file_marked_during_a_check_keeps_its_marker(project):
    c, t, epoch, remote, broker = project
    write(broker, t, epoch, "a.c", "int a;\n", "w1")
    checker = Checker({}, ROUTES)
    team = team_for(c, broker, checker)
    original = checker.exchange

    async def meanwhile(route, message):
        broker.drafts.checks.mark(t["project_id"], "b.c", "worker.opus", "y")
        return await original(route, message)

    checker.exchange = meanwhile
    asyncio.run(team.independent.run(t["project_id"]))
    assert [i["path"] for i in broker.drafts.checks.pending(t["project_id"])] == ["b.c"]
