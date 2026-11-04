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
| `CHATMODE-20261104-INTERACTIVE-ECHO-A` | A bounded scheduled run **completed** (08:34:32 UTC) and inspected its available native actions. It reported **BLOCKED-NO-SUPPORTED-USER-MESSAGE-TOOL**: no operation for adding a user-role message to the same chat and independently triggering ordinary interactive Chat Mode. | `notify_parent` is not a transcript user message; no test message was submitted, so another interface or future product change remains untested. |
| `CHATMODE-20261104-GITHUB-WRITE-A` + `CHATMODE-20261104-GITHUB-WRITE-AUDITOR-A` | A scheduled Chat Mode run **completed** and created exactly one harmless file on a previously prepared non-main GitHub experiment branch, with readback. A **separate scheduled auditor** independently fetched exact commit `8eaa4ba5657cbcd4b4b663af2e79714a81d27a4d` and blob `fe649e1a23a0078ae612d7ecfcd4483135d37d05`. The authoring run and auditor have **different chat references**. | This verifies this particular scheduled GitHub connector read/write flow without an approval interruption; not arbitrary production repository access, other MCP connections, broader autonomous HA operation, or formal qualified review. |
| `CHATMODE-20261104-REVIVE-MANAGER-A` | One scheduled manager completed at **09:08:30 UTC**, reporting two accepted and persisted updates to **test-owned** disabled automations: one previously exhausted one-time target and one previously self-paused target; both were re-enabled with future schedules and replacement prompts. The former independently dispatched and **completed its first post-revival occurrence** (`scheduled_for=09:45 UTC`, completed at 09:42:06 UTC). | Manager update acceptance plus first revived run verified; do not claim the later second occurrence or self-paused target's new run before their own completed records. Unrelated user pauses remained out of scope. |
| `CHATMODE-20261103-ONESHOT-PARENT-A` and `CHATMODE-20261103-PARENTCHILD-A` | Scheduled parent runs executed and inspected the registry, but their runtime prohibited creating an additional scheduled task. No child existed. | **Blocked at permission level**; no backend creation attempt, cannot infer implementation incapability. |

All completed prior bounded tests were disabled afterward; no indefinite worker was created. Some scheduled starts occurred early/late; intended times alone do not establish actual execution. All reported status claims require task identity, exact `scheduled_for`, `last_run.id`, `recorded_status`, `completed_at`, and matching `latest_result.run_id`.

## Continuing bounded experiments on November 4

Some **initial** updates and runs are now verified; later occurrences remain **scheduled or pending**, not passed until their own completed records and readback are observed.

| Key | Hypothesis and bounds |
| --- | --- |
| `CHATMODE-20261104-RECUR-3X2H-A` | **Initial change and completion verified:** single scheduled execution changed its own schedule to `DTSTART:20261104T112000Z` and `RRULE:FREQ=HOURLY;INTERVAL=2;COUNT=3`, with readback; actual completed initial run scheduled for 09:20 UTC, completed 09:25:05. Future three occurrences intended for 11:20, 13:20, 15:20 UTC and read-only auditors remain under observation. Don't infer repeated cadence from accepted configuration. |
| `CHATMODE-20261104-REVIVED-EXPIRED-A` and `CHATMODE-20261104-REVIVED-SELFPAUSED-A` | The completed manager successfully set both test-owned tasks' new prompts/schedules/enabled state; **first** expired-task revival completed for scheduled-for 09:45 UTC. Its second occurrence is intended for 10:45 UTC. Self-paused task is intended to restart at 10:05 UTC, pending recorded execution. |
| `CHATMODE-20261104-REVIVE-AUDITOR-A` | Later read-only check of the manager and both revived tasks; separate config acceptance from post-revival execution and completion. |
| `CHATMODE-20261104-HA-WAVE-EVIDENCE-SYNC-A` | A separate, five-occurrence, two-hourly scheduled observer will read the bounded test records **and the real private BinaryWorkbench workforce's completed run/repository metadata**; it may update only public HA skill and case-study documentation on genuinely new, independently corroborated evidence. No mutation of worker schedules, private project source or branches. |

## Real-work BinaryWorkbench review

The owner is using an advance-provisioned **five-role** Chat Mode team for substantive private RE-Wizard BinaryWorkbench refinement, not merely for a simulated test. It is the **test case for both** (a) genuinely parallel useful worker activity and (b) output/check/integration **inheritance between work waves**. At initial inspection, all five tasks were enabled but had not recorded runs; actual overlap, committed work, accepted handoffs and reviewer independence were **unverified**. A bounded scheduled observer will examine only permitted private metadata, not expose private code, task IDs, private branch names, protected inputs or chat refs in the public HA repository. The [case study](REWIZARD_BINARYWORKBENCH_CASE_STUDY.md) tracks high-level findings; the exact private records remain in their own repository. The observer must not control or alter that team's workflows, code, branches or schedules.

