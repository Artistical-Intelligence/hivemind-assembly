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
| `CHATMODE-20261104-REVIVE-MANAGER-A` | Manager completed 09:08:30 UTC and re-enabled two test-owned disabled automations. The exhausted target subsequently completed **both** post-revival bounded occurrences: scheduled 09:45 UTC (finished 09:42:06) and 10:45 UTC (finished 10:46:46). The formerly self-paused target also completed its restarted 10:05 UTC one-off (finished 10:08:25). Latest completed registry runs have matching result run IDs. | This verifies actual post-revival completion, not a **second re-enablement** of the same one-off, independent reviewer qualification, or permission to restart unrelated user-paused tasks. Task-authored text captured during in-progress execution can lag final registry status. |
| `CHATMODE-20261103-ONESHOT-PARENT-A` and `CHATMODE-20261103-PARENTCHILD-A` | Scheduled parent runs executed and inspected the registry, but their runtime prohibited creating an additional scheduled task. No child existed. | **Blocked at permission level**; no backend creation attempt, cannot infer implementation incapability. |

All completed prior bounded tests were disabled afterward; no indefinite worker was created. Some scheduled starts occurred early/late; intended times alone do not establish actual execution. All reported status claims require task identity, exact `scheduled_for`, `last_run.id`, `recorded_status`, `completed_at`, and matching `latest_result.run_id`.

## Continuing bounded experiments on November 4

Some **initial** updates and runs are now verified; later occurrences remain **scheduled or pending**, not passed until their own completed records and readback are observed.

| Key | Hypothesis and bounds |
| --- | --- |
| `CHATMODE-20261104-RECUR-3X2H-A` | **Initial change and one subsequent occurrence completed:** initial schedule edit and completed run at 09:20 UTC; a distinct first bounded two-hour follow-up was scheduled 11:20 UTC, started 11:20:03 and completed 11:20:44 UTC with a matching latest-result run ID. Saved recurrence remains `FREQ=HOURLY;INTERVAL=2;COUNT=3`. This confirms one follow-up dispatch; the 13:20 and 15:20 UTC occurrences, and hence multi-interval cadence, are still pending. The target-authored report captured `in_progress` before finalization, while the registry later confirmed completion. Two intentionally redundant auditors were paused; do not count them as failed checks. |
| `CHATMODE-20261104-REVIVED-EXPIRED-A` and `CHATMODE-20261104-REVIVED-SELFPAUSED-A` | **Completed:** both intended post-revival runs of the expired target and the single resumed self-paused target run now have completed receipts. The separate later audit remains pending. |
| `CHATMODE-20261104-REVIVE-AUDITOR-A` | **Completed 11:15:47 UTC:** the separate bounded auditor independently re-read the manager and target registry records, confirming post-revival completion and preserved task IDs. This is registry corroboration, not qualified independent code review. |
| `CHATMODE-20261104-HA-WAVE-EVIDENCE-SYNC-A` | A separate, five-occurrence, two-hourly scheduled observer will read the bounded test records **and the real private BinaryWorkbench workforce's completed run/repository metadata**; it may update only public HA skill and case-study documentation on genuinely new, independently corroborated evidence. No mutation of worker schedules, private project source or branches. |

## Real-work BinaryWorkbench review

The private RE-Wizard BinaryWorkbench project expanded from five provisioned roles to **eight hourly scheduled roles**, plus a separate interactive developer. It is the test case for both (a) real parallel development and (b) artifact inheritance into subsequent work waves. The observer has read completed Automations results and independently checked private GitHub commit and branch-comparison metadata; exact private task IDs, branch names, source files and chat references are not published here.

**November 4 first-wave finding:** Three substantive scheduled development tasks have distinct completed run IDs, different recorded ChatGPT chat references, and **actual overlapping start/end windows**. Their separate branches contain independently verified source and synthetic-test commits. A later integrator completed a separate run and consumed the five developer branches at exact revisions, saving **13 passing static source/interface checks** and a 23-path, zero-direct-collision comparison. The conductor completed a configuration wave and saved the eight-role hourly team state. A milestone-reporting task produced a completed owner-facing summary and persisted deduplication state; actual human notification delivery was not separately established. The fourth compiler branch contains previous work, but its specific **scheduled** worker had no completed run recorded yet. A reviewer run remained in progress. **Qualified independent review, real repository-level tests, executable integration, CI and approved PR/main merge remain unproven.** See the [privacy-limited case study](REWIZARD_BINARYWORKBENCH_CASE_STUDY.md).

