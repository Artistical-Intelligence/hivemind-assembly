# GitHub MCP and bounded-execution discoveries

Recorded: 2 November 2026.

**CHECKS PENDING:** Independent evidence review is required. This is an owner-requested preservation of operational discoveries and a continuation brief, not an HA runtime implementation, release gate approval, or proof of unlimited autonomous execution. Read the adjacent `STATUS.md` and root `CHECKS_STATUS.md`.

## 1. Scope and evidence discipline

The owner asked to preserve the current connector and execution-test discoveries in HA before changing conversations. This save changes documentation and its pending-check records only. It does not authorize changing HA runtime code, other ongoing tooling work, schedules, credentials, plugin permissions, or published RE-Wizard material.

Distinguish four kinds of evidence:

- **Direct observation:** A tool result or owner-supplied screenshot actually showed the behavior.
- **Saved and read back:** A remote artifact or plugin release exists and was retrieved again. This proves persistence, not every assertion inside it.
- **Reported run outcome:** A scheduler associates a completed run with its result. Its claims still need the corresponding remote artifacts and acceptance checks.
- **Proposed or untested:** An architecture or test has not passed merely because it was described or scheduled.

Do not copy private textbook content, credentials, account tokens, personal email addresses, conversation identifiers or raw account dumps into HA. RE-Wizard remains a separately authorized maintenance task; HA task agents still require mediated textbook retrieval under `AGENTS.md`.

## 2. Materialization, not ordinary GitHub tool consent, was the observed interruption

The owner's screenshot identified **GitHub MCP** and said:

> Allow file materialization? ChatGPT needs your approval to materialize 1 file attachments returned by GitHub MCP.

The request was a file-content read of a small Markdown diagnostic file, not a repository write. Its arguments identified owner, repository, file path and branch. Earlier native MCP file reads returned an embedded text resource and produced a mounted attachment. This establishes the observed representation/host-materialization path. It does **not** identify every component's internal responsibility or prove that all native MCP reads behave identically.

Permission inspections in the earlier tests reported **Allow all actions** for both GitHub and GitHub MCP. Nevertheless, the screenshot shows an additional materialization confirmation. Do not conclude that permissive tool settings eliminate every host confirmation or that an operation was approval-free merely because it eventually returned successfully.

**Not established:** Whether this approval is once per file, once per run, once per conversation, or repeated under another condition. Deliberate repeat materialization across controlled fresh contexts was not completed. A separate scheduler-authorization failure was also not demonstrated as the cause of the screenshot.

## 3. Tested read/write paths and the actual plugin change

| Operation or change | Evidence and limit |
| --- | --- |
| Standard GitHub `fetch_file` for UTF-8 text | Returned ordinary inline content, including repeated and bounded-line reads. The test file's blob SHA was `359188f6771081d6c6f47949db93903c6a504394`. No file artifact was returned by those tested calls; this is not a universal claim about client-side prompts. |
| GitHub MCP directory `get_file_contents` with `fields` | Returned ordinary JSON metadata for name/type/SHA/size. The `fields` option is directory-only, not a text-only switch for files. |
| GitHub MCP writes | Earlier scoped writes returned remote commits. Tool functionality was demonstrated; the assistant cannot infer every client-side approval event from success alone. |
| Standard GitHub writes | A later scheduled review reported successful writes and remote readback; its saved result and pending audit were checked again while preparing this document. |
| GitHub MCP plugin update | Version **1.0.1** was saved in place and its source read back. The original App binding remains; the added skill is `skills/github-text-first/SKILL.md`. |
| GitHub Personal Repos | A separate saved package was found. It was not modified, and its own live file-reading behavior was not tested. Finding an owned package does not establish that it is enabled or callable in a particular conversation. |

### Version 1.0.1 is a routing workaround, not a backend repair

The existing GitHub MCP package originally exposed an App binding and manifest, not the server source. The update adds a skill that chooses the already-connected **standard GitHub** connector for ordinary inline file reads, while retaining native GitHub MCP metadata and authorized writes. Both connectors must remain available for that tested arrangement. The update does not combine their credentials or make their repository permissions identical.

The update preserved the existing plugin identity, App binding and presentation. It did not replace native `get_file_contents`, deploy a server, disable confirmations, or modify GitHub Personal Repos. A later metadata/source read confirmed version 1.0.1 and release `pluginrel_6ae8f35c64548191b7a7c9d28ec5b2d5`.

