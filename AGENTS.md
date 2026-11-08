# Hivemind Assembly development

## Current scope and process guidance (owner update, 8 November 2026)

**HA development remains PAUSED.** The owner authorized this documentation update
only. Do not resume engineering, tests, builds, GitHub Actions, releases, schedules
or staffing because of this guidance. Older priorities, rosters and handoffs are
historical evidence, not authority to restart work. No other project's phase
sequence or permissions are adopted here.

When HA work is separately authorized, use these practices within its existing
provider/surface, source-access, ownership and review boundaries:

- Keep the existing live status/handoff compact: current objective, exact source
  revision, assigned owner and branch/path scope, verified result, concrete
  blocker and next permitted action. Update superseded current-state text rather
  than appending another full shift narrative. Mark unknown or stale state.
- Keep historical receipts immutable and separate from the live summary. Link
  exact commits, report paths and hashes; retain original failures, limitations
  and supersession evidence. A newer summary must not rewrite an old result or
  count historical tests as current acceptance.
- Reconcile a stale handoff against current HEADs, relevant source blobs, open
  PRs and active claims before acting. Repair current pointers with pinned
  replacements while retaining historical provenance. Do not recreate retired
  branches, repeat completed work or revive an obsolete assignment from a link.
- For ChatGPT Chat Mode staffing, retain one District Manager with clear
  assignments and one integration/saving owner for shared files. Do not create a
  second manager or competing ledger. Other surfaces keep their existing
  authorized owner/coordinator; this does not extend Chat Mode management to them.
- Reuse suitable existing branches as required below. Batch compatible,
  nonoverlapping consolidation evidence and work where this reduces duplicate
  handoffs safely; compare against a suitable common baseline, including
  dependencies, renames, deletions, shared configuration and workflow triggers.
  Route conflicts to their owners rather than assuming distinct filenames imply
  compatibility. No batch may bypass a lease, review gate or prompt saving.
- Before any separately authorized ref retirement, verify the exact current
  source and retained destination HEADs, PR/claim dependencies and preservation of
  every useful change and required history/object in a durable retained ref or
  approved archive. Record original SHAs and preservation proof first. Recheck
  immediately before mutation; a moved head or changed claim invalidates the
  earlier decision. Never force-push or discard unique/unresolved work.
- Keep independent verification proportional to the change and risk, while
  retaining every required review and acceptance gate. Reuse valid exact-input
  evidence; rerun affected checks only when permitted and warranted. Static
  document/hash review is not executable validation or release acceptance.
- Set bounded assignments up front: named owner, exact branch/path and input
  scope, acceptance criteria and preauthorized next actions. Keep the existing
  single-writer lease and any required qualified independent final check.
- Once that final check passes where required and fresh source/HEAD, PR, claim,
  ownership and safety guards pass, the assigned owner may proceed directly to
  the ready-work handoff or specifically preauthorized cleanup. Do not wait for
  another purely clerical manager acknowledgment of the same approved action.
  Record the actual action and verified outcome afterward in the existing live
  status and retained receipt. This does not defer preservation proof or other
  prerequisites that must be recorded before a destructive action.
- A changed input, failed guard, unresolved owner, missing action authorization
  or required action-time approval still blocks that action. Resolve that exact
  condition rather than treating removal of clerical waits as a permission or
  safety bypass. The HA development pause remains in force.
- Avoid duplicate handoffs, unchanged-status polling and unnecessary waits.
  Continue independent authorized work while an unrelated item is blocked, but
  do not interpret this as permission to bypass approval, ownership or a pause.
  Report a specific blocker, its owner and the next condition needed to proceed.

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

## Reuse existing branches first (owner directive, 7 November 2026)

- Reuse a suitable existing assigned branch and exclusive file lease for continuing work,
  evidence, receipts, reports, checkpoints and revisions. Before writing, check
  its current head, intended base, pending changes, active claims and ownership.
  A new run, small fix, review pass or date alone never justifies a new branch.
- Create a new branch only when existing branches cannot safely serve the task
  because of a concrete isolation, incompatible base/history, ownership or
  concurrency conflict, security/provenance constraint or justified consolidation
  destination. Record the reason, scope explicitly approved by the authorized owner/coordinator,
  single writer and planned disposition in the existing task or handoff record.
- Branch reuse never grants access to another worker's branch or file lease.
  Obtain the authorized owner/coordinator's explicit assignment or safe handoff
  before writing shared or separately owned paths. Preserve independent-review
  boundaries, source permissions, security holds and approval requirements.
- Preserve unique and unresolved work, original history and evidence. Never
  overwrite concurrent edits, force-push, reset away work or delete branches to
  make reuse easier. Branch reduction is not proof of accepted implementation.

