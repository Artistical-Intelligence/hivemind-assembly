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

## HA shift manager: distinct corrective one-offs and maximum work runway

The owner wants the HA shift manager to **do corrective work immediately** and
to have **as much time as possible to plan and act** after the relevant team
results arrive, without becoming a gate for the workers.

An incomplete high-priority shift generates a **new generalized corrective
task instance**, not an unchanged extra recurrence. Make a concise handoff
containing what is missing, source/test revision, executable fix or diagnostic,
acceptance criterion and affected downstream consumer. Dispatch to the earliest
suitable existing authorized worker or **completed reusable one-time task
slot**, not necessarily the original author; preserve output ownership and
avoid duplicating an in-progress mutation. The two-revival one-off
experiment proves the same task ID can be reused for different assignments,
but has **not** measured the earliest supported time after a preceding run.
For a genuinely new ad hoc one-time assignment, **do not automatically apply
an hourly cooldown** inferred from the hourly `RRULE` recurrence rule.
Request the earliest supported future one-time event and verify both the
accepted configuration and its later completed execution. A new prompt
alone is not a new run. The platform may reject a particular timing or
enforce other permissions and active-task limits; report those actual
constraints rather than assuming either an exemption or impossibility.
Never create endless copies of the same recurring job to evade restrictions.

**Mathematical scheduling objective:** Maximize the manager's **usable
work runway**, not minimize the time until a downstream task receives
permission to work. From actual run timestamps, estimate when the
**relevant** worker, verifier and integrator evidence will be ready
(including observed jitter). Search the 60 candidate hourly minute phases.
Among phases with sufficiently high evidence-readiness confidence, pick
the **earliest one immediately after those outputs become available**:
it leaves the greatest available time until the next major worker cohort.
Allow appropriate update/start safety margins, document the uncertainty,
and revise the phase as actual timing distributions change. Do not
preserve a fixed :08 phase just because another team's schedule used it.
Do not force workers to wait for the manager. When not all outputs are
ready, the manager can still use the available evidence and independent
work can continue. The next cohort's start is an opportunity to have
reassignments prepared, **not** a deadline that stops the manager's own
run or a permission barrier for those workers.

The full HA-specific mathematical definition, evidence tiers and
one-time reactivation procedure are in
[SHIFT_MANAGER.md](SHIFT_MANAGER.md). This corrects the earlier
critical-path-latency objective and unsupported statement that every
new task instance on an old automation ID must automatically wait one
hour. CHECKS PENDING: instructions and the bounded two-revival experiment
do not yet prove immediate or sub-hour corrective dispatch, an
automatically computed optimal phase, or shipped HA runtime integration.

## Deep substantive work within each scheduled wave

**Owner instruction (November 4, 2026):** For the live BinaryWorkbench
team and future authorized ChatGPT Chat Mode waves, a scheduled execution
should perform as many **substantive consecutive implementation and
targeted testing steps** as are feasible within its *actual* execution.
A saved first improvement, commit, checkpoint, review note or passing
synthetic check is a **recovery milestone, not an automatic stop**.
After saving and validating the revision, continue into the next useful
independent or dependent step during the SAME invocation: additional
implementation, test execution, diagnosis, fixes, verification or
integration within the worker's approved write scope. Reconcile newly
discovered blockers and choose the next most valuable authorized action.
Preserve artifact hashes, review gates, sole-writer rules and exact
handoffs before each materially risky transition.

Do not impose a one-commit/one-subtask-per-run quota or spend a run only
repeating a plan/status report when actionable work is available.
Conductor oversight must not force each worker to stop at a milestone,
nor require it to wait for an unrelated role. A reviewer/integrator can
continue multiple checks/repairs on unblocked paths, but must never
self-approve or merge work whose mandatory independent gate is missing.

**Execution duration is not a scheduler setting.** Longer and deeper
work is an instruction about effort within the actual service
invocation; it does not guarantee an hour-long model run, change
per-run runtime limits, grant more context/model allowance, or permit
run-now loops, recursion, child task spawning or approval workarounds.
The worker finishes on a genuine service/resource/tool constraint,
owner stop, satisfied objective or exhaustion of useful permitted work,
with a complete durable resume point.

Observed state: the separate live BinaryWorkbench chat already saved
an equivalent owner-requested DEEP EXECUTION RULE in the prompts of
all eight existing scheduled project roles. This establishes
instruction propagation, not yet that each future run completed
multiple steps. The bounded HA evidence review should verify real
artifact and synthetic-test substance, not count commits or add a
performance ledger.

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
preserving the same task ID. A finite scheduled coordinator **successfully performed two consecutive
revivals of the same previously expired, test-owned one-time task**;
the original and both new runs completed with distinct run IDs but the
same immutable automation ID, no RRULE or new child automation. This
verifies two successful reuse cycles, not indefinite life, universal
scheduling support or independent review. A conductor can therefore
reuse a bounded pre-provisioned staff slot
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

## Recurring cross-team blockers: test the route, not the assumption

**Owner-reported failures in the real BinaryWorkbench waves (November 4):**
workers repeatedly conflated a failed authenticated **local** repository
checkout with an inability to execute source tests anywhere; an
integrator considered GitHub Actions but did not attempt the small
isolated workflow that could resolve the question; and strict
per-worker file ownership left the shared execution bottleneck without
a cross-team owner. The owner subsequently demonstrated multiple
successful **scoped** branch-only GitHub Actions synthetic runs.
These do **not** prove current worker-branch or integrated acceptance.

