# Chat Mode scheduling recipes and safe task updates

**CHECKS PENDING:** Supplementary field manual. Applies only to owner-authorized ChatGPT Chat Mode tasks; does not grant tool permissions or indicate that GitHub files are automatically read. See [SKILL.md](../SKILL.md) and [CONDUCTOR.md](../../../dev/continuous_execution/CONDUCTOR.md).

## RRULE / VEVENT quick reference

The saved schedule is iCalendar (RFC 5545), not JSON. An automation tool serializes this text as a JSON string. Use UTC DTSTART with Z when possible; check timezone and DST for local schedules.

| Field | Meaning |
| --- | --- |
| DTSTART:20261104T140000Z | First occurrence at 14:00 UTC on Nov 4, 2026 |
| RRULE:FREQ=HOURLY | Repeat hourly without a specified end |
| RRULE:FREQ=HOURLY;COUNT=2 | **Two total** occurrences, including DTSTART |
| RRULE:FREQ=HOURLY;INTERVAL=2;COUNT=3 | Three total occurrences separated by two hours |
| RRULE:FREQ=DAILY | Once a day |
| RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR | Monday, Wednesday, Friday |
| RRULE:FREQ=HOURLY;UNTIL=20261105T140000Z | Until an inclusive UTC end boundary |
| BYHOUR / BYMINUTE / BYSECOND | Clock-component selectors in compatible rules |
| TIMING_MODE | Tool argument, not an RRULE field: exact_schedule, flexible_schedule, condition_watch |

Example exact 2-hour cadence, three occurrences:

    BEGIN:VEVENT
    DTSTART:20261104T140000Z
    RRULE:FREQ=HOURLY;INTERVAL=2;COUNT=3
    END:VEVENT

Example one-time:

    BEGIN:VEVENT
    DTSTART:20261104T140000Z
    END:VEVENT

## Updating an existing authorized task

1. Inspect the Automations registry. Match exactly one unique test/project key, known task ID, task ownership and old saved prompt marker. Confirm user-authorized scope and current paused/exhausted status.
2. Copy the **entire** immutable header plus updated mutable role and next milestone; never replace a safe full prompt with a fragment that deletes authorization and objective boundaries.
3. Call the supported update with jawbone_id and only fields intended to change (prompt, schedule and optionally is_enabled). To move next execution, update DTSTART; next_run_time is a **read-only** output field.
4. Reread that exact ID. Verify the complete saved prompt, schedule, enabled state and actual returned tool success. Do not mistake success of saving for success of executing.
5. On the later occurrence, compare last_run.id, scheduled_for, started_at, completed_at, recorded_status and latest_result.run_id. in_progress is not completed. One-time completed tasks may automatically disable.
6. A re-enable action, if allowed, may require a valid **future** schedule. Distinguish prior deliberate owner pause from test-owned pause or natural completion. Never restart unrelated/user-paused tasks automatically.

Pseudo-call:

    update({
      jawbone_id: '<exact verified ID>',
      prompt: '<full immutable header + adapted milestone>',
      schedule: 'BEGIN:VEVENT\nDTSTART:20261104T140000Z\nRRULE:FREQ=HOURLY;COUNT=2\nEND:VEVENT',
      is_enabled: true  // only when explicitly authorized
    })

Creation of one/many new tasks from a scheduled Chat Mode execution was blocked in tests. A newly scheduled one-time task from an authorized **interactive** chat is a different tested capability. Do not use multiple copies to evade the minimum hourly recurrence.

## Reusable one-time task: actual demonstrated "necromancy"

**Completed evidence, Nov 4:** One test-owned one-time task completed
its original assignment and was then updated and re-enabled **twice**
with distinct instructions. Both revived executions completed with
new run IDs under the **same original automation ID**; the saved
VEVENT remained single-use without an `RRULE`. This establishes
repeated reuse of a slot, **not** unlimited executions, arbitrary
sub-hour restart or a new conversation per revival.

A legitimate **corrective task instance** can reuse such a completed
one-time slot instead of creating a fresh automation object:

1. Identify exactly one approved and **completed**, presently disabled
   one-time automation; verify real completed `last_run`, its matching
   `latest_result.run_id`, the original assignment, and no `RRULE`.
   Never repurpose a user-paused or unrelated automation.
2. Construct a **new corrective assignment** with precise missing
   deliverable, committed source/test SHA, executable diagnosis/fix,
   acceptance criterion, dependency and authorized writer scope.
   Carry forward the complete immutable owner/safety header.
