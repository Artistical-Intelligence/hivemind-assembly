# ChatGPT Chat Mode adaptive execution process

Policy revision: 1.4 — 2026-11-04.

## Provider/surface scope — ChatGPT Chat Mode only

These are owner-directed operating instructions for the ChatGPT **Chat Mode** workflow, not a provider-neutral or all-OpenAI HA execution policy. Read with root `AGENTS.md`, `CHATGPT.md` and the task's own permissions and acceptance rules. The owner adopted all ten optimization steps only for ChatGPT Chat Mode, with the large-task clarification overriding any earlier suggestion of fixed backlog caps or compulsory small assignments.

Do not apply or inject this methodology into **ChatGPT Work**, **Codex**, Claude prompts, Claude worker/coordinator briefs, `CLAUDE.md`, or other provider/surface instructions. Do not use it as a common, unknown-provider, unknown-surface, or generic OpenAI default. Preserve Work, Codex and Claude processes, roles, model assignments and runtime behavior. Applying this methodology to any of them requires separate owner authorization and surface-specific validation. Chat Mode observations do not establish support in Work, Codex, or another OpenAI surface.

The evidence obtained so far concerns particular ChatGPT **Chat Mode** executions. This scope does not mean every proposed capability is already verified even within Chat Mode. Keep each capability's actual evidence and limitations. Shared safety, privacy, saving, source-access and independent-review rules predating this profile keep their existing scope; this document neither removes them nor adds a new Claude workflow.

**CHECKS PENDING:** The instruction implementation and consistency checks require a separate reviewer. Adopting an owner instruction is not evidence that every described runtime capability exists or has passed live acceptance. This change does not implement a new scheduler, launch workers, change credentials, extend a time window, or approve a release. Preserve the adjacent `STATUS.md` and root `CHECKS_STATUS.md`.

## Objective and non-negotiable clarification

Make cumulative, substantive progress on large tasks, carrying useful work through independent checking and integration when its gates are available. Large coherent chunks may take many waves to finish. Durable partial work is real progress; saving, mechanical checking, independent acceptance and publication are different states.

A **wave** is a bounded opportunity to execute and reassess, not a deadline for completing the whole assignment and not a barrier that makes all workers wait for one another. Do not add fixed limits on pending drafts, chunk size, units per wave, or waves per task. Do not force idle time solely because downstream review is unavailable. Checkpoints are recovery points, not stop commands. Actual owner deadlines, provider/runtime limits, access restrictions, write ownership, dependencies and quality gates still apply.

Do not optimize for commit counts, tiny easy-to-close tasks, or novelty in the plan. Optimize for useful cumulative results, reduced rework and the owner's eventual objective. Never weaken independent checking to inflate completions.

## Evidence-driven task chains, not prescheduled loops

In the ChatGPT **Chat Mode** methodology, a chain is an ordered sequence of *decisions informed by new evidence*, not a fixed repeating loop or a prescripted series of small jobs. Each execution reads the actual latest state, observes reviewer or tool results, and decides whether to finish, continue the same large chunk, repair, change method, pursue a new dependency, schedule a justified successor, or stop at a genuine boundary. The chain has **no arbitrary total length**: it remains logically open until the owner-authorized objective is independently accepted/completed or an actual stop, deadline, permission, provider/service, resource, or dependency constraint prevents further authorized progress. Individual tasks remain bounded/recoverable; their count is not capped merely for convenience. A finished milestone is not a reason to end the objective.

**Adaptive succession under the verified Chat Mode restriction:** The two
scheduled parent-child experiments reached their execution contexts but were
prohibited by the scheduled runtime from creating another automation. No
creation API attempt was allowed. Do not build a production plan around scheduled
child-task spawning, multiple descendants or an assumed interactive-turn
escape. Instead, the owner prefers **pre-provisioning a bounded pool of
project-owned existing automations**, then updating their full saved prompts,
scheduled times and enabled states as the next real work requires. Keep a
stable permanent objective and changing milestones; do not confuse dynamic
reassignment of a known task with a new chat or independent reviewer. An
alternate execution environment may support new-task creation, but requires
separate explicit authority and validation. Do not use descendants or parallel
task copies to bypass frequency/usage restrictions.

