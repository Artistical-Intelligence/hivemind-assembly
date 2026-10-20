"""Wall-clock corrections must not rewind committed authority or recovery."""

from types import SimpleNamespace

import pytest

from hivemind_assembly.automation.onboarding import NativeSetup
from hivemind_assembly.automation.recovery import Recovery
from hivemind_assembly.automation.sessions import Sessions
from hivemind_assembly.automation.team import NativeTeam
from hivemind_assembly.core.publication import Publications
from hivemind_assembly.core.telemetry import export_local
from hivemind_assembly.learning.curation import KnowledgeCuration
from hivemind_assembly.learning.engine import Learning
from hivemind_assembly.learning.native_rollouts import NativeRollouts
from hivemind_assembly.learning.scopes import KnowledgeScopes


@pytest.fixture(params=[0, -10], ids=["tied-clock", "clock-rollback"])
def clocked_store(store, monkeypatch, request):
    original = store.put
    stamp = 1000

    def put(kind, key, payload, conn=None):
        nonlocal stamp
        result = original(kind, key, payload, conn)
        stamp += request.param
        if conn is not None:
            conn.execute(
                "UPDATE records SET created=? WHERE kind=? AND id=?", (stamp, kind, key)
            )
        else:
            with store.tx() as db:
                db.execute(
                    "UPDATE records SET created=? WHERE kind=? AND id=?",
                    (stamp, kind, key),
                )
        return result

    monkeypatch.setattr(store, "put", put)
    return store


def test_revocation_changes_authority_and_session_scope(clocked_store):
    store = clocked_store
    scopes, learning = KnowledgeScopes(store), Learning(store)
    scopes.create_tag("code", "Code")
    lesson = learning.propose(
        "method",
        "knowledge",
        {
            "scope": ["core"],
            "tags": ["code"],
            "content": "private procedure",
            "preconditions": [],
            "exclusions": [],
            "evidence": ["fixture"],
        },
    )
    task = store.create_project("permission", "code")
    scopes.select(task["id"], ["code"], scopes.catalog()["revision"])
    row = store.one("SELECT * FROM lessons WHERE id=?", (lesson,))
    learning.share(lesson, True)
    shared_scope = scopes.fingerprint(task["id"])
    assert learning.external_allowed(row)
    learning.share(lesson, False)
    assert not learning.external_allowed(row)
    assert scopes.fingerprint(task["id"]) != shared_scope


def test_skill_changes_and_reverts_follow_journal(clocked_store):
    scopes = KnowledgeScopes(clocked_store)
    skill = {"id": "method", "scope": ["code"], "content": "first"}
    scopes.register_skills("core", [skill])
    task = clocked_store.create_project("skill", "code")
    scopes.select(task["id"], ["code"], scopes.catalog()["revision"])
    before = scopes.fingerprint(task["id"])
    scopes.register_skills("core", [{**skill, "content": "second"}])
    assert scopes.fingerprint(task["id"]) != before
    scopes.register_skills("core", [skill])
    assert scopes.fingerprint(task["id"]) == before


def test_latest_workflow_setup_publication_and_learning_states(clocked_store, tmp_path):
    store = clocked_store
    # Each reader must use the same durable append order across independent kinds.
    team = NativeTeam.__new__(NativeTeam)
    team.store, team.scopes = store, KnowledgeScopes(store)
    setup = NativeSetup(None, store, tmp_path / "settings.json")
    publication = Publications(SimpleNamespace(store=store))
    curation = KnowledgeCuration(SimpleNamespace(store=store))
    trials = NativeRollouts(store, None, None, None, None, None)
    task = store.create_project("resume", "work")["id"]
    for seq in (1, 2):
        team.save_flow(task, {"seq": seq, "phase": "intent"})
        setup.save("worker", stage="stage" + str(seq))
        publication._save("publication_head", "project", {"sha": str(seq)})
        curation.state("item", "stage" + str(seq))
        trials.state("trial", "stage" + str(seq))
    assert team.flow(task)["seq"] == 2
    assert setup.status("worker")["stage"] == "stage2"
    assert publication.status("project")["sha"] == "2"
    assert curation.status("item")["stage"] == "stage2"
    assert trials.status("trial")["stage"] == "stage2"


def test_session_crash_recovery_applies_binding_chain_in_commit_order(
    clocked_store, tmp_path
):
    config = {"routes": {"worker": {"conversation_url": "old"}}}
    for old, new in (("old", "middle"), ("middle", "latest")):
        clocked_store.put(
            "session_commit",
            new,
            {
                "route": "worker",
                "previous": old,
                "binding": {"conversation_url": new},
            },
        )
    sessions = Sessions(
        SimpleNamespace(config=config, controller=SimpleNamespace(store=clocked_store)),
        tmp_path / "settings.json",
    )
    sessions.restore_bindings()
    assert config["routes"]["worker"]["conversation_url"] == "latest"
    sessions.restore_bindings()
    assert config["routes"]["worker"]["conversation_url"] == "latest"


def test_recovery_counts_consecutive_attempts_in_commit_order(clocked_store):
    recovery = Recovery(clocked_store)
    for method in ("old", "new", "new", "new"):
        result = recovery.record_attempt("task", method, {}, {"error": "same"})
    assert result["needs_reviewer"]
    assert result["attempt"]["consecutive"] == 3


def test_export_cursor_does_not_rewind_after_clock_correction(clocked_store):
    # No network should be attempted when the latest cursor covers the journal.
    clocked_store.put("otlp_cursor:6006", "first", {"seq": 10})
    clocked_store.put("otlp_cursor:6006", "second", {"seq": 20})
    assert export_local(clocked_store) == {"sent": 0, "through": 20}