Relevant saved plugin files:

- `plugin.json` and `.app.json`;
- `README.md`;
- `skills/github-text-first/SKILL.md`;
- `skills/github-text-first/agents/openai.yaml`;
- `skills/github-text-first/references/VALIDATION.md`.

Do not claim that the new skill automatically loaded in every existing or scheduled context. The narrow fresh-context read-only test is now reported successful below; universal invocation remains unproven. The installed update is already account-side; re-uploading its ZIP or rotating credentials is not required merely to save the update.

### Fresh-context read-only test — owner-supplied result

The owner supplied the result of the specifically requested fresh-chat test. Evidence classification: **reported success from an owner-supplied test report**, not a direct observation of that other execution by this documenting agent, a scheduler record, or an independent review of this findings document. The original purpose was to test the installed skill in a fresh context, not to transfer review coordination or start an independent research reviewer.

The report states that `github-text-first` was available, read and followed before retrieval. It used `GitHub.fetch_file` with UTF-8 and lines 1–3 of `Research/Continuation/B02/review_work_2026-10-27/continuation_2026-11-02/automation_capability_probe.md` in `Artistical-Intelligence/RE-Wizard` on `reviews/b02-batch-continuation-2026-11-02`. The response was inline text, with no returned attachment, no fallback and no tool-level error. The reported blob SHA was `359188f6771081d6c6f47949db93903c6a504394`, matching the previously retained test-file identity above.

The report records no approval blocker in the returned operation result; it explicitly does not establish that the owner saw no client-side dialog. It reports no access to the previous authoring conversation, no repository/plugin/permission/schedule writes, and no reviews, workers or coordination takeover. Preserve these as reported scope observations rather than independently audited activity.

**Disposition:** The original fresh-chat skill-loading and inline-text read smoke test is complete on the supplied evidence. No additional coordinator handoff or repeat of this same smoke test is required merely to continue existing work. This result does not validate native MCP file-response repair, fresh-context writes, every scheduled context, independent research review, successor creation, detached persistence or universal approval-free behavior. The remaining independent evidence-review marker on this document stays in place; it is not a request to repeat the successful smoke test.

### Retrieval policy to retain

Select a suitable representation before calling a tool. Use inline UTF-8 reads and pinned revisions for source inspection; use directory/tree metadata when only identities or existence are needed. Treat truncated output, or empty output for a known nonempty file, as incomplete retrieval. Line-range parameters do not prove support for oversized files.

Use materialization when actual file bytes are genuinely needed, with normal approval. Never auto-approve, conceal, bypass or switch routes to evade a denied or pending gate. When approval blocks a task, record the precise operation once and preserve progress instead of repeatedly issuing the same request.

Preserve writes with the appropriate existing tool and its documented pre-read/expected-SHA requirements. `push_files` is not an expected-head compare-and-swap lock. Reconcile uncertain writes before retrying, and verify the actual remote commit and changed paths.

## 4. Continuation experiments: what passed and what did not

| Mechanism | Status as recorded here | What it establishes |
| --- | --- | --- |
| Durable repository handoff | Demonstrated | Saved checkpoints and pending review artifacts can be read by subsequent executions. They are not automatic acceptance. |
| Scheduled recurring task creation | Demonstrated | An hourly review-continuation task was created. Creation alone was not evidence of an actual run. |
| Immediate `run_now` invocation | Demonstrated **inline** in the earlier test | The tool returned instructions to execute in the invoking conversation. That result was not a detached worker or a new runtime budget. |
| Scheduled substantive review | One completed run and corresponding remote artifact verified | Scheduler evidence later superseded the earlier empty-history uncertainty; see section 5. It does not establish indefinite operation. |
| One-time successor scheduling from interactive chat | Demonstrated | A separately scheduled probe was created from the parent conversation. This was not a scheduled worker creating its own successor. |
| Sequential duplicate avoidance | Demonstrated narrowly | Registry lookup found the existing named probe, so another creation was skipped. This was application logic, not an atomic service guarantee. |
| Simultaneous duplicate prevention | Not tested | Check-before-create can race. No concurrent atomic-claim acceptance is claimed. |
| Scheduled worker creates a successor | Not verified | The later recorded review did not create one. Its result reported a restriction against another automation; do not generalize that run-specific limitation into a permanent platform fact. |
| Nested subagent chain | Not tested | No suitable agent-spawning interface was exposed in the earlier test environment. A child agent must not be assumed to reset its parent's limits. |
| Detached worker surviving its parent | Not tested | Scheduling a future task or launching a process is not proof of survival after parent execution ends. |
| Persistent coordinator launching successive workers | Proposed | Requires an accessible supported environment and actual lifecycle tests. |
| HA host connection | Prior attempt failed internally | The owner suggested the computer was unavailable while using a phone. That is a plausible explanation, not a verified root cause. |
| Concurrent connector retrieval | Requests completed in the earlier test | Demonstrates successful independent reads, not independent AI reviewers or a proven speed advantage. |
| Runtime ceiling / automatic rollover budget | Not established | No trustworthy universal maximum time, call count or countdown was measured. |
| Automatic model switching, event-driven restart or watchdog recovery | Not validated by these experiments | Keep configured provider/surface/model/mode/effort exact; no API fallback or unverified substitution. |

