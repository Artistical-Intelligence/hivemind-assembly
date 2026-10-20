import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from hivemind_assembly.core.common import Blocked, ContractError, Conflict
from hivemind_assembly.learning.scopes import KnowledgeScopes
from hivemind_assembly.learning.knowledge import Knowledge
from hivemind_assembly.learning.engine import Learning
from hivemind_assembly.learning.playbook import select_context
from hivemind_assembly.automation.sessions import Sessions


def scoped_sources(store, tmp_path):
    scopes = KnowledgeScopes(store)
    scopes.create_tag("arithmetic", "Arithmetic")
    scopes.create_tag("audio", "Audio")
    knowledge = Knowledge(store)
    result = []
    for tag in ("arithmetic", "audio"):
        path = tmp_path / (tag + ".txt")
        path.write_text("shared keyword SECRET-" + tag)
        result.append(knowledge.ingest(path, True, [tag]))
    task = store.create_project("scope", "arithmetic task")
    return scopes, knowledge, result, task


def test_categories_only_then_tag_gated_sources_and_obligations(store, tmp_path):
    scopes, knowledge, sources, task = scoped_sources(store, tmp_path)
    assert "SECRET" not in json.dumps(scopes.catalog())
    assert "source_" not in json.dumps(scopes.catalog())
    with pytest.raises(Blocked, match="scope"):
        knowledge.search("shared", task=task["id"])
    with pytest.raises(ContractError, match="existing"):
        scopes.select(task["id"], ["made-up"], scopes.catalog()["revision"])
    scopes.select(task["id"], ["arithmetic"], scopes.catalog()["revision"])
    hits = knowledge.search("shared", external=True, task=task["id"])
    assert [h["source"] for h in hits] == [sources[0]["id"]]
    with pytest.raises(Blocked, match="outside"):
        knowledge.source(sources[1]["id"], "adviser", True, task["id"])
    obligation = {
        "source": sources[1]["id"],
        "revision": sources[1]["revision"],
        "section": "1",
    }
    reading = knowledge.reading([obligation], task=task["id"])
    assert not reading["records"] and reading["critical_gaps"]
    scopes.select(task["id"], [], scopes.catalog()["revision"])
    assert knowledge.search("shared", external=True, task=task["id"]) == []


def test_existing_material_stays_private_and_scope_versions_follow_access(
    store, tmp_path
):
    scopes, knowledge, sources, task = scoped_sources(store, tmp_path)
    scopes.select(task["id"], ["arithmetic"], scopes.catalog()["revision"])
    before = scopes.fingerprint(task["id"])
    scopes.assign("source", sources[0]["id"], ["audio"])
    assert scopes.fingerprint(task["id"]) != before
    assert not knowledge.search("shared", task=task["id"])
    path = tmp_path / "legacy.txt"
    path.write_text("shared keyword legacy private")
    legacy = knowledge.ingest(path, True)
    assert scopes.tags("source", legacy["id"]) == ["unclassified"]
    assert not knowledge.search("shared", task=task["id"])
    with store.tx() as db:
        db.execute("UPDATE tasks SET objective='audio task' WHERE id=?", (task["id"],))
    assert not scopes.status(task["id"])["selected"]


def test_lesson_ranking_cannot_cross_tags_or_export_permission(store):
    scopes = KnowledgeScopes(store)
    for tag in ("arithmetic", "audio"):
        scopes.create_tag(tag, tag)
    learning = Learning(store)
    ids = []
    for tag, shared in (("arithmetic", True), ("audio", True), ("arithmetic", False)):
        key = learning.propose(
            "method-" + str(len(ids)),
            "knowledge",
            {
                "scope": ["core"],
                "tags": [tag],
                "preconditions": [],
                "exclusions": [],
                "evidence": ["fixture"],
                "external_allowed": shared,
                "content": "shared keyword " + tag,
            },
        )
        with store.tx() as db:
            db.execute("UPDATE lessons SET status='active' WHERE id=?", (key,))
        ids.append(key)
    task = store.create_project("learn", "shared keyword")
    scopes.select(task["id"], ["arithmetic"], scopes.catalog()["revision"])
    result = select_context(store, "core", "shared", external=True, task=task["id"])
    assert [x["id"] for x in result["selected"]] == ids[:1]
    assert ids[1] not in json.dumps(result) and ids[2] not in json.dumps(result)


