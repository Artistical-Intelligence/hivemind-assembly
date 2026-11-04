# RE-Wizard BinaryWorkbench — live Chat Mode orchestration case study

**CHECKS PENDING.** This is a scheduling/runtime **observation** of a real, owner-authorized development project in a separate **private** repository, not its source code, a test of archived games, a code-quality verdict, or qualified independent acceptance. The private project's contents, private branch names, task IDs, account-specific chat references, and protected evidence must **not** be copied into this public HA repository. Only summarize permitted general behavior; the authorized workers maintain their exact private artifacts and identities in their own restricted state.

## Why this case is useful

Unlike the isolated November 3–4 automation probes, this is ongoing substantive work to improve an automated, non-AI decompilation/recompilation program. The owner explicitly requested that HA's orchestration methodology be informed by whether **multiple workers operate concurrently and whether their verified outputs flow to later waves**. HA itself targets ChatGPT and Claude, but these Chat Mode scheduling experiments are **exclusive to ChatGPT**, not evidence that Claude, Work or Codex have the same capabilities.

### Workforce and intended interleaving

The private project has **five explicitly pre-provisioned Chat Mode scheduled roles**: compiler-metadata/identification worker, pipeline/recompilation reliability worker, provisional verifier, integrator, and conductor. These are distinct work responsibilities, not five model-qualified independent conversations. The conductor is the sole automation-assignment and timing editor; workers own nonoverlapping branches/output paths; acceptance and final integration remain separate. No game tests or untrusted compiler execution are authorized. Each worker uses a shared durable final goal, a role-specific current milestone, and an external project checkpoint.

The target pattern combines both:

- **Parallel:** two technical workers can make different useful changes at once; verification may examine prior completed output while unrelated implementation continues; the integrator need not hold unrelated work.
- **Inherited/serial waves:** source discoveries, a compiler manifest result, a failed synthetic test, a verifier finding or integration conflict can become the **next scoped assignment** for the same worker or a pre-existing colleague. Use exact artifact revision/commit lineage, not an assumed shared chat transcript.
- **Adaptive control:** conductor reviews actual work and changes existing roles' prompts, DTSTART/RRULE, enabled status and assignments **when permitted**. Staggered planned start times do not prove actual overlap. Multiple run IDs may share a chat ref, so a verifier's separate task ID is not automatically qualified independent review.

## Initial observation — November 4, 2026

The actual Automations registry contained five **enabled** RE-Wizard project tasks (conductor, two workers, verifier, integrator) with individualized hourly, two-hour and three-hour recurrence settings. At the time of this first observation **none had a recorded completed run**, so actual parallel execution, GitHub modification by these scheduled workers, result inheritance, reviewer isolation and successful integrated testing were all **UNKNOWN**, not passed.

The project's own private coordination checkpoint described two independent work lanes, a provisional verifier, an integrator and a conductor responsible for revised scheduling. Compiler archive metadata had been inventoried, but its synthetic tests were explicitly marked **NOT RUN** at initial bootstrap. This is a statement about the private project's checkpoint, not fresh program validation. Do not disclose protected implementation content in HA's public evidence.

## Evidence collection rules

For each later bounded observation:

1. Inspect unique exact task identities and `recorded_status`, `scheduled_for`, `started_at`, `completed_at`, `latest_result.run_id`, `chat_ref`, and any current prompt/schedule changes. A null `next_run_time` is not proof that an enabled recurrence cannot run.
2. Verify any claimed GitHub work against actual private repository branch/PR metadata **with authorized read tools**. Never disclose private source text, filenames outside already approved public references, account IDs, secrets, protected inputs, or full artifacts here. Never write to the active private project or take over its conductor.
3. To claim **actual concurrent execution**, find at least two overlapping start/finish intervals for different tasks, and note whether tools/model sessions and writers were genuinely separate; merely staggered planned hours do not prove it.
4. To claim **inheritance**, find a completed producing wave with an exact committed artifact SHA, a subsequent receiving task consuming that exact revision/finding, and its own completed result. Prompt updates alone prove reassignment, not successful consumption of results.
5. Classify verifier findings as **provisional** unless independently qualified context/model and required review boundaries are verified; a separate task ID, separate branch or even a different chat ID by itself is insufficient.
6. Keep findings concise and evidence-only. No performance ledger or duplicate full-run transcripts. On each material new test result, update the [Chat Mode findings](CHAT_MODE_FINDINGS.md), this case study, and, if a capability/limitation changes the reusable procedure, the [skill](../../skills/chatmode-scheduled-orchestration/SKILL.md) / [conductor policy](CONDUCTOR.md), preserving CHECKS PENDING and provider scope.

## Status

**Observation pending:** scheduled task execution and actual repo commits by the live team; overlap, handoff, independent review and end-to-end outcome remain to be checked from real completed records. A finite scheduled status/evidence-sync task is authorized to follow up without changing RE-Wizard work or team automations.

This document is public HA instruction evidence only. Authoritative project work and private identifiers remain in the project's own private repository.
