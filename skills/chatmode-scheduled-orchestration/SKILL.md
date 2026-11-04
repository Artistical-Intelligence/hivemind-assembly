---
name: chatmode-scheduled-orchestration
description: Draft operations manual for bounded ChatGPT Chat Mode scheduled-task coordination, task updates, iCalendar scheduling, registry verification, and GitHub handoffs. No API or Work/Codex dependency.
---

# Chat Mode scheduled orchestration — experimental skill

**Status:** Working draft as of 2026-11-04. This is a reference file, **not** an installed ChatGPT skill and **not** a grant of permissions. Validate the actual available tools on every execution. Do not silently substitute another mode, provider, model, service, or billing path.


## 2026-11-04 owner-approved HA application and bootstrap

**CHECKS PENDING:** This manual is committed as owner-authorized guidance, not independently source-reviewed, a ChatGPT-installed skill, a working HA scheduler feature, a guarantee that GitHub files are auto-read, or permission to start autonomous agents. See [CONDUCTOR.md](../../dev/continuous_execution/CONDUCTOR.md) for the HA-specific integration plan.

- **Pre-provision, do not self-spawn:** Maintain a roster of up to ten permitted project-scoped existing automations, starting with **five** when quota and real work justify it: one conductor, two substantive workers, one verifier and one integration/acceptance coordinator. This is a proposed *pool size*, not automatic startup, five guaranteed simultaneous agents or five independently qualified contexts. Scale down idle roles and reassign by updating their saved prompts; do not create child schedules from scheduled Chat Mode or bypass hourly task cadence. The scheduler's active-task cap is a separate constraint.
- **Common foundation plus distinct assignments:** Agents may share most policies and the same final outcome. Each active role must nevertheless have a real complementary responsibility, output ownership, handoff contract and stopping condition. A staggered schedule may coordinate independent work; not merely replicate one hourly task to evade a frequency limit.
- **Durable objective, changing milestones:** Preserve in a checkpoint the terminal acceptance condition (for example passing a final product capability test). Every authorized run reads its own current saved instructions and current authoritative state, selects the next evidence-driven milestone, executes a useful step, records results and updates pre-existing task responsibilities/schedules as necessary. Never overwrite the immutable mission and safety header with a transient task.
- **Instructions do not automatically materialize:** A GitHub `AGENTS.md`, this skill, or a new repository commit is **not automatically reread by arbitrary native ChatGPT scheduled executions**. Include a compact invariant header in **each saved automation prompt**, with an explicit instruction to read exact approved paths/revision on every run *when the GitHub or local retrieval tool is available*. In HA's own app, the Chat Mode profile is included by the route-specific request construction only for explicit `provider=openai, mode=Chat`; verify actual delivery. After prompt rewrite, reread the registry and ensure the invariant header survived.
- **Reactivation boundary:** `is_enabled=true` exists on the update tool but a task previously disabled or completed must be verified by its exact task ID, owner, finish reason and fresh schedule. Never revive user-paused work by default. Bounded scheduled-run reactivation and sustained 2-hour intervals are subjects of new Nov 4 tests; mark pending until recorded completion.
- **Context discipline:** Codex's context-window metrics, if surfaced in a Codex tool, are not automatically available as Chat Mode environment variables. No cross-mode variable alias is demonstrated. Use meaningful checkpoint/rollover triggers and the documented standalone-per-run fresh-chat pattern when that *specific task surface* supports it. Preserve project permissions/source mediation and don't copy a whole textbook into a handoff.
- **GitHub state:** Use `projects/<slug>/state/` for strictly minimal current state, handoff and task mapping *when owner-approved*. Restrict direct GitHub reads to sources each role is permitted to access, and do not expose private conversation IDs or credentials in a public repo. Track service-assigned IDs only in an appropriately private state store if necessary to address tasks.
- **Status and accounting:** Open-ended `RRULE` does not mean a continuously live model. A task might auto-pause after inactivity or approval. Chat scheduled executions may consume normal plan allowance whether or not a dot initiated them. No confirmed free route exists by asking a dot to send an ordinary Chat task.

