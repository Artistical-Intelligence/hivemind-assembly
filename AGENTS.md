# Hivemind Assembly development

- Reverse engineering capability is the primary goal. Preserve complete Ghidra
  and REA foundations and deep, efficient integration; additions must not reduce
  upstream functionality.
- Ship one integrated application with clear internal modules. Keep core,
  automation and learning independent of the reverse engineering domain and UI.
  Do not prioritize a universal plugin system or a Codex port.
- Hermes is the initial agent runtime. The controller owns deterministic state
  and execution safeguards, not a competing general-purpose reasoning runtime.
- Native autonomous sessions are mandatory. Preserve exact configured
  provider/surface/model/mode/effort and allowance distinctions. No model API
  fallback, manual relay substitute or overage. During work, re-read usage every
  10 minutes while an account has usage left; once it runs out, check once a day.
- Learning includes knowledge, procedures and executable workflows. Measure
  correctness and speed with independent holdouts/regressions before promotion.
  Do not claim self-improvement from retrieval or contracts alone.
- Retain operation idempotency, uncertain-write reconciliation, writer epochs,
  revision fences and role isolation. Preserve originals and protected evaluators.
- Use `_app/hivemind_assembly` for implementation. `workbench` is compatibility
  only. See `dev/ARCHITECTURE.md` and `dev/ROADMAP.md`.
- Preserve user settings, histories, projects and profiles across drop-in ZIP
  updates. Runtime release root: README and launcher; internals under `_app`.
- Keep runtime data, browser profiles, credentials and private source documents
  out of version control and release artifacts.
- State what was actually verified. Keep historical evidence separate from
  current-run results; never count fixtures as live provider acceptance.
- Keep monitoring brief. Use existing deterministic job/status mechanisms where
  available; summarize material progress, failures, blockers and completion.
  Avoid repeated unchanged-status commentary, full logs or new analysis/review
  turns for routine polls. Follow any service-required heartbeat without
  presenting waiting as token-free model work.

## Core adaptive execution and incremental progress

Apply [the core process](dev/continuous_execution/PROCESS.md), revision 1.0,
when developing HA and specifying the native coordinator/worker briefs it supplies.
The owner adopted all ten steps, with the explicit clarification that useful large
chunks and partial results should accumulate across waves. This is an operating
requirement, not a claim that untested runtime mechanisms are implemented.

1. **Read, reassess, decide each wave:** reconcile current owner directions,
   repository state, outputs, verdicts, interruptions and real capabilities.
2. **Define outcomes and evidence:** keep the long-horizon goal and distinguish
   useful incremental progress from independent acceptance and publication.
3. **Prioritize bottlenecks and cumulative value:** unlock completion without
   selecting only small/easy wins or excluding valuable foundational work.
4. **Verify capabilities:** check actual executor/reviewer/model/context and
   artifact-return support; reuse unchanged capability evidence, never invent it.
5. **Manage dependencies, not arbitrary backlog caps:** continue useful, reviewable,
   nonduplicative and resumable work despite pending reviews. Defer only affected
   paths for concrete dependencies, invalidated premises, conflicts, resource/access
   constraints, owner stops or lack of useful work. Do not impose a fixed draft cap.
6. **Preserve large coherent tasks:** a chunk may span many waves. Maintain its goal
   and exact resume point; split only when practical constraints justify it.
   Checkpoints are recovery points, not stop commands or one-unit-per-wave limits.
7. **Reduce overhead:** use deterministic scripts, safe batched reads, pinned inputs
   and scoped reuse without reducing required coverage or independent scrutiny.
8. **Test explicit hypotheses:** separate automation experiments from project
   validation; distinguish live results, isolated tests, simulations and blockers.
9. **Recover through durable handoffs:** promptly save complete snapshots, verify
   remote persistence, reconcile uncertain writes and preserve writer ownership.
10. **Compare, learn, replan:** assess results at milestones, record concise rationale
    and next decision triggers, and change ineffective methods without forcing novelty.

A wave is a decision/execution opportunity, not a deadline for the whole assignment
or a synchronization barrier. Do not stop merely because one milestone was saved,
reviews are pending, or a large task will not finish in one turn. Continue valuable
work within real budgets, permissions, dependencies and owner deadlines. Never trade
away quality gates or claim partial work is accepted. Do not add a performance ledger.

Scheduled executions may occur in another chat. Recover current authorized task
state and material owner corrections from durable project/GitHub records; never
assume the scheduling conversation or full author context is present. A different
chat/task ID alone does not establish fresh context or reviewer independence.
AI-only coordination must not depend on the owner opening chats, running commands,
copying reports or recruiting reviewers. Respect mandatory approval and stop gates.
Revise this process as the owner clarifies goals and verified findings accumulate.

## Setup UX preference