### Prevent branch creep and finish the lifecycle (owner directive, 8 November 2026)

These practices apply to projects of different sizes and types. Use the existing
task, PR or handoff record, not a new branch registry, recurring job or reporting
layer. Keep the existing project's coordinator, permissions and review standard.

- **Prevent duplication at assignment time.** Inspect current branches, open PRs
  and active claims before assigning work. Prefer the existing suitable workstream
  or approved mainline path; there is no branch-per-task, worker, review, run or
  checkpoint default. A fresh conversation, retry or continuation must recover
  the recorded branch rather than mint another. A reviewer can inspect pinned
  inputs and save evidence through its assigned path without a new source branch.
  Do not reuse an incompatible or separately owned branch merely to reduce count.
- **Make exceptions temporary and purposeful.** When isolation really requires a
  branch, record its purpose, single writer, exact starting revision, intended
  integration target, dependencies and exit condition in the existing handoff.
  The approved scope must explain why reuse is unsafe. Check these fields when
  handing off work; a branch with no remaining purpose needs disposition, not a
  replacement branch with a newer date.
- **Recognize common redundancy, then prove it.** Typical candidates are duplicate
  tips, ancestors already retained downstream, superseded experiments, overlapping
  worker/retry branches, patches already ported to the target, and branches whose
  only extra content is status, reviews or test receipts. Age, name, a closed PR
  or an ahead/behind count is only a clue. Distinguish commit ancestry, full-tree
  equality and source/behavior equivalence: identical trees do not preserve
  distinct histories; ancestry alone does not show that later commits retained
  the intended behavior. Compare complete relevant deltas, renames, deletions,
  tests, configuration and dependencies, and account for every unique item.
- **Consolidate useful work, not just branch names.** Integrate accepted, compatible
  source changes into the intended destination in cohesive reviewable units, using
  the existing merge owner and required independent checks. Recompare remaining
  candidates after the destination moves. Preserve useful evidence in its normal
  retained location with original source pins; do not create evidence-only branches
  by default. An archive, merge record or empty/history-only merge is not proof
  that useful functionality was integrated. Rejected, unsafe or unresolved work
  stays preserved and explicitly held, not silently accepted to simplify cleanup.
- **Require both preservation and retirement clearance.** Before deleting a name,
  prove that useful unique content and the complete original commit history and
  required objects are durably retained. Prefer reachability from the accepted
  destination; where that is unsuitable, verify an owner-approved retained ref or
  recoverable archive, including its access restrictions and recovery method.
  A copied working tree, squash/cherry-pick, recorded SHA, closed PR or unverified
  remote object lookup alone is not full-history preservation. Do not merge held
  content into an active/public target merely to establish reachability, or turn
  cleanup into one new archival branch per old branch.
- **Check live dependencies immediately before mutation.** Record exact source and
  retained destination heads and preservation proof first. Resolve active writers,
  file leases, open PR heads/bases, stacked-branch dependencies, release/default
  branch roles, automation assignments and live links with their existing owners.
  Preserve security, licensing, privacy and source-access holds. A moved head,
  changed claim or uncertain preservation result invalidates the prior clearance.
  Serialize mutations, use expected-head guards where supported, and never call a
  preflight read an atomic lock. Never force-push, reset away or discard unique
  work. Verify remote results and reconcile uncertain outcomes before any retry.
- **Make cleanup part of completion.** During authorized work, check disposition
  at assignment, successful integration and handoff/completion, not through
  unchanged-status polling. The assigned merge owner should proactively integrate
  ready accepted work and retire genuinely obsolete names once the action is
  authorized and all required guards pass, without another purely clerical wait.
  Update the existing live pointers and record original/final SHAs and outcome.
  Keep held branches with a concrete reason, responsible owner and release
  condition. Necessary active branches are not failures; accepted useful work and
  fewer redundant refs matter more than a branch-count target.

This is process guidance, not acceptance of any branch or blanket permission to
merge, delete, change schedules, bypass protection or restart paused work.

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

## Current owner P0 — consolidate existing branches into main (6 November 2026)

For current authorized ChatGPT engineering work, reconcile HA's four non-main branches with current `main` before expanding new side branches. Read `dev/continuous_execution/BRANCH_CONSOLIDATION_P0_20261106.md` and its SHA-pinned branch ledger. District Manager coordinates assignments, workers identify unique work, and independently checked changes are integrated without force-pushing or altering preserved controls. Keep RE-Wizard private-source mediation, no GitHub Actions, owner authorization and existing checked-release policy. This priority does not override higher-trust instructions or authorize importing private material.
