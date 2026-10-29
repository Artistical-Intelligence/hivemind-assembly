import asyncio
import json
import pytest
from hivemind_assembly.core.common import Blocked, ContractError, Retryable, canonical
from hivemind_assembly.core.controller import Controller
from hivemind_assembly.core.traces import Traces
from hivemind_assembly.core.backups import snapshot, restore, verify
from hivemind_assembly.automation.native import NativeBrowser
from hivemind_assembly.learning.engine import Learning
from hivemind_assembly.learning.experiments import Experiments, EvolutionArchive
from hivemind_assembly.learning.campaigns import Campaigns


def test_private_trace_search_pagination_annotation_and_export(store):
    t = store.create_project("trace", "debug")
    traces = Traces(store)
    a = traces.append(
        t["id"],
        "request1",
        "adviser.extra",
        "response_error",
        {"text": "<script>bad reply</script>"},
    )
    assert (
        traces.append(
            t["id"],
            "request1",
            "adviser.extra",
            "response_error",
            {"text": "<script>bad reply</script>"},
        )
        == a
    )
    first = traces.search(query="BAD", limit=1)
    assert len(first["items"]) == 1
    traces.annotate(first["after"], "Wrong protocol")
    assert traces.search(after=first["after"])["items"][0]["kind"] == "annotation"
    assert len(list(traces.export(task=t["id"]))) == 2
    assert not traces.search(route="worker.opus")["items"]


@pytest.mark.parametrize("complete", [True, False])
def test_raw_model_reply_survives_missing_request_id(store, tmp_path, complete):
    t = store.create_project("raw", "capture")
    c = Controller(store)
    m = c.prepare_message(
        t["id"], "worker.opus", "https://fixture.invalid", {"body": "hello"}
    )
    envelope = (
        "WORKBENCH_REQUEST:"
        + m["id"]
        + "\n"
        + canonical({"request_id": m["id"], "body": "hello"})
    )

    class User:
        def filter(self, **kw):
            return self

        async def count(self):
            return 1

        async def inner_text(self):
            return envelope

    class Page:
        def locator(self, s):
            return User()

        async def evaluate(self, *a):
            from hivemind_assembly.automation.native import REQUEST_ECHO
            if a[0] == REQUEST_ECHO:
                return [envelope]
            if "document.querySelectorAll(complete)" in a[0]:
                return complete
            return ["Malformed model reply with no request ID"]

    class Browser(NativeBrowser):
        async def observe(self, r):
            return {}

        async def page(self, r):
            return Page()

        async def visible(self, p, s):
            return complete if s == "done" else False

    b = Browser(
        {
            "routes": {
                "worker.opus": {
                    "selectors": {
                        "user_messages": ".user",
                        "assistant_messages": ".assistant",
                        "complete": "done",
                    }
                }
            }
        },
        tmp_path,
        c,
    )
    with pytest.raises(ContractError if complete else Retryable):
        asyncio.run(b.exchange("worker.opus", m, timeout=3 if complete else 0.05))
    records = c.traces.search(kind="response_snapshot")["items"]
    assert len(records) == 1 and "Malformed" in records[0]["payload"]["text"]
    assert store.one("SELECT state FROM messages WHERE id=?", (m["id"],))["state"] == (
        "invalid" if complete else "processing"
    )


def test_full_backup_restore_includes_sources_project_and_transcripts(store, tmp_path):
    task = store.create_project("backup", "preserve", paused=True)
    root = store.root / "projects" / task["project_id"] / "ghidra"
    root.mkdir()
    (root / "program.gpr").write_bytes(b"original project")
    (store.root / "settings.json").write_text("{}")
    Traces(store).append(
        task["id"], "m", "worker.opus", "response_complete", {"text": "retained output"}
    )
    private = store.root / "private"
    private.mkdir()
    (private / "credential").write_text("must not export")
    target = tmp_path / "backup.zip"
    snapshot(store, target)
    manifest = verify(target)
    assert not any("private" in x for x in manifest["files"])
    destination = tmp_path / "restored"
    restore(target, destination)
    assert (
        destination / "projects" / task["project_id"] / "ghidra" / "program.gpr"
    ).read_bytes() == b"original project"
    from hivemind_assembly.core.store import Store

    restored = Store(destination)
    try:
        assert (
            Traces(restored).search()["items"][0]["payload"]["text"]
            == "retained output"
        )
    finally:
        restored.close()
    with pytest.raises(Blocked):
        restore(target, destination)