**Conductor duty:** Treat source access, local execution, hosted CI,
integration tests and qualified acceptance as distinct gates. If
multiple workers report the same blocker, or it appears over **two
completed waves**, prioritize a minimal permitted **executable**
experiment rather than producing another research-only blocker
report. Assign one **existing** worker/integrator temporary ownership
of the shared enabling capability, adjust its role and branch scope
with proper writer fences, and record a decision trigger. Other
independent useful work continues; do not serially halt everyone.
Escalate immediately when the shared blocker prevents the entire team.

**Worker/integrator duty:** Propose and, when authorized, actually
attempt the smallest safe independent alternative. For inaccessible
local GitHub checkout, try repository-authenticated CI on a
**separate allowed test branch**, pinned exact source, no downloaded
games/opaque compilers, minimal permissions and a bounded synthetic
test. Inspect actual workflow run, job/step success, tested commit
SHA, test count, skips and failures. If GitHub Actions or tool write
requires approval, stop at the genuine gate and record the tool
response; never bypass. A successful branch-scoped run disproves
a blanket inability-to-test claim but does not establish main,
integration or all worker branches pass.

**Shared responsibility:** Exclusive code write ownership prevents
collisions; it must never prevent anyone from recognizing, proposing
or escalating a project-wide bottleneck. The interactive main-chat
worker should intervene on real shared constraints during its
active turn. Conductor and verifier must check whether new
cross-lane test evidence led to actual corrected downstream work
and a repeatable source-revision test gate. Preserve existing
CHECKS PENDING and qualified independent review; a successful
CI workflow or passing subset is not general acceptance. Full
case evidence is limited to the private project and abstracted in
[the case study](REWIZARD_BINARYWORKBENCH_CASE_STUDY.md).

## Findings to use; limits to retain

Verified on one ChatGPT Chat Mode configuration during November 3–4, 2026:
- A scheduled run changed its own saved instructions, schedule, recurrence interval and enabled state; follow-up runs received persisted instructions. The longer bounded **three-occurrence two-hour schedule has now fully completed**, with all three follow-up executions, a matching final result and an independently audited auto-disable. Start times varied around nominal execution times.
- A scheduled run changed an **existing** separate automation's saved prompt and schedule. Separate target runs executed the updates, and read-only scheduled observers retrieved completed results through the Automations registry.
- A one-time scheduled parent was **prohibited by its execution environment** from creating another automation. No backend creation attempt occurred; this is not evidence about technical scheduler capacity. Do not try child-creation workarounds or claim unlimited task spawning.
- The **earliest** producer/consumer and coordinator/target task runs shared one chat reference. **Later revival manager/target runs used different recorded ChatGPT conversation references** and completed their cross-task coordination. Distinct chat references strengthen task-registry cross-conversation evidence, but do not alone prove model/effort qualification, author-free independent review or detached live processes.
- **Reactivation and GitHub evidence improved:** A scheduled manager successfully updated and re-enabled two *test-owned* completed/paused automations; the formerly exhausted task's **two bounded post-revival scheduled runs both completed**, and the formerly self-paused task's single restarted run also **completed**. A separate same-ID one-off experiment completed **two consecutive reactivations** of its original task with distinct finished run IDs and correctly saved one-time markers; both auto-disabled afterward. This is not an unlimited revival guarantee. A scheduled Chat Mode agent successfully created/read back one harmless file on a pre-provisioned test branch; a different scheduled observer independently verified the exact commit/blob. This does **not** authorize unrelated production writes, user-paused task revival or other MCP providers. The bounded scheduled-to-ordinary-interactive-message probe **completed BLOCKED**: no supported same-chat user-role message injection tool was available.
- **Real productive waves (November 4):** The private hourly BinaryWorkbench team now has **four substantive scheduled workers with a common completed-run overlap from 11:23:25 to 11:24:33 UTC**, distinct ChatGPT chat references and separately committed private GitHub branch work. A later provisional verifier run also completed and committed a further regression report, but qualified reviewer independence is still unproven. Their separately committed GitHub artifacts were read by a **later completed integrator** whose saved checkpoint records **13 passing static interface/source checks** and 23 nonoverlapping paths across five development branches. This is verified parallel **recorded execution** and downstream **source/checkpoint inheritance**. Later **real executable source-bound CI** has run and surfaced failures; one completed shift-manager correction was inherited and committed by a receiving worker. **Integrated CI remains failing**, formal independent review remains unqualified, and none of this proves HA native runtime readiness. The conductor persisted the owner-directed eight-role hourly schedule; the milestone reporter saved a completed owner-facing summary with deduplication state, but notification delivery is not independently established. Preserve both concurrent lanes and sequential inherited waves. See the [privacy-safe case study](REWIZARD_BINARYWORKBENCH_CASE_STUDY.md).
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

For exact completed experimental results and current limits, see [the multi-session audit](CHAT_MODE_SESSION_TEST_AUDIT_20261104.md) and [CHAT_MODE_FINDINGS.md](CHAT_MODE_FINDINGS.md). For iCalendar templates and safe automation-update procedures, see [SKILL.md](../../skills/chatmode-scheduled-orchestration/SKILL.md).
