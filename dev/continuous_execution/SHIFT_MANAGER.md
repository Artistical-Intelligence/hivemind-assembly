# HA ChatGPT Chat Mode — Shift Manager operating policy

**Authority:** Owner-approved HA application of the November 4, 2026 [BinaryWorkbench Shift Manager Policy](https://github.com/Artistical-Intelligence/RE-Wizard/blob/automation/binaryworkbench-orchestration-20261104/Tools/BinaryWorkbench/orchestration/SHIFT_MANAGER_POLICY_20261104.md). This file is the **single authoritative HA Chat Mode shift-management procedure**. [CONDUCTOR.md](CONDUCTOR.md), [PROCESS.md](PROCESS.md), [CHATGPT.md](../../CHATGPT.md) and the [scheduling skill](../../skills/chatmode-scheduled-orchestration/SKILL.md) provide background, exact tools and evidence, not competing manager policies.

**Scope and status:** **CHECKS PENDING. ChatGPT Chat Mode only.** HA also targets Claude, but this experimental scheduling policy must **not** be injected into Claude, ChatGPT Work, Codex or unknown modes. This is a documented design and pure helper contract; it does **not** install a scheduler, create a team, activate a worker, or change any private RE-Wizard automation. Actual HA-native prompt receipt, worker permissions, independent acceptance and service integration need separate verification. Apply the user's general design principles without copying RE-Wizard-specific private task IDs, branch names, eight-person staffing decisions or game restrictions as universal HA requirements.

## 1. Office roles and decision authority

There are **two disjoint classes of scheduled employees**. An agent's title, historical identity or disabled flag alone cannot confer access to either class.

| Class | Work contract | Who can change its scheduled prompt, time and enabled state |
| --- | --- | --- |
| **Full-time / permanent** | Owner-authorized existing recurring roles (typically hourly when owner requests the service minimum), each with a permanent project mission, distinct current workload, branch/file ownership and acceptance criteria. A stopped full-time role remains full-time. | **Only the Shift Manager** may reassign, reschedule, pause, revive, restore recurrence or change the role's rights, subject to owner authorization and host permissions. Workers cannot update each other's full-time task objects. |
| **Temporary / shared coffee pool** | Explicitly owner-approved, already-existing reusable **one-time** task IDs. A fresh substantive finite assignment is loaded into a dormant ID, executed, checked and returned to the pool. Temps never inherit permanent source write rights by default. | **Any specifically authorized Chat Mode project worker, including the Shift Manager and a temp already executing**, may *claim and dispatch* an eligible temp through the atomic exclusive-claim protocol in §5. The main interactive chat may do so only during its live user turn and within its permissions. |

**The manager supervises, but does not gate, temp assignments.** The shared temp pool exists so independent staff can request useful parallel help without waiting for the manager's next hourly check. Conversely, this does **not** give any regular employee permission to retask a full-time colleague. A project bootstrap might provision a nominal five-role permanent workforce, expandable when useful and within quota; **do not hard-code RE-Wizard's eight roles as HA's universal structure**.

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

This mechanism uses **pre-provisioned, expressly authorized task objects**, because scheduled Chat Mode child-task creation was prohibited in completed tests. The pool must be held in a **project-authorized restricted workspace**, not in HA's public agent instructions or an unprotected repo containing other users' task IDs. A conceptual layout, adapted per project:

```text
<private-project-control>/coffee_pool.json
<private-project-control>/coffee_claims/<opaque-temp-ID>.json
<private-project-control>/coffee_history/<work-order-key>.json
```

A membership registry must list immutable eligible temp IDs, original provenance and explicit owner permission. A disabled task that is not on the allowlist is **not** free coffee. The owner-approved permanent roster and temporary pool are disjoint. Never publish account-specific task IDs, secrets or protected source in a public HA policy file.

### Claim, dispatch and release

1. **Discover and preflight.** Read the exact registry member and actual live Automations entry. It must be authorized, currently disabled, have a completed or suitably adjudicated prior one-time shift (or be an approved unused slot), and have **no** active run or outstanding future appointment/claim. Check plan active-task capacity, source authorization and an available tool that supports exclusive create-if-absent.
2. **Prepare genuinely different work.** Assign a unique work-order key and useful objective with predecessor SHA, acceptance, source revisions, downstream consumer and *exclusive* output scope. No duplicate source writer or cloned unchanged recurring job.
3. **Acquire the exclusive claim.** Use an **atomic create-if-absent** operation against the **same private coordination branch** and canonical per-temp claim path. Required claim metadata: schema, immutable temp ID, work-order key, claiming task/run, previous temp run ID, objective, acceptance, source SHAs, output branch/write scope, earliest requested dispatch. If the file already exists, any write conflicts, or atomicity cannot be established, **fail closed**: do not dispatch that temp; choose another authorized slot or escalate to manager. Never overwrite an existing claim by a blind save or whole-branch batch write.
4. **Verify before modifying the task.** Re-read the exact claim's GitHub commit/blob and current task status. If the task is active or ownership changed since preflight, stop and preserve the claim for reconciliation.
5. **Only the successful claimant dispatches.** Update **that temp alone** with complete new prompt/title, future **one-time** `DTSTART` *without* `RRULE`, and `is_enabled=true`. Validate the service's accepted configuration, actual future run ID, completion, prompt marker, artifact and test receipts. A successfully created claim is not an executed job. Do not try to reactivate a temp still running.
6. **Return to pool after proven closure.** On completion, write a compact immutable history record with the output SHA, test outcome, disposition (`accepted`, `partial`, `failed`, `needs-check`) and next consumer. Only after verifying the temp auto-disabled and no newer run/claim replaced it may the claimant delete its **own** claim file by the **latest exact blob SHA**. If it cannot prove ownership or delete permission, ask the manager to reconcile; never release a stale or guessed claim.

**Do not reclaim by time-to-live alone.** A worker can exceed the scheduled time or be delayed. A claim remains exclusive until an authorized actor checks the actual run state and releases it. An already executing temp may request another available temp using this same protocol, but cannot claim itself or borrow the same writer lease as its parent. Respect actual active-task and usage caps; no self-restarting unbounded descendants or alternate provider/API route.

**No live acceptance inferred:** Existing tests established same-ID one-time resurrection and cross-task updates, *not* two concurrent agents racing over atomic claims or a functional HA-native coffee-pool dispatcher. Requiring a claim in documentation is a safety design, not evidence that HA currently implements one.

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

The manager records one compact decision summary in the **existing private project checkpoint**: (1) what completed vs remains running/incomplete, (2) actual run IDs and source/test receipts, (3) the current critical blocker/explicit owner, (4) changed prompts, `DTSTART` and enabled states accepted and independently re-read, (5) candidate phase and expected manager working window with uncertainty, and (6) what work proceeds independently. No duplicate performance ledger. A main-chat contributor acts only during an actual turn, not continuously between turns; scheduled workers must identify unresolved gaps autonomously.

**Prove each capability separately** before claiming deployment:

- **Full-time authority:** only manager updates a permanent role and it later receives the correct assignment; no unrelated task touched.
- **Corrective dispatch:** a completed manager identifies an incomplete important outcome; writes a generalized brief; moves the **same eligible worker's next start earlier** where genuinely permitted and beneficial (retained acceptance demonstration), and separately tests dispatching a nonconflicting fragment to a **different** suitable role. Verify actual receipts, not just configuration. This is not a requirement to make the manager a gate or to violate actual cadence restrictions.
- **Shared temp pool:** at least two authorized scheduled agents successfully obtain **different** temporary claims without collision, execute distinct one-time assignments, record exact results, release with verified blob SHA, and demonstrate later reuse. Independently test a same-temp concurrent claim race and fail-closed behavior; **no double dispatch**.
- **Stopped recurring revival:** a genuinely stopped manager-controlled full-time task resumes under the **same task ID** and produces actual work, or properly returns to dormancy as a single-event corrective instance. Don't manufacture the stopped state by pausing healthy work.
- **Manager-phase optimization:** actual output and jitter samples produce a justified maximum-work-runway phase; the manager updates its schedule only when permitted, re-reads it, and verifies later actual timing. Other workers proceed independently.
- **Safety:** no unapproved provider switch, model/effort claim, protected-source bypass, user-paused task resurrection, conflicting writers, approval workaround, false independent-review assertion or unrestricted child creation.

**Current evidence:** Service-level Chat Mode tests proved self/cross-task updates, bounded 2-hour recurrence, completed self-paused/expired task revival, two same-ID one-time resurrections and an isolated GitHub write, and real-work scheduling demonstrated overlapping sessions and an inherited correction. **HA's full-time/temp claim partition, stopped recurring resurrection, live manager optimization and source-native acceptance remain CHECKS PENDING.** See [the multi-session audit](CHAT_MODE_SESSION_TEST_AUDIT_20261104.md). The private RE-Wizard source policy is a *reference*, not an authorization to edit its live project.
