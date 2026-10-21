# Hivemind Assembly roadmap

Version 0.25.0 remains an engineering preview. Implementation, automated
verification and live account acceptance are separate. Successful fixtures do not
establish unattended reconstruction or measured native-model learning gains.

## Current implementation

HA is one modular application with a persistent controller, project objectives,
native worker/adviser/reviewer sessions, model-output logging, scoped knowledge,
evaluated learning, independent acceptance and optional verified-source publishing.
Objectives continue through ordinary controller actions; no chat slash command
is required. New objectives have no HA request cap unless the owner sets one.

Ghidra, REA and Hermes remain complete pinned foundations. Specialist adapters
support persistent analysis, batched context, annotations, callgraph planning and
artifact handoffs. The dashboard exposes project files, editing, uploads, examples,
checks, evidence, setup, recovery and backups.

Current reconstruction lanes include register proofs, compiled integer/pointer
function comparisons across x64 and ARM64 ABIs, supplied PE DLL dependencies,
and bounded static/dynamic x64 and ARM64 Linux program replay. Linux process,
file, directory, memory and supplied-random inputs are explicit.

The Windows x64 console lane supports streams, files, raw command-line/environment
inputs and private virtual memory. Version 0.21 adds reserve/commit/protect/decommit/
recommit/release, zeroing, CPU/API permission enforcement and a dynamic-buffer
file-transform starter with a page-crossing case. API writes to read-only PE
sections are rejected. Version 0.21.1 adds guest instruction/image offsets, active
API arguments and faulting buffer addresses for failed replay. Diagnostics do not
participate in equivalence and sealed-original details remain protected.

Trusted native recipes can compile and test general tools or reconstructed
executables against original programs or expected results. Raw RGBA frames,
ordered frame sequences and PCM audio support exact defaults, owner-defined
tolerances, repeatability checks and visual review. Actual offscreen Mesa readback
was previously exercised. These facilities do not establish arbitrary game or
graphics-driver equivalence.

Version 0.22 also applies the shared raw frame/audio comparators to bounded
Windows and Linux program streams/files, including AArch64. Protected cases pin
shapes and tolerances; the dashboard inspects their retained frames and waveforms.
An emulated renderer starter catches a one-frame delay with unchanged final state.
This adds output-level temporal checks, not GPU or arbitrary GUI compatibility.

Version 0.23 adds pinned musl memory routines to Windows and Linux program
builds; 0.23.1 extends the same runtime to linked-function builds for all four
calling conventions, including Windows ARM64. Compiler-generated zero
initialization and struct copies now link without custom helper functions. Candidate definitions retain precedence; source hashes
and embedded license notices are checked during builds. General CRT/OS support
remains a separate scope.

Version 0.24 adds failure locations to static Linux and all four linked-function
ABIs, including relocated supplied DLLs. Guest instruction bytes, image/file
offsets, memory bounds, active syscalls and calling-convention register violations
help diagnose failed reconstruction. Engine-reported timeout distinguishes time
and instruction limits. Pre-execution and periodic cancellation now reaches these
replay engines. Diagnostics stay outside equivalence decisions; sealed-original
preflight evidence remains protected.

Version 0.25 adds project-level reconstruction: dependency-ordered function checks,
recovered-region composition into the original static ELF with original-code
fallback for every other function, cumulative isolation of regions that break the
program, rollback of regressed regions, verified source snapshots for local and
connected projects, a `linux_project` acceptance scope and the fixed three-target
suite. A read-only MCP publication status completes the reconnect path.

Inbound project-scoped MCP, outbound tool grants, standard HTTP OAuth onboarding,
private-tunnel supervision and optional Codespaces snapshot jobs are implemented.
Repository creation and Codespaces are optional. Local-only projects and existing
repositories are supported. Connected projects publish tested source checkpoints;
original inputs, binaries, credentials and runtime state are not automatically
published.

