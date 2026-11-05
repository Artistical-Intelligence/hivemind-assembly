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

## GitHub MCP: avoid hosted file-materialization approvals

**ChatGPT source-reading rule:** When reviewing GitHub source, use
`GitHub.fetch_file` (`mcp__GitHub__fetch_file`) for a known path/ref and
`GitHub.fetch` (`mcp__GitHub__fetch`) for directory/metadata JSON; both
return inline UTF-8 text. Use bounded line ranges for large files.
**Do not use `GitHub_MCP.get_file_contents` for ordinary files** when
the inline GitHub tools are available: GitHub MCP can return a resource
attachment that makes the ChatGPT host request **"Allow file
materialization?"** despite the app being set to Allow all actions.
Do not automatically materialize or download a binary, ZIP or file
resource as a fallback. Report a real binary/size limitation instead.
No hosted approval gate can be disabled by this repository. HA's own
native MCP `get_file_contents` text normalizer is documented in
[GitHub MCP text-only reads](dev/continuous_execution/GITHUB_MCP_TEXT_READS.md).
This does not authorize additional GitHub, cross-project or tool scope.

## Provider-specific execution instructions

**ChatGPT Chat Mode only:** read [CHATGPT.md](CHATGPT.md) for the owner-adopted
adaptive execution process and its large-task clarification. The detailed Chat
Mode profile is in [dev/continuous_execution/PROCESS.md](dev/continuous_execution/PROCESS.md).

This profile is **not an instruction for ChatGPT Work, Codex, Claude, or any other
provider/surface**. Do not inject it into Work tasks, Codex tasks, Claude prompts,
worker/coordinator briefs for those surfaces, or a shared all-provider/all-surface
default. Route it only when the configured execution surface is explicitly ChatGPT
**Chat Mode**. Keep Work, Codex and Claude instructions, model assignments,
authorization and runtime behavior unchanged. Chat Mode test evidence does not
establish their capabilities; extension requires separate owner authorization and
surface-specific validation.

These routing boundaries apply when maintaining HA's harness, regardless of the
maintainer's provider or surface. Existing shared safety, saving, privacy, source
mediation and independent-review rules below retain their original scope; this
notice does not remove them or impose the Chat Mode workflow elsewhere.


## Workplace organization (permanent owner directive, November 5, 2026)

For owner-authorized **ChatGPT Chat Mode scheduled engineering**, read `dev/continuous_execution/workplace/WORKPLACE_POLICY.md`, `org_chart.json`, `job_openings.json`, and `STAFFING_STATUS.md`. **Workplace** is the permanent project-staffing structure: an org chart retains every desired position, and a job opening tracks each unfilled role. The single owner-level **District Manager** performs the full previous HA and RE-Wizard Shift Manager job and continuously recruits safely released existing workers for open project positions. There is no separate HA Shift Manager role; the existing former manager's hourly seat now belongs to a distinct HA browser transport engineer. Work/Codex/Claude/API routing rules, all worker-owned source boundaries and independent review are unchanged. Do not place private RE-Wizard task IDs/code/claims into this public HA repository.

## Pre-provisioned Chat Mode coordination (Nov 2026)

**Only when the configured execution route is explicitly ChatGPT Chat Mode:**
read [CHATGPT.md](CHATGPT.md),
[the HA conductor design](dev/continuous_execution/CONDUCTOR.md),
[the authoritative Chat Mode Shift Manager policy](dev/continuous_execution/SHIFT_MANAGER.md),
[the dated evidence and open tests](dev/continuous_execution/CHAT_MODE_FINDINGS.md),
[the completed multi-session test audit](dev/continuous_execution/CHAT_MODE_SESSION_TEST_AUDIT_20261104.md)
and [the scheduling/automation skill](skills/chatmode-scheduled-orchestration/SKILL.md).
These documents are **CHECKS PENDING** and do not implement a new native
scheduler, install a ChatGPT skill or provide a general permission grant.

