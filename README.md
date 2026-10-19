# Hivemind Assembly

A local reverse-engineering workspace for collaborative agents, independent verification, and reusable learning. Version 0.4.0 is an engineering preview. Ghidra and REA remain complete foundations; task control, native browser sessions, evidence, and learning are integrated around them.

## Start on Windows

1. Extract the Windows release ZIP and open `Start_Hivemind_Assembly.cmd`.
2. The launcher installs the bundled Python runtime and pinned dependencies into your user data directory, then opens the dashboard.
3. Run **Semantic self-check** to exercise the independent verifier.
4. Install Git, Node.js and Java 21 or newer for the complete foundations, then use **Setup & settings → Install pinned foundations** and restart. Existing installations can be configured in settings.
5. Configure the native sessions using `_app/NATIVE_SETUP.md`. Each role retains its designated provider, surface, model and effort. Inference APIs, paid overage and manual relay are not fallbacks.

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

- Persistent Ghidra projects, inventories, decompilation, instruction P-code and guarded annotations with saved-operation reconciliation. Complete REA analysis remains available.
- Retained local operations and batches of independent checks continue without model allowance. Response timeouts use persistent bounded backoff; uncertain deliveries retain their original request identity.
- SQLite task ownership, writer epochs, revision checks, durable handoffs, operation journals and immutable artifacts. Restarted native exchanges retain their request IDs.
- Exact native route/account observation, shared-allowance admission, one scheduled usage attempt per account scope per rolling 24 hours, separate role conversations and late-response rejection.
- Automatic large-result attachments when configured, hash-checked returned downloads, bounded artifact reads and guarded binary/text saves.
- Original-preserving document ingestion, revision-aware required reading and explicit source-sharing permissions.
- Real SLEIGH/P-code lifting, independent Unicorn differential execution, scoped Z3 proofs and an executable hybrid recovery fixture.
- Acceptance evidence, project controls, sources, baseline methods, learned assets, rollback, settings and controller backups in the dashboard.

## Learning

Accepted work retains evidence-backed knowledge and procedure candidates. A single success does not activate them across projects. Structured playbooks support localized, hash-guarded edits that preserve untouched details and exceptions. Active context is ranked within a budget and checked for dependency and route compatibility; proposals still require independent evaluation.

The executable workflow engine runs bounded registered operations without arbitrary shell or Python execution. Its initial optimizer reuses identical region proofs within one invocation. Evaluation uses protected, family-separated regression and holdout cases; repeated trials alternate baseline/candidate order and compare all outputs. Promotion requires preserved correctness, measured aggregate speed improvement and bounded per-case slowdown. Execution is tied to the verified engine/dependency fingerprint, and active assets can be rolled back.

Use **Knowledge & skills → Evaluate repeated-proof optimization**, or run `python _app/launch.py learn --data-dir <state-directory>` while the application is stopped. This measures one concrete workflow optimization. General knowledge/procedure optimizers, donor-framework integration and broader cross-project improvement remain unfinished.

## Updates and architecture

Extract a new release over the application folder. Settings, projects, originals, browser profiles, artifacts and learned assets remain in the user data directory. Stop the application before updating or copying that directory. The dashboard backup covers controller metadata only.

One application contains separate core, automation, learning, reverse-engineering and UI modules. Legacy `workbench` imports, existing data paths and older launchers remain compatible. See [architecture](dev/ARCHITECTURE.md), [roadmap](dev/ROADMAP.md), and [related-system decisions](dev/RELATED_WORK.md).

## Development and verification

Use Python 3.12:

```bash
python -m venv .venv
# Activate the environment for your shell.
python -m pip install -r _app/requirements.txt pytest
python -m pytest tests -q
python _app/launch.py verify
python _app/launch.py serve
```

Set `WORKBENCH_TEST_CHROME` to a Chromium executable to run the local browser transport/upload/download fixture. Run `npm install` and `npm run test:dom` inside `dev` for dashboard interaction checks. `_app/release_status.json` records verification evidence.

Local scripted team and browser fixtures do not constitute live-provider acceptance. The five signed-in routes, full Hermes runtime coordination, complete Windows installation/update behavior, broader processor/platform coverage and full application reconstruction remain mandatory unfinished work. The OpenAI Python package is an upstream Hermes import dependency; this application does not instantiate model API clients.