## Goal and scope

Continue useful project work across **separate scheduled Chat Mode executions**, using a retained top-level objective, narrowly scoped next milestones, versioned external evidence and checkpoint handoffs. A scheduled run is a finite model invocation, **not a persistent live agent process**. An automation can be reused; a run cannot be prolonged indefinitely by its schedule. Existing experiments demonstrate task-to-task **configuration updates** and retrieval of recorded results, not creation of child tasks or independent, unscheduled user messages.

## Evidence / permissions matrix

| Operation in scheduled Chat Mode | Evidence or limitation |
| --- | --- |
| Read Automations registry, task status and latest result | Tested; `peek` supports full registry or task ID. |
| Edit own saved instructions (`prompt`) | Tested: accepted, persisted, and used in a later execution. |
| Edit own `schedule` / reschedule next run | Tested: accepted, persisted, and follow-up executed at revised occurrence; timing not exact. |
| Change own `RRULE` interval | Tested: schedule accepted and one revised future occurrence executed. **Repeated 2-hour cadence was not tested** because `COUNT=1`. |
| Pause own schedule via `is_enabled=false` | Tested: accepted and persisted; no next run shown. |
| Change another existing task's saved instructions or schedule | Tested on exact-ID target with completed producer/target/observer runs. |
| Retrieve another task's completed result | Tested via producer/consumer/auditor and coordinator/target/observer. |
| Re-enable (`is_enabled=true`) a previously paused task | Update API exposes this field; not independently tested in the above experiment series. Only resume explicitly authorized tasks. |
| Create a new automation **from a scheduled Chat Mode run** | **Blocked by scheduled-run permission boundary** in prior tests; the model did not call the backend to test low-level rejection. Do not retry through alternate routes. |
| Create one or many child automations from scheduled runs | Same restriction. Do not use copies/descendants to evade cadence restrictions. |
| Insert a new user-role message in the same chat that triggers an independent interactive turn | Unproven; no suitable native tool identified in interactive tool listing. A bounded scheduled probe was created 2026-11-04, result requires recorded-run inspection. `notify_parent` is not equivalent. |
| Spawn an ordinary new interactive chat from a scheduled run | Not established. Do not claim that changing task IDs creates or retargets chats. |
| GitHub writes / plugin or MCP operations | Official documentation permits connected tools in scheduled tasks under permissions and possible approvals. A specific scheduled GitHub write was **not** established by these experiments. |

## Scheduling language

The saved `schedule` field is **iCalendar VEVENT / RFC 5545**, not JSON and not a database query. `RRULE` is a semicolon-separated recurrence rule. API tool arguments are JSON-shaped; *the `schedule` property inside them is an iCalendar text string*. Reference: https://www.rfc-editor.org/rfc/rfc5545 and https://learn.chatgpt.com/docs/automations.

### Common fields

| Field | Role | Example / caution |
| --- | --- | --- |
| `BEGIN:VEVENT` / `END:VEVENT` | Delimit a schedule. | Required by this tool. |
| `DTSTART` | Date and time of the first intended occurrence. | `DTSTART:20261104T140000Z` (UTC). |
| `RRULE` | Repeating rule. Omit for one-time execution. | `RRULE:FREQ=HOURLY` |
| `FREQ` | Rule frequency. | `HOURLY`, `DAILY`, `WEEKLY`, `MONTHLY`; platform may reject too-frequent values even if RFC permits them. |
| `INTERVAL` | Repeat every N units of `FREQ`. | `FREQ=HOURLY;INTERVAL=2` = every 2 hours. |
| `COUNT` | **Total number of occurrences of the current rule**, including `DTSTART`. | `COUNT=2` = 2 total occurrences; **yes, COUNT can be 2**. |
| `UNTIL` | Last permitted recurrence boundary (inclusive by RFC). | `UNTIL=20261105T140000Z`; don't combine with `COUNT`. |
| `BYHOUR` / `BYMINUTE` / `BYSECOND` | Select clock-time components. | E.g. for daily 09:30 use `BYHOUR=9;BYMINUTE=30`. |
| `BYDAY` | Weekdays for a compatible recurrence rule. | `MO,TU,WE,TH,FR`. |
| `BYMONTHDAY` | Day of the month. | `1`. |
| `TZID` | Time-zone identifier if supported by selected surface. | Prefer tool's `default_timezone` + unambiguous UTC `DTSTART` if applicable; examine daylight saving behavior. |

