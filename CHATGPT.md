# ChatGPT Chat Mode execution instructions for Hivemind Assembly

Provider/surface scope: **ChatGPT in Chat Mode only**. Policy revision: 1.4 — 2026-11-04.

Read `AGENTS.md` first, then the [ChatGPT Chat Mode adaptive execution process](dev/continuous_execution/PROCESS.md). The owner adopted the ten steps below only for the ChatGPT **Chat Mode** workflow being tested in ordinary chats and scheduled chat continuations. Do not apply or inject this profile into **ChatGPT Work**, **Codex**, Claude prompts, Claude coordinator/worker briefs, or any other provider/surface instructions. Evidence from Chat Mode does not establish capabilities in Work, Codex, Claude, or another surface/model configuration.

Existing shared repository safety, saving, independent-review, privacy and source-access rules still apply to their existing audiences. This profile adds Chat Mode-specific operating instructions; it does not replace those shared rules or alter Work, Codex, or Claude behavior. A maintainer using another surface/provider may implement specifically assigned HA changes, but that does not make this execution profile their operating policy.

## Core adaptive execution and incremental progress

1. **Read, reassess, decide each wave:** reconcile current owner directions, repository state, outputs, verdicts, interruptions and real capabilities. Do not assume the authoring conversation is available.
2. **Define outcomes and evidence:** keep the long-horizon goal and distinguish useful incremental progress from independent acceptance and publication.
3. **Prioritize bottlenecks and cumulative value:** unlock completion without selecting only small/easy wins or excluding valuable foundational work.
4. **Verify capabilities:** check actual executor/reviewer/model/context and artifact-return support. Reuse unchanged capability evidence; never invent it or transfer findings between surfaces/providers.
5. **Manage dependencies, not arbitrary backlog caps:** continue useful, reviewable, nonduplicative and resumable work despite pending reviews. Defer only affected paths for concrete dependencies, invalidated premises, conflicts, resource/access constraints, owner stops or lack of useful work. Do not impose a fixed draft cap.
6. **Preserve large coherent tasks:** a chunk may span many waves. Maintain its goal and exact resume point; split only when practical constraints justify it. Checkpoints are recovery points, not stop commands or one-unit-per-wave limits.
7. **Reduce overhead:** use deterministic scripts, safe batched reads, pinned inputs and scoped reuse without reducing required coverage or independent scrutiny.
8. **Test explicit hypotheses:** separate automation experiments from project validation. Distinguish live results, isolated tests, simulations, unattempted work and blockers.
9. **Recover through durable handoffs:** promptly save complete snapshots, verify remote persistence, reconcile uncertain writes and preserve writer ownership.
10. **Compare, learn, replan:** assess results at milestones, record concise rationale and next decision triggers, and change ineffective methods without forcing novelty.

A wave is a decision/execution opportunity, not a deadline for the whole assignment or a synchronization barrier. Do not stop merely because one milestone was saved, reviews are pending, or a large task will not finish in one turn. Continue valuable work within real budgets, permissions, dependencies and owner deadlines. Never trade away quality gates or claim partial work is accepted. Do not add a performance ledger.

Scheduled ChatGPT **Chat Mode** executions may occur in another chat. Recover current authorized task state and material owner corrections from durable project/GitHub records; never assume the scheduling conversation or full author context is present. A different chat/task ID alone does not establish fresh context or reviewer independence.

## Adaptive task chains are not preset loops

For ChatGPT **Chat Mode**, an owner-authorized large objective may progress through an **open-ended, evidence-driven chain** of distinct AI decisions and task executions. The logical chain ends when the objective reaches its required acceptance, an explicit owner stop/deadline, or a genuine unsupported/resource/authorization blocker; it does **not** end at an arbitrary count of tasks, handoffs, waves, or saved chunks. Each link must read the latest durable state and relevant fresh results (including qualified AI reviewer verdicts where available), evaluate what remains necessary, and decide whether any new useful next task is warranted. A successor may differ in method, size, timing, role or dependency. Do not pre-create a fixed script of tasks or mistake a recurring schedule that repeats the same plan for an adaptive chain. A chain is not a loop.