Knowledge classification initially exposes only available tags. Material is
released after scope selection, including an explicit no-relevant-tag outcome.
Scoped conversations, native session renewal, retained learning reservations,
protected evaluations, promotion and rollback are implemented. Experimental
learning defaults off; Chat-only workers and observed model selection preserve
manual overrides and do not impose a default HA usage budget.

## Completion plan: eight delivery stops

These stops close against runnable outcomes. Checkpoint commits and successful
fixtures do not close a live-account requirement. Stops 1–6 complete implementation,
Stop 7 audits the integrated product, and Stop 8 repairs findings and releases it.
They are delivery milestones, not a promise that every milestone fits one chat turn.

| Stop | Work and required outcome | Weight in remaining plan | Status |
| --- | --- | --- | --- |
| 1. First usable autonomous workflow | Trace requirements, establish the host and native sessions, connect category selection, separate worker/adviser, Ghidra/REA analysis, source editing, compilation and independent verification. Close on a real unattended reconstruction with retained artifacts and continuation through checkpoints. | 20% | In progress |
| 2. Resilient agent team | Validate all five actual routes; handle allowance, preferred-route promotion, adviser continuity, review, renewal, cancellation, uncertain sends and application/browser restarts without duplicate operations. Retain useful raw model/tool logs. | 15% | Open |
| 3. Project-level reconstruction | Complete inventories/dependency plans, cumulative builds and real region replacement/fallback with rollback. Exercise the fixed three-target suite below and reject incorrect mutants. | 20% | Implemented; source-known suite passes; live-team run open |
| 4. General coding and integrations | Complete a general programming task through bidirectional MCP with durable disconnect recovery and verified GitHub publication. Exercise optional repository creation, browser-assisted setup, Codespaces/hosted execution and conflict-safe import; retain a local-only path. | 15% | Open |
| 5. Demonstrated long-term learning | Complete category-first scoping, existing-tag/no-tag selection, fresh conversations, persistent knowledge and knowledge/procedure/executable improvement. Demonstrate correctness and measured speed gains on independent cross-project holdouts, with promotion, invalidation and rollback. Preserve optional Chat-only experiments and unlimited HA budgets. | 15% | Open |
| 6. Integrated installation and product | Complete onboarding, settings, status, evidence, recovery and documentation. Verify clean Windows prerequisites, credential persistence, restart, backup/restore and drop-in update. No hidden mandatory implementation TODOs. | 5% | Open |
| 7. Full audit | Audit requirements, correctness, privacy, protected evaluators, credentials, publication, recovery, upstream preservation, maintainability and claims. Produce reproducible findings with severity and repairs. | 5% | Open |
| 8. Revision and release | Resolve audit/acceptance defects, rerun affected workflows and installation/regression gates, package and publish exact source/evidence. No mandatory open requirement or blocking defect. | 5% | Open |

Progress is estimated against this fixed remaining-work plan, not lines of code or
test counts. Current estimate: **about 5% of the plan**, with **Stop 1 about 25%**
and **0/8 stops closed**. Existing implemented capabilities are described above;
this is not a claim that only 5% of the repository has been built. Any change to
scope or weighting must be stated rather than silently changing the denominator.

### Stop 1 implementation and acceptance

- Implemented: continuing objectives wait for root/task acceptance contracts before
  obtaining a native worker lease or spending model turns. Preparation permits
  uploads/edits; pinning checks releases unpaused work; explicit pause survives.
- Implemented: unset usage-page mappings cannot consume the daily polling attempt.
  Setup recovers readiness after a durable session commit without another canary
  request or usage-page fetch inside the existing polling interval.
- Implemented: sign-in/binding recovery rechecks the accepted native session using
  the original fresh allowance observation, without refreshing quota. Exhaustion
  persists on the actual affected route and remains blocked through setup/restart.
- Implemented: shared allowance reservation contention waits in a resumable state.
  Releasing the active reservation lets the waiting project start, including after
  a host restart, without marking the provider exhausted or polling usage again.
- Implemented: the dashboard's autonomous reconstruction trial supplies a compiled
  multi-function x64 ELF, an unfinished C candidate, development inputs and nine
  protected input cases. Original C and protected inputs are absent from the
  project workspace. The objective names Ghidra, REA and the separate adviser.
