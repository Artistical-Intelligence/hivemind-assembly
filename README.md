# Hivemind Assembly

A local reverse-engineering workspace for collaborative agents, independent verification, and reusable learning. Version 0.12.0 is an engineering preview. Ghidra and REA remain complete foundations; task control, native browser sessions, evidence, and learning are integrated around them.

## Start on Windows

1. Extract the Windows release ZIP and open `Start_Hivemind_Assembly.cmd`.
2. The launcher installs the bundled Python runtime and the hash-locked Windows dependency set into your user data directory, then opens the dashboard. The first dependency installation needs internet access.
3. Open **Project files** and choose **Create register example**. Run checks, edit `candidate.hex`, save, and check again. The native Python example also works without a compiler after you authorize its supplied recipes. **Semantic self-check** exercises the verifier separately.
4. Use **Setup & settings → Install pinned foundations**. On Windows, setup uses WinGet to install missing Git, Node.js 24+, Java 21+ and a C compiler, then installs and automatically checks the pinned foundations on a source-known fixture. Windows may require system authorization or a restart. Existing installations can be configured in settings.
5. Use **Set up all native sessions** on Overview. Setup reuses dedicated sign-ins, discovers exact controls, creates separate conversations and verifies two-way attachment transfers. Unrecognized controls or allowance mappings remain unverified; `_app/NATIVE_SETUP.md` describes the recovery path. Each role retains its designated provider, surface, model and effort. Inference APIs, paid overage and manual relay are not fallbacks.

The application uses dedicated Edge, Chrome or Playwright profiles. It does not copy your everyday browser credentials. User data remains in `%LOCALAPPDATA%\UnifiedWorkbench`, outside the application folder. The host must remain running for autonomous work.

## Working with a project

Create a project in its prepared state. In **Project files**, upload targets, browse files, and edit UTF-8 candidates. Save preserves the previous bytes and refuses stale overwrites; polling never replaces an unsaved draft. Uploads accept files up to 256 MiB each, and the text editor supports 512 KiB. Larger targets can use local-path import. For Python scripts, single C sources and executables, use **Configure a native comparison** in **Project files**: select a candidate and optional original, enter input cases and expected text, and authorize execution. The advanced recipe and other acceptance types remain in **Projects & tasks**. Run the pinned checks directly from **Project files** before resuming agents. **Download saved file** retrieves the exact version you opened. Manual checks leave the task paused and do not declare autonomous completion. Workers declare bounded steps, receive an adviser briefing, request broker operations, and use the retained results to continue. Separate reviewer sessions support recovery.

For a bounded x86-64 integer register region, **Independent acceptance → Register equivalence proof** pins the original bytes and names the candidate file, input registers and observed outputs. Completion independently reads the candidate and reruns the proof. Missing files, counterexamples, unsupported semantics, stale ownership and concurrent changes prevent acceptance. Failed supported checks return their evidence for up to three correction attempts. Unconfigured objectives remain `awaiting_acceptance`.

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

Use **Knowledge & skills → Evaluate workflow optimization** and choose proofs or function calls, or run `python _app/launch.py learn --workflow calls --data-dir <state-directory>` while the application is stopped. The two built-in optimizers each measure four local cases; function calls include independent scalar and pointer-buffer expectations. These measure bounded reuse optimizations. Native knowledge/procedure effectiveness and broader real cross-project improvement remain unverified; the donor-backed candidate and evaluation paths are described below.

## Updates and architecture

Extract a new release over the application folder. Settings, projects, originals, browser profiles, artifacts and learned assets remain in the user data directory. Stop the application before updating or copying that directory. The dashboard creates a verified workspace ZIP, including controller and project data.

One application contains separate core, automation, learning, reverse-engineering and UI modules. Legacy `workbench` imports, existing data paths and older launchers remain compatible. See [architecture](dev/ARCHITECTURE.md), [roadmap](dev/ROADMAP.md), and [related-system decisions](dev/RELATED_WORK.md).

## Development and verification

