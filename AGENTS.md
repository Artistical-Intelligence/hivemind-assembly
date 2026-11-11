# Hivemind Assembly development

## Token use: fewer requests, long chains to agents (owner directive, 11 November 2026)

Every request an assistant makes re-sends its whole context: the app's instructions, every tool description and
the conversation so far. Cached, that is cheap per request, but it is most of the cost over a long session.
- **Fewer, bigger steps.** Batch independent commands, reads and checks into one request (one shell call doing
  several things, several tool calls sent together). Never poll "is it done yet": wait for a completion notice or
  schedule one check-in, and let a tool wait and report once.
- **Long chains go to subagents.** A long chain is a run of many dependent steps that each need the previous
  result: build, test, fix, retest; scanning many files; a release pipeline; a decode-and-rerun loop. Give the
  whole chain to one subagent with a short brief (goal, files to read first, rules, report length). It starts
  with a small context and reports one short result. The coordinator keeps decisions, not the steps.
- **Agent rules.** The coordinator keeps decisions; any chain of more than about three dependent steps goes to
  one agent, briefed once with the goal, the files to read first (paths, not pasted contents), the rules and a
  report limit. Follow-ups on the same work go to the same agent (resume it: it already holds the context); start
  a new agent for new work or when the old one's context has grown very large. Clerical chains (collecting
  results, releases, records) go to a script first and a cheaper model second.
- **Waiting.** Whoever waits does it inside one blocking call (a background command, `collect --wait`); the
  coordinator gets one completion notice. A scheduled check-in is set once, for the expected finish time, never
  repeated at short intervals. A check-in that only does mechanical steps runs one script in one call (or is a
  fresh-session scheduled task) instead of a long turn in the coordinator's chat.
- **Short results.** Reports are tables, counts and the first failure; details go to files that are named, not pasted.

## Blocker-to-resolution lifecycle — owner amendment, 10 November 2026

**Current scope:** HA development remains **PAUSED**. This is an owner-requested documentation/process correction only. It does not authorize implementation, build/test execution, deployment, worker activation, GitHub Actions, model APIs, schedule/role changes, or access to another project's private source. It becomes operational for HA engineering only when the owner explicitly resumes that work. HA-only agents retain HA-only access.

**A discovered blocker must enter a closed-loop resolution process, not a perpetual report cycle.** For each blocker, its existing authorized coordinator must record in the *current owned handoff*, not a new general-purpose ledger: (a) affected smallest coherent candidate and exact source/test/dependency pins; (b) whether the issue is a genuine failing test, missing execution capability, missing independent review, absent write lease, dependency, or scope mismatch; (c) one accountable existing resolution owner; (d) a **specific next permitted action** within that owner's scope; (e) the exact evidence/condition that proves the blocker cleared; and (f) the next recipient/trigger. A report-only update, unchanged HOLD, created task, delegated suggestion, or successful source staging is not a resolved issue.

**Coordinator obligation.** At the next lawful safe boundary, actually make the permitted assignment, lease handoff, or review/application decision. If a required narrow write lease is the blocker and authorization already exists, grant it through the existing sole-writer control after current ownership/conflict checks. If a task cannot execute in its present surface, establish a genuinely permitted alternate method or advance an independent ready slice; do not repeatedly choose the same blocked runner. Do not demand renewed owner approval for the unchanged authorized scope. If owner action or a platform denial truly prevents the operation, state the exact missing permission/action and retain it without pretending the blocker is closed.

**Delivery obligation after HA resumes.** Prioritize **finish → execute applicable checks → independent qualified acceptance → sole-authorized integration → repeat** on the smallest dependency-complete useful slice. Preserve predecessor semantics; integrate a coherent predecessor+fix+tests when a lone hunk lacks required prerequisites. Keep unrelated failures, historical phases, old plan-only instructions and quarantined work from globally freezing independent accepted changes. Do not turn a docs-only correction, model-level simulation, test discovery count or partial Windows-selected-module PASS into production acceptance. Count actual implemented and tested outputs, not reports generated. A real cross-file shared dependency, security, licensing, privacy, runtime or review gate remains binding.

