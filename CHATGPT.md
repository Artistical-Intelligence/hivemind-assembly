# ChatGPT Chat Mode execution instructions for Hivemind Assembly

Provider/surface scope: **ChatGPT in Chat Mode only**. Policy revision: 1.4 — 2026-11-04.

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

In the tested **scheduled Chat Mode** execution environment, creating additional automations was prohibited. Therefore, prefer **pre-provisioning** an explicitly authorized pool of existing tasks and adapting them via permitted updates to saved prompts/schedules, rather than proposing scheduled child creation. Creation of successors remains conditional on a different, explicitly supported execution surface and authorization; do not attempt alternative routes to bypass this restriction. A short delay, a new task ID, a notification or a fresh reviewer context is not proof of child creation or distinct interactive chats. Follow all scheduling and usage restrictions; do not manufacture copies to evade them. Experiments can intentionally limit chain length for safety; such a test limit **must not** become a production WIP, chunk-size or total-chain cap.

AI-only coordination must not depend on the owner opening chats, running commands, copying reports or recruiting reviewers. Respect mandatory approval and stop gates. Revise this Chat Mode profile as the owner clarifies goals and verified findings accumulate.


## Retaskable pre-provisioned scheduled workforce (owner update, November 4)

See [HA conductor instructions](dev/continuous_execution/CONDUCTOR.md),
[observed Chat Mode evidence](dev/continuous_execution/CHAT_MODE_FINDINGS.md)
and [scheduling/automation SKILL.md](skills/chatmode-scheduled-orchestration/SKILL.md).
These are instructions and **CHECKS PENDING** design artifacts, not a released
scheduler extension or an approval to start autonomous HA workers.

- **Provision deliberately:** The owner's suggested default is **five
  existing project-owned automations**, expandable toward ten if useful,
  within plan/active-task limits: one conductor, two complementary workers,
  one verifier and one integrator. A team is not useful merely because all
  slots are active. No scheduled child creation, no frequency-limit
  circumvention, no automatic activation of unrelated or owner-paused tasks.
- **Parallelism is the core, not a relay:** Recruit multiple useful workers
  in advance, assign genuinely independent workstreams concurrently, and let
  them progress without awaiting the conductor or an unrelated review. The
  conductor dynamically changes each authorized task's current goal,
  `DTSTART`, recurrence interval, occurrence limit, and enabled state
  according to dependencies, actual evidence, and resource availability.
  A staggered start plan is optional and does not itself demonstrate
  simultaneously running models or independent chat contexts. Record and
  verify actual run overlap before claiming parallel execution. The
  worker/verifier/integrator labels are flexible responsibilities, **not a
  compulsory linear worker -> reviewer -> tester pipeline**. Retain sole-writer
  fences, required acceptance gates and the scheduler's real per-task limits.
- **Base assignments on the actual project:** The common 80% may consist of
  owner objective, rules and source boundaries; the remaining role-specific
  responsibilities must be meaningful and have separate output ownership.
  The conductor reads real project outcomes and assigns the next useful
  milestone, not an arbitrary fixed small task or repeating one-step script.
  Preserve the **permanent acceptance objective** while revising the next
  milestone, schedule and existing staff assignments as evidence changes.
- **Exact receipts matter:** Own-task prompt/schedule updates, self-pause,
  cross-task updates, target execution and completed-result retrieval have
  completed Chat Mode experiments. Those tests did **not** prove independent
  chats, detached live processes, independent acceptance or unlimited
  execution. A bounded scheduled run also found **no native operation** for posting a new user-role message in the same chat to trigger an independent ordinary interactive turn; it submitted no message. The earlier two-hour interval had one future occurrence;
  multiple later intervals, resumption of disabled test-owned tasks and a
  scheduled GitHub write remain pending until their bounded new runs finish.
- **Read instructions explicitly:** ChatGPT scheduled executions receive
  their persisted automation instructions and whatever chat context is
  available; a **new GitHub commit does not automatically refresh the prompts
  of existing ChatGPT automations**. Each saved task must retain a short
  immutable header with project identity, stable objective, allowed work,
  source mediation, safety/quality gates, and an explicit instruction to read
  the authorized latest HA instructions and compact checkpoint *if tools
  actually permit it*. When updating prompts, preserve and verify that header.
  HA's own route-specific prompt injection applies only when the selected
  provider and mode exactly match ChatGPT Chat; even then, verify real receipt.
- **Manage task lifecycle carefully:** A completed one-time task normally
  becomes disabled. The update API exposes `is_enabled=true`, but
  reactivation with a fresh finite schedule must be verified for the precise
  owner-authorized task. Never restart a user pause by default. `next_run_time`
  is read-only; change `schedule`/`DTSTART` and verify scheduled-for plus
  completed run results. Open-ended recurrence is not an always-running model.
- **Cross-chat and context:** Existing tests found distinct runs that shared
  one `chat_ref`. IDs can guide safe updates and evidence lookups, but the
  available update operation cannot retarget a conversation. Codex-specific
  context-left indicators are not established as Chat Mode variables. Prefer
  owner-authorized standalone new-chat-per-run execution with a concise
  durable GitHub handoff when available, not a forced-context reset, full
  transcript replay, or an invented new chat.
- **External tools and costs:** Connected GitHub or other MCP permissions must
  be checked in the *actual scheduled environment*, including approvals.
  Ordinary scheduled Chat runs may consume plan usage even if a dot coordinates
  them; the free allowance for talking *to* a dot is not a free execution
  grant to its delegates. No provider/API/Work/Codex substitution.

For every run: verify exact task ID and scope; read relevant current state;
choose a substantial justified action; execute with sole-writer fences;
persist verified artifacts and concise handoff; check actual task results;
only then revise authorized existing task assignments or timing. If the
objective is independently accepted or a genuine stop gate applies, pause
the appropriate owned tasks; do not self-publish or declare source approval.

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