**Not a claimed ChatGPT scheduling feature:** a successful one-time parent→child test would prove only that specific hop and conditions, not arbitrary-depth recursive execution, detached live-worker persistence, automatic independent checking, or an exemption from the platform's schedule/usage limits. Never use a one-time chain to evade a recurring-task frequency cap or authorization gate. Five-minute ad hoc deadlines and other short delays are hypotheses to test rather than guaranteed service support. A *bounded experiment* may cap its own depth to guard against uncontrolled recursion; that is a test safety constraint, not a global production chain or work-in-progress limit. Keep pending results at their correct evidence tier.


## Interleaved concurrent and inherited work waves

**Owner clarification:** Both forms of scheduling are central to HA's
ChatGPT Chat Mode orchestration. Many agents can pursue genuinely
independent useful work **in parallel**, while results can also **feed
successor waves** in the same agent or through another existing agent.
A dependency can create a serial handoff; integration can merge branches;
a failed test can create a correction wave while unrelated work proceeds.
Neither an exclusively parallel pool with no inheritance nor a fixed
single-file worker/reviewer/tester relay describes the intended process.

Maintain the permanent final objective and a compact graph of material
work dependencies and versioned artifacts. Assign only ready and
authorized work; select start times and recurrence/stop parameters per
worker based on evidence, deadlines and usage allowance. Existing
Chat Mode automations can be retasked or rescheduled by permitted
scheduled updates. Their tested runtime was **not permitted to create
additional scheduled child tasks**, so "inheritance" normally means a
new assignment for an already pre-provisioned task, not a new
automation or a new live ChatGPT process. A separate session can
use the same short GitHub checkpoint only when its authorized tools
actually fetch it. Keep writer ownership/revision fences and qualified
independent review for affected outputs. Verify actual overlapping
run timestamps before asserting parallel execution and verify
the receiving run's recorded use of an exact source artifact before
asserting a handoff worked.

## HA shift manager: maximal work window and distinct corrective tasks

This **HA-specific ChatGPT Chat Mode** clarification takes precedence
over any earlier policy that treated the shift manager as a required gate
or sought only to minimize downstream worker delay.

The manager should begin **just after the outputs needed for its next
decisions are likely to be ready**, leaving the **longest usable period**
for substantive diagnosis, brief writing, scheduling updates and
coordination before the next substantial worker wave. Use completed-run
evidence, dispatch jitter and source readiness, not a fixed phase from
another project. Compare all supported hourly minute phases and pick
the earliest high-confidence post-evidence phase. Workers may proceed
without manager approval on ready independent work. Missing/noncritical
results do not block the manager or workers; source dependencies and
one-writer controls still apply. See [SHIFT_MANAGER.md](SHIFT_MANAGER.md)
for an explicit work-runway objective and acceptance requirements.

A previous run's missing deliverable generates a **new, generalized
corrective one-time task instance**, rather than a repeat of the
original assignment. Reassign it to the earliest suitable authorized
worker, including a **reusable, previously completed one-time task ID**
when available. Twice reviving the same one-off has been demonstrated;
the exact earliest permitted dispatch following a completion has **not**
been established. Thus do not impose a categorical 60-minute wait
based solely on the **hourly recurring** RRULE rule; instead attempt
a genuinely distinct owner-authorized future one-time event and
check actual service acceptance and execution. Do not promise instant
or sub-hour dispatch until empirically confirmed, and do not turn
multiple semantically identical one-offs into a forbidden substitute
for sub-hour recurring tasks. Permissions, safety and task caps remain.

## Pre-provisioned conductor and continuously evolving objective

Owner choice (November 4, 2026): if authorized for the real project,
recruit a **nominal five-role** pool in advance (conductor; two specialized
workers; verifier; integrator), optionally rising toward ten if the plan
allows and tasks are genuinely valuable. Distinct roles may share the
majority of a mission brief while having different meaningful capabilities,
milestones, output paths and exclusive edit ownership. A staggered
hourly schedule may order those workstreams but does not guarantee precise
start times, native parallelism, independent chat context or unlimited model
allowance. Do not create ten recurring tasks merely because ten slots exist.
The conductor owns the allowed task roster, not every task in the account.

