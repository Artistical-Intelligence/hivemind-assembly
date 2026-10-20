# Hivemind Assembly

A local reverse-engineering workspace for collaborative agents, independent verification, and reusable learning. Version 0.6.0 is an engineering preview. Ghidra and REA remain complete foundations; task control, native browser sessions, evidence, and learning are integrated around them.

## Start on Windows

1. Extract the Windows release ZIP and open `Start_Hivemind_Assembly.cmd`.
2. The launcher installs the bundled Python runtime and the hash-locked Windows dependency set into your user data directory, then opens the dashboard. The first dependency installation needs internet access.
3. Run **Semantic self-check** to exercise the independent verifier.
4. Use **Setup & settings → Install pinned foundations**. On Windows, setup uses WinGet to install missing Git, Node.js 24+, Java 21+ and a C compiler, then installs and automatically checks the pinned foundations on a source-known fixture. Windows may require system authorization or a restart. Existing installations can be configured in settings.
5. Use **Set up all native sessions** on Overview. Setup reuses dedicated sign-ins, discovers exact controls, creates separate conversations and verifies two-way attachment transfers. Unrecognized controls or allowance mappings remain unverified; `_app/NATIVE_SETUP.md` describes the recovery path. Each role retains its designated provider, surface, model and effort. Inference APIs, paid overage and manual relay are not fallbacks.

The application uses dedicated Edge, Chrome or Playwright profiles. It does not copy your everyday browser credentials. User data remains in `%LOCALAPPDATA%\UnifiedWorkbench`, outside the application folder. The host must remain running for autonomous work.

## Working with a project

Create a project in its prepared state, import the target, and define acceptance before resuming the task. Workers declare bounded steps, receive an adviser briefing, request broker operations, and use the retained results to continue. Separate reviewer sessions support recovery.

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

The executable workflow engine runs bounded registered operations without arbitrary shell or Python execution. Its initial optimizer reuses identical region proofs within one invocation. Evaluation uses protected, family-separated regression and holdout cases; repeated trials alternate baseline/candidate order and compare all outputs. Promotion requires preserved correctness, measured aggregate speed improvement and bounded per-case slowdown. Execution is tied to the verified engine/dependency fingerprint, and active assets can be rolled back.

Use **Knowledge & skills → Evaluate repeated-proof optimization**, or run `python _app/launch.py learn --data-dir <state-directory>` while the application is stopped. This measures one concrete workflow optimization. Native knowledge/procedure effectiveness and broader real cross-project improvement remain unverified; the donor-backed candidate and evaluation paths are described below.

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

## Cumulative program reconstruction

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
boundaries to recovered C. Host files, process creation and networking are not
forwarded. Undeclared or unsupported effects cannot pass acceptance. **Complete static Linux program** acceptance pins an original ELF and
input corpus, rebuilds independently, checks output, exit, input consumption,
paired memory regions and declared external effects, and retains an executable.
It rejects unsupported syscalls, dynamic linking, faults and exhausted budgets.
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
