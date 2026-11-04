# Chat Mode conductor and pre-provisioned workforce — HA policy

**CHECKS PENDING:** Owner-directed design; not yet separately reviewed, implemented as a new HA scheduler, or accepted as a live multi-chat runtime. This file applies only to **ChatGPT Chat Mode**, not Work, Codex, Claude or an unknown provider/surface. Read root `AGENTS.md`, `CHATGPT.md`, [PROCESS.md](PROCESS.md) and [the scheduling skill](../../skills/chatmode-scheduled-orchestration/SKILL.md).

**Purpose:** Advance an owner-authorized **terminal acceptance objective** across many independently bounded scheduled Chat Mode executions. The team may be recruited in advance and retrained by changing existing, authorized automations. A schedule is a wakeup, not a continuous agent or an independent reviewer guarantee.

## Primary design: parallel workforce, adaptive orchestrator, variable timing

The owner's **central design requirement** is not a linear worker → reviewer → tester queue or merely several repeating reminders. It is a **pool of multiple AI workers tackling different useful tasks in parallel**, supervised by a **scheduled conductor/orchestrator** that continually changes assignments and each worker's **timing parameters** according to project needs and results.

Treat the permanent project objective as shared across the workforce, not as a single scheduled task. The conductor maintains an evolving dependency graph and can give different specialists distinct ready work at once. Work whose inputs and write ownership are independent should proceed concurrently whenever the native service actually permits overlap; no worker is required to wait for another phase merely to fit a fixed pipeline. Necessary integration, acceptance, data dependencies, writer leases or resource constraints still impose real sequencing.

**Adaptive control per authorized worker:** the conductor can inspect actual completed results, select/reassign an active milestone, set a suitable future `DTSTART`, adjust `RRULE:FREQ`/`INTERVAL`/`COUNT`/`UNTIL`, or enable/pause that task when permitted. Timing depends on urgency, predicted useful work, observed completion, dependencies, service delay and allowance, rather than a universal :00/:15/:30/:45 rotation. These are supported *schedule fields*, not a guarantee the scheduler starts precisely or that scheduled runs can be more frequent than the per-task hourly minimum. Prefer fewer idle invocations when waiting on an actual prerequisite; awaken already authorized roles at the next supported time when genuinely useful work becomes ready.

**Actual parallelism must be verified:** several task schedules with 15-minute offsets provide a staggered **start plan** but do not, by themselves, prove overlapping model execution, separately isolated conversations, independent reviewer qualifications, or independent writing. A true parallel run needs distinct observed run IDs with overlapping start/finish intervals and real nonconflicting useful work; chat refs, writer ownership and tool-delivery/return receipts must be examined separately. Parallelism is the **goal**, not a capability established by the earlier scheduled tests.

The conductor is **not** the mandatory gate for every worker action. Workers may continue coherent assigned work under their own saved prompts and the common immutable objective. The conductor periodically reconciles actual changes and revises work/timing only when evidence demands it. Review and testing can proceed concurrently with unrelated implementation; required qualified independent acceptance remains a gate only for the affected deliverable. Avoid unnecessary routine polling and duplicate planner messages.

Distinct members may share the majority of the mission/safety brief, but **must have materially different assigned outputs or responsibilities**, with agreed merge/check ownership. The nominal five-role roster below is a bootstrap example, not a fixed sequential pipeline or permanent division of labor. Change role count and assignments from the actual project backlog, not a forced staffing number; no clones created solely to evade the once-hourly recurrence restriction.

## Findings to use; limits to retain

Verified on one ChatGPT Chat Mode configuration during November 3–4, 2026:
- A scheduled run changed its own saved instructions, schedule, recurrence interval and enabled state; follow-up runs received persisted instructions. One revised two-hour recurrence ran **once**; multiple consecutive two-hour intervals are still being tested.
- A scheduled run changed an **existing** separate automation's saved prompt and schedule. Separate target runs executed the updates, and read-only scheduled observers retrieved completed results through the Automations registry.
- A one-time scheduled parent was **prohibited by its execution environment** from creating another automation. No backend creation attempt occurred; this is not evidence about technical scheduler capacity. Do not try child-creation workarounds or claim unlimited task spawning.
- The tested separate task run IDs shared the **same chat reference**. Distinct task IDs, prompts and run IDs do not prove separate chat contexts, qualified independent review or a detached live process.
- Re-enabling an expired or self-paused prior test task is **not yet verified**; a scoped Nov 4 test is scheduled. Scheduled GitHub connector writes are **not yet verified**; a test is scheduled on a disposable non-production branch. The bounded scheduled-to-ordinary-interactive-message probe **completed BLOCKED**: no supported same-chat user-role message injection tool was available; no new ordinary turn was triggered.
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

GitHub connection permissions currently show repository `push=true` for the owner in the interactive interface. A scheduled GitHub write still needs its own actual tool availability and approval validation; the Nov 4 one-time test uses a separate `experiment/` branch only. Never expand a capability probe to production writes or credentials by inference.

## Evidence and rollout gate

A proposed five-to-ten-agent conductor design is not a shipped HA feature. Before enabling substantial autonomous work, verify native transport for each specific provider/surface/model: briefing reaches the intended tab/chat, tools function, actual project artifacts return, and restart resumes without duplicating work. Fingerprint consistency or a successful click alone does not suffice. Separate checker must have qualified model/context and not merely a different task ID in the same chat ref. Existing owner-paused HA project tasks remain paused until separately authorized.

For chronology and exact status, see [CHAT_MODE_FINDINGS.md](CHAT_MODE_FINDINGS.md), and for iCalendar templates and safe automation-update procedures see [SKILL.md](../../skills/chatmode-scheduled-orchestration/SKILL.md).