**Second production observation, November 4, 12:56 UTC:** Four specialized development workers now have corroborated **simultaneously overlapping recorded execution windows** from 11:23:25–11:24:33 UTC and distinct completed task/run/chat references, confirmed in the private conductor checkpoint and persisted worker records. New scheduled worker commits appear as separate private GitHub branch advances (13, 29, 9 and 5 commits ahead of the unchanged main baseline, respectively); these are branch counts, **not** claims that every commit came from this wave. A completed provisional verifier run at 12:56:17 UTC read the new work, saved a synthetic regression and reported a further call-graph gap; its own verification branch is 9 commits ahead of main. A worker's prior defect fix was source-reviewed, but **qualification and execution of actual repository test suites remain pending**. The latest integrator run was still `in_progress`, so its latest intended consumption must not be declared completed; earlier static handoffs remain verified. All eight active private roles still have persisted hourly schedules, with a conductor-saved updated assignment/checkpoint and no authorized PR/merge. Distinct chat references strengthen separation evidence, not model/effort or independently qualified acceptance.

## Repeated one-time reactivation — "necromancy" (**two resurrections verified**)

**November 4, 2026 — PASS within this bounded ChatGPT Chat Mode experiment.** A previously completed, automatically disabled **one-time** task was twice re-enabled by an existing finite hourly coordinator via saved prompt, future single `DTSTART`, and `is_enabled=true`. Original, first revived and second revived executions all completed under **the same stable automation ID** with **three distinct recorded run IDs**. The first revived task ran with `NECRO_ROUND=1` and finished 10:48:45 UTC. The second round used `NECRO_ROUND=2`, retained a **no-RRULE** one-time VEVENT and finished **11:45:41 UTC**; its latest result has the exact recorded run ID and the saved marker. After both revived executions the registry showed the task disabled. The bounded coordinator's final completed result independently compared all three run IDs and then stopped; no new child automation was created.

**Limits and distinction:** This establishes two successful same-ID revivals for genuinely separate single-use assignments, not unlimited repeated invocation, arbitrary user-paused task revival, automatic task creation, a new ordinary user-role message, context independence or qualified review. The minimum hourly interval for recurring `RRULE` tasks does **not by itself establish** a mandatory 60-minute cooldown for every *new* single-event corrective assignment. However, this test did **not** deliberately verify a sub-hour single-event dispatch after a prior completed run; do not promise immediate scheduling until a bounded service experiment verifies it. The tested account also encountered an active-task cap, and usage/approval rules still apply. Target-authored text can still describe `in_progress` because final registry completion happens after text generation; rely on the later persisted completion and matching latest-result run ID.

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
review later. At the historical **10:20 UTC initial snapshot**, eight project-related
scheduled roles were enabled with hourly saved recurrence but had no
confirmed completed results. **Later completed records now verify**
overlapping development runs, GitHub artifact production and static
inheritance into the integrator's separate wave. The bounded public
HA observer reads their *actual* later execution records and
private GitHub artifact metadata without altering the team's
schedules, files, or permissions. See the privacy-safe
[BinaryWorkbench case study](REWIZARD_BINARYWORKBENCH_CASE_STUDY.md).

## HA-specific manager correction: maximum available work time

The owner corrected two overgeneralizations in the earlier HA shift-manager guidance. **First**, a new corrective brief can reuse an expired one-time automation as a logically distinct task; its earliest supported next event must be checked on the actual scheduler rather than inferred from the hourly **recurring** RRULE minimum. The November 4 two-revival PASS proves slot reuse but not arbitrary sub-hour dispatch. **Second**, the manager's own hourly check-in should be positioned to **maximize its useful working window after relevant results are ready and before the next major worker cohort**, rather than minimizing a downstream worker's wait for the manager. Independent work proceeds without managerial gating. The explicit phase-search objective and testable pure helper are in [SHIFT_MANAGER.md](SHIFT_MANAGER.md) and `_app/hivemind_assembly/automation/shift_window.py` (source tests pending CI/independent review); no live private RE-Wizard task or schedule was changed by this HA correction.

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
