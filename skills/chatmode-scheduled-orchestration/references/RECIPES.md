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