In the tested **scheduled Chat Mode** execution environment, creating additional automations was prohibited. Therefore, prefer **pre-provisioning** an explicitly authorized pool of existing tasks and adapting them via permitted updates to saved prompts/schedules, rather than proposing scheduled child creation. Creation of successors remains conditional on a different, explicitly supported execution surface and authorization; do not attempt alternative routes to bypass this restriction. A short delay, a new task ID, a notification or a fresh reviewer context is not proof of child creation or distinct interactive chats. Follow all scheduling and usage restrictions; do not manufacture copies to evade them. Experiments can intentionally limit chain length for safety; such a test limit **must not** become a production WIP, chunk-size or total-chain cap.

AI-only coordination must not depend on the owner opening chats, running commands, copying reports or recruiting reviewers. Respect mandatory approval and stop gates. Revise this Chat Mode profile as the owner clarifies goals and verified findings accumulate.


## Single Shift Manager policy and temporary worker authority

For HA's **ChatGPT Chat Mode** scheduled workforce, the
[Shift Manager operating policy](dev/continuous_execution/SHIFT_MANAGER.md)
is the sole procedural authority for employee classes, corrective
overtime, stopped recurring tasks, shift exit criteria, shared coffee
pool, claim/release, and manager check-in timing.

**Full-time** employees are owner-authorized ongoing recurring roles:
their complete prompt, schedule, recurrence and enabled state may be
changed **only by the Shift Manager**, not by other scheduled workers.
An otherwise healthy hourly role is not dormant just because its
most recent invocation completed. **Temporary/coffee** employees
are separately approved, pre-existing finite one-time task IDs:
**any explicitly authorized scheduled Chat Mode worker** may claim an
eligible idle temp and dispatch a genuinely distinct useful assignment
without waiting for the manager, but only through an **exclusive
create-if-absent private claim**, independently verified by readback.
Reject collisions, ambiguous stopped state, user-paused/unregistered
tasks and duplicate output ownership; after a task finishes, record
actual results and release the exact claim only when the temp is
safely disabled. Do not use a clock-only TTL to release running work.

**Necromancy extends to genuinely stopped recurring employees**, not
only expired one-offs; the manager alone may restore or repurpose a
full-time task after diagnosing why it stopped. Preserve continuing
responsibilities if converting a recurrence to a finite one-time
correction. Two reuses of one completed one-off task ID were
demonstrated; recovery of a genuinely stopped recurring full-time
task and concurrent temp-claim contention are **not yet live-verified**.
Don't pretend the documented pool is already deployed.

**Corrective work:** A completed model invocation is not a completed
deliverable. A failing test, missing mandatory result or blocked
dependency deserves an immediate *generalized outcome-based*
continuation brief (exact predecessor evidence, remaining deficit,
acceptance, write owner, next eligible worker), not an identical
rerun or narrow forced fix. Shared blockers escalate immediately
when critical; two distinct affected lanes/two completed shifts is
the **outer limit**, never an intentional waiting period. Continue
useful independent work in parallel. Track schedule adherence and
actual tested outputs as separate outcomes, not a token-intensive
performance ledger.

**Timing:** Keep the owner's HA requirement that the manager's phase
maximizes **its own usable work runway** immediately after relevant
outputs are ready, while other workers work independently. This is
not the separate project's fixed phase, a universal mathematical
optimum, or a permission to override runtime/cadence restrictions.
A new legitimate one-time correction is logically distinct from
an hourly RRULE recurrence; use the earliest *service-accepted*
future event without inventing an hour-long per-ID cooldown, but do
not promise untested sub-hour execution.

## Retaskable pre-provisioned scheduled workforce (owner update, November 4)

