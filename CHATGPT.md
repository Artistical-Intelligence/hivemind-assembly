# ChatGPT Chat Mode execution instructions for Hivemind Assembly

Provider/surface scope: **ChatGPT in Chat Mode only**. Policy revision: 1.3 — 2026-11-03.

Read `AGENTS.md` first, then the [ChatGPT Chat Mode adaptive execution process](dev/continuous_execution/PROCESS.md). The owner adopted the ten steps below only for the ChatGPT **Chat Mode** workflow being tested in ordinary chats and scheduled chat continuations. Do not apply or inject this profile into **ChatGPT Work**, **Codex**, Claude prompts, Claude coordinator/worker briefs, or any other provider/surface instructions. Evidence from Chat Mode does not establish capabilities in Work, Codex, Claude, or another surface/model configuration.

Existing shared repository safety, saving, independent-review, privacy and source-access rules still apply to their existing audiences. This profile adds Chat Mode-specific operating instructions; it does not replace those shared rules or alter Work, Codex, or Claude behavior. A maintainer using another surface/provider may implement specifically assigned HA changes, but that does not make this execution profile their operating policy.

## Core adaptive execution and incremental progress

1. **Read, reassess, decide each wave:** reconcile current owner directions, repository state, outputs, verdicts, interruptions and real capabilities. Do not assume the authoring conversation is available.
2. **Define outcomes and evidence:** keep the long-horizon goal and distinguish useful incremental progress from independent acceptance and publication.
3. **Prioritize bottlenecks and cumulative value:** unlock completion without selecting only small/easy wins or excluding valuable foundational work.
4. **Verify capabilities:** check actual executor/reviewer/model/context and artifact-return support. Reuse unchanged capability evidence; never invent it or transfer findings between surfaces/providers.
5. **Manage dependencies, not arbitrary backlog caps:** continue useful, reviewable, nonduplicative and resumable work despite pending reviews. Defer only affected paths for concrete dependencies, invalidated premises, conflicts, resource/access constraints, owner stops or lack of useful work. Do not impose a fixed draft cap.
6. **Preserve large coherent tasks:** a chunk may span many waves. Maintain its goal and exact resume point; split only when practical constraints justify it. Checkpoints are recovery points, not stop commands or one-unit-per-wave limits.
7. **Reduce overhead:** use deterministic scripts, safe batched reads, pinned inputs and scoped reuse without reducing required coverage or independent scrutiny.
8. **Test explicit hypotheses:** separate automation experiments from project validation. Distinguish live results, isolated tests, simulations, unattempted work and blockers.
9. **Recover through durable handoffs:** promptly save complete snapshots, verify remote persistence, reconcile uncertain writes and preserve writer ownership.
10. **Compare, learn, replan:** assess results at milestones, record concise rationale and next decision triggers, and change ineffective methods without forcing novelty.

A wave is a decision/execution opportunity, not a deadline for the whole assignment or a synchronization barrier. Do not stop merely because one milestone was saved, reviews are pending, or a large task will not finish in one turn. Continue valuable work within real budgets, permissions, dependencies and owner deadlines. Never trade away quality gates or claim partial work is accepted. Do not add a performance ledger.

Scheduled ChatGPT **Chat Mode** executions may occur in another chat. Recover current authorized task state and material owner corrections from durable project/GitHub records; never assume the scheduling conversation or full author context is present. A different chat/task ID alone does not establish fresh context or reviewer independence.

## Adaptive task chains are not preset loops

For ChatGPT **Chat Mode**, an owner-authorized large objective may progress through an **open-ended, evidence-driven chain** of distinct AI decisions and task executions. The logical chain ends when the objective reaches its required acceptance, an explicit owner stop/deadline, or a genuine unsupported/resource/authorization blocker; it does **not** end at an arbitrary count of tasks, handoffs, waves, or saved chunks. Each link must read the latest durable state and relevant fresh results (including qualified AI reviewer verdicts where available), evaluate what remains necessary, and decide whether any new useful next task is warranted. A successor may differ in method, size, timing, role or dependency. Do not pre-create a fixed script of tasks or mistake a recurring schedule that repeats the same plan for an adaptive chain. A chain is not a loop.

A task may arrange a later *ad hoc one-time* successor only when the actual scheduler and authorization rules permit it, using a grounded next assignment, pinned inputs, explicit ownership/deduplication, and safe recovery. Do not assume that a five-minute delay, recursive task creation, or fresh reviewer context is supported; measure those capabilities separately. Follow the provider's scheduling and usage restrictions. No task creation solely to remain active or to work around recurrence limits, no uncontrolled spawning, and no premature claim that a scheduled child executed. Experiments can intentionally limit chain length for safety; such a test limit **must not** become a production WIP, chunk-size or total-chain cap.

AI-only coordination must not depend on the owner opening chats, running commands, copying reports or recruiting reviewers. Respect mandatory approval and stop gates. Revise this Chat Mode profile as the owner clarifies goals and verified findings accumulate.

## Harness routing and evidence boundary

When implementing or editing HA's brief construction, select this profile only for an explicitly configured **ChatGPT Chat Mode** execution. Do not select it merely because the provider is OpenAI or the product is ChatGPT. In particular:

- **Do not inject it into ChatGPT Work.**
- **Do not inject it into Codex or Codex tasks.**
- **Do not inject it into Claude.**
- Do not append it to a common all-provider/all-surface instruction bundle or use it as an unknown-surface default.
- Route it by an explicit ChatGPT + Chat Mode surface/mode distinction, preserving the configured model, effort and allowance.

Work, Codex and Claude retain their own instructions, model assignments, authorization and runtime behavior. Extending this methodology to any of those surfaces requires separate owner authorization and surface-specific validation; no such extension is approved by this file.

The profile is an operating requirement, not a claim that untested runtime mechanisms exist. Some Chat Mode retrieval, scheduling and handoff behaviors have been demonstrated; independent delegation, lifecycle, cancellation and other proposed behaviors retain their individual evidence states. Static instruction tests cannot establish live behavior, universal ChatGPT support, Work/Codex support, or Claude acceptance.

**CHECKS PENDING:** Independent review of these instructions, their Chat Mode-only boundary and associated static checks remains required. No runtime implementation, release, scheduler extension or new permission is approved here.