A run MUST keep:
1. **Immutable contract:** project key, full-term final objective, acceptance
   criteria, approved source/tool scope, execution mode/model constraints,
   secrets/privacy/RE-Wizard mediation, writer fences and owner stop gates.
2. **Mutable assignment:** this run's meaningful dependency-aware work,
   concise inputs/outputs, targeted tests, current milestone and next decision.
3. **Actual evidence:** authoritative changed file/revision hashes, completed
   task results, last-run identity/status and blockers.

The conductor may **retrain** allowlisted existing tasks by updating complete
saved prompts, schedules and enabled state if the live tool/runtime permits.
Preserve the immutable contract across every prompt rewrite, verify the
persisted prompt in the registry, and confirm the next execution actually
received it. Changing a task does not by itself change its service-assigned
conversation or launch a separate interactive chat. Before re-enabling a
disabled task, identify the reason (user pause, autonomous pause, expired one-
time schedule, approval hold) and set a valid finite future schedule when
needed. Never revive owner-paused unrelated tasks.

**Do not assume repository instructions are read every scheduled turn:**
native ChatGPT scheduled runs receive their own saved instructions and the
available chat context. Repo files such as `AGENTS.md` and `SKILL.md` are
read only if a supported tool retrieves them or HA's own exactly routed
prompt-builder includes their compact contents. Every saved prompt must
request the minimum relevant fresh instructions/checkpoint through an
authorized tool when accessible. Verify receipt; never claim that writing
GitHub automatically refreshed every worker.

For sustained work, prefer concise revision-bound project checkpoints over
transcripts. The standalone scheduled-task product documents a fresh chat per
run; validate it on the chosen surface and reconstruct only necessary context.
No Chat Mode-scheduled tool in these tests supplied remaining-context
percentage, a new ordinary-chat creation operation or a conversation-retarget
argument. A Codex-specific context signal is **not** an established Chat Mode
variable. Shorten handoffs when prior context becomes inaccessible, and
declare automatic rollover blocked if there is no permitted native mechanism.

Evidence as of Nov 4: own-prompt/schedule updates, self-pause, cross-task
updating and task-result retrieval have completed live scheduled runs.
One revised 2-hour recurrence executed once; new multiple-interval and
test-owned revival verification is partially complete: a scheduled
manager re-enabled two authorized previously disabled tests and one
previously exhausted one-time target completed its first new occurrence.
Later dispatches remain under observation. Scheduled child creation
was blocked. A separate scheduled auditor corroborated that a scheduled
Chat Mode GitHub write **completed** on an isolated test branch and read
back exact commit and blob; other MCP/service permissions remain unverified.
The private real-work BinaryWorkbench team is a standing case for
both true parallel useful work and artifact-linked inherited follow-ups.
An owner-authorized bounded status observer will collect real completed
task/run/commit evidence without modifying the private project.
A different task ID does not establish qualified independent review when
both share the same chat reference. Do not release or self-approve based on
these experiments.

Read [REWIZARD_BINARYWORKBENCH_CASE_STUDY.md](REWIZARD_BINARYWORKBENCH_CASE_STUDY.md) for the privacy-limited live real-work orchestration check. Read [CONDUCTOR.md](CONDUCTOR.md),
[CHAT_MODE_FINDINGS.md](CHAT_MODE_FINDINGS.md) and the
[SKILL.md](../../skills/chatmode-scheduled-orchestration/SKILL.md) for safe
`RRULE`, task identity and handoff recipes. These docs are CHECKS PENDING
until a separate qualified session reviews them.

## Known issue: shared execution blocker left unresolved despite viable CI

**Owner corrective finding from the live BinaryWorkbench Chat Mode team
(November 4, 2026):** Workers confused inability to obtain a local
authenticated private-repository checkout (sometimes with direct
network DNS failures) with inability to execute source tests anywhere.
The integrator repeatedly analyzed potential GitHub Actions setups
without conducting the decisive minimal isolated branch experiment.
Strict separate write ownership prevented conflicting edits but also
left the shared test-execution prerequisite without a clear problem
owner. The owner then demonstrated working **scoped synthetic CI**
on isolated branches. Those successful runs do not prove current
worker revisions or integration are accepted.

