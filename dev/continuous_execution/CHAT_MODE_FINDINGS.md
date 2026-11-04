# Scheduled Chat Mode experiments — evidence and limits

**CHECKS PENDING:** This is a concise evidence ledger based on the November 3–4, 2026 ChatGPT Automations registry and completed task reports. It is **not** independent review of HA implementation or a release artifact. Separate run reports are model-authored and not an immutable transaction log; persisted registry state and actual completed run IDs corroborate what was observed. Do not equate a completed task with acceptance of underlying code.

## Completed experiments

| Evidence key (task prompt) | Finding | Limit |
| --- | --- | --- |
| `CHATMODE-20261103-SELF-INSTRUCTIONS-A` | A scheduled run updated its own complete saved prompt; a later scheduled run received the replacement; completed results recorded. | The saved instructions are not a guarantee that external GitHub instructions were reloaded. |
| `CHATMODE-20261103-SELF-FREQUENCY-A` | A scheduled run changed its recurrence to `FREQ=HOURLY;INTERVAL=2;COUNT=1`; a later run completed with scheduled-for 2026-11-04 04:15 UTC. | Exactly **one** revised occurrence, **not** proof of multiple consecutive two-hour intervals. |
| `CHATMODE-20261103-SELF-NEXT-A` | A scheduled run moved its own schedule; later completed run recorded scheduled-for 04:00 UTC. | Real start occurred 03:57:03 UTC, roughly 3 minutes early. |
| `CHATMODE-20261103-SELF-PAUSE-A` | A scheduled run called an update on itself with `is_enabled=false`; saved registry state remained disabled and its run completed. | Did not demonstrate resume from paused state. |
| `CHATMODE-20261104-XTASK-PRODUCER-A` + `CHATMODE-20261104-XTASK-CONSUMER-A` + auditor | Scheduled producer changed exactly one separate consumer's saved prompt; consumer independently ran the new marker and completed; auditor retrieved completed results. | Separate **run IDs** but the **same ChatGPT chat reference**, not qualified independent review. |
| `CHATMODE-20261104-COOP-COORDINATOR-A` + `CHATMODE-20261104-COOP-TARGET-A` + observer | A scheduled coordinator changed the target's prompt and one-time DTSTART; target completed at the revised occurrence; observer retrieved both completed results. | Same chat reference; model reports of updates are not independent tool transaction logs. |
| `CHATMODE-20261103-ONESHOT-PARENT-A` and `CHATMODE-20261103-PARENTCHILD-A` | Scheduled parent runs executed and inspected the registry, but their runtime prohibited creating an additional scheduled task. No child existed. | **Blocked at permission level**; no backend creation attempt, cannot infer implementation incapability. |

All completed prior bounded tests were disabled afterward; no indefinite worker was created. Some scheduled starts occurred early/late; intended times alone do not establish actual execution. All reported status claims require task identity, exact `scheduled_for`, `last_run.id`, `recorded_status`, `completed_at`, and matching `latest_result.run_id`.

## Newly scheduled bounded experiments on November 4

These are **scheduled, not passed** until observed completed execution and independently read persisted state.

| Key | Hypothesis and bounds |
| --- | --- |
| `CHATMODE-20261104-INTERACTIVE-ECHO-A` | Whether a scheduled Chat Mode execution can post a new **user-role** message into the *same conversation* to trigger a separate ordinary interactive turn. No supported native action is known in the inspected interactive interface; no relays or descendants. |
| `CHATMODE-20261104-RECUR-3X2H-A` | From an initial hourly schedule, update to `DTSTART:20261104T112000Z\nRRULE:FREQ=HOURLY;INTERVAL=2;COUNT=3`. Expected three future runs at 11:20, 13:20 and 15:20 UTC; separate read-only auditors check each result. Do not claim all three ran merely because the update was saved. |
| `CHATMODE-20261104-REVIVE-MANAGER-A` | Scheduled manager is permitted to update **exactly two prior test-owned automations**, not other owner-paused tasks: completed one-time `COOP-TARGET-A` -> a future `COUNT=2` hourly schedule, and prior self-paused `SELF-PAUSE-A` -> a future one-time schedule. Prompts replaced and tasks re-enabled only if owner/id/current-status validation passes. |
| `CHATMODE-20261104-REVIVE-AUDITOR-A` | Later read-only inspection of manager and both revised tests; separate config acceptance from actual post-revival execution and completion. |
| `CHATMODE-20261104-GITHUB-WRITE-A` | One scheduled Chat Mode run checks whether its GitHub connector can **actually write and read back one harmless test file on branch `experiment/chatmode-scheduled-github-20261104`**, leaving main unchanged. Branch provisioned interactively. Requires authorized tool access and approval; a scheduled task may be blocked. |

## Orchestration design decision

The practical pattern is a **pre-provisioned, owner-authorized pool of existing tasks**, with a default proposal of five useful roles and upper target of ten when plan limits/actual work justify it. A conductor can adapt authorized tasks' prompts, schedule and enabled status. This does not permit it to create children from its own scheduled runtime, circumvent per-task hourly limits, manufacture independent chat contexts, override source mediation or restart user-paused work.

Permanent objective persists across ever-changing evidence-based milestones; check the project's final pinned acceptance rather than declaring success after a single chunk. Every scheduled prompt must carry short immutable safety/mission instructions. A GitHub `AGENTS.md` or `SKILL.md` edit is **not** automatically read by existing ChatGPT scheduled runs; retrieval or HA-specific injection must be verified. External project checkpoints must remain small and revision-bound.

See [CONDUCTOR.md](CONDUCTOR.md), [PROCESS.md](PROCESS.md), [CHATGPT.md](../../CHATGPT.md), and [SKILL.md](../../skills/chatmode-scheduled-orchestration/SKILL.md).

## Usage and documentation

Official task documentation states that **a completed scheduled Chat task may consume plan usage allowance even without a visible reply**. Conversations directly with a dot do not count against ordinary ChatGPT limits, but no source guarantees that delegated ordinary Chat tasks become free. Dot can create cloud threads and delegate Work/Codex tasks, not proven permission to turn all Chat Mode scheduled work into free dot conversation. References:
- https://help.openai.com/en/articles/10291617-scheduled-tasks-in-chatgpt
- https://learn.chatgpt.com/docs/automations
- https://learn.chatgpt.com/docs/dots
- https://learn.chatgpt.com/docs/dots/tasks-and-memory

Never treat a Codex-specific context metric as an available Chat Mode variable without identifying and testing its precise supported interface.
