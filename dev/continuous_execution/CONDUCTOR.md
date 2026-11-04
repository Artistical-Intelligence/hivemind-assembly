# Chat Mode conductor and pre-provisioned workforce — HA policy

**CHECKS PENDING:** Owner-directed design; not yet separately reviewed, implemented as a new HA scheduler, or accepted as a live multi-chat runtime. This file applies only to **ChatGPT Chat Mode**, not Work, Codex, Claude or an unknown provider/surface. Read root `AGENTS.md`, `CHATGPT.md`, [PROCESS.md](PROCESS.md) and [the scheduling skill](../../skills/chatmode-scheduled-orchestration/SKILL.md).

**Purpose:** Advance an owner-authorized **terminal acceptance objective** across many independently bounded scheduled Chat Mode executions. The team may be recruited in advance and retrained by changing existing, authorized automations. A schedule is a wakeup, not a continuous agent or an independent reviewer guarantee.

## Primary design: interleaved waves of parallel work AND inherited continuation

**Owner clarification (November 4, 2026): both are essential.** The
orchestration model is an **ocean of work waves**: several useful workers act
in parallel; their outputs, discoveries, checks and constraints flow into
later waves, sometimes within the same worker and sometimes by transfer to
another worker. A branch can split into independent workstreams; multiple
branches can merge for integration; a failed test can send a corrective wave
back to implementation while unrelated work continues. **Do not force either
an all-parallel team with no handoffs or an entirely linear relay.**

The conductor maintains a dependency-aware **wave graph** over a permanent
project objective. Nodes are substantive execution/milestone efforts; edges
record *why* a later wave consumes an earlier artifact, a test verdict, a
decision or an exclusive output lock. Valid edges include chronological
continuation, dependency, review/repair, inheritance/handoff and integration.
Different nodes may run at the same time when safe. A worker can also keep
one large coherent effort across many scheduled invocations.

Illustrative, **not a rigid schedule or mandatory set of roles**:

```text
                       objective + acceptance criteria
                        /                       \
   Worker A: investigate -> build             Worker B: research -> validate
               |              \               /
               |               joint integration/test
               |                    |
               |         pass -> next milestone / finish
               |         fail -> targeted repair to A or B
               +----------> independent parallel follow-on work
              (reassign existing task IDs; retain artifact lineage)
```

**Inheritance does not require child task creation.** Scheduled Chat Mode
could not create descendant automations in the tested execution context,
but it **can change existing tasks' complete prompts and schedules**.
The conductor can transfer an evidence-backed follow-up to an already
provisioned worker, or the same worker can continue an inherited assignment.
The receiving wave reads the latest project checkpoint plus the exact
prior output revision, rather than assuming the author chat is in context.
The handoff is a logical link between work/results, not a claim that a
new task or chat was physically spawned. A new authorization or other
supported interface would be needed to expand beyond the existing pool.

**Adaptive timing is per existing automation.** After checking actual
completion, dependency readiness, plan limits and ownership, the conductor
can, where authorized and supported, revise the worker's saved assignment,
`DTSTART`, `RRULE:FREQ`/`INTERVAL`/`COUNT`/`UNTIL`, and enabled
state. The timing should vary with what the work requires: independent
workstreams may proceed at the same time; dependent tests run after a
suitable prerequisite; long jobs can receive follow-up checks; idle
assignments can pause or slow down. A fixed :00/:15/:30/:45 pattern is
only an example, not a requirement or a mechanism to evade per-task
hourly recurrence limits.

**Preserve autonomy without losing coordination.** The conductor is not
a mandatory gate at every step. An authorized worker can continue a
coherent assignment and checkpoint its results while the conductor
periodically reconciles independent and inherited waves. Multiple workers
must not overwrite the same project file: use explicit output ownership,
leases/revision fences, branches or one integrator. Review and testing
can overlap unrelated implementation; qualified independent acceptance
is still mandatory for the affected deliverable. The conductor chooses
dependencies based on facts, not on titles such as "worker" or "reviewer."

**Verify actual overlap and transfer separately.** Staggered requested
times do not prove concurrent model execution; actual overlapping
`started_at`–`completed_at` windows plus distinct run identities and
nonconflicting work establish measured parallelism for those runs.
A completed donor result, exact committed artifact/hash and the receiving
worker's recorded use of it establish inheritance. A distinct task ID
alone proves neither fresh conversation isolation nor qualified review;
previous tests found several executions sharing one chat reference.

Keep a concise per-wave lineage in the **existing** project handoff and
evidence records, not a new verbose performance ledger: `wave_key`,
assigned task ID, input artifact/commit and dependencies, output artifacts
and verdicts, next consumers, last verified state. Do not retain every
token, routine poll, complete chat transcript or copied textbook.

## Current real-work cadence, interactive worker and one-off reuse

