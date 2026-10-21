# Hivemind Assembly roadmap

Version 0.21.1 remains an engineering preview. Implementation, automated
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

The v0.21.0 memory checkpoint `90fc291` passed every job in
[run 39552405664](https://github.com/Artistical-Intelligence/hivemind-assembly/actions/runs/39552405664):
670 Linux tests with 16 skips, 660 Windows tests with 26 skips, fourteen separate
native Windows checks, nine Chromium checks and packaged install/update/restore.
The native PE oracle independently checked virtual-memory return values, page
rounding, zeroing, old protections and exact output bytes.

The v0.21.1 diagnostic checkpoint `bb9de83` passed the full local suite:
677 tests with 16 platform skips, 693 total, in 448.25 seconds. Nine focused
diagnostic checks also passed, including PE-byte resolution and protected-evidence
access. All four hosted jobs then passed in
[run 39553956769](https://github.com/Artistical-Intelligence/hivemind-assembly/actions/runs/39553956769):
Linux 677 passed/16 skipped (421.716s), Windows 667 passed/26 skipped (741.856s),
fourteen separate native Windows checks (27.413s), nine Chromium checks (82.535s)
and packaged Windows install/update/restore. The
[tested Windows/source packages](https://github.com/Artistical-Intelligence/hivemind-assembly/actions/runs/39553956769/artifacts/12324534067)
are retained for fourteen days.

Earlier [run 39543882473](https://github.com/Artistical-Intelligence/hivemind-assembly/actions/runs/39543882473)
passed fresh pinned Ghidra/REA/Hermes installation and actual adapters on Windows.
These are source-known and scripted checks; signed-in model validation remains
separate.

Detailed current and historical evidence is retained in
[`release_status.json`](../_app/release_status.json). Runtime boundaries and setup
instructions are in [README](../README.md); architectural decisions and external
approaches are in [ARCHITECTURE](ARCHITECTURE.md) and
[RELATED_WORK](RELATED_WORK.md).