**Enforced Chat Mode recovery rule:** A failed local route is not an
overall impossibility proof. Identify the exact blocked operation,
try the smallest supported/authorized executable alternative, and
observe the real test result rather than writing a repeated
feasibility report. An isolated, permission-scoped GitHub Actions
workflow that checks out the required exact commit and runs
no-game synthetic Python tests is one concrete option *where the
connection and approval rules permit it*. The saved YAML file,
successful API access or output report alone is not a test pass;
compare actual workflow run ID, source SHA, run/job/step result,
test count and failures/skips.

If >=2 independently assigned work lanes share one blocker, or it
remains across 2 completed waves, the conductor must designate an
existing authorized owner for the **cross-lane enabling capability**
and schedule the next minimal proof while unrelated independent
work continues. Role-specific **write** boundaries do not restrict
recognizing and reporting common bottlenecks. The main interactive
worker should help resolve such problems during live turns rather
than becoming another passive observer. Preserve tool approval,
source mediation, single-writer ownership, check-pending markers,
and the owner's prohibition on games and opaque compiler execution.
Do not claim a repeatable current-revision CI gate until it has
actually been tested on relevant producer and integration HEADs.

## 1. Read, reassess and decide at every wave

Reconcile the actual current project revision with the existing queue/handoff, newly saved outputs, checker verdicts, interruptions, relevant explicit owner directions and authorized capabilities. Read changed and decision-relevant material plus required project instructions rather than repeatedly loading entire histories. Confirm what the previous wave intended and what actually persisted.

Choose deliberately: continue, check/integrate saved work, repair a concrete failure, adapt the method, test a specific unresolved capability, advance other useful work, or stop at a genuine boundary. An unchanged plan is valid when evidence still supports it. Record concise rationale and the next decision trigger with substantive outputs; do not manufacture a new decision or planning-only wave for appearances. Reconcile remote state again before shared-file integration.

## 2. Define outcomes and evidence before acting

Retain a stable long-horizon assignment: objective, permitted repository/ref and output paths, source/input identities, dependencies, roles, acceptance criteria and stop conditions. Choose a useful progress objective for the current wave without requiring total completion within it.

Specify separately what establishes incremental progress and what establishes acceptance. For example, an actual importer run and its reproducible result advance a review; a candidate report alone does not establish that execution occurred. When source review and automation research are both requested, keep their outcomes separate. Neither commits nor a successful tool response alone establish technical correctness, independent acceptance or absence of a client-side approval prompt.

## 3. Prioritize bottlenecks and cumulative value

Work backward from the eventual objective and identify its limiting dependencies. Favor useful checking, integration and concrete blocker resolution when executable, while accounting for durable value, dependencies and likely rework. A large foundational task can be the best choice even when it will not close this wave.

Do not continually choose easy small wins or rewrite equivalent pending proposals because a key gate is unavailable. Diagnose the exact missing input or capability. Try another supported route only within the owner's authority and unchanged review standard; otherwise advance valuable independent or preparatory work. Dependency priority is not a prohibition on long-running progress.

## 4. Verify required capabilities without assuming them

Before relying on an executor, reviewer or lifecycle feature, establish the actual tool/interface, authorized source access, provider/surface/model/mode/effort, role, context provenance and artifact-return path. A planned launch is not a launched worker. Distinguish unavailable, blocked, failed, fixture-only and live-verified behavior. Retain evidence and recheck when relevant inputs, versions or environment change rather than repeating unchanged probes every wave.

A missing independent checker prevents acceptance of affected work, not every useful reading, writing, validation or preparation task. Do not assign a lower-qualified replacement, silently switch to an API, or label self-review independent. Discover supported alternatives within scope; retain honest blockers when none exists.

## 5. Manage dependencies without arbitrary work-in-progress caps

There is **no fixed cap on pending work** under this methodology. Continue useful independent or preparatory work, including substantial drafts, when it is authorized, reviewable, nonduplicative, resumable and has a credible future use. Keep inputs and pending gates explicit. Prioritize available review and integration without turning that priority into a global halt when a checker is unavailable.

