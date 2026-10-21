# Hivemind Assembly roadmap

Version 0.23.1 remains an engineering preview. Implementation, automated
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

## Remaining work

| Area | Remaining implementation or acceptance |
| --- | --- |
| Broader reconstruction | Extend target-level coverage beyond current bounded contracts, including broader Windows runtime and graphics/game behavior. CRT, GUI, threads, arbitrary Windows APIs and console-specific loaders remain outside emulated Windows acceptance. Trusted native recipes are a separate execution option. |
| Exact native routes | Validate all five configured routes on actual signed-in accounts: provider, surface, model, mode, effort, account, allowance, completion, transfers and renewal. Resolve adapter gaps revealed by these checks. Ambiguous controls remain blocked. |
| Autonomous reconstruction | Run a real unattended worker/adviser/reviewer/Ghidra/REA reconstruction through interruptions, handoffs, fresh independent acceptance and verified checkpoint publication. Scripted model responses do not close this gate. |
| Learning effectiveness | Measure correctness and speed gains across independent native projects and repeated trials, including provider account-wide memory isolation. Retrieval, fixtures and promotion logic alone are not evidence of improvement. |
| Live integrations | Exercise authorized MCP OAuth consent, web-chat tunnel access, GitHub setup/publication, optional Codespaces delivery and HA-dispatched hosted jobs on live accounts. Local protocol and recovery checks already exist. |
| Desktop installation | Validate WinGet prerequisite installation on a real desktop. Hosted Windows runners supplied prerequisites; package installation/update/restore and fresh foundation installation have passed. |
| Audit and revision | Perform the separately requested full audit, then revise its findings. This implementation pass is not that audit. |

## Verification

The linked-memory implementation passed the full local suite: 745 tests and
18 skips, 763 total, in 678.83 seconds. Fifteen focused linked-memory checks and
69 integrated linked-call/ARM/dependency checks passed across all four calling
conventions. The program-memory runtime passed 34 focused checks (one skip) and
64 integrated program/capture checks (two skips).

Hosted Linux exposed a five-second wall-bound failure when all 64 unoptimized
ARM corpus commands shared one replay. The unchanged corpus now runs in eight-case
batches, retaining the product's execution limits. All eight compiler/optimization
corpus combinations passed locally after this correction (27.16 seconds).

Corrected checkpoint `2512728` passed all four jobs in
[run 39608363476](https://github.com/Artistical-Intelligence/hivemind-assembly/actions/runs/39608363476):
Linux 745 passed/18 skipped (565.805 seconds); Windows 727 passed/36 skipped
(859.134 seconds); 15 separate native Windows checks (61.578 seconds); ten actual
Chromium checks (122.384 seconds); and Windows package installation, update and
backup restoration. The [verified runtime and source packages](https://github.com/Artistical-Intelligence/hivemind-assembly/actions/runs/39608363476/artifacts/12349711822)
are retained by that run. The source and runtime archives were also independently
hash-manifest checked locally, including all pinned memory sources and notices.

Fresh Ghidra/REA/Hermes installation and actual adapters passed at `a2eadb2` in
[run 39606521680](https://github.com/Artistical-Intelligence/hivemind-assembly/actions/runs/39606521680):
compiler, ARM64 program replay, x64/ARM64 Qiling file/process behavior, four linked
ABIs with an independent native oracle, Ghidra context/reopened annotations,
REA analysis and Hermes lifecycle. Model inference was not invoked; desktop
prerequisites were preinstalled. No live native-model or arbitrary application
compatibility claim follows from these source-known checks.

Detailed current and historical evidence is retained in
[`release_status.json`](../_app/release_status.json). Runtime boundaries and setup
instructions are in [README](../README.md); architectural decisions and external
approaches are in [ARCHITECTURE](ARCHITECTURE.md) and
[RELATED_WORK](RELATED_WORK.md).