`RRULE` without `COUNT` or `UNTIL` is unbounded in RFC terms, but actual execution remains subject to plan limits, service availability, and permission. **In this ChatGPT automation interface the minimum recurrence is one hour.** A platform describing minute-level follow-up loops in another configuration does not authorize sub-hour values here. Scheduled starts may occur minutes early/late. Never treat `next_run_time:null` alone as proof of no future execution: check enabled status, saved schedule and run details.

### Copyable VEVENT examples

**One time:**

```text
BEGIN:VEVENT
DTSTART:20261104T140000Z
END:VEVENT
```

**Hourly until explicitly paused:**

```text
BEGIN:VEVENT
DTSTART:20261104T140000Z
RRULE:FREQ=HOURLY
END:VEVENT
```

**Exactly two hourly occurrences:**

```text
BEGIN:VEVENT
DTSTART:20261104T140000Z
RRULE:FREQ=HOURLY;COUNT=2
END:VEVENT
```

**Every two hours, 4 total occurrences:**

```text
BEGIN:VEVENT
DTSTART:20261104T140000Z
RRULE:FREQ=HOURLY;INTERVAL=2;COUNT=4
END:VEVENT
```

**Hourly through a UTC end time:**

```text
BEGIN:VEVENT
DTSTART:20261104T140000Z
RRULE:FREQ=HOURLY;UNTIL=20261105T140000Z
END:VEVENT
```

**Weekdays at 09:30:**

```text
BEGIN:VEVENT
DTSTART:20261104T093000
RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;BYHOUR=9;BYMINUTE=30
END:VEVENT
```

For local clock times across DST changes, resolve `TZID` and `default_timezone` consistently. The simple floating-local-time example requires verification in the intended UI/account. Avoid scheduling critical simultaneous writes based solely on these intended clock times.

### Supported automation tool model (exact field names)

```text
create(title, prompt, schedule, timing_mode, default_timezone?, dtstart_offset_json?)
update(jawbone_id, prompt?, title?, schedule?, dtstart_offset_json?, default_timezone?, is_enabled?)
peek(jawbone_id?)
list()  # use only when the user requests to display their full task list
run_now(jawbone_id)  # ONLY when the user requests an immediate run; never a self-wake loop
```

`timing_mode` is typically `exact_schedule`, `flexible_schedule`, or `condition_watch`; condition watches must be recurring. For a relative one-time delay, `dtstart_offset_json` (for example `{"minutes":20}`) may be used when permitted; that JSON is **not** the RRULE and does not alter recurrence limits. Omit `SUMMARY` and `DTEND` in schedule strings for this tool.

`next_run_time` is **read-only** in registry output, not an accepted direct update argument. Move the next run by writing a new `schedule`/`DTSTART`, then verify the eventual `scheduled_for`, `started_at`, `completed_at`. A task marked `in_progress` is **not** proof of completion.

### Safe prompt update recipe