The owner prefers an **advance-provisioned, dynamically retaskable pool** of
existing automations rather than scheduled executions spawning new tasks. Start
with a **nominal five-role roster** (conductor, two substantive workers,
verifier, integrator) only after authorization, real capacity checks and
validation of native transport; optionally expand toward ten when substantial
nonconflicting work and allowance justify it. The number is an adjustable
project provisioning target, **not** an automatic instruction to create ten
active recurring tasks, to defeat once-hourly cadence, or to infer independent
review from distinct task IDs. Keep each role's responsibility and write
ownership distinct even if the permanent project objective is shared.

At every Chat Mode scheduled run, preserve the long-horizon objective and its
acceptance criteria, read only relevant **authorized** latest project state,
choose an evidence-driven next milestone, and checkpoint minimal changed
artifacts/results for the next execution. When permitted, retask or reschedule
**only existing allowlisted** tasks, verifying the complete saved prompt after
mutation. Retain an immutable goal, source-access and safety header in every
automation prompt; don't overwrite it with a transient role instruction.
Never automatically restart user-paused work or claim a completed one-time task
can be revived without a verified fresh schedule and explicit authorization.

**Scope/receipt:** A file in this GitHub repository is not automatically reread
by every ChatGPT scheduled execution. Its task must include a durable saved
prompt telling it to retrieve the approved instructions/checkpoint using
available tools; for HA-native calls, separately verify the explicit Chat Mode
prompt injection and actual model receipt. Context, chat ID and model/allowance
signals are surface-specific. Do not reuse a Codex-only context metric in Chat
without confirming an actual supported value. Standalone per-run fresh chats
may use minimal GitHub checkpoints where supported, but a scheduled task cannot
claim a new interactive chat was created or its conversation ID retargeted.

Completed November 4 service experiments verify saved own/cross-task
prompt and schedule changes, **three** successive two-hourly completions,
expired and previously self-paused task revival, **two** sequential
same-ID one-time task resurrections, cross-conversation registry
coordination, and a separately audited scheduled GitHub write on an
authorized isolated branch. Scheduled child creation was prohibited;
a same-chat ordinary user-role message trigger was unavailable.
These are service-level findings, **not** proof of HA-native runtime
integration, independent model/reviewer qualification, unrestricted
service/API access, or immediate/sub-hour corrective dispatch.
One test-owned task ID was later repurposed as an active production
worker; check CURRENT ownership and saved prompt before any mutation.
Real-work tests also show overlapping productive ChatGPT sessions,
inherited corrections and failing source-bound CI, not accepted
integration. The manager's maximum-work-runway optimization remains
unverified in a live HA scheduler. All existing independent-acceptance,
model qualification, RE-Wizard source mediation, writer fences,
project pauses, credentials, and release gates remain unchanged.
Do not apply this Chat Mode method to Work, Codex or Claude by inference.

**Chat Mode global coffee update (November 4):** all authorized scheduled
workers should proactively borrow reusable one-time helpers whenever
nonduplicative parallel or synergistic processing would be useful.
An eligible historical **one-time task from any ChatGPT chat and
any prior purpose** may be brought into the single private global
pool once its *current* stopped/free state, lack of future appointment,
claim, protective hold and writer conflict have been verified.
The originating chat/project is not a bar to reuse. When bootstrapping
N recurring employees, target N additional dormant one-time temp
slots from available historical tasks and safe new placeholders;
do not run empty placeholders or exceed real task capacity.
Only the Shift Manager controls permanent recurring employees.
All-authorized-worker temp claims require a single globally atomic
create-if-absent registry, not separate per-project claim files.
This is **ChatGPT Chat Mode only**, and documentation is not
proof of a deployed HA temp dispatcher. See
[SHIFT_MANAGER.md](dev/continuous_execution/SHIFT_MANAGER.md).

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