**Status accounting and escalation.** Use the already owned summary/manager record to distinguish `IDENTIFIED → ASSIGNED → REPRODUCED/TESTED → FIXED → INDEPENDENTLY_ACCEPTED → INTEGRATED`; record `BLOCKED_EXTERNAL` only when a concrete unavailable capability/approval has been established. The coordinator is responsible for keeping the same blocker moving across source owner, tester, reviewer and integrator until there is a verified resolution or a real external stop. Never mark the process successful merely because a manager read or reposted the finding. A source or test owner cannot self-approve its result; a coordinator cannot bypass denied permissions, quotas, owner pauses or independent verification to force a green outcome.

**Historical instruction precedence.** Older policies, archived task prompts, dormant branches and handoff reports are evidence, not standing orders to reimpose a superseded workflow. In case of conflict, honor the owner's latest explicit project-specific scope and safety requirements. Do not apply RE-Wizard's active Phase 3 permissions to paused HA.

## Current scope and delivery structure (owner update, 9 November 2026)

**HA development remains PAUSED.** This update authorizes documentation maintenance
only, not engineering, tests, builds, GitHub Actions, releases, staffing or
schedules. Older priorities, rosters and handoffs are historical evidence, not
authority to restart work. No other project's phase or permissions are adopted.



### Immediate District Manager review-and-apply handoff (owner directive, 9 November 2026)

This standing rule applies to Hivemind Assembly as well as RE-Wizard. When the
owner asks any assistant, chat, worker or other authorized surface to create,
change, fix, stage or update something for HA and completion of that exact
requested scope requires District Manager/coordinator review, approval,
assignment, publication, integration authorization or another manager-owned
control write, **send the concrete handoff to the existing District Manager
immediately**. Do not leave owner-requested work sitting in `HELD`,
`NOT_APPROVED`, proposal-only or "awaiting manager review" state merely because
nobody explicitly asked the manager a second time.

The handoff must identify the exact artifact/update, source and evidence pins,
the requested manager-owned action, current dependencies/gates, and relevant
claims or concurrency constraints. The owner's request already supplies owner
intent for the unchanged requested scope; **do not ask the owner to approve it
again solely because manager review is required**.

The District Manager treats such handoffs as immediate review-and-apply work at
the next safe write boundary. In that invocation, review the exact update and,
when the existing required gates pass, make/approve/assign/publish/integrate the
requested change immediately rather than returning a status-only acknowledgment.
If a genuine independent-review, security, licensing, ownership, capability,
execution, concurrency or provider/surface gate blocks the full change, name the
exact blocker and responsible owner, clear or assign that gate immediately where
already authorized, and apply every unaffected eligible part. Do not use
"needs manager review" as a reason to defer otherwise ready owner-authorized
work.

**This rule does not resume HA development while the HA pause is active.** During
the pause it governs documentation/coordination and preserves ready handoffs; it
becomes actionable for engineering only when the owner separately authorizes HA
work. It is a routing and priority rule, not a bypass of mandatory safeguards.
Independent acceptance, source ownership, provider/surface limits, privacy,
security, licensing, execution and receiving-tree gates remain binding.

When HA work is separately authorized, use the existing project structure and
provider/surface, source-access, ownership, preservation and review boundaries:

- **One coordinator, distinct owners.** ChatGPT Chat Mode scheduled work retains
  the single owner-level District Manager, not a second HA manager. Other
  surfaces retain their existing authorized coordinator. Keep one saving and
  integration owner for shared paths, named source owners and an independently
  qualified verifier. Management, test execution, acceptance and integration
  remain distinct responsibilities.
- **Finish the highest-priority ready slice.** Select a small, coherent,
  dependency-complete candidate with exact source/test revisions, required
  coverage and acceptance criteria. Carry it through permitted regression
  execution, failure repair by its source owner, independent review and authorized
  integration before continually expanding the candidate. Keep unrelated
  discoveries in the existing backlog. This is a priority rule, not a fixed
  task-size/WIP cap, a full-team barrier or permission to omit required inputs,
  whole-deliverable checks or valuable foundational work. Independent ready work
  may continue within its assigned paths.