The scheduling interface used for these experiments limited recurring cadence to hourly. Do not construct chains or overlapping schedules to evade a service limit. Inspect the actual current interface and permissions before scheduling anything further.

### Do not promote weak benchmark claims

Earlier sequential/concurrent connector timings were not controlled for cache, ordering or clock behavior. They do not support choosing the faster path. An earlier chat summary also asserted a local hashing speedup without a corresponding retained execution result in the available record; do not treat that number as verified. No ongoing performance ledger is introduced here. Any later owner-authorized benchmark should be bounded, useful and reproducible rather than consume tokens merely to hit a limit.

## 5. Scheduled work now has a concrete saved result

During this documentation save, the existing **RE-Wizard review continuation test** was inspected by exact task identity. Its most recent returned run was marked `completed`; the latest result matched that run and was created after it started. The result was not truncated, reported `requires_user_action=false` and was not marked a failure. Delivery remained unknown. No schedule was changed or task triggered by this save.

The result reported substantive canonical-record reconciliation, scoped commits and remote readback using the standard GitHub connector. The pending audit was then retrieved directly from the reported final commit:

- Repository: `Artistical-Intelligence/RE-Wizard`.
- Branch: `reviews/b02-batch-continuation-2026-11-02`.
- Reported final commit, subsequently used for successful artifact retrieval: `c4301050a05ca867c118018c1f9bfc8dd9b321a8`.
- Audit: `Research/Continuation/B02/review_work_2026-10-27/continuation_2026-11-02/ps2_canonical_stage_mapping_audit_2026-11-02.pending.json`.
- Retrieved audit Git blob: `e7092db62e75d8851f7cf26a1497cc536715a9ec`.

This is stronger evidence than merely seeing an enabled automation. It supports a successful bounded scheduled repository-work episode. It does not prove a separate new chat/process, fresh context, uninterrupted parent-independent persistence, globally approval-free calls, automatic successor creation, or unlimited runtime. Do not infer these from the scheduler's completed label.

The audit is explicitly **pending**, not an independent final closure check. Its existence is verified; its full technical contents were not independently rechecked for this HA documentation task. The review still requires separate canonical closure acceptance. No private source quotations or textbook content are copied here, and no source-review coverage is awarded by this note.

## 6. Implications for HA design, not claims of implementation

The useful objective is sustained **verified progress across bounded executions**, not keeping one model turn alive indefinitely. Reuse HA's existing controller, idempotency, writer epochs, revision fences, role isolation and durable recovery mechanisms rather than creating a competing general-purpose coordinator or second progress ledger.

A bounded assignment should identify the authorized repository/ref, source fingerprint, exact unfinished unit, output ownership, acceptance criteria and next action. Save complete pending artifacts promptly. Re-read remote state before promotion, preserve independent reviewer requirements and continue to another ready task when a genuinely independent path remains available.

Keep read access, write access, output representation, local-file permission and worker lifecycle as distinct capability checks. A successful metadata call, visible browser tab or recognized model fingerprint does not prove delivery, tools, publication, persistence or resumption. A scheduled continuation with inherited author context is not automatically an independent checker.

For rollovers, use bounded lineage and one intended active successor, with owner-visible stop conditions. Where supported, atomic task claim, fencing and idempotency must protect against simultaneous starts, stale workers and ambiguous create/write results. Expiring a lease without fencing the old writer is insufficient. Do not implement these mechanisms in unrelated ongoing work merely because this note describes them.