The owner's **specific RE-Wizard BinaryWorkbench workforce update** is to
schedule each active production role at the **earliest permissible useful
initial execution** and recur **hourly** (the smallest supported recurring
interval), rather than intentionally slowing some to two or three hours.
Do not delay independent specialists to create an artificial stagger;
tasks that safely split a large milestone may share requested start times.
This is a deliberate workload-specific cadence, **not** a global
restriction on all bounded HA diagnostic tests or other owner-authorized
projects. The conductor still manages mutable assignment, DTSTART,
enabled state, and dependency-aware timing; adjust any recurrence
interval away from hourly only when the **owner's current project
instructions permit it**. Actual execution concurrency requires
recorded overlapping runs, not just saved clocks.

The main interactive project conversation is **another worker** when it
has a live model turn: it should make substantial contributions in
parallel with scheduled work, own its file/branch/lease scope, and
checkpoint results. An interactive chat is not an always-on agent between
turns. The owner requires clear **milestone updates in the chat** to
read later; use compact owner-facing reports on material commits,
tests, integrations and blockers, not repetitive untouched-status
commentary or a substitute for working. A dedicated reporter can
summarize verified milestones while workers remain focused.

**Necromancy / reusable one-time slots.** A previously completed and
auto-disabled one-time task can be **re-enabled** with new prompt and
new single-future-event DTSTART via the supported update interface,
preserving the same task ID. An earlier scheduled manager successfully
revived one exhausted test-owned one-off, and its first new run
completed. This does not yet prove a second or third resurrection of
that **same one-off**. A new bounded hourly coordinator test is
scheduled to attempt **two consecutive revivals of the same previously
expired, test-owned target ID** (one-off VEVENT each time, no RRULE,
distinct completed runs, same immutable automation ID). One coordinator
can therefore potentially reuse a bounded pre-provisioned staff slot
instead of asking the scheduled runtime to create child automations;
verify each step from the actual registry and **do not** treat
configuration acceptance alone as successful dispatch. Never revive
an unrelated task, deliberately user-paused task or running task.
Neither resuscitation nor a short DTSTART authorizes evasion of
hourly recurrence, active-task limits, usage accounting or approvals.

The scheduler refused a new trial one-off creation with
`too_many_active_automations` and a 15-active-task cap in the tested
account at that time. Two **redundant test-owned read-only** cadence
observers were paused because the already scheduled evidence-sync
covers their checks, leaving production RE-Wizard roles and previously
user-paused tasks untouched. This is a specific measured quota
observation, not a universal plan limit. Prefer reassigning useful
existing roles and ceasing redundant observers over filling the
registry with unnecessary scheduled tasks.

## Findings to use; limits to retain

Verified on one ChatGPT Chat Mode configuration during November 3–4, 2026:
- A scheduled run changed its own saved instructions, schedule, recurrence interval and enabled state; follow-up runs received persisted instructions. One revised two-hour recurrence ran **once**; multiple consecutive two-hour intervals are still being tested.
- A scheduled run changed an **existing** separate automation's saved prompt and schedule. Separate target runs executed the updates, and read-only scheduled observers retrieved completed results through the Automations registry.
- A one-time scheduled parent was **prohibited by its execution environment** from creating another automation. No backend creation attempt occurred; this is not evidence about technical scheduler capacity. Do not try child-creation workarounds or claim unlimited task spawning.
- The tested separate task run IDs shared the **same chat reference**. Distinct task IDs, prompts and run IDs do not prove separate chat contexts, qualified independent review or a detached live process.
- **Reactivation and GitHub evidence improved:** A scheduled manager successfully updated and re-enabled two *test-owned* completed/paused automations; the previously exhausted one-time task's **first new run completed**. Subsequent intended runs remain to be checked individually. A scheduled Chat Mode agent successfully created/read back one harmless file on a separately pre-provisioned test branch; a different scheduled observer independently verified the exact commit/blob. This does **not** authorize unrelated production writes or other MCP providers. The bounded scheduled-to-ordinary-interactive-message probe **completed BLOCKED**: no supported same-chat user-role message injection tool was available.
- Scheduled starts were minutes early or late. Treat `next_run_time=null`, `in_progress`, `is_enabled` and a saved `RRULE` as different evidence. Each run must be verified by its recorded run ID and result.

## Owner-approved bootstrap strategy

The owner proposes a **default nominal pool of five** existing, pre-provisioned tasks, adaptable up to **ten** if there is meaningful work, available plan capacity and explicit setup authorization. The number is a capacity target, **not** a requirement to create ten recurring executions or keep idle agents consuming allowance. The conductor first inventories registered authorized tasks; it never repurposes unrelated/user-paused tasks or opens new automated descendants.