1. `peek({})`; locate exactly one exact task key and its saved `id`. Confirm owner, original prompt marker, enabled state and schedule.
2. Confirm the intended target is explicitly authorized and has not already been updated. For cross-task mutation, designate **one writer only** to avoid collisions.
3. Compute the next bounded milestone from durable evidence. Preserve the permanent objective and non-negotiable guardrails; replace only permitted mutable instructions.
4. If scheduled-run tools and permission allow, call `update({jawbone_id: exact_id, prompt: full_replacement, schedule: full_ical})` once. If changing only one field, omit unrelated fields.
5. Re-peek by ID; compare **whole saved value**, schedule and enabled status. Record tool acceptance separately from persisted state and executed work.
6. On later runs, verify `last_run.recorded_status`, `scheduled_for`, `started_at`, `completed_at`, and `latest_result` matching `run_id`.
7. If successful, checkpoint the evidence, select the next meaningful milestone, and update the existing authorized task if needed. If objective met or blocked, pause the associated task. Never create descendants from scheduled runs.

## Adaptive progressive-work template

> Project: `<slug>`; permanent objective: `<measurable acceptance condition>`; current milestone: `<bounded action>`; permitted repository and branch: `<repo/ref>`; coordinator/worker IDs: `<exact IDs>`; operating mode: `Chat Mode`. At each execution: (1) re-read `projects/<slug>/state/current.json` and the latest recorded outcome, (2) verify this task ID and ownership, (3) choose the smallest useful work package advancing acceptance, (4) execute available tools subject to authorization, (5) run targeted checks, (6) commit/checkpoint only when authorized, (7) update the brief handoff log with exact commit, tested commands, outcomes and blockers, (8) adjust **existing** scheduled tasks' instructions/timing within their authorized scope, and (9) stop/pause when acceptance is met or a safety/permission limit is reached. Do not replace an external evidence check with a claim based solely on chat history.

Subtasks can be chosen adaptively, but **the permanent objective must survive every prompt rewrite**. Multiple executions collectively advance an acceptance target. A schedule is a wakeup mechanism, not proof of continuous work, infinite runtime, or independent reviewer qualification.

## Coordinator / conductor rules

- Maintain an **allowlist** mapping project role -> task key -> automation ID -> conversation ref -> allowed update fields. Never update a task simply because its title resembles an active role.
- Read task registry and completed results; do not confuse `last_run` from one run with another; match `run_id` and scheduled/completion timestamps.
- Coordinate **existing** tasks by updating their saved prompts, schedules or enabled status, when authorized. Cross-task mutation has been tested; creating a new child task from a scheduled run has **not** been permitted.
- If a task is paused, inspect whether it was paused by the user, expired after `COUNT`, blocked for approval, or stopped by the workflow. Do not automatically resume previously user-paused tasks. Re-enabling an exhausted rule may also require a future DTSTART and a valid new count.
- If a chat gets too large, checkpoint externally, reduce retained context, and request or use an approved fresh-chat workflow. No tested operation can silently create a new ordinary Chat chat and retarget the automation to it.
- Prefer short snapshots and targeted testing. Send to the next execution **only** active objectives, verified state, changed paths, blockers, and next checks; never include full textbooks when mediated retrieval should be used.
- Distinct responsibilities may share most of their foundation, but must not be replicated merely to defeat the minimum recurrence limit. The scheduling tool is limited to >= one hour per recurring task.

## GitHub project-state layout (proposal only; do not write without authorization)

```text
projects/
  <project-slug>/
    README.md                   # permanent purpose, acceptance criteria, allowed resources
    state/
      current.json              # compact machine-readable authoritative snapshot
      handoff.md                # human-readable latest handoff, <= ~2k words
      automations.json          # task key/id, chat_ref, role, schedule, permissions
    decisions.md                # only consequential durable decisions
    evidence/
      <milestone>.md            # exact test evidence; link to commit/check outputs
    archive/
      ...                       # obsolete prior states, not automatically loaded
```

**Example `state/current.json`:**

```json
{
  "schema_version": 1,
  "project": "example",
  "objective": "Deliver a tested outcome satisfying explicit acceptance criteria",
  "phase": "verification",
  "checkpoint_commit": "<40-char-commit-sha>",
  "last_verified_at": "2026-11-04T05:00:00Z",
  "current_milestone": "Verify targeted acceptance check",
  "last_evidence": ["evidence/targeted-check.md"],
  "blockers": [],
  "next_actions": ["Run the smallest missing test", "Record reproducible outcome"],
  "tasks": [{"key":"<exact-task-key>","automation_id":"<id>","conversation_id":"<read-only-ref>","allowed_update_fields":["prompt","schedule"]}],
  "checkpoint_status": "verified"
}
```

