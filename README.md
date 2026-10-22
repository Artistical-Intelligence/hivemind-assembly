# Hivemind Assembly

A local reverse-engineering workspace for collaborative agents, independent verification, and reusable learning. Current version: 0.25.2. Ghidra and REA remain complete foundations; task control, native browser sessions, evidence, and learning are integrated around them.

## Start on Windows

1. Download **Hivemind_Assembly_<version>_Setup.exe** from the [latest release](https://github.com/Artistical-Intelligence/hivemind-assembly/releases/latest) and run it. It installs for your Windows user without administrator rights and adds a Start menu shortcut. The installer is not code-signed, so SmartScreen may warn: choose **More info → Run anyway**. You can choose the installation folder.
2. The first start installs the bundled Python runtime and the hash-locked Windows dependency set into your user data directory, then opens the dashboard. The first dependency installation needs internet access.
3. The dashboard offers **Install required tools** until Ghidra, REA and Hermes are installed. Setup uses WinGet to install missing Git, Node.js 24.11+ (24.x) or 26+, Java 21+ and a C compiler, then installs and checks the pinned foundations on a source-known fixture. The same step also installs the GitHub CLI (for Codespaces) and the MCP tunnel client; if one of these optional tools fails, the rest of setup still completes and the result says which one to retry. Windows may require system authorization or a restart. HA loads the new paths without restarting; existing installations can be configured in **Settings**.
4. Open **Project files** and choose **Create register example**. Run tests, edit `candidate.hex`, save, and check again. The native Python example also works without a compiler after you authorize its supplied recipes. **Semantic self-check** exercises the verifier separately.
5. Use **Set up AI assistants** on Overview. Setup reuses dedicated sign-ins, discovers exact controls, creates separate conversations and verifies two-way attachment transfers. Unrecognized controls or allowance mappings remain unverified; `_app/NATIVE_SETUP.md` describes the recovery path. Each role retains its designated provider, surface, model and effort. Inference APIs, paid overage and manual relay are not fallbacks.

To update, run the newer installer (or extract the newer ZIP over the old folder). Uninstalling removes only application files. The application uses dedicated Edge, Chrome or Playwright profiles. It does not copy your everyday browser credentials. User data remains in `%LOCALAPPDATA%\UnifiedWorkbench`, outside the application folder. The host must remain running for autonomous work.

Every CI run also retains the installer and ZIPs as a 14-day workflow artifact. When the full CI passes on `main` with a version that has no release yet, the release workflow rebuilds, installs, upgrades, uninstalls and verifies the packages, then publishes them as release `v<version>`. A version tag or a manual run also publishes.

## First autonomous reconstruction trial

After installing the foundations and verifying native sessions, open **Project
files → Create autonomous reconstruction trial**. HA builds a small multi-function
x64 ELF and prepares an unfinished `candidate.c`, `build.json`, two development
inputs and nine pinned independent cases. The original C source and protected
inputs are not placed in the project workspace. Choose **Projects & tasks →
Project objective → Start** to have the team investigate, edit and compare it.

The empty candidate deliberately fails checks. The objective requests Ghidra and
REA analysis and a separate adviser; checkpoints do not finish it. Completion
requires independently rebuilding the saved candidate and replaying the pinned
corpus. This is a synthetic finite-corpus exercise, not proof of arbitrary program
equivalence. Creating the trial or passing scripted transport tests does not verify
real signed-in model operation.

## Working with a project

Create a project in its prepared state. In **Project files**, upload targets, browse files, and edit UTF-8 candidates. Save preserves the previous bytes and refuses stale overwrites; polling never replaces an unsaved draft. Uploads accept files up to 256 MiB each, and the text editor supports 512 KiB. Larger targets can use local-path import. For Python scripts, single C sources and executables, use **Configure a native comparison** in **Project files**: select a candidate and optional original, enter input cases and expected text, and authorize execution. The advanced recipe and other acceptance types remain in **Projects & tasks**. Run the pinned checks directly from **Project files** before resuming agents. **Download file** retrieves the exact version you opened. Manual checks leave the task paused and do not declare autonomous completion. Workers declare bounded steps, receive an adviser briefing, request broker operations, and use the retained results to continue. Separate reviewer sessions support recovery.

For a bounded x86-64 integer register region, **Independent acceptance → Register equivalence proof** pins the original bytes and names the candidate file, input registers and observed outputs. Completion independently reads the candidate and reruns the proof. Missing files, counterexamples, unsupported semantics, stale ownership and concurrent changes prevent acceptance. Failed supported checks return their evidence for up to three correction attempts. New continuing objectives remain `waiting_setup` until their independent checks are pinned; no native worker is assigned and no model request is spent during preparation. Pinning checks starts unpaused work automatically. Explicitly paused projects stay paused. Older tasks that already proposed completion without a contract remain `awaiting_acceptance`.

Hexadecimal text and binary regions are supported. These proofs cover only their listed observations and recorded assumptions; they do not establish whole-program equivalence.

For a recovered scalar C function, choose **Compiled C function comparison**.
Install Clang or GCC (or set `foundations.c_compiler`), name the function and its
unsigned argument/return widths, and provide the original function bytes including
its return instruction. The compiler builds a separate object; the evaluator runs
both implementations in Unicorn on protected boundary and random inputs. This lane
supports branches, loops and private stack use under the SysV x86-64 calling
convention. It rejects includes, inline assembly, external symbols and relocations;
pointer arguments, external data and OS behavior are outside its scope.

To check a candidate locally without native sessions:

```bash
python _app/launch.py check-function --candidate recovered.c --original 89f801f0c3 --function recovered --argument-bits 32,32 --output-bits 32
```

This command uses public development samples. Project completion uses separately
pinned evidence and reruns the build against the actual candidate file.

## Capabilities

- Persistent Ghidra projects, inventories, batched decompilation, memory layouts, imports, types, strings, references, raw bytes, instruction P-code and guarded annotations with saved-operation reconciliation. REA static queries include complete function analysis, literal search, references, byte reads, call targets and bounded data-flow tracing. Complete native installations remain available.
- Retained local operations and batches of independent checks continue without model allowance. Response timeouts use persistent bounded backoff; uncertain deliveries retain their original request identity.
- SQLite task ownership, writer epochs, revision checks, durable handoffs, operation journals and immutable artifacts. Restarted native exchanges retain their request IDs.
- Exact native route/account observation, shared-allowance admission, one scheduled usage attempt per account scope per rolling 24 hours, separate role conversations and late-response rejection.
- Automatic large-result attachments when configured, hash-checked returned downloads, bounded artifact reads and guarded binary/text saves.
- Original-preserving document ingestion, revision-aware required reading and explicit source-sharing permissions.
- Real SLEIGH/P-code lifting, independent Unicorn differential execution, scoped Z3 proofs and an executable hybrid recovery fixture.
- Acceptance evidence, project controls, sources, baseline methods, learned assets, rollback, settings and workspace backups in the dashboard.

## Learning

Accepted work retains evidence-backed knowledge and procedure candidates. A single success does not activate them across projects. Structured playbooks support localized, hash-guarded edits that preserve untouched details and exceptions. Active context is ranked within a budget and checked for dependency and route compatibility; proposals still require independent evaluation.

The executable workflow engine runs bounded registered operations without arbitrary shell or Python execution. Workflows compose region proofs and deterministic function/image calls, pass selected outputs between steps, and reuse identical operations within one invocation. Evaluation uses protected, family-separated regression and holdout cases; repeated trials alternate baseline/candidate order and compare all outputs. Promotion requires preserved correctness, measured aggregate speed improvement and bounded per-case slowdown. Execution is tied to the verified engine/dependency fingerprint, and active assets can be rolled back.

Captured lessons move through a visible pipeline (**Knowledge & skills → Learning
pipeline**): owner permission to send them to native trials, categorization when the
task chose no tags, then native evaluation against a protected suite and promotion
only on measured gains. Two owner settings, both off by default, remove manual steps:
*send captured lessons to native trials* and a *default suite* for future captured
lessons. Each lesson shows the step it is waiting for. Promotion accepts only
evaluations the host ran itself over a protected suite; caller-supplied results are
advisory.

For an independent holdout that HA did not author, **Build or import protected
corpus → HumanEval-Decompile** fetches the C subset of the public LLM4Decompile
benchmark (MIT; pinned commit and SHA-256) and seals its tests. Problems, not
optimization levels, define families, so a problem never spans regression and
holdout. Scoring compiles each candidate with the benchmark's own test and runs it
on this computer, so it also needs *Allow public benchmark checks to run candidate
code* in Experimental learning.

Use **Knowledge & skills → Evaluate workflow optimization** and choose proofs or function calls, or run `python _app/launch.py learn --workflow calls --data-dir <state-directory>` while the application is stopped. The two built-in optimizers each measure four local cases; function calls include independent scalar and pointer-buffer expectations. These measure bounded reuse optimizations. Native knowledge/procedure effectiveness and broader real cross-project improvement remain unverified; the donor-backed candidate and evaluation paths are described below.

## Updates and architecture

Extract a new release over the application folder. Settings, projects, originals, browser profiles, artifacts and learned assets remain in the user data directory. Stop the application before updating or copying that directory. The dashboard creates a verified workspace ZIP, including controller and project data.

One application contains separate core, automation, learning, reverse-engineering and UI modules. Legacy `workbench` imports, existing data paths and older launchers remain compatible. See [architecture](dev/ARCHITECTURE.md), [roadmap](dev/ROADMAP.md), and [related-system decisions](dev/RELATED_WORK.md).

## Development and verification

Use Python 3.12. Windows release dependencies are fully locked in `_app/requirements-windows.lock`; `dev/lock_windows.py` checks Windows-specific dependency markers and wheel hashes. Source archives include the pure-Python bootstrap wheels needed to reproduce that lock.

For development:

```bash
python -m venv .venv
# Activate the environment for your shell.
python -m pip install -r _app/requirements.txt pytest
python -m pytest tests -q                 # everything (CI)
python -m pytest tests -q -m "not slow"  # quick tier, about two minutes
python dev/status_docs.py                # status blocks match release_status.json
python _app/launch.py verify
python _app/launch.py serve
```

The expanded compiler corpus uses GCC and Clang at O0/O2 over 24 functions
from 12 families (96 variants); `python dev/corpus/verify.py DIRECTORY` compares
5,472 vectors with source-known native execution and rejects a wrong mutant.
`python _app/launch.py verify-foundations --data-dir STATE` runs the installed
compiler, Ghidra, REA and Hermes checks without inference.

For linked PE/ELF tests, install Clang and LLD on PATH or set `HA_TEST_CLANG` and `HA_TEST_LLD` to their executable paths. Missing compilers produce explicit skips.

Set `WORKBENCH_TEST_CHROME` to a Chromium executable to run the local browser transport/upload/download fixture. Run `npm install`, `npm run test:dom` and `npm run test:native-dom` inside `dev` for dashboard interaction checks. `_app/release_status.json` records verification evidence.

Local scripted team and browser fixtures do not constitute live-provider acceptance. The five signed-in routes, unattended native orchestration, desktop prerequisite setup and broader application reconstruction remain unfinished acceptance or implementation work. Hosted Windows checks passed package install/update/restore and fresh installation of the full pinned foundations, including actual Hermes SessionDB/Kanban, Ghidra import/decompile/context/annotation and REA analysis. The runner supplied Git, Node, Java and the compiler; WinGet installation remains unverified. The OpenAI Python package is an upstream Hermes import dependency; this application does not instantiate model API clients.

## GitHub project repositories

Use **Connect with Client ID** for browser-assisted registration
and connection. Alternatively, expand **Connect with an existing Client ID**,
enter an OAuth app's public Client ID and approve its device code. Device Flow
must be enabled; an existing app's callback URL can stay unchanged.
No client secret is required for this local sign-in. HA requests `repo` access
and refreshable authorization. Tokens are stored in Windows Credential Manager,
macOS Keychain or Linux Secret Service, outside projects, settings and backups.
An unlocked supported OS credential store is required; there is no plaintext
fallback. **Test GitHub connection** verifies an authorization after restart.

Repository creation is optional. Choose **Connect existing private repository**
to use an existing repository, or leave the project local without GitHub.
To create a new one, enable **Allow private repository creation for projects**. Use **Projects &
tasks → Project repository** while preparing a project, or let its assigned
worker request `create_repository` through the broker. Workers also have
`repository_status`, and the verified repository is included in their project
context. The capability is independent of the reverse engineering domain.
The personal account is the default owner; organizations must be explicitly
listed in GitHub settings and permit the connected account to create repositories.

Each project has one primary repository, reused across tasks and experiments.
New repositories start private and empty. With **Automatically push verified source
checkpoints** enabled (the default), successful supported reconstruction comparisons
queue checked source and manifest snapshots during the run. Local-only projects
continue without GitHub. Compilation alone does not trigger publication.
Publication never force-pushes or uploads binaries, private runtime logs or protected
evaluation data. Remote conflicts stop publication for reconciliation. A name collision
is reported without modifying the existing repository. GitHub may reject an
organization request because of its policy or the account's permissions.

If a request is interrupted, use **Results & backups → Reconcile saved
operation**. HA checks the recorded repository identity, privacy and write access
before accepting it; it does not blindly repeat an uncertain creation request.
If the repository remains inaccessible, the request stays unresolved rather
than creating another repository. Reconnect the original account and reconcile
again. Permission denials are reported separately and can be retried after
fixing authorization. Disconnecting locally removes saved credentials; revoke
access in GitHub's application settings to revoke authorization on GitHub too.

## Automatic GitHub setup

In **Settings**, choose **Connect with Client ID**.
The visible browser creates or reuses a distinct local OAuth application,
configures its required fields and Device Flow, reads the public Client ID,
and starts authorization. Sign-in, passkeys, 2FA or provider challenges remain
in the browser. Setup keeps running while you complete those steps. An interrupted
registration is reconciled by its retained unique name before another submission.
No client secret is generated or copied. Tokens live in the OS credential store.
Enable private repository creation after connecting; every creation uses the
same durable operation journal and uncertain-write reconciliation as agent work.
The setup state machine has automated fixture coverage; its current GitHub UI
selectors still require live-account validation.

## Model and tool review

**Activity logs** searches requests, partial and complete model responses,
validation errors, tool calls and results by task, role and text. Responses are
captured before parsing and correlated by observed browser turn order. Review
notes are append-only. JSONL exports stay local. An optional explicit export
sends batches in OpenInference/OTLP format to a local Phoenix listener on port
6006; viewer downtime does not interrupt capture. Hidden provider reasoning and
unreported token counts are not invented. Logs are private owner data and are
not supplied as worker context or included in repository publication.

## Cumulative Linux program reconstruction

A build manifest contains `sources` (relative C file paths), optional shared
`declarations`, and `optimization` (`O0` or `O2`). Define `int ha_main(void)` and
use `ha_read`, `ha_write` and `ha_exit` for the explicit runtime boundaries.
`build_program` links multiple translation units, calls and global data into a
static x86-64 Linux ELF. `compare_program` replays development inputs under
Unicorn. Cases with `runtime: "qiling_linux"` use the complete pinned Qiling
engine for declared guest files, memory mapping, file descriptors, fixed time
and supplied random bytes. Files are absolute guest paths mapped to hexadecimal
contents; a fresh root is staged for each execution. `ha_open`, `ha_close`,
`ha_seek`, `ha_file_read`, `ha_file_write`, `ha_map` and `ha_unmap` expose those
boundaries to recovered C. Cases may also declare `argv` (including the program
name) and `env`; both replay engines supply exactly these UTF-8 inputs and never
inherit host environment variables. Defaults are `["program"]` and `{}`.
Recovered C reads them through `ha_argc()`, `ha_argv(index)` and `ha_getenv(name)`.
Direct clock/random instructions and port I/O are rejected in the low-level lane.
The x86-64 Qiling dependency lane uses a verified Haswell guest CPU and a fixed timestamp
counter tied to `clock_ns`; CPU random instructions still stop replay. Host files, process creation and networking are not
forwarded. `ha_mkdir`, `ha_rmdir`, `ha_remove`, `ha_rename`, `ha_clock` and
`ha_random` expose the corresponding declared effects to recovered C.

**Complete Linux x64 / AArch64 program** acceptance supports static ELF for both architectures, and bounded dynamic
ELF/PIE originals for both architectures under Qiling. AArch64 replay supports declared
files, directories, mappings and supplied random bytes, with a verified Cortex-A72
guest CPU. Cross-architecture reconstructions can use observable comparison when
the two ABIs express the same file operation through different syscall sequences.
`original_dependencies` maps absolute guest
interpreter/library paths to files in the project. Every dependency is protected
and hashed; no host libraries are discovered automatically. The rebuilt C
candidate remains freestanding and static. Loader metadata, mapping, TLS setup
and single-thread registration use an explicit guest contract. Constructors
cannot consume standard input or perform external writes before program entry.
Loader activity is retained separately from application events. Stopped Qiling
replays retain the guest instruction address/bytes, loader or application phase,
active syscall, declared image identity and executable mapping. Program virtual
addresses can be looked up in Ghidra; host staging paths are omitted. These
diagnostics accompany comparison evidence and never relax acceptance. Failed
original preflight also retains a protected diagnostic artifact for owner review.

Static Linux replay and linked-function calls across all four supported ABIs also
return `stop_context` on failure. It retains the last observed instruction address
and bytes, the current program counter, executable mapping, image hash and image/
file offsets. Supplied PE dependencies identify their own DLL and relocated base,
with the original source hash and base retained separately. Invalid memory accesses
include direction, size and, when applicable, the caller buffer and exact bounds.
Static programs identify the active unsupported syscall; linked calls identify
registers that violate the calling convention. Unicorn's timeout query distinguishes
wall-clock exhaustion from instruction exhaustion. Cancellation is checked before
execution and every 1,024 instructions. Successful calls have no stop diagnostic;
these fields never affect equivalence. Sealed-original preflight failures retain
protected diagnostics available to the owner and evaluator.

For targeted Ghidra inspection, select the diagnostic's `image`. For a relocated
DLL imported at its original base, translate the observed instruction address as
`program_counter - image_base + original_image_base`. `source_image_sha256`
identifies the supplied original; `image_sha256` identifies the loaded image.
`stop_reason` distinguishes `instruction_limit`, `wall_clock_limit` and
`abi_violation`. Successful completed syscalls are not labeled active when a bound
stops replay immediately after their return.

ARM dynamic replay supplies baseline FP/ASIMD capability metadata, guest TLS,
explicit ordering barriers and backward-compatible BTI hints for its Cortex-A72
CPU. SVE, LSE, PAC, MTE, hardware counters and cache-line zero operations are not
modeled. The interpreter and libraries must match the dynamic program architecture.
A static reconstruction may inspect the preserved original dependency files,
but does not execute them. Actual glibc startup, printf, initial-exec and dynamic
TLS have regression fixtures; this is not arbitrary Linux compatibility.

Acceptance pins the original, dependencies and input corpus, rebuilds
independently, and retains the resulting executable. Strict mode (the default)
also matches recorded application effects and random consumption. Explicit
`effect_policy: "observable"` compares stdout/stderr, exit, stdin consumption,
paired memory and final file/directory contents, allowing a different allocator
or library implementation. Both modes retain event traces. Neither ignores a
fault, unsupported syscall, missing dependency or exhausted startup budget.
This lane is bounded Linux reconstruction, not arbitrary Windows/game/OS
compatibility or an all-input equivalence proof.

## Project-level reconstruction with original-code fallback

`compare_project` checks a whole project rather than one function. Its manifest
(`project.json`) names either a complete-program `build` manifest or the region
units (`sources`, `declarations`, `optimization`), and lists every recovered
function with the units that define it and the calling convention it was written
for (`sysv` or `aapcs64`). Optional `addresses` give `{address, size}` for stripped
originals. A Ghidra `plan_reconstruction` result orders the work dependency-first.

1. **Function checks.** Each declared function with linked-call cases is rebuilt
   alone and compared with the original function. The report gives the verified
   prefix of the plan and the first failing group.
2. **Region composition** (same architecture as the original). Recovered functions
   are linked above the original image and each original entry is redirected to
   them. Everything else, including global data, the runtime and every unrecovered
   function, keeps running the original machine code. The composed static ELF is
   an ordinary executable; the test suite also runs it natively on x86-64 Linux.
   If the composed program diverges from the original, regions are re-added
   cumulatively in plan order and each region whose addition breaks the program is
   rejected with its failing cases and left on original code. Entry counts show
   whether each region actually ran; a region that never ran (for example because
   the original compiler inlined it) is reported as unexercised, and a program-only
   region that never ran cannot pass.
3. **Complete program** (when `build` is named). The source-only program is rebuilt
   and replayed. This is the path for cross-architecture work, such as an AArch64
   original reconstructed as x86-64 C.

Every passing host check retains its exact sources as content-addressed artifacts,
for local-only and connected projects alike. `verified_sources` lists recent
snapshots and whether the workspace still matches them; restoring one uses ordinary
fenced `write_file` operations. A region that belonged to the last verified
composition and now fails is reported as `regressed` and `rolled_back` to original
code automatically.

**Windows console executables.** The same composition works for x64 PE
originals: recovered regions are linked by lld-link as new sections that begin at
the original image end, unrecovered functions and data bind to absolute addresses,
each replaced entry receives a jump and the image is marked non-relocatable so the
regions stay valid. Frames and audio use the Windows capture comparators. PE files
rarely carry symbols, so region addresses come from the manifest's `addresses`, from
an owner-built image's linker map (`build_windows_program` returns `symbols`) or from
a saved Ghidra inventory (`inventory_path`; detached chunks are bounded by the next
function entry). Recovered regions have no unwind data.

**Ordinary libc programs.** Composition binds only the symbols the regions use, so
static glibc tools compose too; the test suite runs one natively and a wrong region
changes its output. The emulated lane still stops such images at CPU feature probes
(CPUID), so they are checked through owner-authorized native test recipes.

**Inlined originals.** For a region that never ran, `no_direct_callers` names
regions whose original entry no direct call or jump reaches: the original compiler
inlined them or they are reached only indirectly.

The `linux_project` acceptance scope seals the original, the program corpus and
every function corpus. `required_functions` must be recovered and validated, not
left on fallback code, and `minimum_recovered` sets how many regions must be
accepted. Rejected-region case details stay protected.

The dashboard's *game project example* recovers input, physics, audio and the
main loop of a small game while frame rendering stays on original code. Its
physics region passes its function cases but breaks the composed program at the
right wall; the check rejects it until it is repaired. Frames and audio use the
pinned RGBA/PCM comparators. Region replacement redirects entries through
symbols; copies the original compiler inlined into other functions are not
redirected, and inputs outside the declared corpus are not established.

## Coordination and learning

Hermes Kanban owns task dependency readiness and claims. Native workers can
propose a bounded dependency graph after an adviser brief; children must pass
their pinned checks before the root resumes final integration. Project leases
serialize shared-workspace writers. Graph publication and controller handoff
are reconciled after interruption.

ACE-derived reflection and curation run through the native adviser. SkillOpt
applies bounded procedure patches; its validation gate supplements protected
correctness and timing checks. Shinka selects parents from measured candidate
archives. Workers can propose revisions to active executable workflows; the
host evaluates them against a bound protected suite and only promotes qualifying
results. The generic experiment interface supports trusted domain evaluators
with family- and project-separated holdouts and paired timings. Native knowledge/procedure rollout evaluation is connected to the dashboard.
Build a protected corpus, allow sharing for a candidate and select its worker
route. Paired trials use separate conversations, keep expected outputs local,
retain interrupted results, respect shared reservations and promote only after
independent checks. Binding a suite also schedules future revisions of that
asset. Compiler/evaluator fingerprints invalidate stale learning evidence.
Local fixtures validate this control flow; they do not establish live native
learning gains or account-wide memory isolation. Upstream licenses and exact module provenance
are retained under `_app/hivemind_assembly/vendor`.

## Backup and restore

**Back up now** saves controller metadata, model logs, learning state,
originals, workspace/native project files, artifacts, sources, settings and
Hermes databases in a verified ZIP. Pause active work first. Browser profiles
and OS credentials are excluded and require reconnecting. Restore offline to an
empty directory with `python -m hivemind_assembly restore --backup FILE.zip
--data-dir EMPTY_DIRECTORY`. The application folder can be replaced without
moving or clearing its external user data directory.

Installation and **Check installed tools** now run source-known process/file
replay and ELF/PE pointer probes. A native shared library supplies an independent
result on the installed host (including a generated DLL on Windows). Each probe
retains its own result, so a missing runtime does not hide the other failures.
These probes passed on hosted Windows, including the native DLL oracle and all four function ABIs.

Current implementation and verification limits are recorded in
`_app/release_status.json`. The full audit is a separate pass.

## Linked x86-64 and AArch64 function reconstruction

Choose **Linked x86-64 / AArch64 function calls** in Independent acceptance.
An original function may be selected by symbol or absolute address. The candidate
uses a sources/declarations/optimization build manifest, a function symbol and
`sysv`, `win64`, `aapcs64` or `winarm64` ABI. Windows and AArch64 builds require Clang and LLD.
The original and candidate may use different supported architectures and ABIs.
AArch64 accepts static little-endian ELF and standard ARM64 PE images with base integer/pointer
calls, with 16 arguments, eight register arguments and aligned stack arguments.
The compiler uses each target’s real C data model (LP64 versus Windows LLP64);
matching C spellings alone do not establish matching behavior. ARM64EC/ARM64X
are unsupported. Explicit ARM64 DLL dependencies use the same bounded import/relocation lane as x64; mixed architectures are rejected.
Callee-saved integer registers and the low 64 bits of v8-v15 are checked; x18 is
reserved. System-register access, TLS, exceptions, authenticated branches, SVE/SME,
floating-point parameters, aggregates and variadic interfaces are outside this lane.

After installing Clang/LLD, use **Project files → Create AArch64 example** to
compile an ARM original and check an editable x86-64 C reconstruction. The example
includes pinned cases and a deliberate wrong-edit exercise; target code runs only
in Unicorn. You can run these checks without any model account.

Cases contain `arguments`, `buffers` and `output_bits`. Pointer arguments use
`{"buffer":"data","offset":0}` and buffers use `{"id":"data","hex":"01000000"}`.
Multiple pointers can reference the same buffer. All buffer bytes and the integer
return are checked; writes to read-only buffers or outside exact bounds fail.
Protected acceptance requires at least two cases and rebuilds independently.
Optional `original_dependencies` maps DLL filenames to project paths. Supplied
x64 PE dependencies are relocated and their named/ordinal imports and forwarded
exports resolved using pefile. Missing imports, TLS, DLL initialization,
image-global writes and operating-system effects stop verification.

Function inventories and static callgraphs support pagination. The
`plan_reconstruction` capability validates a complete set of callgraph pages,
groups mutually recursive functions and orders groups by their dependencies.
It retains external targets and does not claim to discover all indirect calls.

## Persistent objectives

New projects automatically retain their objective in HA's controller. Prepared
projects stay paused while targets and acceptance checks are configured. Use
**Projects → Project objective → Start** when ready. HA continues across turns
and restarts until the root task's independent acceptance checks pass; child
completion, progress summaries and checkpoints do not finish the objective.
This mechanism does not depend on slash-command support in any model's chat UI.

Use the Start, Resume, Pause continuation and Stop continuation controls directly.
Pause/stop take effect at the next step boundary; task pause/cancel can interrupt
active work. All worker, adviser and reviewer requests, including project children,
share one optional request allowance. New objectives have no HA request cap;
existing configured limits are preserved. Retrying the same retained request counts
once. Request allowance accepts a maximum or **No HA request limit**. Raising
a spent allowance does not silently resume work. Exact native routes and provider
allowances still apply; no auxiliary API judge is used.

Automation calls `ha_goal` with `task` and `action` (`status`, `start`, `pause`,
`resume`, `clear`, or `budget`). For `budget`, supply an integer `max_turns`;
zero explicitly means unlimited. The local `/api/goal` endpoint accepts the same
structured fields. Legacy `command` strings remain a compatibility adapter for
older integrations; neither the dashboard nor the automated path needs them.

## Native executable and tool testing

**Projects → Native program & tool tests** supports an owner-defined JSON recipe
for a reconstructed application or general-purpose utility. Pin the recipe before
starting the task, including its original program or exact expected outputs.
The original and cases remain protected; workers request `test_programs` with
empty arguments and cannot substitute commands or rewrite the oracle. Completion
rebuilds/retests and checks source hashes. Permission can be revoked per project.
Passing publishable source checks feed automatic GitHub checkpoints when enabled.

Native testing executes real code with the host account's access. It is optional
and requires explicit owner permission. Fresh working folders, stripped environment
credentials and process cleanup are not a security sandbox. Use trusted code on
your installation or an appropriately isolated disposable runner. Emulated and
symbolic verification remain available without this permission.

Each recipe declares program files, command argument arrays, optional build
commands, cases, observed output paths and repetitions. `{python}` selects this
installation's Python; `{cc}` selects the configured compiler. Programs build once
per suite; every execution receives fresh files. Comparisons include exact binary
stdin/stdout/stderr, exit status and selected output-file hashes. Repetitions detect
unstable observations; matching crashes, timeouts and incomplete output never pass.
Raw streams, selected file bytes, build logs, timings, source hashes and optional
diagnostic files are retained for review. Tests establish sampled observations,
not equivalence for all inputs or unobserved effects. Programs needing services,
interactive input or hardware require a corresponding test recipe/environment.

Bundled examples:

- `_app/examples/native_cli`: independently written C implementations, different
  optimization levels and three exact input/output cases, including unsigned overflow.
- `_app/examples/offscreen_gl`: a Linux Mesa/EGL fixture that creates a real offscreen
  OpenGL context, reads back RGBA pixels and compares them with an independent buffer.
  It needs EGL/OpenGL libraries; unsupported graphics setup is a failure, not a fake frame.
- `_app/examples/audio_replay`: an independent Python reference and compiled C
  reconstruction replay sample-indexed level changes into signed stereo PCM.
  Silence, a pulse and level changes are checked without an audio device.
- `_app/examples/frame_replay`: independent Python and C software renderers replay
  frame-indexed movement into sixteen RGBA frames. **Create frame replay example**
  in Project files prepares the project and protected checks. Run tests, change
  `tick == frame` to `tick == frame - 1` in `candidate.c`, save and rerun. The delayed
  input fails intermediate frames despite matching final state. This example needs
  a C compiler; it does not require a GPU or model account.

Recipes may declare `comparators` for selected `output_paths`. Unlisted files
remain byte-exact. For a frame, use
`{"frame.rgba":{"format":"rgba8","width":16,"height":16}}`.
Pixels are tightly packed RGBA bytes in stored row order, including alpha.
Optional `max_channel_error` and `max_bad_pixels` default to zero. The result
reports changed pixels, peak channel error and the bounds of pixels exceeding
the threshold. Every selected frame must be present at the declared size.

For an ordered capture sequence, use
`{"frames.rgba":{"format":"rgba8_sequence","width":16,"height":16,
"frames":16,"frame_rate_num":60,"frame_rate_den":1}}`.
Frames are concatenated RGBA8 buffers, compatible with FFmpeg rawvideo. Every
frame is compared at the same index, including alpha; the pixel allowances apply
independently to each frame. Missing, extra, shifted or reordered differing frames
fail. No frame matching or averaging can hide a bad frame. Reports retain each
frame's metrics and the first differing and failing indices. A sequence is bounded
to 4,096 frames and the existing 2 MiB output limit. Both frame-rate integers must
be positive (at most 1,000,000); use 30000/1001 for fractional sampling rates.
The rate labels declared sampling positions, not measured wall-clock or display
timing. If timing itself is part of the contract, record it in an additional exact
output file. Identical bytes cannot reveal duplicated indistinguishable frames.

For audio, use `{"audio.pcm":{"format":"pcm_s16le","channels":2,
"sample_rate":8000,"frames":32}}`. Samples are interleaved signed 16-bit
little-endian values. Optional `max_sample_error` and `max_rms_error` default to
zero and both must pass independently for every channel. Sample count and channel
order remain exact. There is no time alignment, resampling or gain adjustment.
Sample rate describes the capture contract; raw PCM cannot prove hardware timing.

Tolerances are pinned with the owner's recipe and cannot be changed by workers.
Each program must still produce identical observations across repetitions,
even when differences between the original and reconstruction are tolerated.
Exit status and stdout/stderr remain exact. **View recorded output** beside workspace
checks, or **View latest results** in test setup, shows frame and per-channel
waveform previews with quantitative comparison results. Sequences have a shared
reference/candidate slider and a jump to the first failing frame.
Each preview also offers a raw download of its complete stored capture, preserving
the original pixel/sample bytes for external inspection rather than re-encoding
the canvas. Downloads stay on your computer unless you choose to share them.
Captures and oracle details stay in protected evidence, tied to the task and
suite that produced them; they are not disclosed to workers or published.

For CLI use, run `python _app/launch.py test-programs --suite SUITE.json
--workspace INPUT_FOLDER --compiler COMPILER --allow-native` on one line.
The source distribution also provides the dependency-free
`dev/run_native_tests.py` runner with a required `--output RESULTS.json` argument.

Native recipes need their target's headers, libraries and runtime dependencies.
On Windows, ordinary C builds with Clang require the Visual C++ Build Tools and
Windows SDK; installing LLVM alone supplies the freestanding reconstruction
compiler, not those C runtime headers. CLI callers may select an installed MinGW
compiler with `--compiler`. Compiler diagnostics are retained with build evidence.

The **Native reconstructed program tests** GitHub Actions workflow is manually
dispatched on a standard Linux or Windows runner. It checks out the selected commit
without retaining repository credentials, runs the reviewed recipe and retains
observations for three days. Inputs are passed as data, never interpolated into a
shell command. The owner must confirm an account spending boundary before dispatch;
the workflow does not configure billing and does not prove remaining quota.
No repository creation is required. The default recipe is the bundled C fixture;
select the offscreen example on a compatible Linux runner for graphics checks.
Hosted runs are not automatically accepted as local task completion.

**Projects → Hosted native tests** manages these runs from HA. Connect the
project's existing private repository, select a full reviewed commit SHA, choose
the suite and program folder, and confirm the trusted code and configured spending
boundary. The repository must already contain this release's managed
`.github/workflows/native-tests.yml` and the test runner/runtime from the source
distribution. The installed workflow template is also available under
`_app/hivemind_assembly/integrations/native-tests.yml`.

HA creates a unique `ha-native-…` tag at the reviewed commit, dispatches once and
checks retained requests every 30 seconds while the application is open. Requests
survive restarts. **Check status** looks up a lost response; it never repeats
an uncertain dispatch. The same request ID keeps retries idempotent. Use **New
request ID** for an intentional later run after the existing request has settled.
Cancellation is retained and checked; it cannot be confirmed until GitHub reports
the run completed. A request interrupted before dispatch can be stopped locally.
Tags remain for traceability; HA does not delete them or move the source branch.
Tag creation can trigger other workflows in that repository, so review those too.
HA's own contract workflow is restricted to branch pushes and pull requests.

The dashboard links to the identified run and its artifacts. It retains the exact
commit, run attempt, conclusion and artifact metadata. Workers can read their own
project's retained status using `hosted_test_status` without causing a network call
or starting a paid run. Hosted success is not silently imported as local acceptance.
Wrong repository/commit/workflow identities, duplicate matching runs and external
reruns stop automatic adoption. No live hosted or Windows acceptance is claimed
from the API fixtures used to validate this integration.

## MCP and optional Codespaces

Open **Connections & cloud** to enable the official-SDK MCP bridge, select shared
projects, and optionally allow clients to create paused projects. HA can merge its
connection into a JSON MCP client configuration while preserving other entries
and saving a backup. Keep HA running; the bridge connects to its authenticated
local controller. Web chat needs a supported private tunnel in addition to this
local connection. Provider account authorization is a separate setup step.

Connected chats can call `ha_run_checks(task, request_id)` and poll
`ha_check_status(task, request_id)` for a shared paused project with owner-pinned
acceptance. Keep the same request ID when retrying: a lost response or controller
restart never silently reruns a check. Results report success, revision staleness
and execution status without exposing protected cases or expected outputs. These
checks leave the project paused; objective completion still requires a separate
independent acceptance run. Native recipes require prior owner authorization.
`ha_publication_status(task)` reports the project's repository link, the last
published checkpoint and recent host-verified source snapshots, so a client that
reconnects can confirm what was verified and published. It is read-only; MCP
clients cannot publish or change repository settings.

External stdio and HTTP MCP connections have explicit project and tool grants.
Workers receive only their authorized connection names and tool names. Calls use
the existing operation journal and revision fences; an interrupted external
mutation is not automatically replayed. Connection arguments must not contain
credentials. HTTP bearer tokens can be held for the session or saved in the OS
credential store, bound to the exact endpoint. For an OAuth-enabled HTTP server,
use **Authorize in browser**: HA discovers the authorization server, registers a
public client when supported, opens its dedicated browser profile, validates the
loopback callback, and refreshes tokens. Credentials are session-only unless you
select OS-vault storage. Existing registrations and verified token endpoints are
retained for reconnects. Providers requiring pre-registration can use a public
client ID and registered loopback port in the optional fields. Provider sign-in
and consent still follow that provider's requirements; HA does not bypass them.
Disconnect removes HA's local authorization; provider-side revocation is separate.

Codespaces is disabled by default and requires separate execution permission.
HA can prepare GitHub CLI on Windows, request the Codespaces OAuth scope, list
machines, create a Codespace for an **existing** repository, start/stop it, and
probe its installed tools and GPU. Repository creation is never required.
A cloud job snapshots explicit source-text paths from a paused project and runs
explicit argument arrays. Up to four separate Codespaces execute concurrently;
jobs within one Codespace queue in submission order. Source export checks reject
protected/private paths and recognized secrets. The runner is not a security
sandbox: submitted commands run with the Codespace account's permissions.

Results survive lost connections. Use **reconcile** rather than submitting a new
job ID after an uncertain delivery. Requested output files can be imported into
a paused local project, with a current-file hash required for replacement.
Cloud execution does not accept a task or replace independent project checks.
GPU requirements are checked both against the capability probe and at execution.
GitHub compute/storage quotas and charges apply; HA does not enable paid usage.
Live account authorization, cloud SSH delivery and web-chat tunnel access still
need integration acceptance; local SDK and runner tests do not establish them.

**Private web-chat setup:** the connection panel can now download and checksum-check
the official OpenAI `tunnel-client`, generate a local profile, run its configuration
doctor, and supervise start/stop. Enter an existing tunnel ID and runtime key from
OpenAI Platform; choose session-only storage or the OS credential store. No key is
written into the profile. Tunnel creation/account permission and adding the tunnel
in the web client still depend on that service's account controls. A running process
or a passing configuration check does not prove an end-to-end chat connection.

Workers can submit authorized cloud snapshots through `cloud_submit`, inspect
retained jobs with `cloud_status`, and read result artifacts. Worker requests use
the controller's operation identity and writer fences. Local setup never silently
creates a cloud machine or enables cloud execution.

**No HA request limit** explicitly removes HA's project turn cap while retaining
usage records and independent completion checks. Provider allowance and availability
checks still apply. Existing bounded goals retain their configured limits.

Cloud creation requests remain visible after restart. **Recover / inspect** matches
a retained creation to its repository, machine, display name and requested ref;
an uncertain request is never replaced automatically. Worker `cloud_status` can
reconcile a job ID and returns output artifact IDs for the existing guarded
`write_file` operation. A stale status response cannot overwrite a completed result.


Task knowledge is now tag-gated. The initial classification turn receives only
the task and category catalog; it selects existing tags or none. Source reading,
lesson retrieval and skill briefings then enforce those grants. Changed access
starts a fresh conversation and briefing. Existing untagged material is retained
as unclassified and remains unavailable to task models until categorized.
The Knowledge page manages categories, material assignments and paused-task
scope overrides. Authorized source ingestion queues an isolated native adviser
categorization turn; ingestion may create reusable categories, while project
classification cannot. External-processing permission remains a separate gate.


Experimental learning is optional and off by default. Its controls are on the
Knowledge page. Chat-only is the default; Work or other limited worker routes
require turning that restriction off. The controller tries the documented model
and effort preferences against actual visible Chat controls, or uses an exact
manual override, and pins the selected model for all paired samples. Main work
routes keep their exact configured targets. There is no default HA turn cap;
an optional per-evaluation cap counts session verification and trial messages,
with retries counted once. Unknown remaining allowance can be allowed explicitly;
observed provider blocks and identity mismatches still stop delivery. Statistical
holdout exposure and correctness requirements are separate from usage limits.
Stored approved lessons remain available to matching tasks when experiments are off.

The separate **Installed Windows foundations** workflow installs the full pinned
Ghidra, REA and Hermes foundations on a fresh Windows runner and executes the
source-known verification probes. It runs for installer/adapter changes and can
be started manually. The Windows analysis fixture is a native PE DLL because
REA’s experimental Windows provider does not admit Linux ELF targets. This gate
does not sign into model accounts or replace live autonomous acceptance.

The full foundation check passed at checkpoint `2f8785b` in [hosted run 39476662077](https://github.com/Artistical-Intelligence/hivemind-assembly/actions/runs/39476662077), using default Ghidra analyzers and upstream REA process/filesystem controls. The runner supplied prerequisite tools; this does not establish desktop WinGet setup.

HTTP MCP authorization also accepts a hosted client metadata URL. In Connections, generate the public document using a fixed callback port, serve it at your HTTPS URL, and connect. HA uses the official SDK to prefer this registration when the server advertises support, retaining the choice for reconnects and token refresh. The document contains no credentials. Editing the registration or endpoint invalidates in-flight authorization; an HTTPS host is required for the document.

Static AArch64 program reconstruction is available from **Project files → Create AArch64 program example**. This runs the complete source-known ARM ELF and compares an editable x64 reconstruction, including state across multiple input reads. Set `"architecture": "aarch64"` in the candidate build manifest to produce an ARM executable; the default is `x86_64`. Both support deterministic stream I/O, exit, explicit arguments/environment and clock under Unicorn. Choose `qiling_linux` for bounded file/memory effects and supplied dynamic dependencies on either architecture. Unknown OS effects remain unsupported. Protected acceptance uses `linux_program`; earlier program scope names remain accepted.


## Freestanding C memory support

Windows x64 and Linux x64/AArch64 program builds, and linked-function builds for
SysV x64, Windows x64, Linux ARM64 and Windows ARM64, provide `memcpy`, `memmove`,
`memset` and `memcmp`, including calls the compiler generates for array
initialization or struct copies. Their declarations are supplied automatically;
program counts use `ha_size`, and linked-function counts use the compiler type
`__SIZE_TYPE__` (both 64-bit on supported targets). No host headers are needed.
`memmove` supports overlapping ranges; `memcmp` compares unsigned bytes and only
its negative/zero/positive sign is a portable result.

These are the pinned musl 1.2.6 memory implementations, compiled into the generated
PE/ELF image. They execute within the existing guest CPU, page-permission and
instruction/time bounds. They do not call host memory routines. Supplied candidate
definitions take precedence over the bundled fallback, and protected acceptance
still checks the resulting behavior against the sealed original.

Builds verify the retained upstream source hashes, record a memory-runtime hash,
and embed the complete upstream copyright notice in each generated image. Both
GCC and Clang are supported for x64 Linux; cross-target and Windows builds require
Clang/LLD. Full CRT imports, allocation libraries, formatted I/O and additional
Windows APIs still require their own runtime support; these four routines do not
add arbitrary libc or Windows compatibility.

## Frame and audio checks for emulated programs

Choose **Project files → Create emulated frame example** for a complete local
workflow: compile a Windows PE renderer, edit the reconstruction, run sealed
checks and inspect eight synchronized frames. Clang and LLD are required. The
example emits raw frames through the bounded emulator; it needs no native target
execution permission. A one-frame delay fails even when final position matches.

Windows and Linux program cases accept an optional `captures` map:

```json
{"id":"motion","input_hex":"0001000100000000",
 "captures":{"stdout":{"format":"rgba8_sequence","width":8,"height":8,
 "frames":8,"frame_rate_num":60,"frame_rate_den":1}}}
```

Selectors are `stdout`, `stderr` or `file:<guest path>`. Windows file selectors
use canonical lowercase basenames such as `file:frames.rgba`; Linux file
selectors use canonical absolute paths such as `file:/frames.rgba` and require
`runtime: "qiling_linux"`. Streams work in both Linux runtime lanes, including
AArch64. Files refer to final guest contents, never host paths.

The existing raw `rgba8`, `rgba8_sequence` and `pcm_s16le` comparators are shared
with native-tool checks. Defaults are exact; the owner may pin the same explicit
pixel/channel/peak/RMS tolerances described above. Each capture is limited to
1 MB; dimensions, frame count and sample layout must match exactly. Missing or
malformed captures fail even when both programs produce the same malformed data.
Original capture shapes are checked before sealing acceptance. Frames match by
index, including alpha; no alignment, dropped-frame compensation, resampling or
normalization is performed.

Only selected outputs use these comparators. All other streams/files, exit codes,
input consumption, selected memory and strict effects keep their existing checks.
Strict file traces may reject differing writes despite an allowed final-capture
tolerance; choose observable effects explicitly when internal writes may differ.
Workers cannot edit protected original images, cases or tolerances. Fresh
acceptance rebuilds the candidate and retains detailed metrics and raw captures
in protected evidence. **View recorded output** loads that evidence for the owner,
shows the checked revision, scrubs frames, plots audio and downloads original raw
bytes. Editing the visible example `acceptance.json` does not change pinned rules.

These are bounded emulated program observations, not a GPU/window-system or
arbitrary game runtime. Frame rate and sample rate describe the declared data;
native hardware timing and repeated native execution are not measured here.

## Game play-testing

AI workers, local bots and you can play the games HA rebuilds to test, troubleshoot
and improve them. Choose **Project files → Create game testing example**, then use
**Play and test the game**: load the game, press its action buttons, play the
original, the reconstruction or both compared tick by tick, explore, shrink findings
and run saved regressions. No model account, GPU or native execution permission is
needed; the example needs a C compiler.

A project's `game.json` is the play-testing contract: fixed-size input records and
named controls, macro actions, the per-tick output layout on stdout/stderr (a raw
state record, RGBA frames and PCM audio), decoded state fields, optional memory
fields by symbol, declarative rules (bounds, other fields, equality, monotonic,
maximum per-tick change, optional `when` conditions), exploration cells, tick and
instruction limits, comparison tolerances for frames/audio, allowed exit codes and
named starts with preconditions. Nothing in it is evaluated as code.

Static x86-64 and AArch64 ELF games run in a stepping engine that pauses whenever
the game waits for input, so every input is frame-exact and state can be read from
memory between ticks. Snapshots, function coverage from symbols and a per-tick
instruction budget (freeze detection) are built in. Reads block until the requested
bytes or end of input arrive, so a stepped session produces exactly the streams,
exit status and input consumption of the batch replay used elsewhere (tests check
both architectures). Windows x64 console games use the existing batch replay; their
observations always follow end of input and live memory is unavailable.

Every session is its input log. Results carry trajectory tokens that replay
exactly, which also makes every operation safe to recompute after an interruption.
Detected outcomes are `divergence` (state, frame, audio, status, exit code or tick
count differ beyond pinned tolerances), `crash`, `freeze`, `invariant`, `slowdown`,
`bad_exit`, `protocol`, `unreached` (a start's preconditions were not met), `limit`
and `cancelled`; the last two are inconclusive and never count as a pass. A candidate
problem that the original reproduces with the same trajectory is reported as original
behavior, not as a reconstruction defect.

- **Explore** runs seeded Go-Explore without training: it returns to situations it
  has reached (snapshots of declared cell fields) and tries new sticky actions,
  favouring rarely chosen cells and newly executed functions. With **Both**, the
  original and the reconstruction run in lockstep and the first divergent tick is
  recorded at once. Each finding keeps its trajectory.
- **Shrink** truncates after the failing tick, removes chunks by delta debugging,
  replaces the rest with the neutral input where possible, and confirms the result on
  fresh engines twice. **Bug package** returns the inputs, a state window from both
  sides and frames around the failing tick.
- **Saved regressions** (`game-regressions.json`) rerun on every build;
  `match_original` compares with the original and `no_problems` checks one build.

Native workers use the same operations: `describe_game`, `play_game` (a few named
actions per turn) and `test_game` (`compare`, `run`, `explore`, `shrink`, `package`,
`regressions`). Rendered frames are attached to the worker's next turn as PNG files
when its route supports uploads; small frames also get a character view with a
colour legend. For independent completion, the `game_play` acceptance scope seals
the original, the contract and the owner's trajectories; checks rebuild the
candidate, replay every trajectory on fresh engines and report per-case outcomes
while sealed inputs and observations stay protected.

### Real games: Godot projects and SDL2 programs

Real games run natively through a small adapter instead of the emulator. Add a
`native` section to `game.json`:

```json
{
  "version": 1,
  "name": "Dodge the Creeps",
  "native": {
    "adapter": "godot",
    "original": {"project": "gdscript"},
    "candidate": {"project": "rust"},
    "inputs": [{"action": "move_left"}, {"action": "move_right"}, {"action": "start_game"}],
    "state": [{"name": "x", "type": "f32", "node": "Main/Player", "property": "position:x"}],
    "frame": {"width": 48, "height": 72}
  }
}
```

- **Godot 4 projects** (GDScript, C#, or GDExtension code in Rust or C++): HA copies the
  project, adds its `ha_tick.gd` autoload through `override.cfg`, imports assets once and
  runs the game at a fixed frame rate. Each input bit presses a key or an input action
  (an action is pressed with its first key binding, so button shortcuts see it too).
  State values are node properties or group counts. Set `foundations.godot` (or the
  `HA_GODOT` environment variable) to the Godot executable.
- **SDL2 programs** (C, C++, Rust or anything that calls SDL2) on Linux: HA preloads its
  adapter library, which gives the game's own code virtual clocks and seeded
  randomness, presses keys and captures each presented frame. State values come from
  the paused process's memory by symbol and pointer path, for example
  `{"name": "score", "type": "f32", "symbol": "_ZN6Global4heroE", "pointers": [244]}`,
  so the program needs its symbols; a stripped build can still be compared by frames.
- Frames render on a virtual X display (`Xvfb`) with software OpenGL; Godot can also run
  headless for state-only play.

Controls, actions, the output layout and state fields are derived from the native
section, so playing, comparing, exploring, shrinking, bug packages and saved
regressions work as for emulated games. Native play runs the game's own code on this
computer: enable **trusted native execution** for the project first (the permission
used by native test recipes). It is not a sandbox; use a disposable machine for games
you do not trust. `describe_game` plays a probe twice (past the title screen through a
named start) and reports whether the game replays deterministically; a game that reads
the clock or operating-system entropy in ways the adapter does not control can differ
between runs, and HA reports that rather than guessing. Per-frame and startup time
limits turn a hang into a freeze and a signal into a crash. Snapshots replay the input
log from a fresh launch, so native exploration is slower than emulated exploration.
`game_play` acceptance seals emulated games only; keep native regressions instead.
Real-game results are in [game play-testing design](dev/GAME_TESTING.md).

From the command line:

```bash
python _app/launch.py game-test --workspace GAME_FOLDER --mode explore --steps 300 --seed 0
python _app/launch.py game-test --workspace GAME_FOLDER --mode describe --allow-native --godot /path/to/godot
```

Other modes are `describe`, `compare`, `run`, `shrink`, `package` and `regressions`
(`--trajectory` takes a token or a named start; `--end` ends input). Native games need
`--allow-native`. This verifies sampled play under a declared contract. It is not a
GPU, window-system or hardware-timing claim, and exploration that finds nothing does
not prove a game correct. Windows SDL2 programs, exported Godot binaries, mouse input,
native audio capture and trained policies are not implemented; see
[game play-testing design](dev/GAME_TESTING.md).

## Windows console reconstruction

Choose **Project files → Create Windows console example** to build a real x64
Windows file-transform executable, edit its C reconstruction and run sealed comparisons. Clang
and LLD are required; target execution uses Speakeasy and needs neither Windows
DLLs nor native execution permission. The same generated PE can run on Windows.

For your own target, upload the original `.exe` and candidate `.c` files, then
create a build manifest such as:

```json
{"sources":["main.c","transform.c"],"architecture":"x86_64","optimization":"O2"}
```

The entry point is `int ha_main(void)`. The supplied runtime exposes
`ha_read(buffer,count)`, `ha_write(buffer,count)`, `ha_error(buffer,count)` and
`ha_exit(code)`. Counts use `ha_size` (64-bit); stream functions return signed
64-bit counts. Shared C declarations belong in the manifest's `declarations`.
Preprocessor directives, host headers and inline assembly are rejected.

Select **Windows x64 console program** in Project acceptance. Use the original
PE path and build manifest path, with at least two cases:

```json
[{"id":"empty","files":{"input.bin":""}},
 {"id":"sample","files":{"input.bin":"616263"},"clock_ms":1000}]
```

HA pins original bytes and cases outside worker access, independently rebuilds
the current candidate at completion, and checks exact stdout, stderr, consumed
input, unsigned 32-bit exit status and every final file (except outputs with explicit
raw capture comparators described above). Strict mode also compares
file/process/memory operations and fixed-clock observations; observable mode allows different
internal activity with identical final results. Development tools `build_windows_program` and
`compare_windows_program` use the same runtime. Passing development comparisons
can schedule verified source checkpoints when a project repository is connected.

This lane admits x64 PE32+ console images and kernel32 imports `GetStdHandle`,
`ReadFile`, `WriteFile`, `ExitProcess`, `GetTickCount`, `GetTickCount64`,
`CreateFileA/W`, `CloseHandle`, `SetFilePointerEx`, `GetFileSizeEx`,
`SetEndOfFile`, `DeleteFileA/W`, `GetLastError` and `SetLastError`.
Private memory uses VirtualAlloc, VirtualProtect and VirtualFree.
Process input queries use `GetCommandLineA/W` and `GetEnvironmentVariableA/W`.
These declarations are supplied automatically to C builds; no Windows headers
are needed. `CreateFile` returns `(void*)-1` on failure. Use `ha_dword` for
DWORD values and signed `long long` for 64-bit file positions/sizes.

Each case's optional `files` map supplies hexadecimal contents. Names are ordinary
ASCII file names in the fixed `C:\work` directory, case-insensitive, without
subdirectories, devices, alternate streams or trailing spaces/dots. Relative
names, `.\name` and `C:\work\name` identify the same file; duplicate input
aliases are rejected. Missing names represent absent files and new files may be
created. All final files, including unchanged inputs, participate in comparison.
Replays never read or modify host files. Limits are 64 files, 1 MB total stored
bytes, 128 open handles and 4 MB cumulative file transfer per run.

Files support generic read/write access, read/write
sharing, the five creation dispositions, normal attributes, synchronous reads and
writes, independent handle cursors, size queries, seeking, truncation and deletion.
Sharing conflicts and missing/closed/read-only handles return Win32 errors.
Metadata-only zero-access handles, security structures, template handles, delete sharing and special flags are
unsupported. Seek alone does not extend a file; writing beyond EOF zero-fills
the gap. Extending through `SetEndOfFile` is rejected because Windows documents
the added contents as undefined. `GetLastError` is supported after a failed call,
`SetLastError`, or the defined `CREATE_ALWAYS`/`OPEN_ALWAYS` outcomes; querying
unspecified successful-call error state is rejected.
`CREATE_ALWAYS` requires generic write access in this contract.

Cases may also provide `command_line` and `env`, for example:

```json
{"id":"copy-mode","command_line":"program.exe --mode copy",
 "env":{"HA_MODE":"copy"},"files":{"input.bin":"616263"}}
```

The command line is the exact string observed by the program, including its
executable name and quoting; HA does not parse it into arguments or promise
`CreateProcess` path normalization. It defaults to `program.exe`. The environment
defaults to empty and never inherits host values. Names are case-insensitive
ASCII letters/digits/underscores (starting with a letter or underscore, maximum
128 characters), and duplicate aliases are rejected. Up to 128 variables and
64 KB of environment text are admitted. Command lines and individual values
are NUL-free ASCII, at most 8192 characters; empty environment values are allowed.
Both ANSI and UTF-16 API entry points are supported for these ASCII values.

Use zero capacity for an environment size query, then allocate enough room for
the value and its terminator. Missing variables return error 203. Positive
insufficient capacities are rejected because Windows leaves those output bytes
undefined. Command-line buffers are read-only, including writes attempted through
other API calls. Strict comparisons retain process-query sequences; observable
comparisons permit different queries when final results match. Environment
mutation, environment-block enumeration and non-ASCII code-page conversion are
outside this contract. All process inputs are sealed with the acceptance corpus.

Private dynamic buffers support `VirtualAlloc(address,size,flags,protection)`,
`VirtualProtect(address,size,protection,old_protection_pointer)` and
`VirtualFree(address,size,flags)`. Sizes and pointers are 64-bit; flags and the
old-protection output are 32-bit. New reservations use a null address, with
`MEM_RESERVE=0x2000`, `MEM_COMMIT=0x1000`, or both. A later commit can address
pages within an owned reservation. Pages are 4096 bytes; reservation bases are
64 KiB aligned. Newly committed pages contain zeros. Recommit preserves data;
changing an already committed page's protection must use VirtualProtect.

Supported protection is `PAGE_NOACCESS=1`, `PAGE_READONLY=2` or
`PAGE_READWRITE=4`. Protection covers entire touched pages, including ranges
crossing a page boundary. The previous protection of the first page is returned.
The output pointer must not overlap those pages. Protecting uncommitted pages
fails without changing them; its platform-specific last-error value is not modeled.

`MEM_DECOMMIT=0x4000` returns touched pages to reserved state. At the allocation
base, a zero size decommits the whole reservation. Recommit zeroes those pages.
`MEM_RELEASE=0x8000` requires the allocation base and zero size. Released pages
remain inaccessible during replay; access through CPU instructions or API buffers
fails acceptance. Reservations total at most 16 MiB and 256 regions over a replay's
lifetime, including released regions. Fixed-address reservations, executable
memory, guards, copy-on-write and changes to loader/stack pages are unsupported.
All modeled API buffers also respect the loaded PE and stack mapping permissions.
Strict comparison includes allocation identities and operation sequences;
observable comparison allows different allocation strategies with identical
external results. The editable Windows starter exercises file-size-driven
allocation, read-only output buffers, release and page-crossing inputs.

Stopped Windows replays include guest-only `stop_context` diagnostics: the last
program instruction, absolute address, image-relative offset, on-disk file offset
when available, mapped permissions and the active API with its numeric arguments.
API buffer permission faults report the attempted address, byte count and access
direction. Successful replays have no stop diagnostic. These fields help locate
the failure in Ghidra; they do not participate in equivalence comparison.
Diagnostics for sealed originals remain protected evaluator artifacts, while
development comparisons return diagnostics for the caller's declared samples.

Streams model redirected regular files, including EOF; handles are virtual.
Standard-stream metadata, seek and close operations remain unsupported. Every
replay starts fresh and must call ExitProcess. Input/output, image, instruction,
API-call and elapsed-time bounds are enforced.
TLS, other imports, overlapped I/O, arbitrary files, CRT, GUI, threads, direct CPU
environment queries and host process/network effects are rejected. Matching
faults or budget exhaustion never pass. This is corpus evidence within the
explicit runtime contract, not proof of arbitrary Windows application equivalence.


## Current evidence

<!-- status:begin -->
<!-- Generated by dev/status_docs.py from _app/release_status.json; edit that file. -->

**Version 0.25.2.** Live native routes accepted: 0 of 5. Unattended worker/adviser/Ghidra loop with live models: not established. Clean Windows desktop installation: not verified.

| Evidence | Commit | Runs | Host | Model inference |
| --- | --- | --- | --- | --- |
| hosted-ci-second-audit (2026-10-21) | `62e53a7` | [39688769075](https://github.com/Artistical-Intelligence/hivemind-assembly/actions/runs/39688769075) | GitHub Linux and Windows | no |
| windows-project-acceptance (2026-10-21) | `62e53a7` | [39688769075](https://github.com/Artistical-Intelligence/hivemind-assembly/actions/runs/39688769075) | Linux local and hosted Windows | no |
| audit-second-pass (2026-10-21) | `62e53a7` | [39688769075](https://github.com/Artistical-Intelligence/hivemind-assembly/actions/runs/39688769075) | Linux x86-64 local and hosted CI | no |
| hosted-ci-improvements (2026-10-21) | `7bb76bb` | [39674657186](https://github.com/Artistical-Intelligence/hivemind-assembly/actions/runs/39674657186), [39674657324](https://github.com/Artistical-Intelligence/hivemind-assembly/actions/runs/39674657324) | GitHub Linux and Windows | no |
| audit-2026-10-21 (2026-10-21) | `7bb76bb` | [39674657186](https://github.com/Artistical-Intelligence/hivemind-assembly/actions/runs/39674657186) | Linux x86-64 local and hosted CI | no |
| windows-pe-composition (2026-10-21) | `7bb76bb` | [39674657186](https://github.com/Artistical-Intelligence/hivemind-assembly/actions/runs/39674657186) | Linux local and hosted Windows | no |
| public-holdout-import (2026-10-21) | `7bb76bb` | local | Linux x86-64 local | no |
| hosted-ci-0.25 (2026-10-21) | `4f057ab` | [39650550445](https://github.com/Artistical-Intelligence/hivemind-assembly/actions/runs/39650550445) | GitHub Linux and Windows | no |
| project-reconstruction-suite (2026-10-21) | `4f057ab` | [39650550445](https://github.com/Artistical-Intelligence/hivemind-assembly/actions/runs/39650550445) | Linux x86-64 local and hosted CI | no |
| ghidra-project-plan (2026-10-21) | `4907b10` | [39650087898](https://github.com/Artistical-Intelligence/hivemind-assembly/actions/runs/39650087898) | Fresh Linux x86-64 install and hosted Windows | no |
| baseline-suite-1c05abf (2026-10-21) | `1c05abf` | [39632598272](https://github.com/Artistical-Intelligence/hivemind-assembly/actions/runs/39632598272) | GitHub Linux and Windows | no |

- **hosted-ci-second-audit** (`62e53a7`): All four contract jobs passed: Linux 842 passed/18 skipped, including the pinned HumanEval-Decompile fetch and scoring test; Windows 819 passed/41 skipped in 30 minutes under the new 40-minute limit; fifteen native Windows checks; ten Chromium checks; Windows package install, update and restore.
- **windows-project-acceptance** (`62e53a7`): windows_project acceptance seals the Windows game target with pinned addresses, rejects the physics mutant at program level and moved region addresses, and accepts the repaired candidate with four recovered regions.
- **audit-second-pass** (`62e53a7`): Fixes for the browser automation, backup, Codespaces and dashboard findings in dev/AUDIT.md, each with a regression test.
- **hosted-ci-improvements** (`7bb76bb`): All four contract jobs passed: Linux 828 passed/19 skipped; Windows 807 passed/40 skipped; fifteen native Windows checks; ten Chromium checks; Windows package install, update and restore of the 0.25.0 package. Hosted Windows foundations passed, including the Ghidra project plan.
- **audit-2026-10-21** (`7bb76bb`): Fixes for the findings in dev/AUDIT.md, including the high-severity leak of sealed function cases to workers; each has a regression test that fails on the earlier code where applicable.
- **windows-pe-composition** (`7bb76bb`): The game target built as an x64 Windows console PE composes four recovered regions with original rendering, passes frame/audio cases and rejects the right-wall physics mutant at program level. A static glibc tool composes and runs natively with identical output; a wrong region changes it.
- **public-holdout-import** (`7bb76bb`): HumanEval-Decompile C subset fetched at the pinned commit and SHA-256 (656 rows); problem-level families keep every optimization level of a problem in one split; the benchmark's reference function passes its sealed test natively. The fetch test runs only with HA_BENCHMARK_FETCH=1.
- **hosted-ci-0.25** (`4f057ab`): All four jobs passed: Linux 807 passed/18 skipped; Windows 788 passed/37 skipped after one rerun of an unrelated native compile timeout; fifteen native Windows checks; ten Chromium checks; Windows package install, update and restore. The package was built before the 0.25.0 version label.
- **project-reconstruction-suite** (`4f057ab`): Fixed source-known Stop 3 suite: x86-64 utility with original-code fallback, AArch64 original rebuilt as x86-64, game state/frame/audio target. Thirteen planted incorrect variants rejected, eight only by whole-program checks. The composed utility ran natively with output identical to the original.
- **ghidra-project-plan** (`4907b10`): Fresh Ghidra 12.1.4, REA 6.7.0 and Hermes c0015464f0f4 installations passed every foundation check, including composition over an actual Ghidra callgraph plan (30 functions, four regions recovered).
- **baseline-suite-1c05abf** (`1c05abf`): Handoff baseline: all four jobs passed; local Linux full suite 795 passed/18 skipped.

Still required:

- Live GitHub browser registration/device authorization and all five exact native routes.
- Unattended real worker/adviser/reviewer/Ghidra/REA artifact, recovery and acceptance loops.
- Native cross-project learning gains, provider account-wide memory isolation and repeated timing evidence.
- Desktop prerequisite installation through WinGet; hosted Windows package install/update/restore and full foundation installation/basic native adapters have passed.
- Run the managed native workflow through HA using a live authorized account with a configured spending boundary; review representative Linux/Windows target recipes and retained artifacts.
- Run the Stop 3 suite through a live native team with Ghidra-produced plans; broader application targets beyond the fixed suite remain separate scope.
- Measure native learning gains on the HumanEval-Decompile holdout once live routes exist.
<!-- status:end -->

Older validation history is kept below, in [ROADMAP](dev/ROADMAP.md) and in `historical_checks` of
`_app/release_status.json`.

### Validation history

Validation for implementation `73fd1d9`: all four jobs passed in
[run 39615843168](https://github.com/Artistical-Intelligence/hivemind-assembly/actions/runs/39615843168).
Linux passed 778 tests with 18 platform skips; Windows passed 760 with 36 skips.
Fifteen separate native Windows checks, ten Chromium checks and packaged Windows
installation/update/backup restoration passed. Replay diagnostics cover real
x64/ARM64 faults, relocated DLLs, caller-buffer bounds, ABI violations, cancellation,
engine timeouts and exact completed-syscall boundaries. Sealed-original details
remain protected. The initial full local regression passed 776 tests with 18 skips;
the final syscall-boundary correction passed all 37 targeted diagnostics/program
checks before the full hosted suites.

Fresh [Ghidra/REA/Hermes installation and adapter checks](https://github.com/Artistical-Intelligence/hivemind-assembly/actions/runs/39615843195)
also passed at the same implementation, including four linked ABIs with a native
oracle, ARM64 programs, both Qiling architectures, Ghidra context and reopened
annotations, REA analysis and Hermes lifecycle. Model inference was not invoked;
desktop prerequisites were preinstalled. The
[tested v0.24.0 Windows/source packages](https://github.com/Artistical-Intelligence/hivemind-assembly/actions/runs/39615843168/artifacts/12352452923)
are retained for fourteen days.