Suggested initial roles:
1. **Conductor:** Select milestones, verify state, manage the allowlisted tasks and their schedules/assignments, reconcile errors and avoid duplicate writers.
2. **Worker A:** Main technical implementation, evidence acquisition or specialist action on its exclusive outputs.
3. **Worker B:** Complementary independent *workstream* on distinct outputs; not an independently qualified reviewer solely because it has another task ID.
4. **Verifier:** Targeted tests, counterexamples, reproducible evidence and integration feedback. Independence/qualification is checked separately before any acceptance.
5. **Integrator:** Integrate approved results behind sole-writer/revision fences, rerun whole-project checks and prepare release/acceptance evidence.

Roles six–ten are optional for specialized nonconflicting work only. Every task shares the same **permanent project objective and safeguards**, but has a specific current responsibility, resource allowance and output owner. An overlapping common policy is expected, not license to create copies solely to achieve sub-hour recurrence. Different roles may use staggered hourly schedules, e.g. :00/:15/:30/:45, but actual starts are not precise and overlap must be handled by leases.

**Provisioning:** An interactive, explicitly owner-authorized bootstrap may create the initial pool when its tools permit it. Scheduled Chat Mode runs **may update but must not create new automations** under the tested restriction. A future fresh conversation must use supported task-creation/rebinding mechanisms where available; the tested update tool does **not** take a destination `conversation_id`. Do not claim to have instantiated five independent conversations without examining their distinct real chat refs, tool exchange and artifact return.

## What an executing scheduled task actually reads

There is no guarantee that all repository instructions are reread on each ChatGPT scheduled turn. The task receives the **saved automation prompt** and available conversation context. Files such as `AGENTS.md` and `SKILL.md` matter only when explicitly retrieved by a tool or included by a **verified HA-native prompt-routing implementation**. In HA's own route, `chat_mode_profile.py` injects a compact policy **only when** the configured provider and mode match `openai` + `Chat`; config matching is not proof that a real browser model read it. Do not silently inject this policy into other surfaces.

Each pre-provisioned task therefore gets a durable saved prompt divided into:

```text
IMMUTABLE HEADER (must survive every update):
Project key; Chat Mode only; owner and exact automation ID;
permanent objective + objective completion/acceptance conditions;
allowed repositories, refs, operations, model/mode and allowance;
prohibited sources, secrets, spending, schedules and task creation;
handoff path and writer ownership; exact review/approval boundaries;
re-read authorized docs/checkpoints through supported tools each run.

MUTABLE MILESTONE (conductor/worker may revise if authorized):
Role; current work package; input commit/revisions; output paths;
concrete test hypothesis and evidence standard; expected next checkpoint;
when to stop, pause, escalate or change assignment.
```

Before any prompt update, compare the *full replacement* to required immutable header fields. Then perform **one scoped update** with exact automation ID and reread persisted state. A task's own subsequent run must verify the header survived. A source update on GitHub does **not** instantly replace existing scheduled prompts.

## One bounded run

1. Confirm correct provider/surface, current task key + ID, actual tools/permissions, enabled status and real run metadata. Reject ambiguity and stale/non-owned automation targets.
2. Load only the project's **current minimal checkpoint**, task mapping and decision-relevant changed evidence. Require original-source access where necessary; never bypass RE-Wizard mediated-textbook rules.
3. Compare current objective acceptance against completed checks. Pick the next substantive bottleneck or continue a coherent unfinished assignment; do not choose trivial milestones merely for task churn.
4. Identify exclusive output writer, revision expectations and dependencies. If another worker is editing the same output, use deterministic coordination, not hopeful timing.
5. Perform authorized operations and targeted tests. A source read, an accepted schedule update, a completed model run and independent acceptance are different states.
6. Save full necessary artifact bytes and brief evidence; verify persisted bytes/hash/commit. Reconcile uncertain writes, do not replay blindly.
7. Update the one compact checkpoint and concise next-run handoff **only if there is material change**. Avoid redundant full histories, textbook copies, performance ledgers and unchanged polling prose.
8. Conductor may retask/reschedule/re-enable **only allowlisted existing tasks**, preserving headers and owner decisions. For a paused task, first distinguish deliberate owner pause, test self-pause, exhausted `COUNT`, approval blocked, model usage blocked and completion; never resume owner-paused work by default. To move `next_run_time`, update `schedule`/`DTSTART`; that output field cannot be set directly.
9. Stop or pause only after measured acceptance, explicit owner stop, real authorization/resource limitation or no useful permitted work. Open-ended objective does not override actual model/session limits or approval requirements.

## Persistence and minimal handoff

Per-project external state convention:

```text
projects/<slug>/README.md
projects/<slug>/state/current.json
projects/<slug>/state/handoff.md
projects/<slug>/state/automations.json
projects/<slug>/decisions.md
projects/<slug>/evidence/<test-or-milestone>.md
```

