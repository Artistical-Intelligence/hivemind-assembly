"""Captured lessons advance through permitted steps and report what blocks them."""

import pytest
import test_app

from hivemind_assembly.learning.engine import Learning
from hivemind_assembly.learning.pipeline import DEFAULT_SUITE, advance, stages

app = test_app.app


def captured(store, task="task-a"):
    return Learning(store).propose(
        "accepted-facts:" + task,
        "knowledge",
        {
            "scope": ["reverse_engineering", "core"],
            "preconditions": ["linux_project"],
            "exclusions": [],
            "evidence": ["acceptance-artifact"],
            "content": {"checks": [], "revision": 1},
        },
    )


def stage_of(app, lesson):
    rows = stages(app.store, app.team.experimental.settings(), app.native_learning)
    return next(r for r in rows if r["lesson"] == lesson)


def test_unshared_lesson_waits_for_owner_permission(app):
    lesson = captured(app.store)
    assert advance(app.team, [lesson])[lesson] == []
    assert stage_of(app, lesson)["stage"] == "needs_permission"


def test_owner_settings_share_queue_tagging_and_evaluation(app):
    if app.native_learning is None:
        pytest.skip("A C compiler is required for the native evaluator")
    app.action("/api/learning/settings", {"enabled": True, "share_captured_lessons": True})
    lesson = captured(app.store)
    steps = advance(app.team, [lesson])[lesson]
    # Shared, and because the task chose no tags it is queued for categorization.
    assert steps[:2] == ["shared", "curation_queued"]
    assert stage_of(app, lesson)["stage"] == "needs_tags"
    # Once tagged, the missing default suite is named as the blocker.
    from hivemind_assembly.learning.scopes import KnowledgeScopes

    scopes = KnowledgeScopes(app.store)
    scopes.create_tag("elf", "ELF")
    scopes.assign("lesson", lesson, ["elf"])
    assert stage_of(app, lesson)["stage"] == "needs_suite"
    suite = app.native_learning.protect(
        [
            {"id": "r", "family": "a", "project": "one", "split": "regression",
             "inputs": {"objective": "x"}, "expected": {"original_hex": "c3", "vectors": [], "output_bits": 32}},
            {"id": "h", "family": "b", "project": "two", "split": "holdout",
             "inputs": {"objective": "x"}, "expected": {"original_hex": "c3", "vectors": [], "output_bits": 32}},
        ]
    )
    app.store.put(DEFAULT_SUITE, "binding-1", {"suite": suite, "route": None, "repeats": 3})
    second = captured(app.store, "task-b")
    scopes.assign("lesson", second, ["elf"])
    steps = advance(app.team, [second])[second]
    # This host has no verified native worker session, so queueing names that
    # blocker instead of silently leaving the lesson unevaluated.
    assert steps[-1] == "blocked: No permitted experimental worker has verified session readiness"
    assert stage_of(app, second) | {"lesson": None} == {
        "lesson": None,
        "kind": "knowledge",
        "stage": "blocked",
        "next_action": "No permitted experimental worker has verified session readiness",
    }


def test_disabled_experiments_report_policy_block(app):
    app.action("/api/learning/settings", {"enabled": False, "share_captured_lessons": True})
    lesson = captured(app.store)
    advance(app.team, [lesson])
    from hivemind_assembly.learning.scopes import KnowledgeScopes

    scopes = KnowledgeScopes(app.store)
    scopes.create_tag("elf", "ELF")
    scopes.assign("lesson", lesson, ["elf"])
    assert stage_of(app, lesson)["stage"] == "waiting_policy"
