# HA Workplace — org chart, open positions and staffing handoffs

**Permanent owner policy, November 5, 2026.** **ChatGPT Chat Mode scheduling only.** This document applies to HA's owner-authorized native scheduled engineering team and its relationship with the owner-level **Workplace**. It does not change Work/Codex, Claude, paid API, release or source-permission policies.

## Management: one District Manager, no separate Shift Manager

The owner consolidated **all former Shift Manager responsibilities into the District Manager position** shared across authorized project workstreams. The District Manager is the original existing RE-Wizard conductor, **not a newly created task**. The District Manager performs the exact former HA Shift Manager responsibilities (auditing all HA employees' actual receipts, identifying and assigning corrective tasks, monitoring HA owner stops, independent verification, integration, useful temporary capacity and milestone delivery) **and** continually reviews other owner-authorized project openings to transfer workers safely after a real job is completed.

HA does **not** retain a parallel managerial position. Its former HA Shift Manager scheduled seat may be **reclassified to an HA engineering opening** only after its prior managerial duties and preserved records are explicitly handed over and the same task ID has been safely updated by owner authorization, with exact-ID readback. The HA workforce keeps its existing hourly cadence. No additional recurring task is necessary for the District Manager role.

**Security:** HA worker agents are never authorized to access or modify private RE-Wizard repo sources or task records solely because the District Manager oversees both. Private RE-Wizard task IDs, personal conversation IDs, claims, passwords, schedules, or source evidence must not appear in this public HA repository. The District Manager may use only separately owner-authorized project management metadata and task actions for cross-project hiring. HA production workers keep HA-only scopes; even transferred workers require explicitly verified new project access. No Work/Codex/Claude/API substitution or consent bypass.

## Permanent registries

- `dev/continuous_execution/workplace/org_chart.json` is the complete **desired HA positions** list, filled and unfilled. It is **not** just a task inventory.
- `dev/continuous_execution/workplace/job_openings.json` is a matching list of **currently unfilled positions** and what evidence/skills/resources their filling requires.
- `dev/continuous_execution/workplace/STAFFING_STATUS.md` records last verified reconciliation and outstanding support blockers, without private automation IDs.
- The private RE-Wizard orchestration branch retains a separate master Workplace index and the charts/openings for the owner's other workstreams. These are *not* copied into HA.
- These files may be updated by the specially owner-authorized District Manager to maintain **staffing records**, but are not HA production source-write grants. All pre-existing worker implementation scopes remain unaffected.

A recurring employee can fill one permanent position at a time. A completed one-time temp assigned to cover a role does **not** close the permanent opening unless an actual, owner-authorized staffing promotion occurs. A foreground research session does not count as a verified permanent scheduled worker. `staffing_status` is tracked separately from the **quality/acceptance state** of code and tests.

## Mandatory District hiring cycle

Every actual hourly District Manager run must reconcile HA's role chart and open positions with the exact allowed task registry (not a truncated bulk listing), real worker run results and current source/CI/approval claims. It must examine every HA employee's real output **and** find suitable ready jobs for employees completing their commitments. The former Shift Manager tasks remain mandatory, with no short-run or status-only exception.

For each vacancy: determine priority, readiness and nonconflicting file scope; check whether an eligible permanent worker has truly completed its prior deliverable or has a named safe handoff; examine reusable released/claimed one-time temp capacity for complementary **finite** coverage; decide whether the worker has actual Chat Mode, model and tool access; and prepare a durable district transfer receipt. Do not preempt a running employee or withdraw its claim without provenance. A scheduler `completed` run is not automatic engineering job completion.

On an authorized, supported transfer, prepare old-project handoff, issue new project work order and exclusive branch/path scope, update the **same existing task ID**, read back its settings, then wait for **actual new-run output** before closing the job opening or releasing the old position. Record real tool/usage/permission blockers; never silently borrow an owner-paused or protected worker. Observe host limit (last reported 15 active) and hourly minimum; do not duplicate schedules to evade them.

The District Manager must keep original HA source-level acceptance conditions intact, including Linux and Windows GitHub Actions evidence, live native browser/provider transport validation, correct ACK/receipt lifecycle, replay/authorization safeguards, and independent review. A fixture or passing isolated CI is not live provider acceptance. Maintain meaningful material milestone reporting while avoiding repetitive status notes.

**Authority priority:** This later owner-adopted Workplace policy supersedes references to a separate HA Shift Manager role in `SHIFT_MANAGER.md` and `HA_NATIVE_SHIFT_TEAM_20261105.md`. Those files remain sources for each *technical work lane*, tests and incident history. Owner pauses, project permissions and qualified review requirements retain full force.

**Evidence status:** Workplace policy and vacancy records alone are not proof that an eligible employee has been moved, that a separate review has passed or that the target project works end-to-end.