def test_changed_catalog_rejects_stale_classification(store):
    scopes = KnowledgeScopes(store)
    revision = scopes.catalog()["revision"]
    task = store.create_project("new", "task")
    scopes.create_tag("code", "Code")
    with pytest.raises(Conflict, match="catalog"):
        scopes.select(task["id"], [], revision)


def test_skill_updates_and_reverts_invalidate_context_without_resetting_tags(store):
    scopes = KnowledgeScopes(store)
    skill = {"id": "method", "scope": ["core"], "content": "first"}
    scopes.register_skills("domain", [skill])
    scopes.create_tag("chosen", "Chosen")
    scopes.assign("skill", "domain:method", ["chosen"])
    task = store.create_project("skill", "test")
    scopes.select(task["id"], ["chosen"], scopes.catalog()["revision"])
    original = scopes.fingerprint(task["id"])
    scopes.register_skills("domain", [{**skill, "content": "changed"}])
    assert scopes.fingerprint(task["id"]) != original
    assert scopes.tags("skill", "domain:method") == ["chosen"]
    scopes.register_skills("domain", [skill])
    assert scopes.fingerprint(task["id"]) == original


def test_retained_excerpts_follow_current_task_scope_and_permission(store, tmp_path):
    scopes, knowledge, sources, task = scoped_sources(store, tmp_path)
    scopes.select(task["id"], ["arithmetic"], scopes.catalog()["revision"])
    source = sources[0]
    excerpt = knowledge.authorize_excerpt(
        source["id"], source["revision"], "1", task["project_id"], task["id"]
    )

    def read(task_id=task["id"]):
        return knowledge.artifacts.read(
            excerpt["id"], "worker", task["project_id"], task=task_id
        )

    assert b"SECRET-arithmetic" in read()
    with pytest.raises(Blocked, match="scoped task"):
        read(None)
    scopes.select(task["id"], [], scopes.catalog()["revision"])
    with pytest.raises(Blocked, match="outside"):
        read()
    scopes.select(task["id"], ["arithmetic"], scopes.catalog()["revision"])
    with store.tx() as db:
        db.execute("UPDATE sources SET external_allowed=0 WHERE id=?", (source["id"],))
    with pytest.raises(Blocked, match="revoked"):
        read()
    assert b"SECRET-arithmetic" in knowledge.artifacts.read(excerpt["id"], "controller")


def test_scope_change_renews_session_even_below_context_limit(store, tmp_path):
    config = {"routes": {"worker.extra": {"conversation_url": "old"}}}
    sessions = Sessions(
        SimpleNamespace(config=config, controller=SimpleNamespace(store=store)),
        tmp_path / "settings.json",
    )
    renewals = []

    async def due(route):
        return False

    async def renew(task, route):
        renewals.append((task, route))
        config["routes"][route]["conversation_url"] = "new-" + str(len(renewals))

    sessions.due, sessions.renew = due, renew
    allowance = SimpleNamespace(eligible=lambda: True)

    async def run():
        await sessions.ensure("one", "worker.extra", allowance, context="scope-a")
        await sessions.ensure("one", "worker.extra", allowance, context="scope-a")
        await sessions.ensure("one", "worker.extra", allowance, context="scope-b")
        await sessions.ensure("two", "worker.extra", allowance, context="scope-c")

    asyncio.run(run())
    assert len(renewals) == 3


