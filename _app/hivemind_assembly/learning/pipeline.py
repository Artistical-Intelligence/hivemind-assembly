"""Captured lessons move through owner permission, tagging, evaluation and promotion.

Accepted tasks retain facts and procedures as candidates. Without this pipeline
they could sit indefinitely: unshared lessons cannot be categorized or tested,
lessons from tasks that chose no tags stay unclassified, and per-asset suite
bindings never exist for new asset keys. `advance` performs every step the owner
has already permitted; `stages` names the next blocking step for each lesson.
"""

import json

from hivemind_assembly.core.common import Blocked

DEFAULT_SUITE = "native_suite_default"


def default_suite(store):
    rows = store.rows(
        "SELECT payload FROM records WHERE kind=? ORDER BY rowid DESC LIMIT 1",
        (DEFAULT_SUITE,),
    )
    return json.loads(rows[0]["payload"]) if rows else None


def _evaluations(store, lesson):
    return [
        row["id"]
        for row in store.rows(
            "SELECT id FROM records WHERE kind='native_evaluation' AND json_extract(payload,'$.candidate')=?",
            (lesson,),
        )
    ]


def advance(team, lessons):
    """Apply owner-permitted steps to newly captured lessons; never raises."""
    from .engine import Learning
    from .scopes import KnowledgeScopes

    learning = Learning(team.store)
    settings = team.experimental.settings()
    results = {}
    for lesson in lessons:
        done = []
        try:
            row = team.store.one("SELECT * FROM lessons WHERE id=?", (lesson,))
            if settings["share_captured_lessons"] and not learning.external_allowed(row):
                learning.share(lesson, True)
                done.append("shared")
            if learning.external_allowed(row) or "shared" in done:
                if KnowledgeScopes(team.store).tags("lesson", lesson) == ["unclassified"]:
                    team.curation.queue("lesson", lesson)
                    done.append("curation_queued")
                if settings["enabled"] and team.learning_trials is not None and not _evaluations(team.store, lesson):
                    key = team.queue_learning(lesson)
                    if key:
                        team.learning_trials.state(key, "queued")
                        done.append("evaluation_queued")
        except Blocked as error:
            done.append("blocked: " + str(error))
        except Exception as error:  # Capture must never fail the accepted task.
            done.append("error: " + str(error))
        results[lesson] = done
        team.store.event(lesson, "learning_pipeline_advanced", {"steps": done})
    return results


def stages(store, experimental_settings, trials=None):
    from .engine import Learning
    from .scopes import KnowledgeScopes

    learning = Learning(store)
    scopes = KnowledgeScopes(store)
    suite = default_suite(store)
    result = []
    for row in store.rows(
        "SELECT * FROM lessons WHERE asset_key LIKE 'accepted-%' ORDER BY created DESC LIMIT 200"
    ):
        lesson = row["id"]
        evaluations = _evaluations(store, lesson)
        if row["status"] == "active":
            stage, action = "active", "In use for tasks with matching tags; roll back from Learned assets if needed"
        elif row["status"] != "candidate":
            stage, action = row["status"], "No action"
        elif not learning.external_allowed(row):
            stage, action = "needs_permission", "Allow native processing (or enable sharing of captured lessons) to categorize and evaluate it"
        elif scopes.tags("lesson", lesson) == ["unclassified"]:
            stage, action = "needs_tags", "Automatic categorization is queued or required; unclassified lessons reach no task"
        elif evaluations:
            state = trials.status(evaluations[-1])["stage"] if trials is not None else "recorded"
            stage, action = "evaluating", "Native evaluation " + state
        elif not experimental_settings["enabled"]:
            stage, action = "waiting_policy", "Enable experimental learning to evaluate it"
        elif suite is None:
            stage, action = "needs_suite", "Choose a protected suite as the default for captured lessons"
        else:
            stage, action = "ready", "Evaluation will be queued on the next capture or by Evaluate"
            last = store.rows(
                "SELECT payload FROM events WHERE entity=? AND kind='learning_pipeline_advanced' ORDER BY seq DESC LIMIT 1",
                (lesson,),
            )
            blocked = [
                step for step in (json.loads(last[0]["payload"])["steps"] if last else [])
                if step.startswith(("blocked: ", "error: "))
            ]
            if blocked:
                stage, action = "blocked", blocked[-1].split(": ", 1)[1]
        result.append({"lesson": lesson, "kind": row["kind"], "stage": stage, "next_action": action})
    return result