Pause or defer only the affected path for a concrete dependency, invalidated or high-rework premise, unsafe conflict, resource/access constraint, owner stop, or genuine lack of useful authorized work. State the reason and its reconsideration trigger. Do not idle solely because many drafts exist, demand a closure quota per wave, delete work to reduce a backlog, or reduce quality requirements to make a queue look smaller. Existing concurrency, writer and service limits remain valid; they are not backlog limits.

## 6. Adapt granularity while preserving large coherent tasks

Maintain the same parent objective and exact resume position across waves and chats. A chunk may exceed one wave and finish over time. Use internal milestones and complete intermediate file snapshots to make that work recoverable. Do not reset, discard, arbitrarily subdivide or shrink a worthwhile assignment merely because one execution ended.

Split only for concrete context/runtime, dependency, ownership, parallelism or recoverability benefits. Preserve required source coverage and cross-unit dependencies. Adjust the next working slice using observed completion/interruption evidence without inventing a universal runtime ceiling. A smaller recovery slice does not shrink the total assignment. Continue after a saved milestone when useful work and authorization remain; never impose one-unit-per-wave termination. Bounded experiments are safeguards, not a small-chunk policy for the project.

## 7. Reduce overhead without reducing scrutiny

Use established deterministic scripts for inventories, fingerprints, quotation/range checks and reproducible bookkeeping. Batch safe independent retrievals when supported; serialize conflicting writes. Pin inputs and reuse unchanged accepted evidence only within its recorded scope. Summaries orient the next agent; required primary-source, claim and page checks still occur.

Retrieve relevant sections rather than entire textbooks, unchanged large files or full transcripts. Link detailed evidence once and keep shared queues concise. Preserve prompt saving at meaningful boundaries and the repository's stricter saving rules. Avoid duplicate explanations, competing ledgers, repeated capability-only commits and unnecessary model supervision of deterministic operations. Do not claim tool work is universally free or infer remaining allowance.

## 8. Run explicit, bounded automation experiments

For each unresolved automation behavior identify the hypothesis, current evidence gap, supported isolated experiment, expected observation, failure condition and cleanup/stop boundary. Use useful project artifacts as inputs when appropriate without conflating source-validation results with automation acceptance.

Distinguish live service behavior, actual implementation exercised in isolation, a contract simulation, scheduled-but-not-executed work, unavailable capability and failure. A GitHub stale-write rejection does not prove scheduler-level duplicate prevention; creating a schedule does not prove its execution; a separate task name does not prove independent review. Reuse passed unchanged tests. Never race production writers, damage real evidence, evade cadence/usage controls, launch runaway descendants, or repeatedly test an unavailable interface to appear active.

## 9. Preserve progress and recover through durable handoffs

Use the existing authorized project state and GitHub handoff/check records, not a second general-purpose coordinator or ledger. Save complete pending snapshots promptly at useful boundaries and before planned rollover; verify remote persistence. Record the stable goal, exact input/output revisions, coverage/resume cursor, relevant owner decisions, actual commands/results, corrections, pending gates, blockers and next action. Link detailed artifacts instead of copying them. Preserve privacy and source mediation.

Keep exclusive output ownership and one integration owner for shared records. Use supported expected-revision guards, writer epochs and fencing; a lookup followed by creation is not an atomic lock. After an uncertain save or interrupted response, inspect what reached the repository before retrying. Preserve newer remote work and accepted unchanged evidence. Do not depend on a final chat response or assume a failed scheduler label means no work persisted. Resume the unfinished part without double-counting or resetting completed coverage.

## 10. Compare results, learn and choose the next action

At each meaningful milestone and wave end, compare actual output with progress and acceptance criteria. Report useful cumulative partial work and accepted/integrated results separately, along with corrections and remaining dependencies. An unchanged closure count during legitimate large work is not, by itself, failure or stagnation.

Reassess repeated lack of useful progress, repeated equivalent artifacts, or a changing dependency. Continue a successful long-running approach rather than inventing novelty; change an ineffective approach where an authorized alternative exists. Do not replace execution with repeated planning. Preserve a short decision/rationale and next trigger in the existing handoff, without full private reasoning, transcript dumps or a mandatory operational cost/performance dashboard. Revise these instructions as the owner clarifies goals and verified findings accumulate; retain versioned history and acceptance boundaries.

