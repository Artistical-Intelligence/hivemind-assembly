# Current HA handoff

**CHECKS PENDING / not independent acceptance.** This is a compact checkpoint for the next authorized maintenance session, not instructions to start production scheduled agents.

## What changed

- Owner chose a *pre-provisioned* default five-role Chat Mode conductor/workforce approach, adaptable toward ten only when real work, plan capacity, permission and context independence warrant it.
- Added the Chat Mode scheduling manual under `skills/chatmode-scheduled-orchestration/SKILL.md`, quick recipes, and conductor/evidence documentation. Root instructions, ChatGPT-specific process and the route-specific native guidance were updated; preserve all non-Chat Mode providers' policies.
- A Chat Mode scheduled execution was **not permitted** to create a new automation. However, completed tests verified self-modification of instructions and schedule, self-pause, changing an existing other task, and a later task receiving updated instructions. Distinct run IDs shared a conversation ref, so that is **not** qualified independent review.
- Final November 4 service experiments **verified** three completed consecutive two-hourly follow-ups; completed expired and previously self-paused task revival; two separate one-time same-ID resurrections; cross-conversation task-registry coordination; and scheduled GitHub write/readback with a separate auditor. The full evidence and remaining uncertainty are in `dev/continuous_execution/CHAT_MODE_SESSION_TEST_AUDIT_20261104.md`. Do not overwrite a now-production task merely because it once served as a test corpse.

## HA-only shift-manager correction, November 4

Owner explicitly prohibited changing the private RE-Wizard repository
or any of its live task automations from this HA design discussion.
**Only HA files were modified for the latest correction.**

An important unfinished shift produces a **distinct corrective
one-time task assignment**, not a replay of unchanged hourly work.
The existing same-ID one-off reactivation experiment passed twice,
but an arbitrary immediate/sub-hour corrective dispatch has NOT
been verified; the recurring RRULE hourly limit by itself does not
establish an automatic per-ID 60-minute cooldown for a different
ad hoc one-off. Request the earliest service-permitted future event
and check actual acceptance and completed run rather than assert
a capability or ban.

The HA shift manager should maximize its **own useful runway** after
relevant worker evidence is ready and before the next main work wave,
not make workers wait for managerial approval or optimize their
latency to receiving instructions. The new deterministic
`_app/hivemind_assembly/automation/shift_window.py` and
`tests/test_shift_window.py` implement/test an offline 60-phase
search under observed completion/jitter assumptions. A new
`dev/continuous_execution/SHIFT_MANAGER.md` defines the
formula, safe correction dispatch and unresolved live scheduler
integration. The code is not a native service schedule editor.

All changes are pushed with CHECKS PENDING. Next step:
independent source/instruction review, execute focused helper/routing
tests in CI, and do not claim live HA scheduling optimization or
sub-hour one-time reactivation without a bounded service run.
No owner-paused tasks, private source or live RE-Wizard orchestration
was altered in this HA correction.

## Final scheduled-Chat experiment evidence reconciliation

Read the [completed multi-session audit](../../../dev/continuous_execution/CHAT_MODE_SESSION_TEST_AUDIT_20261104.md) before accepting earlier "pending" claims. Verified service features do **not** imply that HA's browser interface received the prompt, that an independent reviewer was qualified, or that the new shift-window optimizer is deployed. The private real-work team demonstrated overlapping completed sessions and an inherited corrective handoff, but broader hosted integration remains failing and the work is neither integrated nor published.

HA's last full contract workflow at the prior head failed: Ubuntu logged **1,368 passed, 6 failed, 85 skipped** (Linux runtime/ABI regressions), and the browser-fixture job failed installing Playwright/Chromium; Windows contracts/package jobs passed. Investigate failures separately rather than representing the scheduling experiment as the cause or treating passing prompt assertions as live provider acceptance.

The latest corrected instructions remain **ChatGPT Chat Mode only**. The critical remaining native questions are transport/receipt, model/effort/context controls, true independent review, service acceptance of earlier-than-hourly *distinct one-time* corrections, and an actual connected shift-manager schedule optimized for **its own available work runway**. None was proved by the bounded service tests. No RE-Wizard project, file, or scheduled task is authorized for modification through this HA handoff.

## Exact next action

A separate qualified assistant session should read the changed source files and relevant original instructions, compare syntax and safety, run the focused Chat Mode routing and prompt tests in a complete checkout, reconcile review markers and document reproducible results. Do not mark accepted or publish without a qualified independent reviewer and actual owner-authorized HA native runtime validation.

## Guardrails

No provider/model/usage substitution, no API fallbacks, no automatic reactivation of user-paused tasks, no unrelated repository edits or spawned schedules, no RE-Wizard textbook bypass. GitHub and ChatGPT chat context are different: instructions only affect a scheduled task when received through the actual saved prompt or verified authorized retrieval. Handoff is intentionally short; deeper evidence is linked in the [findings](../../../dev/continuous_execution/CHAT_MODE_FINDINGS.md).