- Automated coverage: startup/restart/pinning, explicit pause, poll admission,
  session-commit recovery, and a scripted worker/adviser loop that edits actual C,
  rejects a mutant, retains a checkpoint, repairs it and completes fresh independent
  whole-program replay. Scripted responses are explicitly not model acceptance.
- Still open: establish actual signed-in sessions on an execution host; run that
  trial through real Ghidra/REA and model calls; verify retained live evidence and
  publication. No live route or autonomous-reconstruction completion is claimed.

### Stop 3 implementation and acceptance

- Implemented: `compare_project` checks recovered functions in callgraph-plan
  order, composes them into the original static ELF with every unrecovered function
  and all shared data left on original machine code, replays the program corpus,
  isolates any region that breaks the composed program cumulatively in plan order,
  and optionally rebuilds the complete source program. Entry counts expose regions
  that never ran. The composed image is an ordinary executable.
- Implemented: passing host checks retain exact sources for local and connected
  projects; `verified_sources` lists restorable snapshots, and regions from the last
  verified composition that fail again are reported as regressions and rolled back
  to original code. The `linux_project` acceptance scope seals function and program
  corpora and requires named regions to be recovered, not left on fallback.
- Automated coverage: the fixed suite in `application/project_targets.py`.
  The x86-64 utility combines four recovered regions with original `pack`; the
  AArch64 utility is reconstructed as a complete x86-64 program with cross-ABI
  function checks; the game target recovers input, physics, audio and its loop
  while frame rendering stays original and frames/audio use the pinned comparators.
  Thirteen incorrect alternatives are rejected, eight of them only by whole-program
  composition or replay. The composed utility also runs natively on x86-64 Linux with
  output identical to the original. A worker-path test restores a regressed source
  from its verified snapshot and passes protected acceptance. Callgraph plans in the
  unit tests are source-known fixtures.
- Integration evidence: the foundation verifier now pages the actual Ghidra
  callgraph of the compiled utility, plans it and composes the project over that
  plan. On a fresh Linux x86-64 installation (Ghidra 12.1.4, REA 6.7.0, Hermes
  `c0015464f0f4`, JDK 21, Node 24.22.0) every check passed, including
  `project_plan`: 30 Ghidra functions in 30 groups, four regions recovered and
  `pack` plus the 25 runtime/memory functions left on original code. No model
  inference was involved.
- Still open: run the suite through a live native team with actual Ghidra
  callgraph plans; stripped originals rely on owner/Ghidra-supplied addresses;
  inlined original copies of a recovered function are not redirected.

The fixed Stop 3 suite is a multi-function native utility, an ARM64-to-x64
reconstruction, and a small game-related state/frame/audio target. At least one
complete target must run with both recovered regions and fallback regions, and
incorrect alternatives must fail. Arbitrary Windows API/GUI/CRT support or a
commercial game is not an added prerequisite for this completion plan.

Login, 2FA, unavailable exact model targets or a missing execution host may block
live acceptance. They do not close the stop; independent implementation continues.
Native credentials, profiles and protected target data remain outside GitHub.

## Verification

### Session of 2026-10-21, version 0.25 (Linux cloud host)