- **Handoff on completion where supported.** Save complete outputs promptly,
  with pending markers, then give the next owner the exact evidence and remaining
  acceptance condition. Proceed without another purely clerical acknowledgment
  when the action is already authorized and all guards pass. Use a verified,
  permitted completion trigger only where the actual surface supports it;
  otherwise retain the existing authorized hourly fallback for scheduled Chat
  Mode work. A saved prompt, changed schedule or emitted handoff is not proof of
  a receiving execution. Do not create duplicate workers, force wakeups, change
  cadence outside authority or restart HA while paused.
- **Bootstrap full-time receivers and temporary help at real decision points.**
  For already authorized scheduled ChatGPT Chat Mode work, check at the START
  of every run and again at the END, after completing your own ready authorized
  tasks, for both an existing full-time receiver whose current assignment is
  ready and eligible finite temporary help. Useful mid-run handoffs replace
  neither check. Consume returned results and reconcile owned claims first.
  Do not defer your own tasks, prolong a run solely to bootstrap, manufacture
  work or impose a dispatch quota. Report unfinished or blocked work honestly.
- **Advance a ready full-time peer without an extra manager cycle.** An
  authorized worker may advance only another healthy, enabled, idle permanent
  worker's next eligible `DTSTART` for its existing ready assignment. Preserve
  the complete prompt, title, role, hourly `RRULE`, enabled state, timezone,
  environment, source access and branch/file ownership. Do not retask it,
  convert it to a one-shot, wake yourself, create a wake chain or use
  `run_now` without separate explicit authorization. Check the latest exact
  task/run state, predecessor output and source pins, dependencies, next
  occurrence, holds and service limits; a completed last invocation or null
  next-run field alone is not proof of idleness or eligibility.
  Use a verified exclusive schedule-only reservation in the existing private
  District Manager coordination records: exact target ID, handoff dedupe key,
  predecessor run, scheduling owner, permitted change and release/uncertain-state
  condition. Only that scheduling owner may mutate the target while reserved;
  the manager and other peers must not race it. A read-before-write is not a lock.
  Recheck the reservation and live state immediately before the supported update.
  If exclusivity or fresh run state cannot be verified, preserve the handoff and
  ask the existing manager to reconcile rather than dispatching a duplicate.
- **Keep the manager responsible for structural control, not clerical delay.**
  The District Manager retains assignments, source leases, role/prompt changes,
  general cadence, pause/revival, enabled state and authoritative shared records.
  It must proactively provision narrow peer scheduling reservations for ready
  authorized handoffs at its next safe write boundary, without requiring another
  owner approval or making each handoff wait through an extra manager cycle.
  The peer exception above supersedes older blanket manager-only scheduling
  wording; it does not grant shared-record writes or structural control to peers.
  Restricted, no-trigger or consumer-only roles retain their restrictions and
  immediately give the exact ready packet to the existing manager.
- **Keep temporary claims separate and close the loop.** Eligible finite temps
  still require the existing global exclusive atomic claim protocol and current
  TEMP rights. Full-time IDs never become coffee-pool entries. Verify identity,
  stopped/free state, appointments, holds, claims, source grants, dependencies,
  output ownership, capacity and service limits before a temp dispatch. Give a
  bounded brief with pins and acceptance; qualify independent reviewers.
  For either path, verify the saved configuration separately from the matched
  actual run, useful output and consumed result. Record those states and the
  dedupe/reservation or claim disposition in the existing owned summary, not a
  new ledger. Release only under existing authority after the result and remaining
  obligations are accounted for and the worker is safely stopped. Preserve
  uncertain outcomes and unresolved claims until reconciled; do not retry blindly.