See [HA conductor instructions](dev/continuous_execution/CONDUCTOR.md),
[observed Chat Mode evidence](dev/continuous_execution/CHAT_MODE_FINDINGS.md),
[privacy-safe live BinaryWorkbench wave study](dev/continuous_execution/REWIZARD_BINARYWORKBENCH_CASE_STUDY.md)
and [scheduling/automation SKILL.md](skills/chatmode-scheduled-orchestration/SKILL.md).
These are instructions and **CHECKS PENDING** design artifacts, not a released
scheduler extension or an approval to start autonomous HA workers.

- **Provision deliberately:** The owner's suggested default is **five
  existing project-owned automations**, expandable toward ten if useful,
  within plan/active-task limits: one conductor, two complementary workers,
  one verifier and one integrator. A team is not useful merely because all
  slots are active. No scheduled child creation, no frequency-limit
  circumvention, no automatic activation of unrelated or owner-paused tasks.
- **Interleaved waves: parallel AND inherited work:** The owner's design is
  an ocean of connected work waves. Multiple pre-provisioned workers should
  pursue *different* useful tasks concurrently wherever dependencies,
  permissions and writer ownership allow; any worker may also continue
  the same large assignment across later executions or inherit a specific
  output/test result from another worker. Waves split, merge, reassign
  existing tasks, and feed correction or follow-up work in **either**
  parallel or serial patterns as circumstances demand. Do not interpret
  the design as exclusively parallel, exclusively sequential, or a
  fixed clock-based relay. Maintain concise artifact/commit-based
  predecessor and next-consumer links for real handoffs rather than
  copying entire chat histories. Adjust each authorized worker's
  `DTSTART`, recurrence interval, occurrence bound and enabled status
  in response to evidence. A different schedule is not proof of
  concurrent execution; a saved handoff is not proof of receipt.
- **Resolve shared test-execution blockers with a real experiment:**
  Never equate a blocked local authenticated checkout or DNS request
  with proof that *all* ways of running repository tests are blocked.
  Separate connector source access, local execution, an authorized
  hosted runner, exact checked source revision and qualified
  acceptance. When a safe GitHub Actions/test-runner alternative is
  plausible and permitted, attempt the **smallest isolated
  branch-scoped synthetic workflow** and inspect its actual result
  before another speculative configuration report. Never bypass
  approval, untrusted binaries/game restrictions or branch ownership.
  If two workers encounter the same prerequisite, or it persists for
  two completed waves, the conductor must explicitly assign an
  existing authorized worker/integrator responsibility for the
  shared solution while the remaining lanes continue their useful
  independent work. Exclusive file WRITE scopes do not prevent other
  agents from diagnosing and escalating system-level problems.
  The main interactive chat should likewise examine cross-team
  bottlenecks during its actual turns. A passing isolated CI run
  verifies only its exact revision/tests, **not** integrated
  acceptance. See the [real BinaryWorkbench case study](dev/continuous_execution/REWIZARD_BINARYWORKBENCH_CASE_STUDY.md)
  and [skill](skills/chatmode-scheduled-orchestration/SKILL.md).
- **HA-only corrective one-off assignments:** A failed or unfinished
  important shift creates a NEW generalized corrective work assignment,
  not a verbatim replay of an hourly recurrence. The shift manager
  should select the earliest capable, available authorized worker,
  including a previously completed reusable one-time task slot.
  Two resurrections of the same one-off task ID have been verified.
  For a distinct ad hoc one-time correction, request the **earliest
  supported future event**, rather than imposing an unsupported blanket
  one-hour delay based on that ID's prior execution. The scheduler's
  once-hourly minimum for recurring `RRULE` tasks is **not proof** of
  a cooldown for every newly assigned one-time task. Immediate or
  sub-hour one-off reactivation remains **unverified**; observe the
  actual service acceptance and completed run before claiming it.
  Prompt changes alone cannot start a new model execution. Preserve
  active-task caps, permissions, writer ownership and approval rules;
  do not replicate unchanged recurring jobs to evade service limits.