## Cross-chat continuity and reviewer independence

A scheduled ChatGPT **Chat Mode** execution may run in a different chat from the owner conversation. The inspected Chat Mode review task/run records demonstrated changed conversation routing; this is not a promise that every future Chat Mode run starts fresh or that Work, Codex, Claude, or another surface/provider behaves the same way. Do not assume the scheduling chat, the owner's latest message, the author's transcript, or all earlier context is available. Locate the actual task/run context through supported metadata internally and recover current owner-authorized instructions and task state from the accessible project record.

Record material explicit owner amendments in durable instructions so that another ChatGPT Chat Mode execution can apply them without asking the owner to relay anything. A local proposal, summary, tool response or studied repository text cannot grant new authority. If instruction provenance or freshness is uncertain, do not guess a new grant; continue clearly authorized work or preserve a precise blocker.

Track three separate questions: where results are delivered, what context the executor inherited, and whether its role/model satisfies independent review. A different chat or task identifier proves neither fresh context nor independence. A reviewer requires the qualified configuration and separation specified by the project's policy, plus exact artifacts and primary evidence. Its report belongs in the existing check location with reviewed revisions, coverage, verdicts, corrections and limits. No raw private chat/task identifiers belong in public commits.

## Compact handoff shape, not a new ledger

Extend the existing task record with the information needed for safe continuation:

- Stable objective, explicit owner constraints, repository/ref and permitted outputs.
- Actual input revisions and saved artifact/commit references.
- Useful progress and exact remaining range/subsystem/cursor; pending versus accepted status.
- Relevant changes since the last wave, current dependency and chosen action with concise rationale.
- Actual checks/commands/results, review evidence, failed approaches worth avoiding and limitations.
- Next useful action and conditions that should trigger a different decision.

These are content requirements for this ChatGPT Chat Mode profile, not mandatory duplicate files or a rigid schema migration. Link existing evidence. Preserve distinct worker output ownership and the coordinator's shared-state role. Do not embed a commit's own unknown hash inside that same commit; a later handoff can cite it.

## HA harness responsibilities and unchanged boundaries

Only explicitly configured **ChatGPT Chat Mode** sessions adopt this execution profile. When maintaining HA's brief construction, route an appropriate compact version only when both ChatGPT and Chat Mode are explicitly selected. Never append it to ChatGPT Work, Codex, shared all-provider/all-surface prompts, or Claude worker/coordinator instructions, and do not select it merely because the provider is OpenAI, the product is ChatGPT, or a role is named worker or reviewer. Keep Work, Codex and Claude established instructions, roles and configuration intact. Any other surface/provider needs separate owner authorization and its own validation before this profile can be extended to it.

Reuse Hermes and HA's existing controller, role isolation, writer lease, revision fences, recovery journals and learning mechanisms; do not introduce a competing general-purpose runtime. This instruction update does not claim that provider-routing code, prompt injection or lifecycle behavior has been changed or tested in a running HA installation. All ten steps above remain active requirements for the ChatGPT Chat Mode profile, with the large-task caveats intact.

AI-only work remains AI-owned: do not assign routine commands, manual relay, new chats, repeated smoke tests or reviewer recruitment to the owner. Mandatory authorization still applies. Do not create credentials, spending, API fallback, broader textbook access or unrelated deployment changes. A stop/deadline is a real boundary; no prompt refinement extends an expired schedule. Independent reviews, protected evaluations, publication gates and all unrelated pending work remain intact.

Scenario acceptance for a later qualified check must include: a large ChatGPT Chat Mode task continuing across waves; useful work continuing with a checker unavailable; only an invalidated dependency path being deferred; recovery after a save whose chat response was lost; changed Chat Mode chat routing without restart; no automatic claim of independence; continuing beyond a checkpoint when permitted; and the profile not being applied to ChatGPT Work, Codex, Claude, unknown surfaces, or unknown providers. Static instruction checks are not live runtime acceptance. They also do not establish behavior in ChatGPT Work or Codex. See `test_continuation_contract.py` and `TEST_RESULTS.json` for the exact validation scope when those files are present.