- Prefer prefilled setup links and completed provider forms for known names,
  endpoints, callback URLs, settings and the full permissions required by the
  requested task. Reuse confirmed values and verify that the provider accepted
  them. Continue authorized setup automatically; ask for user action only when
  a step actually requires it. Keep credentials in the provider or secure local
  credential flow, and provide a clear manual fallback when automatic setup
  cannot be verified. The owner explicitly prefers this pattern in HA and other
  integrations.

## Relationship to RE-Wizard and its access boundary

[Hivemind Assembly](https://github.com/Artistical-Intelligence/hivemind-assembly)
is the integrated agent application that applies and tests reverse-engineering
methods around Ghidra, REA, independent verification and reusable learning.
[RE-Wizard](https://github.com/Artistical-Intelligence/RE-Wizard) is its source-review,
evidence and textbook knowledge counterpart for general software reverse engineering,
including game decompilation/recompilation. Verified RE-Wizard findings can inform
HA methods and tests; HA implementation experience and verification limits can
inform RE-Wizard research questions and practical tasks.

Cross-review relevant revisions, sections and underlying evidence when necessary,
within the permissions below. Textbook coverage does not prove HA implements or
has validated a capability; HA behavior does not replace primary-source evidence
for a research claim. Record the supporting revision and limits in normal evidence.
[RE-Wizard's agent instructions](https://github.com/Artistical-Intelligence/RE-Wizard/blob/main/AGENTS.md)
orient separately authorized repository work; this repository's instructions govern
HA edits. Cross-links do not override either repository's rules.

These links are orientation, not access grants. HA runtime/task agents must obtain
RE-Wizard textbook information only through authorized mediated reference retrieval,
limited to relevant sections allowed for their role and task. Never bypass mediation
through direct GitHub access, clones, exports, filesystem access or whole-book
retrieval, even if a tool or signed-in session technically permits it. Do not place
whole-textbook links in native worker prompts or infer broader source permissions
from this relationship. Request needed material through the mediator without
expanding grants; preserve existing source/category and role restrictions.

Direct RE-Wizard study or maintenance requires a separately explicit owner-authorized
task, such as finishing B02. Being a maintainer, having tool access or seeing a URL
is insufficient and does not expand an HA task agent's mediated access. Keep private
reference content out of this public repository unless separately authorized.

- Commit and push to `main` immediately after any file is planned and after every individual file edit, even
  several times within a single reply. Never batch changes or wait for
  checkpoints or the end of a reply. Preserve remote changes; never force-push.
  Exclude credentials, private runtime data and source material without sharing
  permission.

- Record verified evidence in `_app/release_status.json` (`evidence`, with full
  commit SHAs and run IDs), then run `python dev/status_docs.py --write`; the README
  and ROADMAP status blocks are generated and checked by tests.

<!-- checks-workflow:start (kept up to date by Hivemind Assembly) -->
## Push early, check later

Every assistant working in this repository (Claude, ChatGPT or any other) follows these rules:

1. Commit and push every file you create or change right away, before any review.
2. Mark what isn't checked yet: add a line `CHECKS PENDING: <file> — <what still needs checking>`
   to STATUS.md in the file's folder, and a row to CHECKS_STATUS.md at the top of the repository
   (item, folder, waiting for). Missing markers alone do not prove a file was checked.
3. A check is done by a different assistant session than the one that wrote the file (another
   provider when possible, otherwise a fresh conversation). The checker gets only the files and
   their sources, and writes a report under checks/ that stays in the repository.
4. When a check passes, remove its STATUS.md line (and STATUS.md once it's empty) and its
   CHECKS_STATUS.md row in the same commit as the report. When a check fails or stops early,
   keep the marker and say in STATUS.md what failed or what is left.
5. Never put anything with a pending marker into a release, the main deliverable or any other
   published output.
6. When you pick up this repository, reconcile CHECKS_STATUS.md and QUEUE.md with current files,
   their hashes and check reports: finish pending checks before starting more work. Preserve
   completed work; a changed file must be checked again. Failed checks permit focused repairs.
7. Give each worker explicit output ownership. HA's project writer lease and broker own edits
   and saves; assistants outside HA must likewise use one integration/saving owner. Save drafts
   immediately with pending markers; never wait for an entire batch or acceptance check.
8. Brief each worker with the current task, source/revision references, necessary dependencies,
   edit scope and completion criteria. Retrieve additional evidence as needed; do not replace
   required reading with a summary or repeat unrelated conversation history.
9. Validate the combined deliverable against its existing whole-project checks before completion;
   passing child tasks alone is insufficient. Reuse required checks without duplicate reviews.
10. Do not add operational performance records for these practices. Existing correctness evidence,
    recovery journals and learning evaluations remain required.
<!-- checks-workflow:end -->
