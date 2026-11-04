# Current HA handoff

**CHECKS PENDING / not independent acceptance.** This is a compact checkpoint for the next authorized maintenance session, not instructions to start production scheduled agents.

## What changed

- Owner chose a *pre-provisioned* default five-role Chat Mode conductor/workforce approach, adaptable toward ten only when real work, plan capacity, permission and context independence warrant it.
- Added the Chat Mode scheduling manual under `skills/chatmode-scheduled-orchestration/SKILL.md`, quick recipes, and conductor/evidence documentation. Root instructions, ChatGPT-specific process and the route-specific native guidance were updated; preserve all non-Chat Mode providers' policies.
- A Chat Mode scheduled execution was **not permitted** to create a new automation. However, completed tests verified self-modification of instructions and schedule, self-pause, changing an existing other task, and a later task receiving updated instructions. Distinct run IDs shared a conversation ref, so that is **not** qualified independent review.
- Additional bounded real-scheduler tests are scheduled to observe multiple consecutive two-hour occurrences, controlled reactivation of expired or test-self-paused automations, and a GitHub write to a throwaway branch. Do not claim those results until their exact run records are complete.

## Exact next action

A separate qualified assistant session should read the changed source files and relevant original instructions, compare syntax and safety, run the focused Chat Mode routing and prompt tests in a complete checkout, reconcile review markers and document reproducible results. Do not mark accepted or publish without a qualified independent reviewer and actual owner-authorized HA native runtime validation.

## Guardrails

No provider/model/usage substitution, no API fallbacks, no automatic reactivation of user-paused tasks, no unrelated repository edits or spawned schedules, no RE-Wizard textbook bypass. GitHub and ChatGPT chat context are different: instructions only affect a scheduled task when received through the actual saved prompt or verified authorized retrieval. Handoff is intentionally short; deeper evidence is linked in the [findings](../../../dev/continuous_execution/CHAT_MODE_FINDINGS.md).