3. Request the **earliest supported future single-event DTSTART**,
   using one update call with the exact `jawbone_id`, new full
   `prompt`, single future VEVENT/`dtstart_offset_json`, and
   `is_enabled=true`. Do **not** infer a mandatory 60-minute gap
   from the minimum hourly recurrence for repeating `RRULE` tasks.
   The actual lower bound for a new one-time assignment is **untested**:
   if the service rejects an early candidate, obey the returned
   restriction and choose another authorized eligible worker/slot.
   Earlier bounded experiments used a 20-minute offset as a
   **test choice**, not as a product requirement or proven minimum.
4. Re-peek the complete saved task ID, prompt, one-time event,
   enabled status and previous run ID; a persisted update is
   **not** evidence of new execution.
5. After the scheduled execution, verify a **different** run ID,
   `started_at`, `completed_at`, `recorded_status=completed`,
   the exact corrective prompt marker, committed artifacts/tests,
   and the receiving consumer's actual use of the work. Only
   declare the slot eligible for another reactivation once the
   service has finished and disabled it again.

The new task's purpose does not create an unrestricted tool quota.
The demonstrated product also enforced an active-task limit of
**15 for the tested account at the time**; this is not a universal
plan-specific number. Do not claim infinitely many simultaneous
tasks, arbitrary recurrence bypass, approval bypass, or unlimited
model runtime. Unlike a recurring `RRULE`, a new one-off task
is governed by its actually accepted single-event update.

## Shift-manager phase with maximum useful runway

The manager's objective is **maximum time available to do its own
work after relevant preceding results arrive**, not minimum latency
for every worker to get managerial approval.

For each hourly wave:
- Identify the *relevant* last producer/test/integrator completion
  using actual timestamps, with a conservative jitter/readiness
  allowance `R`. Don't wait for unrelated late reports.
- Identify the next major independent worker wave start `D`.
  Workers should **not** wait for manager permission.
- Evaluate hourly manager minute phases `m=0..59`. Keep only
  candidates whose expected start `S(m)` is after `R`.
  Compute `runway(m) = max(0, D - S(m) - update_margin)` and
  choose `argmax runway(m)`. Ordinarily this is the **earliest
  feasible phase after `R`**, because waiting later wastes
  manager time before the next wave.
- If dispatch is unpredictable, use a measured high-confidence
  completion quantile or probability-of-readiness-weighted runway
  instead of assuming an exact wall-clock optimum.
- Treat `D` as a planning window, **not** a stop command; the
  manager can continue within its actual service invocation
  while other workers proceed independently.

See [SHIFT_MANAGER.md](../../../dev/continuous_execution/SHIFT_MANAGER.md)
for the full HA-only mathematical model and safety boundaries.

## Durable task prompt contract

Every pre-provisioned task's saved prompt should include, at a minimum:

- IMMUTABLE: project key, task key and exact verified ID; mode/provider boundaries; permanent objective, explicit final acceptance and stop conditions; allowed repository/ref/source mediator; output ownership/writer lease; approval, privacy, model/usage and review rules; requirement to re-read available authorized instructions and minimal checkpoint each turn.
- MUTABLE: current role, meaningful next milestone, changed input/artifact hashes, executable targeted test, acceptance evidence, blocker and next action. Preserve immutable lines when conductor or the task updates its prompt.
- EVIDENCE: planned versus started versus completed versus independent acceptance; record exact run ID and timestamps, don't claim separate independent chat context from a different task ID.

Pre-provision a nominal five-role project workforce only if authorized and useful (conductor, two substantive workers, verifier, integrator); extend toward ten only when plan capacity and nonconflicting work warrant. Shared overall goals and safeguards are fine; actual roles must be genuinely complementary.

## Project handoffs

Read only projects/<slug>/README.md, state/current.json, state/handoff.md, state/automations.json and a few relevant evidence links. Do not auto-load entire histories or RE-Wizard textbook; obey its authorized mediator. Store session-specific conversation references privately only where operationally useful, not in public git.

Codex context-left metrics do not imply Chat Mode has that variable. A GitHub AGENTS.md or skill edit does not magically update every scheduled prompt; explicitly retrieve/inject with a verified tool on the selected route. Standalone fresh-chat-per-run scheduling is distinct from arbitrary ordinary-chat creation or conversation-ID retargeting.

Scheduled Chat runs may consume plan allowances. A free conversation with a dot does not imply the delegated Chat execution is free.

**See [CHAT_MODE_FINDINGS.md](../../../dev/continuous_execution/CHAT_MODE_FINDINGS.md) for completed results and remaining bounded tests.**
