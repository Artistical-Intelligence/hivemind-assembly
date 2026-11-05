# HA ChatGPT Chat Mode — Shift Manager operating policy

**Authority:** Owner-approved HA application of the November 4, 2026 [BinaryWorkbench Shift Manager Policy](https://github.com/Artistical-Intelligence/RE-Wizard/blob/automation/binaryworkbench-orchestration-20261104/Tools/BinaryWorkbench/orchestration/SHIFT_MANAGER_POLICY_20261104.md). This file is the **single authoritative HA Chat Mode shift-management procedure**. [CONDUCTOR.md](CONDUCTOR.md), [PROCESS.md](PROCESS.md), [CHATGPT.md](../../CHATGPT.md) and the [scheduling skill](../../skills/chatmode-scheduled-orchestration/SKILL.md) provide background, exact tools and evidence, not competing manager policies.

**Scope and status:** **CHECKS PENDING. ChatGPT Chat Mode only.** HA also targets Claude, but this experimental scheduling policy must **not** be injected into Claude, ChatGPT Work, Codex or unknown modes. This is a documented design and pure helper contract; it does **not** install a scheduler, create a team, activate a worker, or change any private RE-Wizard automation. Actual HA-native prompt receipt, worker permissions, independent acceptance and service integration need separate verification. Apply the user's general design principles without copying RE-Wizard-specific private task IDs, branch names, eight-person staffing decisions or game restrictions as universal HA requirements.

## Owner's combined Shift/District Manager decision (November 5, 2026)

**No new permanent scheduling slot.** The owner decided that the existing RE-Wizard/BinaryWorkbench Shift Manager should carry **District Manager duties as a function of the same hourly recurring role**, instead of provisioning a separate recurring District Manager. This is cross-project oversight by an **owner-authorized external coordinator**, not a new HA worker, not a new AI API service, and not permission to add or change HA's currently authorized five full-time tasks without the required safe handoff.

**Management hierarchy:** The HA Shift Manager remains responsible for assignments and execution **within HA**. The combined RE-Wizard Shift/District Manager reviews **bounded, owner-authorized cross-project progress metadata** and coordinates a potential transfer of an existing eligible full-time worker **between** the owner's workstreams after actual delivery/acceptance or a documented, safe handoff to a continuing owner. This narrowly overrides the earlier local-manager-only reassignment wording for a legitimate cross-project move; local team management otherwise stays unchanged. No manager may preempt in-progress workers, steal claimed one-offs, erase unresolved writer obligations, revive owner-paused tasks, or bypass ChatGPT schedule/usage/approval controls.

**Evidence required before transfer:** latest exact task-ID run state and work product; scope/claim/review status; sending and receiving Shift Manager notification/coordination; recorded outstanding commitments and new non-overlapping write lease; supported prompt update and exact-ID readback; separate proof of the next actual run and useful result. If the scheduler prohibits updating a colleague's task from a scheduled invocation, write a `BLOCKED_NO_SUPPORTED_MUTATION` handoff, do not infer success from the new plan. Keep service-minimum hourly schedules and Chat Mode/provider boundaries where applicable. A `completed` invocation does not imply engineering completion.

**Project and source boundaries remain strict.** The District function may inspect only coordination metadata explicitly authorized for cross-project management. HA runtime agents remain **HA-only** and must not fetch or modify private RE-Wizard materials directly, even if a centralized manager knows a RE-Wizard project exists. Cross-project transfer of an HA worker to a RE-Wizard role must receive separate owner-authorized source access and mediation, not inherited from manager metadata. No RE-Wizard private task IDs, code, secrets or source evidence are copied into the public HA repository. Preserve existing HA agent role scopes and independent verification, and do not transfer a colleague whose work is unfinished.

**Canonical District function:** The detailed owner directive is in the private RE-Wizard `Tools/BinaryWorkbench/orchestration/DISTRICT_MANAGER_20261105.md`, maintained by the same existing RE-Wizard Shift Manager. This HA document states only the permitted coordination interface and boundaries. Actual combined-manager prompt update and meaningful cross-project execution remain **CHECKS PENDING** until independently observed.

## 1. Office roles and decision authority

There are **two disjoint classes of scheduled employees**. An agent's title, historical identity or disabled flag alone cannot confer access to either class.

| Class | Work contract | Who can change its scheduled prompt, time and enabled state |
| --- | --- | --- |
| **Full-time / permanent** | Owner-authorized existing recurring roles (typically hourly when owner requests the service minimum), each with a permanent project mission, distinct current workload, branch/file ownership and acceptance criteria. A stopped full-time role remains full-time. | **Only the Shift Manager** may reassign, reschedule, pause, revive, restore recurrence or change the role's rights, subject to owner authorization and host permissions. Workers cannot update each other's full-time task objects. |
| **Temporary / shared coffee pool** | Any **currently available, previously created one-time Chat Mode task** in the owner's accessible task registry, **regardless of original chat, project, title or purpose**; plus new dormant one-time reserve slots prepared at team bootstrap. A newly claimed finite work order replaces the old assignment, without inheriting old project's source access or permanent writes. | **Every authorized scheduled Chat Mode worker** is expected to seek and claim available temporary help when parallel or synergistic work is genuinely useful. The claimant must use the global exclusive claim protocol in §5; the Shift Manager is not a gate. The interactive chat may claim a temp only during an active user turn. |

**Default workforce obligation: actively use temporary Necromancy whenever it enables substantive parallel and/or synergistic progress.** Every scheduled worker, including the manager and an already executing temporary worker, should evaluate whether distinct useful pieces can be advanced simultaneously: implementation alongside independent synthetic testing, research alongside source validation, failure reproduction alongside repair, or independent bounded subtasks of a large objective. When the tasks are meaningful, nonduplicative, and resources/permissions permit, **claim and dispatch available coffee without waiting for Shift Manager approval**. Synergy means complementary work that improves the same outcome, not cloned identical jobs. No need to borrow an agent for trivial work, an unavailable dependent input, insufficient quota or conflicting writers. Preserve deep productive work in the requesting worker's own invocation as well.

**Global cross-chat eligibility is intentional owner authorization.** Search *all accessible previously created one-time tasks from any ChatGPT conversation*, whatever their former use or project. A task is available if the **current** registry establishes that it is not running, not enabled for a future event, not currently claimed/leased or reserved for ongoing work, and not subject to an explicit current owner stop/protective hold. Previous purpose, age, former title and conversation identity do **not** disqualify it. Do not require individual reauthorization solely because it once belonged to another chat/project; this owner instruction supplies standing permission for eligible dormant one-offs. Preserve historical results and avoid importing prior chat context or permissions into the new work order. A cross-chat update does not move the task to a new conversation or certify clean model context; verify the task's actual delivery/tool access. This does **not** give employees authority over healthy or stopped *full-time* roles.

**One-to-one bootstrap reserve:** When creating an owner-authorized cohort of **N active hourly/full-time scheduled roles**, **also prepare N reusable one-time temp slots at the same setup stage** (target 1:1), so temp capacity exists before a later scheduled invocation asks for it. Prefer verified already-created dormant one-offs from the global registry to satisfy the reserve; pre-create additional one-off placeholders to fill any shortage when the interactive/bootstrap interface permits. Keep all reserve slots **disabled/dormant with no pending runnable appointment**, not idle runs that consume allowance. If creation cannot safely produce dormant placeholders or the service quota/permission restricts the count, provision only the confirmed safe number and record the shortfall; never activate placeholder jobs merely to fulfill a ratio. Scheduled-run child creation remains restricted. The target is a ready capacity pool, **not** a permanent extra N hourly executions. No RE-Wizard-specific fixed role count applies to HA.

**The manager supervises, but does not gate, temp assignments.** The shared temp pool exists so independent staff can request useful parallel help without waiting for the manager's next hourly check. Conversely, this does **not** give any regular employee permission to retask a full-time colleague.

For an already authorized project, the immutable owner mission and provider/mode boundaries survive every work-order rewrite. All employees can *identify, diagnose and report* common bottlenecks; exclusive **writing** scope is not exclusive permission to notice problems. Use separate branches/revision fences/leases for actual writes. Independent useful work continues without waiting for the manager except when a real dependency or write lock applies.

## 2. Shift = substantive deliverable, not a completed model invocation

**Every scheduled role has an observable deliverable and exit condition.** The service saying `recorded_status=completed` establishes only that the *invocation* stopped. It does not establish that the engineering, verification or research outcome was achieved. A commit, checkpoint, successful static read or single small test is a recovery point, **not** an automatic stop if meaningful work remains and the current invocation can continue.

A shift manager inspects two separate evidence dimensions: **scheduling reliability** (`scheduled_for`, actual start/finish, jitter, run identity, overlap, accepted updates) and **delivered work** (changed artifact/commit, tests genuinely executed on the correct SHA, pass/fail/skip outcomes, independently qualified review, downstream receipt, unresolved defect). Store only compact evidence and a next-action pointer in the project's existing checkpoint; do not introduce a repetitive timesheet or reward commit counts.

Every invocation should proceed through multiple useful implementation, bounded test, diagnosis or repair steps when permitted by real context/runtime/tools. Nobody may pretend to force a sixty-minute model run. Milestones to the user should distinguish verified successes, known failures, and pending independent review, and avoid unchanged routine chatter.

## 3. Shift Manager: active control and prompt corrective action

At every **actual** managerial invocation, reconcile the owner directives, **current** permanent roster, current temp-claim state, real run/results, source/test revisions, downstream dependencies and explicit stops. Distinguish `in_progress`, `no_update`, failed, blocked, incomplete, accepted and unknown. Missing latest history or `next_run_time:null` is **not** permission to dispatch a duplicate.

An important unfinished or failing shift produces a **new logical corrective work package**, not a verbatim repeat of the old prompt. Draft a **generalized outcome brief** (§4) with valid predecessor evidence, what remains missing, acceptance and constraints, while leaving implementation choices to the receiving worker.

**Immediate triggers, not optional delays:** a failed pinned test, missing mandatory output, failed independent review, repeated non-progress or a currently blocking shared prerequisite warrants corrective action at the **next available manager decision point**. Two distinct workers reporting the same blocker, or the same blocker surviving two completed shifts, is a **maximum escalation delay**, not permission to wait when a consumer is blocked now. The manager assigns one permitted owner to the executable unblock experiment and lets unrelated lanes proceed.

To dispatch, choose the **earliest suitable already authorized full-time worker or available claimed temp** with the necessary skills and nonconflicting write scope. An original worker is a candidate, not a mandatory recipient; a different colleague may investigate a genuinely separate test/reproduction while the original implements the fix. **Only the manager** may change a full-time person's assignment or schedule. A properly claimed temp can be dispatched by any authorized project worker. The manager must actually perform the supported update where permitted, then verify the complete saved prompt/schedule/enable state and later the receiving run and artifact result. Status reporting alone is not dispatch.

**Corrective overtime:** prioritize/redistribute the unfinished deliverable, let a current invocation continue substantive work, and request the earliest **service-accepted** next occurrence for its new assignment. Ordinary permanent recurrence remains hourly when required by the owner; never pretend an updated task prompt forces an additional run or overrides provider limits. An entirely distinct **one-time** corrective assignment should use the earliest permitted future single event rather than an invented per-ID 60-minute cooldown inferred from the recurring `RRULE` minimum. Sub-hour single-event execution is **not established** by the earlier same-ID resurrection tests; test actual service acceptance, no unsupported workaround. Do not duplicate active writers, revive unrelated/user-paused work, spawn scheduled children through prohibited tools, or automatically bypass approvals.

When the work package's acceptance passes, close **that assignment**. A permanent employee continues useful ready work on its authorized cadence; a finite temp normally sleeps again after its completed/reported assignment. The project-wide mission remains until its independent terminal acceptance or explicit owner stop.

## 3A. Mandatory full-roster audit and productive reassignment

**Every Shift Manager invocation MUST inspect the complete accessible scheduled-task
registry across chats**, not merely the manager's last assigned workers or the
handful whose previous results were successful. Classify each task by exact
current ID, project/owner authorization, current full-time versus temporary
role, enabled/paused state, saved VEVENT, actual latest run and result, open
work-order, current claim/lease, next eligible slot and explicit owner stop.
The broad scan discovers unused one-off coffee candidates; it **does not**
authorize taking over unrelated active projects, protected user-paused tasks
or other managers' full-time employees. Maintain a current roster and
separately track every employee of this owner-authorized project, including
workers whose invocation has not run, has failed, is repeatedly delayed or
has returned `no_update`. A task with `next_run_time:null` is not
automatically idle.

**Judge meaningful progress by outcomes, not activity or the model's prose.**
For each project worker, compare the current deliverable and its required
exit criteria with actual revisioned source/artifacts, executed targeted
tests, failures and skips, reviewed evidence, resolved defects and a useful
downstream handoff. A commit, report, tool call, lengthy investigation or
`recorded_status=completed` without material advancement is **not
meaningful progress**. A worker need not pass its final acceptance in
one invocation; concrete valid partial advances that reduce uncertainty
or unblock dependent work do count. Evaluate blockers and the suitability
of the current assignment, not just elapsed time or commit counts.

**No employee left idle with ready authorized work.** If a completed
invocation made no demonstrable progress, repeated the same untested
plan, reported an already-known blocker without testing an available
alternative, reached a closed/no-work milestone or cannot progress
because of a real dependency, **the manager MUST assign a different,
substantive, ready work package during that same manager invocation**.
Use the highest-value unowned item from the project's verified backlog
or another independent fragment of a large milestone. Give a generalized
brief with specific acceptance evidence, owner/write scope and earliest
supported next execution; reassign or rebalance roles, including a
genuinely useful verification/CI/reproduction task, rather than
leaving a worker to repeat an empty hourly invocation. Where needed,
allocate one owner to the shared blocker while other workers pursue
independent progress. If the issue is low capability or repeated
method failure, change the task approach, specialization, evidence
packet or permitted escalation rather than just rewriting the same
instruction. **Do not wait for two cycles** when the first completed
run clearly produced no useful result or a critical dependency is
blocked.

**Respect ongoing execution and genuine constraints.** If a task is
`in_progress`, do not infer failure from partial records or dispatch a
conflicting write; let it finish or choose an independent colleague.
If a worker truly has no ready authorized work, lacks the required
tool/permission/allowance, or is explicitly owner-paused, record
`NO-READY-WORK` or the exact blocker rather than inventing busywork;
the manager can leave it dormant or pause that **authorized** task
and revisit it when a dependency clears. A productive worker should
keep its useful assignment and continue across invocations; do not
churn roles merely to appear active. Temp workers available in the
global coffee pool may support independent parallel/synergistic work,
but manager-only authority over full-time roles remains unchanged.

**Action and receipts are mandatory:** actual changed saved assignment,
next eligible schedule and full-prompt readback, followed by the
worker's distinct completed run and artifact/test evidence. An
unexecuted recommendation or narrative reassignment is a pending
decision, **not** demonstrated recovery. The manager's own check-in
time remains optimized to maximize its useful planning/work runway,
and its decisions must not become a prerequisite for unrelated workers
to keep working.

## 4. Canonical generalized continuation brief — part of this policy

Use a concise work order, not a full chat transcript or a rigid prescribed fix:

```text
CORRECTIVE-WAVE: <project key / unique work-order key>
Standing objective: <owner-requested end state>
Predecessor: <exact completed run and pinned source/test revisions>
Results preserved: <what truly worked and artifact or CI receipts>
Outstanding deficit: <incomplete result; NOT RUN vs FAILED vs BLOCKED>
Criticality / dependencies: <who depends on the missing outcome>
Evidence: <source SHA, test counts/skips/failures, constraints>
Acceptance: <observable behavior and required executed checks>
Write owner: <authorized branch/files, permissions and review gates>
Next eligible recipient: <existing role or claimed temp; permitted time>
Worker discretion: <choose methods, safe experiments and necessary fixes>
Resume: <save exact revisions and continue useful work beyond first commit>
```

The work order must carry the immutable mission/safety header, present source revision and **real** authorization. Suggested implementation methods may be included as evidence, not as compulsory recipes. Keep earlier failed approaches as data so the receiving worker does not merely repeat them. A successful update to a scheduled prompt alone is a configuration receipt: require the subsequent *distinct run ID* and actual output/test evidence before calling the correction complete. Do not self-approve work requiring a qualified independent reviewer.

## 5. Temporary coffee pool — exclusive claims without manager bottleneck

This mechanism uses **pre-provisioned, expressly authorized task objects**, because scheduled Chat Mode child-task creation was prohibited in completed tests. The authoritative claim/pool ledger must use **one restricted, account-wide cross-chat coordination namespace** accessible to authorized dispatchers (not independent project-local claim paths, which would allow two chats to claim the same ID). It must not be placed in HA's public instructions or an unprotected repository. A conceptual layout:

```text
<restricted-shared-control>/global_coffee_pool.json
<restricted-shared-control>/global_coffee_claims/<opaque-temp-ID>.json
<restricted-shared-control>/global_coffee_history/<work-order-key>.json
```

**Discover first, register second.** Global pool membership is a **validated, current availability record**, not a fixed list of only tasks that were originally created for HA. Any accessible historical *one-off* may join regardless of the chat or project in which it was created, without seeking one-off-by-one-off user approval, provided its current status meets the owner's stated availability rule. An expired one-off not yet listed should be inspected and **registered with exact task ID, provenance, present status and owner authorization before claiming**, in the same restricted global control namespace. An inactive title is not enough; exclude future appointments, current in-progress runs, existing claims, explicit holds and unverified states. Never preempt ongoing work. The permanent full-time roster and global temp pool are disjoint. A formerly unrelated **one-off** is not disqualified because it was used elsewhere; a formerly unrelated **recurring** role is not automatically borrowable. Store task IDs and former-chat provenance only in authorized private state, not the public HA policy.

### Claim, dispatch and release

1. **Discover and preflight globally.** Enumerate owner-accessible one-time automation objects **across chats**, not just the requesting project's original tasks; if a candidate is not registered, first validate and enroll it in the shared pool. Inspect the exact live registry ID, owner stop/hold, current prompt, schedule and completed history. It must be currently disabled/dormant, not in progress, not scheduled to run later, not claimed/leased, and without unresolved current assignment ownership. Check task capacity, provider/mode, actual tool availability, data/source authorization and a supported exclusive create-if-absent mechanism. Historical job title or prior project is irrelevant after availability is established.
2. **Prepare genuinely different work.** Assign a unique work-order key and useful objective with predecessor SHA, acceptance, source revisions, downstream consumer and *exclusive* output scope. No duplicate source writer or cloned unchanged recurring job.
3. **Acquire the exclusive claim.** Use an **atomic create-if-absent** operation against the **same single, restricted cross-chat coordination branch/namespace** and canonical per-temp claim path. Required claim metadata: schema, immutable temp ID, work-order key, claiming task/run, previous temp run ID, objective, acceptance, source SHAs, output branch/write scope, earliest requested dispatch. If the file already exists, any write conflicts, or atomicity cannot be established, **fail closed**: do not dispatch that temp; choose another authorized slot or escalate to manager. Never overwrite an existing claim by a blind save or whole-branch batch write.
4. **Verify before modifying the task.** Re-read the exact claim's GitHub commit/blob and current task status. If the task is active or ownership changed since preflight, stop and preserve the claim for reconciliation.
5. **Only the successful claimant dispatches.** Update **that temp alone** with a full *new-project* prompt/title, future **one-time** `DTSTART` *without* `RRULE`, and `is_enabled=true`. Explicitly replace the former assignment, scope and allowed source references; do not assume that previous-chat context, provider/model or tools are isolated or transferable. Verify actual receipt of the new role and only its newly granted permissions. Validate service acceptance, a distinct run ID, completion, prompt marker, artifact and test receipts. A successful claim/prompt update is not execution. Do not reactivate a temp still running.
6. **Return to pool after proven closure.** On completion, write a compact immutable history record with the output SHA, test outcome, disposition (`accepted`, `partial`, `failed`, `needs-check`) and next consumer. Only after verifying the temp auto-disabled and no newer run/claim replaced it may the claimant delete its **own** claim file by the **latest exact blob SHA**. If it cannot prove ownership or delete permission, ask the manager to reconcile; never release a stale or guessed claim.

**Do not reclaim by time-to-live alone.** A worker can exceed the scheduled time or be delayed. A claim remains exclusive until an authorized actor checks the actual run state and releases it. An already executing temp may request another available temp using this same protocol, but cannot claim itself or borrow the same writer lease as its parent. Respect actual active-task and usage caps; no self-restarting unbounded descendants or alternate provider/API route.

**No live acceptance inferred:** Existing tests established same-ID one-time resurrection and cross-conversation registry updates. They have **not** established that a dormant one-off can be safely repurposed across arbitrary previous chats with clean context/source permissions, that two workers can atomically claim candidates simultaneously, that N dormant reserve placeholders can be created safely at initial bootstrap, or that HA has a functional connected coffee-pool dispatcher. These are design requirements and pending acceptance, not shipped capabilities.

## 6. Necromancy of stopped recurring staff — manager exclusively

An otherwise enabled healthy recurring role with a completed last *invocation* is **still employed and scheduled**. It is not an eligible sleeping temp.

A **genuinely stopped** permanent recurring role is different: it may have an exhausted `COUNT`/`UNTIL`, a recorded pause for lack of ready work, a failed/disabled schedule, or another verified lack of future eligible work. The **Shift Manager alone** diagnoses the cause and owner intent. If the employee still owns ongoing independent responsibilities, restore its supported hourly recurrence with a refreshed generalized assignment. If the role instead needs one bounded new corrective instance, the manager can reuse the same ID with a future **single-event VEVENT**, but must preserve its permanent role and restore/reconcile any ongoing mission afterward.

Never convert or pause a **healthy in-progress** permanent worker to manufacture a necromancy test. A user-explicit stop, unrelated project, disabled unknown task, insufficient quota or ambiguous `in_progress` record is not automatically eligible. A stopped full-time role is **not** inserted into the shared temp registry; ordinary workers have no right to modify it.

The bounded November 4 Chat Mode tests confirmed **two resurrections of a previously completed one-time slot**, plus revival of a self-paused test-owned task. They did **not** independently demonstrate actual recovery of an unexpectedly **stopped recurring full-time role** with owner-approved role restoration. That distinct acceptance test remains pending.

## 7. Shift Manager's own timing: maximize useful runway, not worker latency

The mathematical objective approved for **HA** is to position the manager **just after enough relevant work has finished** so it has the **longest feasible useful work window** to diagnose, reassign, test and prepare before the next significant cohort. Other workers **do not wait** for its check-in. The source policy's weighted critical-path delay can inform which outputs count as relevant, but must **not replace the owner's explicit maximum-manager-runway objective**, impose a supervisor gate or hard-code RE-Wizard's provisional `:08` UTC phase.

For one representative wave, let `R_q` be the observed high-confidence ready time of *relevant* prior outputs (with a margin for actual early/late dispatch), and `D` the next independent worker cohort's start. For each allowed hourly phase `m ∈ {0,…,59}`, project its actual start `S_m` with conservative jitter and define:

```text
eligible(m) = [S_m >= R_q + readiness_margin]
runway(m)   = max(0, D - S_m - update_margin)
m*          = argmax_{eligible(m)} runway(m)
```

With reliable evidence the earliest **feasible** phase after the necessary results arrive generally maximizes this window. Estimate from actual completed timestamps and real service jitter; if there are too few samples or no feasible phase, report a provisional recommendation and continue useful work on partial evidence. `D` is a **planning reference**, not a stop condition for the manager's model invocation or a barrier for unrelated workers. A single check cannot guarantee every asynchronous worker has finished.

HA already has a **pure, side-effect-free** phase-search helper:
[`shift_window.py`](../../_app/hivemind_assembly/automation/shift_window.py)
with [offline tests](../../tests/test_shift_window.py). It is not a connected scheduler and does not change an automation. Never claim a mathematically optimal real dispatch without actual trusted completion samples, tool-supported update and later execution evidence.

## 8. Evidence, minimum shift report and acceptance gates

The shift report must also account for **every authorized project worker**, including those with no new artifact, a completed `no_update`, repeated same-blocker reports, or an idle/no-ready-work state. For each worker record only current useful progress, readiness, the kept/reassigned next work order, and actual dispatch evidence. Treat unrelated account tasks as inventory/protected records, **not** as candidates for forced retasking.\n\nThe manager records one compact decision summary in the **existing private project checkpoint**: (1) what completed vs remains running/incomplete, (2) actual run IDs and source/test receipts, (3) the current critical blocker/explicit owner, (4) changed prompts, `DTSTART` and enabled states accepted and independently re-read, (5) candidate phase and expected manager working window with uncertainty, and (6) what work proceeds independently. No duplicate performance ledger. A main-chat contributor acts only during an actual turn, not continuously between turns; scheduled workers must identify unresolved gaps autonomously.

**Prove each capability separately** before claiming deployment:

- **Full-roster anti-idling:** a completed manager invocation enumerates **all accessible scheduled tasks across chats**, classifies unrelated/protected entries without changing them, and evaluates meaningful progress for **every authorized project worker**, including no-update/failed/blocked/delayed employees. At least one eligible nonproductive worker is given a substantive alternative work order **in that manager invocation**, with saved prompt/next-slot readback and a later successful receiving-run result; true no-ready-work and in-progress exclusions are verified without manufacturing duplicate work.
- **Full-time authority:** only manager updates a permanent role and it later receives the correct assignment; no unrelated task touched.
- **Corrective dispatch:** a completed manager identifies an incomplete important outcome; writes a generalized brief; moves the **same eligible worker's next start earlier** where genuinely permitted and beneficial (retained acceptance demonstration), and separately tests dispatching a nonconflicting fragment to a **different** suitable role. Verify actual receipts, not just configuration. This is not a requirement to make the manager a gate or to violate actual cadence restrictions.
- **Global, reusable temp pool:** bootstrap N permanent hourly roles with a **target N dormant one-time reserves** where quota permits, including genuinely idle one-offs discovered in **other ChatGPT chats regardless of previous purpose**. Confirm disabled/no-future-run state, exact global membership and scope reset. At least two authorized scheduled agents obtain **different** claims without collision, execute distinct parallel/synergistic one-time assignments, record actual results, release verified claims, and demonstrate later reuse. Independently test a cross-chat competing claim for the **same** temp and fail-closed behavior; **no double dispatch**. If the reserve target cannot be met, record the actual capacity reason instead of launching placeholders.
- **Stopped recurring revival:** a genuinely stopped manager-controlled full-time task resumes under the **same task ID** and produces actual work, or properly returns to dormancy as a single-event corrective instance. Don't manufacture the stopped state by pausing healthy work.
- **Manager-phase optimization:** actual output and jitter samples produce a justified maximum-work-runway phase; the manager updates its schedule only when permitted, re-reads it, and verifies later actual timing. Other workers proceed independently.
- **Safety:** no unapproved provider switch, model/effort claim, protected-source bypass, user-paused task resurrection, conflicting writers, approval workaround, false independent-review assertion or unrestricted child creation.

**Current evidence:** Service-level Chat Mode tests proved self/cross-task updates, bounded 2-hour recurrence, completed self-paused/expired task revival, two same-ID one-time resurrections and an isolated GitHub write, and real-work scheduling demonstrated overlapping sessions and an inherited correction. **HA's full-time/temp claim partition, stopped recurring resurrection, live manager optimization and source-native acceptance remain CHECKS PENDING.** See [the multi-session audit](CHAT_MODE_SESSION_TEST_AUDIT_20261104.md). The private RE-Wizard source policy is a *reference*, not an authorization to edit its live project.