def test_independent_learning_rejects_bad_holdout_and_promotes_real_gain(store):
    # Trusted evaluator interprets the candidate; only protected expected results
    # determine fitness. The candidate never supplies scores or holdout values.
    def run(content, inputs):
        return {"answer": inputs["value"] * content["multiplier"]}

    exp = Experiments(store, run, "fixture-engine-v1")
    cases = [
        {
            "id": "training-regression",
            "family": "small",
            "project": "one",
            "split": "regression",
            "inputs": {"value": 2},
            "expected": {"answer": 4},
        },
        {
            "id": "withheld",
            "family": "negative",
            "project": "two",
            "split": "holdout",
            "inputs": {"value": -3},
            "expected": {"answer": -6},
        },
    ]
    suite = exp.protect(cases)

    def propose(multiplier):
        return Learning(store).propose(
            "multiply",
            "procedure",
            {
                "scope": ["core"],
                "preconditions": ["integer input"],
                "exclusions": [],
                "evidence": ["test-origin"],
                "content": {"multiplier": multiplier},
            },
        )

    bad = propose(3)
    assert not exp.evaluate(bad, {"multiplier": 1}, suite, 3)["eligible"]
    good = propose(2)
    result = exp.evaluate(good, {"multiplier": 1}, suite, 3)
    assert result["eligible"]
    Learning(store).promote(good, result["evaluation"], "evaluator")
    selected = EvolutionArchive(store).parent("multiply", "fixture-engine-v1")
    assert selected["content"] == {"multiplier": 2}
    assert EvolutionArchive(store).parent("multiply", "other-engine") is None
    cases[1]["project"] = "one"
    with pytest.raises(Blocked):
        exp.protect(cases)
    with pytest.raises(Blocked):
        Experiments(store, run, "v2").evaluate(propose(2), {"multiplier": 2}, suite, 3)


def test_donor_reflection_curation_is_bounded_and_evidence_linked(ready):
    c, t, epoch = ready
    from hivemind_assembly.core.broker import Broker

    result = Broker(c, {}).execute(
        {
            "id": "op-learning",
            "task_id": t["id"],
            "owner": "worker.opus",
            "epoch": epoch,
            "revision": 0,
            "tool": "list_files",
            "args": {},
        }
    )
    base = Learning(c.store).propose(
        "review",
        "knowledge",
        {
            "scope": ["core"],
            "preconditions": ["files"],
            "exclusions": ["unobserved inputs"],
            "evidence": ["op-learning"],
            "external_allowed": True,
            "content": {"entries": {}},
        },
    )
    campaigns = Campaigns(c.store)
    key = campaigns.start(t["id"], base, ["op-learning"])
    assert "learning_feedback" in campaigns.reflection_prompt(key)
    campaigns.retain_reflection(
        key, {"feedback": {"key_insight": "Inspect existing files first"}}
    )
    assert "learning_candidate" in campaigns.curation_prompt(key)
    response = {
        "edits": [
            {
                "action": "add",
                "id": "inspect",
                "entry": {
                    "text": "Inspect before modifying",
                    "conditions": ["files"],
                    "exceptions": ["new workspace"],
                    "evidence": ["op-learning"],
                },
            }
        ]
    }
    first = campaigns.propose(key, response)
    assert campaigns.propose(key, response) == first
    row = c.store.one(
        "SELECT status,payload FROM lessons WHERE id=?", (first["candidate"],)
    )
    assert row["status"] == "candidate" and json.loads(row["payload"])[
        "exclusions"
    ] == ["unobserved inputs"]