- **Use the last two available positions productively.** The District Manager
  must check actual recent temporary-worker use across a meaningful observation
  period, current active tasks/reservations and the service's current capacity.
  If the last two available positions are not consistently being filled by useful
  temporary assignments, use them for suitable permanent workers with ready
  continuing responsibilities instead of indefinitely reserving empty temp seats.
  Do not infer consistent use from configured prompts or a single idle snapshot,
  invent a fixed utilization threshold, promise a fixed task limit or count two
  positions that are not actually available. Respect active temp claims, existing
  appointments, protected work and safe handoffs; reuse eligible existing workers
  through the manager's normal staffing process. Keep actual permanent staffing,
  finite temp use and verified capacity distinct. This policy supersedes an older
  temp-reserve target where that target would keep these positions unused.
- **Preserve all other gates.** No duplicate occurrence, blind revival, scheduled
  child creation, quota/cadence/approval bypass, paid route or takeover of paused
  or unrelated assigned work. Missing safe capability is a concrete blocker.
  Preserve private/public, source, quarantine, licensing and independent review
  boundaries. HA remains paused and GitHub Actions remain prohibited. This
  documentation does not establish a deployed dispatcher or successful run.
- **Keep worker-owned current summaries.** Each assigned worker maintains a
  short summary in its existing owned handoff/status location: goal, owner,
  verified progress, next action, blocker and timestamp with timezone. Link the
  exact supporting source/result rather than copying a full report. Update at
  material state changes and safe handoffs; do not create duplicate summaries
  or cross another worker's lease. Distinguish last observed evidence from last
  edited text, and mark stale, unknown or unverified state explicitly. Do not
  call a scheduled snapshot live or up to the minute.
- **Keep one lean manager overview and act on it.** The existing District
  Manager maintains the single authorized human overview from those summaries
  and current evidence: overall goal, active subprojects/owners, material progress,
  next priorities and actionable blockers. Include a short evidence-backed trend
  since the preceding overview, such as advanced, unchanged or regressed, without
  invented completion percentages, speed claims or a performance ledger. At
  every actual manager run, actively improve the team and project plan: identify
  the current completion bottleneck, resolve or assign it, adjust authorized
  priorities/ownership/handoffs where useful, and apply ready requested changes.
  Do not merely summarize the same state or invent busywork; if no safe useful
  change is available, retain the precise blocker and next condition. Do not
  create a weekly review ritual or schedule. During HA's pause, this is permitted
  documentation/coordination only, not authority to resume engineering or staff.
- **Keep the owner's action inbox minimal.** In the existing authorized inbox,
  show only essential actions the owner must take now as a numbered list:
  "Run this" or "Approve this", with the exact actionable link. Do not include
  explanations, history, optional/reference items, routine status or work the
  agents can already perform. Remove completed or no-longer-needed entries
  promptly after verifying their outcome. Keep receipts and recovery/uploader
  records behind that view; inbox cleanup does not delete evidence or change
  permissions. Keep private owner actions out of this public repository.
- **Preserve the live machine contract.** The overview and worker summaries are
  human views, not replacements for parser-consumed state, schemas, required
  fields, exact source pins, claims, leases, gates or ownership records. Only the
  existing record owner changes shared state. Reconcile current fields together
  without erasing required reader inputs; archive superseded instructions and
  settings with their evidence links in the existing authorized history before
  replacing them. Never compact by dropping live obligations or force-pushing.
  Historical failures and receipts remain immutable; historical tests are not
  current acceptance.
- **Give each actionable blocker an owner.** Identify the specific operation and
  target, responsible existing owner, next corrective action and observable
  condition for resuming. Use the source owner for repair, executor for missing
  test evidence, verifier for acceptance, integrator for receiving-tree work and
  coordinator for assignment/capability conflicts. An unfilled role is an
  explicit coordinator-owned assignment gap, not an anonymous waiting state.
  Escalate missing authority at its real boundary; never bypass a denial.
- **Resolve, do not repeat.** Reuse valid exact-input evidence and rerun only
  affected checks when permitted and needed. If a run adds no new evidence,
  repair or actionable decision, give a short no-change result instead of another
  report-only commit or duplicate review. The coordinator should correct a futile
  assignment or select other useful authorized work, not keep restating it.
- **Preserve before changing or retiring.** Reconcile current heads, open PRs,
  active claims and relevant dependencies before acting. Reuse suitable existing
  branches and exclusive leases; route conflicts to their owners. Before any
  separately authorized retirement, record and verify durable preservation of
  useful unique content, original history and required objects, then recheck live
  heads and claims immediately before mutation. Never force-push, discard work or
  infer approval from a batch, source similarity or removed clerical wait.