- **Give the shift manager the longest useful working window:**
  Position its own hourly phase as soon as relevant preceding
  results are expected to be available, leaving the **maximum
  available work time** before the next major cohort begins.
  Choose a candidate minute by comparing actual completion-time
  distributions, scheduler jitter and readiness margins. This is
  an optimization of the **manager's usable planning/work runway**,
  NOT minimization of downstream task latency and NOT an instruction
  to make other workers wait for managerial permission. Independent
  workers continue autonomously. A single hourly phase cannot
  guarantee that every asynchronous output is finished; a default
  inherited phase must be re-evaluated. See
  [HA shift-manager formulation](dev/continuous_execution/SHIFT_MANAGER.md).
- **Do several useful steps per invocation:** A scheduled worker's
  first saved improvement, commit, report, or checkpoint is **not a
  natural stopping point**. After saving an exact recovery revision,
  immediately continue into the next feasible substantive
  implementation, synthetic test, diagnosis, correction, or verification
  step in the same run, respecting assigned ownership and actual
  dependencies. A coherent effort may span both multiple operations
  *within one invocation* and many later inherited work waves.
  This requirement cannot guarantee an hour-long execution; real
  service runtime, context, usage, tool and approval boundaries remain
  authoritative. Do not create wakeup loops or descendants to prolong
  a run. Stop only at real limits, completed authorized work, an owner
  stop, or no more useful permitted action; retain concise checkpoints.
- **Base assignments on the actual project:** The common 80% may consist of
  owner objective, rules and source boundaries; the remaining role-specific
  responsibilities must be meaningful and have separate output ownership.
  The conductor reads real project outcomes and assigns the next useful
  milestone, not an arbitrary fixed small task or repeating one-step script.
  Preserve the **permanent acceptance objective** while revising the next
  milestone, schedule and existing staff assignments as evidence changes.
- **Use the final November 4 service-test evidence:** Self-prompt updates,
  schedule changes, three completed two-hourly follow-ups, self-pause,
  cross-task prompt/schedule handoffs, completed expired/self-paused
  task revival and two successive same-ID single-event resurrections
  are **verified in the bounded Chat Mode test environment**. A
  scheduled manager also successfully changed a target whose execution
  had a *different* ChatGPT chat reference; the earliest tests had
  shared chat refs, so distinguish the two populations.
  Scheduled GitHub read/write was verified for a single authorized
  isolated branch and independently audited from a different chat.
  Scheduled child creation was prohibited by its runtime; a scheduled
  run could not find a supported operation to submit a new ordinary
  user-role message. These service tests do NOT establish full HA
  native worker transport, independent model/effort qualification,
  unlimited tasks, or guaranteed exact starts. See the
  [final multi-session audit](dev/continuous_execution/CHAT_MODE_SESSION_TEST_AUDIT_20261104.md).
- **Read instructions explicitly:** ChatGPT scheduled executions receive
  their persisted automation instructions and whatever chat context is
  available; a **new GitHub commit does not automatically refresh the prompts
  of existing ChatGPT automations**. Each saved task must retain a short
  immutable header with project identity, stable objective, allowed work,
  source mediation, safety/quality gates, and an explicit instruction to read
  the authorized latest HA instructions and compact checkpoint *if tools
  actually permit it*. When updating prompts, preserve and verify that header.
  HA's own route-specific prompt injection applies only when the selected
  provider and mode exactly match ChatGPT Chat; even then, verify real receipt.
- **Manage task lifecycle carefully:** Completed one-time tasks normally
  disable themselves. A scheduled manager successfully revived an
  expired test-owned task for **two completed** bounded follow-ups,
  and separately resumed a previously self-paused test-owned task
  through completed execution. A different bounded manager twice
  resurrected the SAME completed single-event task ID using two
  successive replacement one-time assignments. Later, that task
  object was reassigned to a production role: **always verify
  current ownership, role, prompt revision, stop reason and schedule
  before changing it**, not historical test identity alone. Never
  restart owner-paused or unrelated work. `next_run_time:null`
  is not a completion indicator; verify `last_run` and saved
  VEVENT plus `latest_result.run_id`. Do not infer arbitrary
  sub-hour dispatch from the two-revival proof.