Minimize this file: preserve hard evidence and active decisions, not long transcripts or model reasoning. Avoid secrets and credentials. Use Git commit SHA and blob hash for provenance. For concurrent writers, prefer per-run append-only evidence or separate branches/PRs over simultaneous overwrites of `current.json`; reconcile changes explicitly. No connector write action is automatically approved.

### ID and chat mapping

- **Exact task key** in prompt: human-stable role identifier; can be found by registry search. Avoid duplicates.
- **`automation.id` / `jawbone_id`**: authoritative automation ID for update and peek. Treat as opaque, not user-editable.
- **`conversation_id` / `thread_id` / `chat_ref.id`**: service-assigned conversation identity. The available `update` operation **does not accept** a destination chat field. Two different tasks may have distinct run IDs but share a chat ref.
- **`last_run.id`**, **`latest_result.run_id`**: execution identities; compare before claiming you read the correct result.
- **`recorded_status`** vs **`latest_result`**: different metadata; validate completion and content independently.
- A **one-time** task becoming disabled after a completed run is expected, not a failure. It also cannot continue work unless an authorized schedule is prepared again.

## Context lifecycle and conversation rollover

No surfaced native Chat Mode operation establishes ability for a scheduled run to append a user-role message that starts a separate interactive turn, spawn a new ordinary interactive chat, or change an existing automation's `conversation_id`.

Supported alternative: in documented **standalone scheduled tasks**, each run starts a new chat. Those fresh chats must reconstruct only necessary context from a durable external handoff. Another alternative is to pre-create distinct chat-attached tasks in their intended conversations and have the conductor coordinate their existing IDs, subject to permissions. Neither is the same as autonomous spawn-on-demand by a scheduled Chat run.

There is no guaranteed public "percentage context remaining" signal in the surfaced Chat Mode tool interface. Proactively checkpoint at milestones; consider rollover if relevant early decisions become inaccessible, sources appear truncated, repeated context repair is needed, or summaries dominate useful context. Do not assume these heuristics measure the actual context-window token limit.

## Usage and approvals

Completed scheduled tasks in Chat **may consume plan usage allowance even when they produce no user-visible update**. Talking to a dot is documented not to count toward normal ChatGPT usage limits, but no authoritative guarantee says Chat tasks coordinated by a dot are free. Work/Codex tasks launched/managed by a dot count toward their respective allowances. Confirm permissions before writing external GitHub data or calling plugins/MCP; some actions require approval and can pause a run. Docs: https://help.openai.com/en/articles/10291617-scheduled-tasks-in-chatgpt , https://help.openai.com/en/articles/20001497-troubleshooting-plugins-and-apps-in-chatgpt , https://learn.chatgpt.com/docs/dots .

## Open questions / next bounded tests

1. Same-chat *user-role* message submission followed by an independent ordinary interactive turn (separate one-time probe created; inspect its actual result before classifying).
2. Whether a paused, **test-owned** automation can be successfully resumed and run at a new scheduled time by another scheduled Chat task, while leaving all other paused tasks untouched.
3. Scheduled Chat tool availability for repository and MCP reads; actual GitHub writes remain subject to permission and approval. Do not write to productive repos solely to satisfy a capability test.
4. Whether a pre-created task in a **different ChatGPT conversation** can be updated by a scheduled coordinator and execute with that distinct `chat_ref`. Existing tests shared one chat ref.

> **Boundary reminder:** The earlier blocked one-shot parent/child experiments apply to **creating new automations from scheduled runs**. They do **not** contradict the observed ability to update existing task prompts, schedules, or enabled state. Avoid claims of unlimited task spawning, guaranteed scheduling precision, or free delegated Chat processing.