Use Python 3.12. Windows release dependencies are fully locked in `_app/requirements-windows.lock`; `dev/lock_windows.py` checks Windows-specific dependency markers and wheel hashes. Source archives include the pure-Python bootstrap wheel needed to reproduce that lock.

For development:

```bash
python -m venv .venv
# Activate the environment for your shell.
python -m pip install -r _app/requirements.txt pytest
python -m pytest tests -q
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

Local scripted team and browser fixtures do not constitute live-provider acceptance. The five signed-in routes, unattended native orchestration, clean Windows installation/update behavior and broader application reconstruction remain unfinished acceptance or implementation work. Actual Hermes SessionDB/Kanban and Ghidra import/decompile/context/annotation paths have passed local native checks. REA execution is blocked on this development host by its process-inspection environment. The OpenAI Python package is an upstream Hermes import dependency; this application does not instantiate model API clients.

## GitHub project repositories

Use **Set up GitHub automatically / Continue** for browser-assisted registration
and connection. Alternatively, expand **Connect with an existing Client ID**,
enter an OAuth app's public Client ID and approve its device code. Device Flow
must be enabled; an existing app's callback URL can stay unchanged.
No client secret is required for this local sign-in. HA requests `repo` access
and refreshable authorization. Tokens are stored in Windows Credential Manager,
macOS Keychain or Linux Secret Service, outside projects, settings and backups.
An unlocked supported OS credential store is required; there is no plaintext
fallback. **Check saved connection** verifies an authorization after restart.

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

If a request is interrupted, use **Evidence & recovery → Reconcile saved
operation**. HA checks the recorded repository identity, privacy and write access
before accepting it; it does not blindly repeat an uncertain creation request.
If the repository remains inaccessible, the request stays unresolved rather
than creating another repository. Reconnect the original account and reconcile
again. Permission denials are reported separately and can be retried after
fixing authorization. Disconnecting locally removes saved credentials; revoke
access in GitHub's application settings to revoke authorization on GitHub too.

## Automatic GitHub setup

In **Setup & settings**, choose **Set up GitHub automatically / Continue**.
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

**Model & tool logs** searches requests, partial and complete model responses,
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
The Qiling dependency lane uses a verified Haswell guest CPU and a fixed timestamp
counter tied to `clock_ns`; CPU random instructions still stop replay. Host files, process creation and networking are not
forwarded. `ha_mkdir`, `ha_rmdir`, `ha_remove`, `ha_rename`, `ha_clock` and
`ha_random` expose the corresponding declared effects to recovered C.

**Complete Linux program** acceptance supports static ELF and bounded dynamic
ELF/PIE originals under Qiling. `original_dependencies` maps absolute guest
interpreter/library paths to files in the project. Every dependency is protected
and hashed; no host libraries are discovered automatically. The rebuilt C
candidate remains freestanding and static. Loader metadata, mapping, TLS setup
and single-thread registration use an explicit guest contract. Constructors
cannot consume standard input or perform external writes before program entry.
Loader activity is retained separately from application events.

Acceptance pins the original, dependencies and input corpus, rebuilds
independently, and retains the resulting executable. Strict mode (the default)
also matches recorded application effects and random consumption. Explicit
`effect_policy: "observable"` compares stdout/stderr, exit, stdin consumption,
paired memory and final file/directory contents, allowing a different allocator
or library implementation. Both modes retain event traces. Neither ignores a
fault, unsupported syscall, missing dependency or exhausted startup budget.
This lane is bounded Linux reconstruction, not arbitrary Windows/game/OS
compatibility or an all-input equivalence proof.

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

**Back up workspace** saves controller metadata, model logs, learning state,
originals, workspace/native project files, artifacts, sources, settings and
Hermes databases in a verified ZIP. Pause active work first. Browser profiles
and OS credentials are excluded and require reconnecting. Restore offline to an
empty directory with `python -m hivemind_assembly restore --backup FILE.zip
--data-dir EMPTY_DIRECTORY`. The application folder can be replaced without
moving or clearing its external user data directory.

Installation and **Check installed foundations** now run source-known process/file
replay and ELF/PE pointer probes. A native shared library supplies an independent
result on the installed host (including a generated DLL on Windows). Each probe
retains its own result, so a missing runtime does not hide the other failures.
The Windows branch still requires actual Windows acceptance.

Current implementation and verification limits are recorded in
`_app/release_status.json`. The full audit is a separate pass.

## Linked ELF and Windows PE function reconstruction

Choose **Linked ELF / Windows PE function calls** in Independent acceptance.
An original function may be selected by symbol or absolute address. The candidate
uses a sources/declarations/optimization build manifest, a function symbol and
`sysv` or `win64` ABI. Windows builds require Clang and LLD. The original and
candidate may use different ABIs, allowing checks of Windows-to-Linux recovery.

Cases contain `arguments`, `buffers` and `output_bits`. Pointer arguments use
`{"buffer":"data","offset":0}` and buffers use `{"id":"data","hex":"01000000"}`.
Multiple pointers can reference the same buffer. All buffer bytes and the integer
return are checked; writes to read-only buffers or outside exact bounds fail.
Protected acceptance requires at least two cases and rebuilds independently.
Optional `original_dependencies` maps DLL filenames to project paths. Supplied
PE dependencies are relocated and their named/ordinal imports and forwarded
exports resolved using pefile. Missing imports, TLS, DLL initialization,
image-global writes and operating-system effects stop verification.

Function inventories and static callgraphs support pagination. The
`plan_reconstruction` capability validates a complete set of callgraph pages,
groups mutually recursive functions and orders groups by their dependencies.
It retains external targets and does not claim to discover all indirect calls.

## Standing goals

In Projects, select the root task under **Standing goal** and enter `/goal`.
HA retains the objective across restarts and continues through incomplete turns.
All worker, adviser and reviewer requests, including project children, share a
1,000-request default budget. Retrying the same retained request counts once.
Use `/goal status`, `/goal pause`, `/goal resume`, `/goal clear`, or
`/goal budget 2000`. Pause/clear stop new work at the next step boundary; task
pause/cancel can interrupt active work. Increasing a spent budget does not
silently resume it. A root goal is achieved only when independent acceptance
passes. Child completion, summaries and checkpoints do not finish it. Exact
native routes and usage limits still apply; no auxiliary API judge is used.

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

Recipes may declare `comparators` for selected `output_paths`. Unlisted files
remain byte-exact. For a frame, use
`{"frame.rgba":{"format":"rgba8","width":16,"height":16}}`.
Pixels are tightly packed RGBA bytes in stored row order, including alpha.
Optional `max_channel_error` and `max_bad_pixels` default to zero. The result
reports changed pixels, peak channel error and the bounds of pixels exceeding
the threshold. Every selected frame must be present at the declared size; use
separate paths to check multiple frames at recorded replay checkpoints.

For audio, use `{"audio.pcm":{"format":"pcm_s16le","channels":2,
"sample_rate":8000,"frames":32}}`. Samples are interleaved signed 16-bit
little-endian values. Optional `max_sample_error` and `max_rms_error` default to
zero and both must pass independently for every channel. Sample count and channel
order remain exact. There is no time alignment, resampling or gain adjustment.
Sample rate describes the capture contract; raw PCM cannot prove hardware timing.

Tolerances are pinned with the owner's recipe and cannot be changed by workers.
Each program must still produce identical observations across repetitions,
even when differences between the original and reconstruction are tolerated.
Exit status and stdout/stderr remain exact. **View latest observations** shows
frame and per-channel waveform previews with quantitative comparison results.
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
survive restarts. **Check / reconcile** looks up a lost response; it never repeats
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

External stdio and HTTP MCP connections have explicit project and tool grants.
Workers receive only their authorized connection names and tool names. Calls use
the existing operation journal and revision fences; an interrupted external
mutation is not automatically replayed. Connection arguments must not contain
credentials. Automatic external OAuth onboarding is not implemented yet.

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

`/goal budget unlimited` explicitly removes HA's project turn cap while retaining
usage records and independent completion checks. Provider allowance and availability
checks still apply. Existing bounded goals retain their configured limits.
