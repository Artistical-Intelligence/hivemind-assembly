# ChatGPT Chat Mode shift manager — corrective one-offs and maximum work runway

**CHECKS PENDING. Owner clarification: November 4, 2026.** This is a ChatGPT **Chat Mode-only** HA orchestration design. It must not be included in Claude, Work, Codex, generic all-provider instructions, or the active private RE-Wizard team's saved tasks. This document is an HA design/reference: committing it does **not** change any live automation schedule or execute new tasks.

## Two corrections to the earlier description

**A new corrective task is not automatically a repeat of the previous scheduled task.** If a prior run failed to achieve a useful milestone, the manager should generate a distinct, generalized corrective assignment from its observed gap: the incomplete behavior/test, exact artifact/revision, necessary follow-up experiment, acceptance criterion, dependencies, and permitted output owner. The **same existing one-time task slot** may be reused with an updated complete prompt and a new single-event DTSTART, or a different authorized available worker may inherit the corrective work. This is task reassignment, not another ordinary `RRULE` occurrence of unchanged instructions.

**The manager's own scheduling objective is to maximize its available useful work window**, not to minimize a worker's wait for the manager or make the manager a gate. Arrange the manager's hourly start **just after the relevant cohort's outputs are expected to be available**, with the largest feasible time before the next major work wave begins. All other authorized workers continue without waiting for the manager except for actual source/data/write dependencies.

## Corrective dispatch: same-ID one-time resurrection and work inheritance

A previously completed one-time Chat Mode automation was **successfully resurrected twice** in the bounded November 4 test: the original task and two revived assignments completed with **three different run IDs under the same immutable automation ID**, with one-time VEVENTs containing no `RRULE`. A scheduled manager changed full saved prompts, future one-time DTSTART and `is_enabled=true`. The target auto-disabled after each completion. This demonstrates reusing the one-time slot; it does **not** establish unbounded resurrection, arbitrary interface permission, or any particular minimum time between distinct resurrections.

For HA, a new **legitimate corrective assignment** is a separate piece of work even if delivered through an old task object. When a task object is completed, **do not impose an invented 60-minute delay solely because its ID ran earlier**. Instead, try the supported one-time update with the **earliest permitted future event** and verify the scheduler's response. The once-per-hour minimum stated for repeating `RRULE` schedules does not, by itself, demonstrate a cooldown on all distinct *ad hoc one-time* assignments. Conversely, the one-off revival experiments have **not** verified that arbitrary sub-hour restarts are allowed. A prompt rewrite alone is not a new model invocation, and a hypothetical ability to create unlimited tasks is not established: an actual attempt to create a further test task returned an **active-task limit of 15** in the tested plan. Never manufacture semantically identical one-offs just to emulate a recurring sub-hour timer or evade a provider restriction.

When a high-priority deficit appears:

