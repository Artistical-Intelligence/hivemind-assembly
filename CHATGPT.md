# ChatGPT execution instructions for Hivemind Assembly

Provider scope: **ChatGPT only**. Policy revision: 1.1 — 2026-11-03.

Read `AGENTS.md` first, then the [ChatGPT adaptive execution process](dev/continuous_execution/PROCESS.md). The owner adopted the ten steps below for the ChatGPT workflow being tested. Do not apply or inject this profile into Claude prompts, Claude coordinator/worker briefs, or another provider's instructions. ChatGPT observations do not establish Claude capabilities. Do not generalize this profile automatically to every OpenAI surface or model either; preserve the actually configured and supported execution environment.

Existing shared repository safety, saving, independent-review, privacy and source-access rules still apply to their existing audiences. This profile adds ChatGPT-specific operating instructions; it does not replace those rules or alter Claude's established process. A maintainer using any provider may work on a specifically assigned implementation, but that does not make this profile the maintainer's execution policy or authorize changing Claude behavior.

## Core adaptive execution and incremental progress

1. **Read, reassess, decide each wave:** reconcile current owner directions, repository state, outputs, verdicts, interruptions and real capabilities. Do not assume the authoring conversation is available.
2. **Define outcomes and evidence:** keep the long-horizon goal and distinguish useful incremental progress from independent acceptance and publication.
3. **Prioritize bottlenecks and cumulative value:** unlock completion without selecting only small/easy wins or excluding valuable foundational work.
4. **Verify capabilities:** check actual executor/reviewer/model/context and artifact-return support. Reuse unchanged capability evidence; never invent it or transfer findings between providers.
5. **Manage dependencies, not arbitrary backlog caps:** continue useful, reviewable, nonduplicative and resumable work despite pending reviews. Defer only affected paths for concrete dependencies, invalidated premises, conflicts, resource/access constraints, owner stops or lack of useful work. Do not impose a fixed draft cap.
6. **Preserve large coherent tasks:** a chunk may span many waves. Maintain its goal and exact resume point; split only when practical constraints justify it. Checkpoints are recovery points, not stop commands or one-unit-per-wave limits.
7. **Reduce overhead:** use deterministic scripts, safe batched reads, pinned inputs and scoped reuse without reducing required coverage or independent scrutiny.
8. **Test explicit hypotheses:** separate automation experiments from project validation. Distinguish live results, isolated tests, simulations, unattempted work and blockers.
9. **Recover through durable handoffs:** promptly save complete snapshots, verify remote persistence, reconcile uncertain writes and preserve writer ownership.
10. **Compare, learn, replan:** assess results at milestones, record concise rationale and next decision triggers, and change ineffective methods without forcing novelty.

A wave is a decision/execution opportunity, not a deadline for the whole assignment or a synchronization barrier. Do not stop merely because one milestone was saved, reviews are pending, or a large task will not finish in one turn. Continue valuable work within real budgets, permissions, dependencies and owner deadlines. Never trade away quality gates or claim partial work is accepted. Do not add a performance ledger.

Scheduled ChatGPT executions may occur in another chat. Recover current authorized task state and material owner corrections from durable project/GitHub records; never assume the scheduling conversation or full author context is present. A different chat/task ID alone does not establish fresh context or reviewer independence.

AI-only coordination must not depend on the owner opening chats, running commands, copying reports or recruiting reviewers. Respect mandatory approval and stop gates. Revise this ChatGPT profile as the owner clarifies goals and verified findings accumulate.

## Harness routing and evidence boundary

When implementing or editing HA's brief construction, select this profile only for explicitly configured ChatGPT execution. Do not append it to a common all-provider instruction bundle, use it as the unknown-provider default, or route it by role name alone. Claude's existing profile, model assignments, authorization and behavior must remain unchanged. Extending this methodology to Claude requires a separate owner authorization and provider-specific validation; no such extension is approved by this file.

The profile is an operating requirement, not a claim that untested runtime mechanisms exist. Some ChatGPT retrieval, scheduling and handoff behaviors have been demonstrated; independent delegation, lifecycle, cancellation and other proposed behaviors retain their individual evidence states. Static instruction tests cannot establish live behavior, universal ChatGPT support or any Claude acceptance.

**CHECKS PENDING:** Independent review of these instructions, their provider boundary and associated static checks remains required. No runtime implementation, release, scheduler extension or new permission is approved here.