## 7. Focused next tests

1. **Fresh-context routing:** The original narrow skill-loading and file-read smoke test is now reported successful in section 3. Do not repeat it or require a coordinator handoff merely to continue work. Directory metadata, fresh-context writes, universal skill invocation and client-only approval behavior are separate scopes; test them only when they resolve a concrete remaining requirement. A screenshot or explicit owner observation is needed to settle client-only UI questions.
2. **Full connector repair, when authorized and source is accessible:** Locate the source and deployment actually owning the App's tools. Test a genuinely inline-text, bounded retrieval implementation, preserving authentication, writes and binary opt-in behavior. Package skills alone cannot override a remote tool. Do not change App bindings through an editor that only permits skill changes, or claim a deployment happened without deployment evidence.
3. **Scheduled successor and duplicate race:** Inspect existing jobs first. Use a bounded, nonrecursive test with an isolated canary output and supported atomic ownership. Check replay, simultaneous claim, uncertain creation result, lease expiry and stale-writer rejection. Respect service cadence and explicit execution restrictions. Do not alter the active review schedule without authorization.
4. **Detached / persistent lifecycle:** When HA's host is reachable, verify an actual task handle, durable output, parent-end behavior, cancellation, recovery and single successor ownership. Distinguish desktop availability, remote endpoint connectivity and provider session capability.
5. **Productive capacity:** Use useful authorized review or deterministic validation units. Save after each unit, compare equivalent inputs, cap experiments, and report an observed lower bound rather than inventing a hard turn limit. Avoid idle loops, repeated downloads and unsupported speed claims.

All research acceptance and textbook publication gates remain unchanged. Other automation-tool work, live HA tasks and repository runtime files remain outside this preservation task.

## 8. New-conversation resume brief

Read this file, adjacent `STATUS.md`, and HA's `AGENTS.md`, `QUEUE.md` and `CHECKS_STATUS.md`. Treat the discoveries as saved observations with independent review pending, not as implemented HA capabilities. Verify the installed GitHub MCP version and read its `github-text-first` skill; keep standard GitHub connected for the tested inline reads. Do not modify GitHub Personal Repos or credentials.

For the separately owner-authorized RE-Wizard continuation, work only on `reviews/b02-batch-continuation-2026-11-02`, read that repository's current instructions and queues, reconcile the saved canonical-stage audit against current remote state, and preserve independent checks. Prioritize unfinished canonical closure requirements rather than rereading accepted claims. Do not claim official closure from mechanical reconciliation. Do not touch BinaryWorkbench, other automation implementation, HA runtime or published book content without the appropriate task and review gates.

Before testing any automated rollover, inspect the existing review and successor tasks. Retain one integration owner and avoid competing writes. Record actual outcomes, not scheduled intentions. A handoff prompt is not permission to bypass host approval or HA's mediated textbook boundary.

## Evidence references and recheck boundaries

- Owner-provided materialization dialog: the initiating observation; transcribed above without embedding the private conversation screenshot.
- Owner-supplied fresh-chat read-only test report: section 3 records its narrow result and limits. No raw trace, complete activity log or independent review of that report was supplied; this save does not claim one.
- Account plugin source/readback: GitHub MCP 1.0.1, especially `README.md`, `plugin.json`, `.app.json` and `skills/github-text-first/references/VALIDATION.md`. These were inspected again for this save; they are account-scoped, not vendored server source.
- Earlier scoped write evidence: RE-Wizard commits `b0a6fb7669293e394ef2cfba68a7db0904365a40` and `da8171a6dd8c2396dc21bb467c5e173e6367243f`, as returned by the earlier tools. Their exact changed-path claims require checking those commits when reused.
- Current scheduled-result linkage and remote audit: section 5. This save verified the audit's retrieval, not every preceding commit or source claim.
- Repository policy: root `AGENTS.md` (observed blob `0a52314c68f1aee2a2fe6878d64c1351e5c45e1e`), `QUEUE.md` and `CHECKS_STATUS.md`.

Independent review should check the source-to-claim distinctions, privacy/scope, plugin-preservation claims, scheduling evidence and proposed acceptance tests. Keep the pending markers until a different qualified session records its review under `checks/`. This document creates no runtime evidence entry or release-status promotion.