- Implementation `4f057ab` passed all four jobs in
  [run 39650550445](https://github.com/Artistical-Intelligence/hivemind-assembly/actions/runs/39650550445):
  Linux 807 passed/18 skipped; Windows 788 passed/37 skipped (one rerun after a native
  compile timeout in an unrelated existing test); fifteen native Windows checks; ten
  Chromium checks; Windows package installation, update and restoration.
- Hosted [Windows foundations run 39650087898](https://github.com/Artistical-Intelligence/hivemind-assembly/actions/runs/39650087898)
  and a fresh local Linux installation both passed every foundation check, including
  the Ghidra-callgraph project composition. No model inference was involved.
- Still blocked on this host: no signed-in HA native browser profiles or desktop
  display, so live route acceptance remains 0 of 5 and no unattended reconstruction
  through actual models is claimed.

### Session of 2026-10-21 (Linux cloud host, implementation `1c05abf`)

- Full local suite at `1c05abf` (Python 3.12, Clang/LLD): 795 passed,
  18 skipped (609.94 seconds).
- Fresh pinned Ghidra 12.1.4 (archive SHA-256 matched), REA 6.7.0 and Hermes
  `c0015464f0f4` installed through `dev/check_installed_foundations.py` on
  Linux x86-64 with JDK 21 and Node 24.22.1; source-known adapter verification
  passed. No model inference was invoked.
- Blocked on this host: no signed-in HA browser profiles or desktop display,
  so live native route acceptance remains 0 of 5.
- Unmerged branch `wip/project-level-checks` (`730d080`) adds a dependency-ordered
  `compare_project` function/program check, a protected `linux_project` scope and
  a read-only `verified_sources` rollback lookup. The existing tests it touches
  (50) pass; it has no dedicated tests and is not part of this release.

The Stop 1 startup/trial checkpoint `23cab3483cc7e15d04be5e38095473a57dfac2d4`
passed 69 focused local checks. In
[run 39625848828](https://github.com/Artistical-Intelligence/hivemind-assembly/actions/runs/39625848828),
its Linux artifact records 784 passed/18 skipped (802 total, 419.197 seconds),
and its Chromium artifact records 10 passed (112.731 seconds). Windows records
766 passed/36 skipped (802 total, 1162.090 seconds), plus 15 native compiler checks
(27.910 seconds). Windows packaging also passed. These results belong to that
checkpoint, not to subsequent changes.

The subsequent sign-in recovery change passed 69 focused native/session/controller
checks (6.11 seconds) and 20 native-learning/policy/objective checks (10.55 seconds).
These use scripted model responses; they establish no live provider acceptance.

The reservation-contention regression reproduced an unscheduled dependency wait
before correction. The correction passed 71 focused startup, readiness, policy,
team, coordination and learning checks (6.21 seconds), including same-process
and reopened-store continuation. It does not establish live-model acceptance.


Corrected implementation `73fd1d9` passed all four jobs in
[run 39615843168](https://github.com/Artistical-Intelligence/hivemind-assembly/actions/runs/39615843168): Linux 778 passed/18 skipped
(626.685 seconds); Windows 760 passed/36 skipped (992.269 seconds); 15 separate
native Windows checks (80.399 seconds); ten Chromium checks (109.953 seconds);
and Windows package installation, update and backup restoration. Both full suites
collected 796 cases. The [verified runtime and source packages](https://github.com/Artistical-Intelligence/hivemind-assembly/actions/runs/39615843168/artifacts/12352452923)
include hash-checked manifests and are retained for fourteen days.

The initial diagnostics implementation passed the full local suite: 776 tests and
18 skips in 707.60 seconds. A subsequent boundary regression reproduced stale
completed-syscall metadata on x64 and ARM64. The correction passed all 37 targeted
diagnostics/static-program checks (22.38 seconds), including both new regressions,
before the full hosted suites. The initial integrated linked-call, ARM and memory
suite also passed all 59 checks.

Fresh Ghidra/REA/Hermes installation and actual adapters passed at the same
implementation in [run 39615843195](https://github.com/Artistical-Intelligence/hivemind-assembly/actions/runs/39615843195): compiler,
ARM64 program replay, both Qiling architectures, four linked ABIs with an independent
native oracle, Ghidra context/reopened annotations, REA analysis and Hermes lifecycle.
Model inference was not invoked; desktop prerequisites were preinstalled. These
source-known checks do not establish signed-in model acceptance or arbitrary
application compatibility.

Detailed current and historical evidence is retained in
[`release_status.json`](../_app/release_status.json). Runtime boundaries and setup
instructions are in [README](../README.md); architectural decisions and external
approaches are in [ARCHITECTURE](ARCHITECTURE.md) and
[RELATED_WORK](RELATED_WORK.md).