## Repeated one-time reactivation — "necromancy" (pending)

**Known:** A scheduled manager already succeeded in re-enabling an
expired, *test-owned* one-time task, and its first independently
dispatched revived run completed. This does **not** establish that the
**same** one-time automation can be revived multiple times.

**New bounded test:** key `CHATMODE-20261104-NECROMANCER-A`,
pre-created hourly manager (four total coordinator opportunities),
will attempt to re-enable exactly one previously expired test-owned
one-time automation **twice**, each time only after the prior
single-event run is independently recorded `completed` and the task
is again disabled. **First scheduled manager execution completed** at
**10:24:45 UTC**. It verified the original test-owned single-use
run was completed and disabled, then accepted one update with the
same task ID, replacement `NECRO_ROUND=1` instructions,
`is_enabled=true`, and a new **one-time** schedule at **10:44:28 UTC**.
A separate registry read confirmed persistence. This verifies the
**first resurrection update**, not yet a completed first revived run,
and not yet repeated resurrections. The target is the originally completed bounded
parent-child test, not a RE-Wizard or owner-paused automation. Each
revival would change its saved `prompt` and future single
`DTSTART`, plus `is_enabled=true`, preserving its **same task ID**.
Proof requires two newly completed runs with distinct run IDs, each
delivered the expected `NECRO_ROUND` marker; no new child automation
or duplicate one-off should appear. This experiment is **scheduled,
not yet verified**, and does not relax the hourly or usage limits.

A direct attempt to create another test one-off failed with
`too_many_active_automations`, reporting a cap of **15 active
tasks** for the tested account at that time. Instead of changing
live production tasks, two redundant **test-owned read-only**
cadence auditors were disabled because the existing scheduled
evidence-sync already observes the underlying cadence task. Their
absence is deliberate, not a failed execution of the recurrence core.

## Live project cadence and milestone preference

Owner's instructions to the separate active private BinaryWorkbench
team: the originally staggered five-role workforce was expanded;
active production scheduled roles should be **hourly, as early as
the service permits**, with large work divided across workers in
parallel where useful. Results may feed inherited successor waves.
The main interactive chat is an **additional worker during live
turns**, and the owner wants concise milestone updates there to
review later. At a 10:20 UTC snapshot, eight project-related
scheduled roles were enabled with hourly saved recurrence, but
their actual execution/parallel work and milestone reporting had
not yet produced completed registry results. The bounded public
HA observer reads their *actual* later execution records and
private GitHub artifact metadata without altering the team's
schedules, files, or permissions. See the privacy-safe
[BinaryWorkbench case study](REWIZARD_BINARYWORKBENCH_CASE_STUDY.md).

## Orchestration design decision

The practical pattern is an **interleaved graph of work waves**, pursued in **parallel** when independent and **sequentially/inherited** when a previous artifact, test, fix or integration result is needed. It uses a pre-provisioned, owner-authorized pool of existing tasks, with a default proposal of five useful roles and upper target of ten when plan limits/actual work justify it. A conductor can adapt authorized tasks' prompts, schedule and enabled status. This does not permit it to create children from its own scheduled runtime, circumvent per-task hourly limits, manufacture independent chat contexts, override source mediation or restart user-paused work.

Permanent objective persists across ever-changing evidence-based milestones; check the project's final pinned acceptance rather than declaring success after a single chunk. Every scheduled prompt must carry short immutable safety/mission instructions. A GitHub `AGENTS.md` or `SKILL.md` edit is **not** automatically read by existing ChatGPT scheduled runs; retrieval or HA-specific injection must be verified. External project checkpoints must remain small and revision-bound.

See [CONDUCTOR.md](CONDUCTOR.md), [PROCESS.md](PROCESS.md), [CHATGPT.md](../../CHATGPT.md), and [SKILL.md](../../skills/chatmode-scheduled-orchestration/SKILL.md).

## Usage and documentation

Official task documentation states that **a completed scheduled Chat task may consume plan usage allowance even without a visible reply**. Conversations directly with a dot do not count against ordinary ChatGPT limits, but no source guarantees that delegated ordinary Chat tasks become free. Dot can create cloud threads and delegate Work/Codex tasks, not proven permission to turn all Chat Mode scheduled work into free dot conversation. References:
- https://help.openai.com/en/articles/10291617-scheduled-tasks-in-chatgpt
- https://learn.chatgpt.com/docs/automations
- https://learn.chatgpt.com/docs/dots
- https://learn.chatgpt.com/docs/dots/tasks-and-memory

Never treat a Codex-specific context metric as an available Chat Mode variable without identifying and testing its precise supported interface.