`current.json`: stable objective and acceptance criteria, phase and last verified commit, active work package, artifact pointers, blocker, next useful actions. `handoff.md`: **only** the current resume point, changed artifact hashes, verified checks/limits, and decisions the next run must know. `automations.json`: exact IDs only for authorized tasks, role/scope, current status, allowed mutations, and whether a chat reference is actually addressable. Do **not** publish account-specific private conversation IDs in a public repository merely for recordkeeping; store opaque ids privately if the coordinator requires them. `decisions.md`: durable, consequential choices, not all conversation history. Archive historic reports instead of auto-injecting them. A README links to the relevant RE-Wizard repository only for orientation, **not direct textbook access**.

Use GitHub's commit/blob SHA, expected-revision updates and single-writer ownership. Do not overwrite a state snapshot just because the read response was stale. Unverified work and source edits retain `CHECKS PENDING` markers and may not be released; a checker must be a qualified independent session.

## Context lifecycle

Codex may expose a remaining-context signal in its own tooling, but **no equivalent value is available in the examined Chat Mode scheduled-automation API**. Do not reuse an imagined Codex variable or claim a context percentage. Detect practical rollover need through information loss, context truncation, repeated fact correction or major checkpoint transitions. Persist a short handoff first.

The documented **standalone scheduled task** pattern starts a fresh chat per run and may consume only the external minimal checkpoint. It must be validated for the chosen execution surface. A chat-attached task reuses conversation context. We have **not** established a scheduled run can create a normal new interactive chat or migrate an existing task to an arbitrary conversation. The attempted native same-chat user-role message trigger was specifically **blocked by unavailable tooling**. If rollover cannot be performed unattended, say so and preserve usable checkpoint data rather than claiming it happened.

## Usage, dot and external tools

Ordinary scheduled Chat model processing may count against plan allowances even if it posts nothing. The documented lack of ordinary ChatGPT usage charges for **conversing directly with a dot** does not prove that normal scheduled Chat tasks orchestrated by dot are free. If considering dot, compare actual UI-supported task types, returned surfaces and allowances in a separately bounded test; no API fallback or silent Work/Codex substitution.

A Nov 4 scheduled GitHub write completed on a **separate experimental branch**, and a later scheduled observer independently verified commit `8eaa4ba5657cbcd4b4b663af2e79714a81d27a4d` and blob `fe649e1a23a0078ae612d7ecfcd4483135d37d05`. This establishes GitHub connector read/write for the tested Chat Mode scheduling context and approved branch, **not** blanket approval of production writes or credentials. Any new project must verify its own role-specific source permissions and approval conditions.

## Real-work validation: RE-Wizard BinaryWorkbench

The owner's active private BinaryWorkbench development project is an explicit
**real work** case for this design, not just a synthetic scheduler experiment.
Its scheduled pool includes two complementary implementers, a conductor,
a provisional verifier and an integrator. Early registry inspection verified
task creation, saved responsibilities, and independent scheduling settings,
**not** actual overlapping runs, qualified independent review, successful
tool output or inheritance. See the [privacy-safe study](REWIZARD_BINARYWORKBENCH_CASE_STUDY.md).

A bounded scheduled evidence monitor reads their actual execution records
and permitted private GitHub commit/PR metadata, without changing the private
project, team assignments, or schedules. It evaluates separately whether:
(a) meaningful worker run intervals actually overlap and safely update
different outputs; (b) a later wave **uses** a pinned prior artifact/finding;
(c) the conductor adjusts responsibilities/timing based on actual work;
(d) any verifier session has genuinely qualified isolation and evidence; and
(e) real code/tests are corroborated by repository artifacts rather than
a successful schedule alone. Preserve private branch names, task IDs, source
bytes, protected cases and conversation references in the private project
rather than copying them into HA's **public** documentation.

Only change the HA Chat Mode scheduling manual or policy when the recorded
result exposes a concrete reusable capability or limitation. Maintain
CHECKS PENDING and do not equate documentation updates with code acceptance.

## Evidence and rollout gate

A proposed five-to-ten-agent conductor design is not a shipped HA feature. Before enabling substantial autonomous work, verify native transport for each specific provider/surface/model: briefing reaches the intended tab/chat, tools function, actual project artifacts return, and restart resumes without duplicating work. Fingerprint consistency or a successful click alone does not suffice. Separate checker must have qualified model/context and not merely a different task ID in the same chat ref. Existing owner-paused HA project tasks remain paused until separately authorized.

For chronology and exact status, see [CHAT_MODE_FINDINGS.md](CHAT_MODE_FINDINGS.md), and for iCalendar templates and safe automation-update procedures see [SKILL.md](../../skills/chatmode-scheduled-orchestration/SKILL.md).
