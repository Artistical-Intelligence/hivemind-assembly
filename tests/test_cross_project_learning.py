"""Lesson lifecycle across projects: capture scope, measured promotion, reuse, rollback.

The evaluator is a trusted host fixture; this establishes the mechanism, not a
measured gain from native model sessions.
"""

import pytest

from hivemind_assembly.core.common import Blocked
from hivemind_assembly.learning.engine import Learning
from hivemind_assembly.learning.experiments import Experiments
from hivemind_assembly.learning.playbook import select_context
from hivemind_assembly.learning.scopes import KnowledgeScopes


def test_promoted_lesson_reaches_only_matching_later_projects_and_rolls_back(store):
    scopes = KnowledgeScopes(store)
    scopes.create_tag("elf-regions", "Static ELF region replacement")
    scopes.create_tag("audio", "Audio output")
    revision = scopes.catalog()["revision"]

    # Project A produced the method; project B supplies the independent holdout.
    def evaluate(content, inputs):
        # Trusted host interpretation of a procedure parameter.
        width = content["chunk"]
        return {"chunks": -(-inputs["bytes"] // width)}

    experiments = Experiments(store, evaluate, "regions-v1")
    suite = experiments.protect(
        [
            {"id": "a-small", "family": "utility", "project": "project-a", "split": "regression",
             "inputs": {"bytes": 130}, "expected": {"chunks": 3}},
            {"id": "a-empty", "family": "utility", "project": "project-a", "split": "regression",
             "inputs": {"bytes": 0}, "expected": {"chunks": 0}},
            {"id": "b-game", "family": "game", "project": "project-b", "split": "holdout",
             "inputs": {"bytes": 192}, "expected": {"chunks": 3}},
        ]
    )
    learning = Learning(store)

    def propose(chunk, version):
        return learning.propose(
            "region-chunking",
            "procedure",
            {
                "scope": ["reverse_engineering"],
                "tags": ["elf-regions"],
                "preconditions": ["static ELF input stream"],
                "exclusions": ["dynamic loaders"],
                "evidence": ["project-a:compare_project:" + version],
                "content": {"chunk": chunk},
                "external_allowed": True,
            },
        )

    baseline = propose(64, "1")
    first = experiments.evaluate(baseline, {"chunk": 1}, suite, 3)
    assert first["eligible"]
    learning.promote(baseline, first["evaluation"], "evaluator")

    # A later candidate that only fits the regression project fails the holdout.
    overfit = propose(65, "2")
    rejected = experiments.evaluate(overfit, {"chunk": 64}, suite, 3)
    assert not rejected["eligible"]
    with pytest.raises(Exception):
        learning.promote(overfit, rejected["evaluation"], "evaluator")

    later = store.create_project("project c", "Recover regions of a new ELF")
    unrelated = store.create_project("project d", "Recover audio mixer")
    scopes.select(later["id"], ["elf-regions"], revision)
    scopes.select(unrelated["id"], ["audio"], revision)
    reached = select_context(store, "reverse_engineering", "regions", external=True, task=later["id"])
    assert [x["id"] for x in reached["selected"]] == [baseline]
    hidden = select_context(store, "reverse_engineering", "regions", external=True, task=unrelated["id"])
    assert baseline not in str(hidden)
    assert [x["id"] for x in learning.applicable("reverse_engineering", task=later["id"])] == [baseline]

    learning.rollback(baseline)
    assert learning.applicable("reverse_engineering", task=later["id"]) == []
    # The stale engine cannot be evaluated against a corpus pinned for another engine.
    with pytest.raises(Blocked):
        Experiments(store, evaluate, "regions-v2").evaluate(propose(64, "3"), {"chunk": 1}, suite, 3)