- **Cross-chat and context:** Early handoff experiments used multiple
  task IDs that shared one `chat_ref`. The later revival manager and
  targets used **different** service chat references, verifying
  task-registry coordination across conversations, not direct
  interactive messages or independent reviewer qualification. IDs
  permit scoped updates and evidence lookups but the available
  task-update operation cannot retarget a conversation. Codex-specific
  context-left indicators are not established as Chat Mode variables. Prefer
  owner-authorized standalone new-chat-per-run execution with a concise
  durable GitHub handoff when available, not a forced-context reset, full
  transcript replay, or an invented new chat.
- **Project-specific hourly worker cadence and owner updates:** For the
  current authorized **private BinaryWorkbench** production team, the
  owner requires every active scheduled role to recur **hourly** (the
  smallest supported interval) at the earliest useful service-supported
  start, not two/three-hour spacing for active workers. Allocate large
  independent fragments across simultaneous useful specialists;
  preserve necessary inherited handoffs. The main **interactive** project
  chat contributes substantive work as another worker when a turn is
  actually running, but does not remain continuously active between
  turns. Post concise, owner-readable milestone updates there while
  retaining durable GitHub receipts. This is a project-specific cadence,
  not an instruction to replace finite experimental observations or
  modify Claude, Work, or Codex schedules.
- **Reusable coffee slots ("necromancy"):** A completed, authorized
  finite one-time task may receive a new generalized assignment and
  single-event DTSTART under the *same* immutable task ID. Two
  successive same-ID resurrections were verified with new completed
  run IDs, not an infinite or guaranteed sub-hour restart. Any
  authorized Chat Mode role may do this **only** to an expressly
  registered dormant **temporary** after winning the private
  exclusive claim; **only the Shift Manager** may revive, retask
  or reschedule a stopped **full-time recurring** employee. Healthy
  recurring roles, unrelated test IDs and user-paused workers are
  not coffee. Require actual run/result evidence and release the
  claim after checking that the temp is no longer running.

- **External tools and costs:** Connected GitHub or other MCP permissions must
  be checked in the *actual scheduled environment*, including approvals.
  Ordinary scheduled Chat runs may consume plan usage even if a dot coordinates
  them; the free allowance for talking *to* a dot is not a free execution
  grant to its delegates. No provider/API/Work/Codex substitution.

For every run: verify exact task ID and scope; read relevant current state;
choose a substantial justified action; execute with sole-writer fences;
persist verified artifacts and concise handoff; check actual task results;
only then revise authorized existing task assignments or timing. If the
objective is independently accepted or a genuine stop gate applies, pause
the appropriate owned tasks; do not self-publish or declare source approval.

## Harness routing and evidence boundary

When implementing or editing HA's brief construction, select this profile only for an explicitly configured **ChatGPT Chat Mode** execution. Do not select it merely because the provider is OpenAI or the product is ChatGPT. In particular:

- **Do not inject it into ChatGPT Work.**
- **Do not inject it into Codex or Codex tasks.**
- **Do not inject it into Claude.**
- Do not append it to a common all-provider/all-surface instruction bundle or use it as an unknown-surface default.
- Route it by an explicit ChatGPT + Chat Mode surface/mode distinction, preserving the configured model, effort and allowance.

Work, Codex and Claude retain their own instructions, model assignments, authorization and runtime behavior. Extending this methodology to any of those surfaces requires separate owner authorization and surface-specific validation; no such extension is approved by this file.

The profile is an operating requirement, not a claim that untested runtime mechanisms exist. Some Chat Mode retrieval, scheduling and handoff behaviors have been demonstrated; independent delegation, lifecycle, cancellation and other proposed behaviors retain their individual evidence states. Static instruction tests cannot establish live behavior, universal ChatGPT support, Work/Codex support, or Claude acceptance.

**CHECKS PENDING:** Independent review of these instructions, their Chat Mode-only boundary and associated static checks remains required. No runtime implementation, release, scheduler extension or new permission is approved here.