The detailed branch lifecycle, bounded original-source execution and independent
review rules below remain binding. Static documentation review is not executable
validation, live scheduler proof, integration acceptance or release approval.

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

## Bounded original-source regression execution (owner update, 9 November 2026)

This is a reusable method for separately authorized work, not proof of an
available executor or a completed role change. It grants no new execution,
source access, publication, staffing or merge permission. Provider/surface
boundaries, owner pauses, quarantines and existing review gates still apply.

**HA development remains PAUSED.** This documentation-only maintenance does not
resume tests, builds, Actions, engineering, staffing or schedules. Keep all private
counterpart task IDs, claims, source and test evidence out of this public repository.

- **Diagnose the bottleneck first.** Reconcile current heads, complete relevant
  source/test/dependency blobs, failures, open PRs, ownership and claims. Decide
  whether the missing result is an actual regression run, failure reproduction,
  source repair, independent acceptance or integration. When execution evidence
  is missing, assign one bounded original-source regression executor/failure
  reproducer instead of another summary producer or duplicate reviewer.
- **Prove the route in the actual scheduled context.** Before relying on the
  assignment, verify that invocation has the authorized source-read, execution,
  dependency and result-saving capabilities. Record the actual tool/runtime,
  source identity and observed outcome. Prior foreground success, a saved prompt,
  an enabled schedule or another provider's run does not prove this route works.
  Do not run a prohibited test merely to probe a capability; absent authority or
  interfaces is a blocker, not permission to change environments or bypass a gate.
- **Bound the work and preserve roles.** Name the existing task/branch, single
  writer, exact inputs, methods or failing case, synthetic fixtures, resource
  bounds, acceptance criteria and allowed next actions. The executor produces
  reproducible evidence and a repair handoff. Source authors retain fixes; a
  separately qualified, author-independent verifier retains acceptance; the
  authorized integrator retains merges. Executing tests does not confer any of
  those other roles or release protected evaluator material.
- **Use complete original inputs.** Pin repository, commit, every source/test
  path and blob identity, relevant package initializers, transitive dependencies,
  configuration and runtime versions. Verify complete retrieval and identity;
  a line window, truncated response or historical receipt is not full-source
  evidence. Review imports and initialization before execution for filesystem,
  bytecode, process, network, native-library and other side effects. Synthetic
  fixtures must not import private production data or broaden source grants.
- **Use memory-only loading only where authorized and sufficient.** A supported
  executor may load the complete unchanged source and tests from verified inline
  blobs in memory, without cloning, downloading, unpacking, materializing source
  files or writing source/bytecode. Disable bytecode writes and account for import
  and package behavior; name any omitted initialization or restricted dependency.
  Keep synthetic temporary fixture/output writes only within explicitly permitted
  bounds. Memory loading is not a sandbox or an exception to execution holds.
  If faithful execution needs unavailable dependencies or forbidden side effects,
  stop that case and report the limit.
- **Do not substitute an implementation.** Hand-transcribed predicates, copied
  fragments, reimplementations, dependency stubs or stand-in packages cannot count
  as original-source or package acceptance. A declared mock/adapter may support
  only the narrower test contract that actually permits it; identify the altered
  boundary and leave dependent integration/package behavior unverified. Run the
  named original test methods against the identified original implementation,
  retain failures and distinguish a harness/setup error from a product assertion.
- **Report method-level evidence honestly.** Retain exact inputs, execution
  command or in-memory loading method, environment/dependency limits, named cases,
  fixture identity, expected and observed results, failure diagnostics and
  reproducible next steps in the existing private or public evidence location
  allowed for that project. Use PASS, FAIL, ERROR, SKIP and NOT RUN distinctly:
  PASS/FAIL require an executed assertion; ERROR records setup/harness/runtime
  failure without a valid case verdict; SKIP records an explicitly skipped case
  and reason; NOT RUN records work never executed. Preserve counts and individual
  outcomes, including negative controls. A focused synthetic pass is not whole
  package, native, platform, live-provider, game or release acceptance.