1. **Recognize the gap.** Compare intended work and source-level evidence with actual completed run results, GitHub revisions, executed tests and missing acceptance. `in_progress` is not a failure; do not duplicate its active write.
2. **Produce a new corrective brief.** Specify the missing capability/evidence, the exact source/test SHA, actionable fix or negative/positive test, acceptance condition, dependencies, permitted tools and output ownership. Preserve immutable mission and safety constraints.
3. **Select the fastest legitimate recipient.** Consider the original worker, another compatible existing worker, or a completed pre-provisioned **one-time** task eligible for new instructions. Compare their actual allowed next dispatch opportunities and output write scopes; transfer exclusive ownership explicitly when necessary. Give independent repair/test fragments to different workers in parallel when helpful.
4. **Dispatch, don't just report.** Update the exact allowlisted task's **full prompt** and one-time DTSTART/`is_enabled` (or compatible existing recurring task's next permissible phase) as appropriate; use a supported future offset when available, and read back the persisted ID, prompt, schedule and enable state. Don't treat a successful update as an executed corrective job.
5. **Verify the new instance.** Confirm its distinct run ID, actual start and completion, delivered instructions, tested artifacts, and resolution or downstream consumption. If dispatch is rejected, record the *actual* service constraint and choose the best other permitted route, not an invented hourly ceiling.

Authorization, active-task caps, model allowances, approval, unrelated paused tasks, per-task **recurring** frequency rules, privacy and one-writer safeguards still apply. A previously completed task may be reassigned, but new work does not grant unrestricted or guaranteed immediate execution.

## Mathematical objective: maximize shift-manager work runway

Let one **relevant work wave** have required producer/checker/integrator outputs with actual completion timestamps, and let `T_next` be the earliest *next* major worker-cohort start. The manager should start after enough of those outputs have arrived to act intelligently, but as **early as safely possible thereafter**. Delaying its start consumes its available analysis/replanning time.

Use a small deterministic phase search once useful data exists. Definitions for a given candidate hourly phase `m ∈ {0,...,59}`:

- `R_q`: a conservative observed readiness time for **relevant** completed outputs (for example, empirical 80th–90th percentile of the latest critical completion within a comparable wave); with few samples, use the latest observed completion and mark it provisional.
- `J_m`: an observed upper-bound or high-quantile allowance for manager start delay/jitter and prompt-update propagation; do **not** claim the service honors exact times.
- `D`: the next major independent worker-cohort start. It is an opportunity for the manager's updated plans to be ready, **not** a stop command or a gate for those workers.
- `S(m)`: the prospective actual manager start with phase `m` in the relevant hourly cycle, adjusted by `J_m`.
- `B`: a modest readiness/update safety margin based on actual tool latency.

Evaluate:

```text
eligible(m)  = [ S(m) >= R_q + B ]                # enough relevant evidence exists
work_runway(m) = max(0, D - S(m) - B)              # available pre-next-wave manager time
m* = argmax_{m in 0..59, eligible(m)} work_runway(m)
```

The optimum **under these stated observations and assumptions** is normally the **earliest feasible manager phase immediately after required results are ready**, since every later minute shortens its runway. In a probabilistic variant, maximize `P(outputs ready at m) × E[work_runway(m)]` or impose a readiness-confidence threshold; do not pretend fixed clock phases yield guaranteed outputs. Estimate using actual run `scheduled_for`, `started_at`, `completed_at`, source receipts and service jitter, not the scheduled clock alone.

**Illustration, not a permanent recommendation:** Suppose the relevant last tests/integration finish around :54–:56 and the next main work wave is near :20 in the following hour. A manager starting shortly after :56 potentially receives substantially more usable preparation runway before :20 than one waiting until :08. The exact selected minute depends on measured jitter, how late relevant outputs arrive, and expected manager duration. Do **not** preserve :08 merely because it was inherited from a separate project's roster. Optimize **manager workspace/time**, not the speed at which workers receive permission to proceed. Workers never pause for a shift-manager check unless an actual required dependency or write lease is unresolved.

If no minute provides a high-confidence post-results, pre-next-wave window, choose the best *partial-evidence* phase and let the manager do useful work from whatever is available; explicitly record what remains unfinished. Do not hold up other workers to manufacture an all-done moment. Once a higher-value time is justified, the manager can revise **its own permitted hourly phase** through a supported schedule update after validating owner instructions, runtime/service restrictions and live task identity.

## Acceptance and evidence

The mechanism is **not fully proven** by these instructions. Verify independently that a real HA-managed coordinator: (1) identifies a missing important deliverable, (2) issues a distinct corrective brief rather than replaying the old job, (3) reuses an authorized existing one-time task or suitable worker, (4) gets an earlier **actual** follow-up when permitted and confirms the service-accepted execution rather than inferring it from a saved prompt, (5) records corrected artifact/test acceptance, and (6) chooses a manager phase because it maximizes the observed work runway rather than because of an inherited fixed time. A bounded test may investigate whether a newly corrected *one-time* assignment can execute within an hour of the preceding one; its success is not assumed until the run finishes.

No automatic scheduling integration or provider permission is granted by this document. Do not modify any private RE-Wizard repo or its active automations while implementing this HA-only policy. Preserve the existing independent reviewer and release checks.