def test_classifier_gets_no_skills_sources_lessons_or_old_results(store, tmp_path):
    from hivemind_assembly.automation.team import NativeTeam
    from hivemind_assembly.automation.policy import Availability
    from hivemind_assembly.core.controller import Controller
    from hivemind_assembly.core.broker import Broker

    scopes, knowledge, sources, task = scoped_sources(store, tmp_path)
    cfg = json.loads(
        (Path(__file__).parents[1] / "_app/config/default.json").read_text()
    )
    cfg["routes"]["worker.extra"]["conversation_url"] = "fixture"
    controller = Controller(store)
    controller.acquire(task["id"], "worker.extra")
    task = store.task(task["id"])
    sent = []

    class Browser:
        async def exchange(self, route, message):
            sent.append(json.loads(message["payload"]))
            return {
                "request_id": message["id"],
                "type": "knowledge_scope",
                "tags": [],
                "catalog_revision": scopes.catalog()["revision"],
            }

    team = NativeTeam(controller, Broker(controller, cfg), Browser(), cfg)
    team.host = SimpleNamespace(record=lambda *args: None)
    team.observations["worker.extra"] = Availability(
        "worker.extra", True, True, True, time.time()
    )
    asyncio.run(
        team.ask(
            task,
            {"seq": 1, "phase": "classify"},
            "worker.extra",
            {"last_result": "OLD-SECRET"},
        )
    )
    raw = json.dumps(sent)
    assert "SECRET" not in raw
    assert (
        "learned_methods" not in raw
        and "domain_instructions" not in raw
        and "capabilities" not in raw
    )
    assert "procedure" not in raw and sources[0]["id"] not in raw


@pytest.mark.parametrize("revoke", [False, True])
def test_ingestion_can_create_tags_but_revocation_stops_assignment(
    store, tmp_path, revoke
):
    from contextlib import nullcontext
    from hivemind_assembly.learning.curation import KnowledgeCuration
    from hivemind_assembly.core.controller import Controller

    scopes, knowledge, sources, task = scoped_sources(store, tmp_path)
    source = sources[0]["id"]
    controller = Controller(store)
    calls = []

    class Browser:
        config = {"routes": {"adviser.extra": {"conversation_url": "curation-only"}}}

        async def exchange(self, route, message):
            payload = json.loads(message["payload"])
            assert "SECRET-arithmetic" in payload["material_excerpt"]
            assert "SECRET-audio" not in payload["material_excerpt"]
            calls.append(message["id"])
            response = {
                "request_id": message["id"],
                "type": "knowledge_tags",
                "tags": ["arithmetic", "integers"],
                "new_tags": [
                    {
                        "id": "integers",
                        "label": "Integers",
                        "description": "Integer arithmetic",
                    }
                ],
            }
            controller.message_state(message["id"], "validated", json.dumps(response))
            if revoke:
                with store.tx() as db:
                    db.execute(
                        "UPDATE sources SET external_allowed=0 WHERE id=?", (source,)
                    )
            return response

    class Isolated:
        async def isolated_browser(self, task, route, identity):
            return Browser()

        async def release_isolated(self, identity):
            pass

    team = SimpleNamespace(
        store=store,
        controller=controller,
        sessions=Isolated(),
        observations={"adviser.extra": SimpleNamespace(eligible=lambda: True)},
        learning_budget=lambda *args: nullcontext(),
    )
    curation = KnowledgeCuration(team)
    key = curation.queue("source", source)["id"]
    if revoke:
        with pytest.raises(Blocked, match="authorized"):
            asyncio.run(curation.run(key))
        assert scopes.tags("source", source) == ["arithmetic"]
        assert "integers" not in [t["id"] for t in scopes.catalog()["tags"]]
    else:
        asyncio.run(curation.run(key))
        asyncio.run(curation.run(key))
        assert len(calls) == 1
        assert scopes.tags("source", source) == ["arithmetic", "integers"]
        assert curation.status(key)["stage"] == "completed"