- **Retask safely, without adding infrastructure.** Where the current surface
  permits an owner-authorized same-ID role handoff, its existing coordinator must
  reconcile active runs, obligations, future appointments, leases and claims
  first. Preserve original history, outstanding reporting/notification duties,
  cadence, destination and settings unless a particular change is authorized.
  Verify the complete saved brief and later receiving execution separately.
  Reuse suitable existing seats, schedules, branches and evidence records by
  default; create no duplicate manager, registry or reporting layer. This is not
  an extension of Chat Mode scheduling permissions to Work, Codex, Claude or
  another provider/surface.
- **Escalate the concrete blocker once.** State the exact missing capability or
  permission, affected operation/target, completed work, owner and condition for
  resuming. Keep the result pending and continue independent ready work already
  authorized. Repeat only when the blocker materially changes or a decision is
  needed; do not spend successive runs restating it or spawn retries around a
  denial. Reconcile uncertain outcomes before retrying, and use a changed route
  only when independently authorized rather than to evade the restriction.

## Reuse existing branches first (owner directive, 7 November 2026)

- Reuse a suitable existing assigned branch and exclusive file lease for continuing work,
  evidence, receipts, reports, checkpoints and revisions. Before writing, check
  its current head, intended base, pending changes, active claims and ownership.
  A new run, small fix, review pass or date alone never justifies a new branch.
- Create a new branch only when existing branches cannot safely serve the task
  because of a concrete isolation, incompatible base/history, ownership or
  concurrency conflict, security/provenance constraint or justified consolidation
  destination. Record the reason, assigned scope, single writer and planned
  disposition in the existing task or handoff record. Reuse authorization already
  covering that scope; request only a genuinely missing required permission.
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
  The assigned scope must explain why reuse is unsafe. Check these fields when
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
  destination; where that is unsuitable, verify an authorized retained ref or
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

### Plan work around actual permission boundaries

- **Use the authority already given.** At assignment, distinguish read-only
  inspection, edits, merges, deletion, publication, execution and access changes.
  Match each intended action to the current user request, standing authorization
  and existing project assignment. A new worker, tool, turn, retry or handoff does
  not by itself require another approval. Keep the same authorized scope; seek
  fresh permission only when the target, data, recipients, terms, cost, access or
  risk materially changes, or a mandatory action-time approval applies. Still
  perform required current-state and ownership checks. Coordination, file leases
  and independent review are not additional user-permission requests.
- **Choose an equivalent supported route with fewer permission needs.** For
  example, prefer inline source text and directory/commit metadata over downloading
  files for ordinary inspection; reuse assigned branches and valid pinned evidence
  rather than creating disposable branches, uploads or new infrastructure. Make
  this choice before a gated operation. Preserve the requested result, required
  evidence, access boundaries and review coverage; if the safer route cannot do
  the full job, state the limitation rather than silently reducing the task.
- **Do not invent gates.** Verify current state and the actual applicable
  requirement using permitted reads before declaring a blocker. Existing scoped
  approval or an authorized coordinator's assignment is sufficient where the
  rules allow it. Do not add a blanket ask-first step, require new approval of
  unchanged work, or treat a historical pause/blocker as current without checking
  the owner's latest direction. A current explicit pause still controls.
- **Ask at the real boundary and keep other work moving.** Prepare permitted
  steps first, then request the specific missing action, target and scope, with
  material consequences; combine foreseeable required decisions when practical.
  Continue independent authorized work meanwhile. A denial or pending approval
  must not be evaded by changing tools, routes, agents or wording. Reconcile an
  uncertain result before retrying; retry a denied action only when materially
  new evidence or authorization permits it, not as a loop.

This guidance neither grants blanket authority nor withdraws existing
authorization. Mandatory confirmations, actual access restrictions, source and
security holds, ownership, required checks and current pauses remain binding.

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
The District Manager controls permanent roles and structural changes; the guarded
schedule-only peer exception in the current delivery structure above also applies.
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
