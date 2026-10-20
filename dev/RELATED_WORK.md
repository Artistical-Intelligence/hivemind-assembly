# Related systems and implementation decisions

This comparison informs engineering choices; upstream benchmark results are not
Hivemind Assembly results. The implemented changes below do not require another
runtime. The subsequent integration decisions describe planned work, including
upstream components, and do not authorize an inference transport substitution.

| Project | Useful approach | Decision for Hivemind Assembly |
| --- | --- | --- |
| [ReAgent](https://github.com/Dryxio/reagent) | Candidate overlays, configured build/runtime gates, dependency-ordered manifests, explicit evidence gaps | Adopt separate candidate builds and independent behavior checks. The implemented first lane compiles freestanding C and executes candidate/original bytes in Unicorn. Multi-function dependency planning and cumulative project builds remain future work. |
| [Hermes scheduler](https://github.com/NousResearch/hermes-agent/blob/ddabd3837862022a6053331fe3ba97cf9716b9e3/cron/scheduler_tick.py) | Durable admission before dispatch, guarded ownership, explicit treatment of recurring and one-shot work | Retain already authorized operations before dispatch, drain them without requiring another model allowance, and avoid resending uncertain native messages. Full Hermes coordination integration remains required; the current SessionDB host does not satisfy that requirement by itself. |
| [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence) | Separate resumable execution checkpoints from durable cross-thread knowledge | Preserve the existing operation/flow journal separately from learning assets. Borrow the separation of concerns without adding a second agent runtime. |
| [ACE](https://github.com/ace-agent/ace) | Localized grow-and-refine edits; generation, reflection and curation have different responsibilities | Add stable playbook entry IDs, guarded delta edits, duplicate rejection, preserved conditions/exceptions and execution evidence. Proposals remain candidates; the complete ACE adaptation loop is not yet integrated. |
| [SkillOpt](https://github.com/microsoft/SkillOpt) | Bounded procedure edits driven by scored trajectories and held-out evaluation | Keep proposal generation separate from protected evaluation and promotion. Do not equate a successful task, a plausible lesson or retrieval with demonstrated procedure improvement. Native-session rollout evaluation is still required. |
| [ShinkaEvolve](https://github.com/SakanaAI/ShinkaEvolve) | Separate candidate generation, execution evaluation and program archive; sample-efficient search | Integrate the candidate archive, parent selection and evaluation machinery with native-session proposals. Use independently measured correctness and timing to select improvements. The current duplicate-proof optimizer is a limited baseline, not completion of the executable-learning requirement. |
| [McSema](https://github.com/lifting-bits/mcsema) | Separate control-flow recovery from instruction translation; reuse an established intermediate representation and toolchain | Continue using Ghidra/SLEIGH and independent execution machinery. Investigate mature lifting engines for broader executable reconstruction rather than treating the bounded interpreter as a complete platform. McSema itself is archived and is not adopted as a new dependency. |

## Implemented changes

- Freestanding C candidates compile in a temporary build directory. ELF extraction
  rejects unresolved relocations and external dependencies. Candidate code runs
  in Unicorn; the candidate executable is never launched directly on the host.
- Protected original bytes and boundary/random cases are retained before a task
  begins. Completion recompiles the actual candidate and compares scalar return
  values, preserved registers and stack balance. Input/output widths and the SysV
  x86-64 calling convention are explicit. Passing these cases is not a proof over
  all inputs, memory effects, operating systems or complete applications.
- Read-only replay-safe computation batches persist each operation independently.
  Successful results survive restart; a failed independent computation does not
  discard the other results. Missing model allowance does not block retained work.
- Response deadlines use bounded persistent backoff. Admission and native request
  identity remain enforced. Missing sign-in, ambiguous delivery and model mismatch
  are not treated as permission to resend or switch transports.
- Playbook edits retain unrelated entries exactly. Context selection ranks relevant
  active assets within a character budget and excludes invalid dependencies or
  incompatible route bindings. Sharing restrictions continue to apply.

## Remaining integration work

The strongest next investments are full Hermes task/role coordination, function
call graph manifests, cumulative builds, richer platform observation and a real
native-session procedure optimization benchmark. A larger collection of framework
wrappers would not substitute for those end-to-end capabilities.

## Integration decisions — research reviewed 2026-10-19

These are implementation targets, not claims that the integrations already work.
The design documents remain authoritative; the acceptance scenarios below are
additional gates, not a replacement or reduction of their scope.

### Model outputs and debugging

Use the existing durable store and Hermes transcripts as the local record, with
OpenTelemetry/OpenInference export to a managed local Phoenix review service.
Provide an integrated review entry point, live activity view, search and filters,
raw/parsed response comparison, artifact links, annotations and JSONL export.
Phoenix deployment and Windows packaging must pass integration tests before this
choice is considered implemented. Capture must continue when the viewer is down.

Sources and tradeoffs:

- [Hermes observer hooks](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/developer-guide/observer-hooks.md)
  provide lifecycle events, explicit correlation IDs, sanitized payloads and
  fail-open callbacks. Reuse this extension contract rather than patching model
  clients for telemetry. Verify the contract against the pinned Hermes revision;
  current upstream documentation is not evidence of pinned-version availability.
- The pinned Hermes `hermes_cli/session_export.py` already supplies JSONL and
  Markdown export renderers. Reuse them where their transcript schema fits.
- [Phoenix architecture](https://arize.com/docs/phoenix/self-hosting/architecture)
  supports a local SQLite-backed viewer and trace collector.
  [Phoenix OTEL](https://arize.com/docs/phoenix/tracing/how-to-tracing/setup-tracing/setup-using-phoenix-otel)
  supports manual instrumentation; native browser exchanges require it.
- [Langfuse](https://langfuse.com/self-hosting) is an alternative trace backend,
  but its self-hosted web/worker, Postgres, ClickHouse, Redis/Valkey and object
  storage stack is heavier for the initial Windows application. Preserve export
  interoperability without making that stack a mandatory installation.
- [Langfuse trace structure](https://langfuse.com/docs/observability/best-practices)
  distinguishes sessions, traces and individual model/tool observations. Record
  every invocation instead of one aggregate final response for an entire run.
- [OpenTelemetry resilience](https://opentelemetry.io/docs/collector/resiliency/)
  documents loss on queue overflow, retry expiry and crashes. An in-memory trace
  exporter is not an authoritative journal.
- [Hermes issue 95057](https://github.com/NousResearch/hermes-agent/issues/95057)
  reports context detach failures across tasks/threads. Test explicit context
  propagation across every async/thread boundary; do not assume callback order
  or thread-local active spans correlate a run correctly.

Required capture contract:

1. Record project, task, run, turn, route/role, conversation, request, attempt,
   operation, parent span, source revision and artifact identities. Distinguish
   requested model/mode/effort from observed labels and identity evidence.
2. Persist outgoing assembled context and attachment hashes before dispatch.
   Persist visible incoming text before parsing, including malformed, partial,
   refused, cancelled and timed-out responses. Capture response association
   evidence independently of the model echoing a valid request ID. Never assign
   an ambiguous response to a task merely because it is the latest page text.
3. Retain raw output, parsed output and validation errors separately. Preserve
   changed partial snapshots with bounded storage and a final snapshot; do not
   claim token-level streaming from periodic DOM observations.
4. Include adviser, worker, reviewer and learning calls; include tool inputs,
   results, latency, retries, allowance decisions and artifact provenance.
   Provider-hidden reasoning and unavailable token/cost measurements remain
   unavailable, not invented. Disable unconfigured auxiliary inference calls.
5. Reuse stable event/span IDs during recovery. Journal first, export through a
   durable outbox, and retain local export progress. Re-exporting must not send a
   model prompt or execute a tool again. Viewer failure is distinct from capture
   failure; surface capture loss and disk exhaustion explicitly.
6. Keep credentials and browser session secrets out of traces. Keep protected
   evaluator inputs/results inaccessible to candidate agents through trace
   search, export or MCP. Separate owner debugging access from learner access.
   Render model output as untrusted content. Local capture is the default;
   external trace upload is a separate configured destination.

### Repository provisioning

Use the official GitHub MCP `create_repository` action through the capability
broker, with explicit owner/name/private settings and a durable operation ID.
Tool advertisement is not evidence that the credential can successfully create
a repository. No test repository was needed for this research.

- [Issue 1075](https://github.com/github/github-mcp-server/issues/1075): a remote
  OAuth session listed tools but repository creation returned 404. A contributor
  diagnosed missing scopes and recommended PAT authentication. The issue later
  closed for inactivity; it is not a confirmed upstream code fix.
- [Issue 756](https://github.com/github/github-mcp-server/issues/756): a separate
  user reported repository creation working with the hosted MCP endpoint and a
  PAT. This supports that workaround for that client's authentication problem,
  not a universal explanation for all connector failures.
- [GitHub REST creation permissions](https://docs.github.com/en/rest/repos/repos#create-a-repository-for-the-authenticated-user):
  classic/OAuth private creation requires `repo`; current fine-grained permission
  alternatives include repository Administration write or Repository creation
  write. Owner, installation scope and organization restrictions still matter.
- [MCP server configuration](https://github.com/github/github-mcp-server/blob/main/docs/server-configuration.md):
  toolsets, explicit exclusions, read-only mode and authentication scope handling
  can change advertised capabilities. Host approval is a separate boundary.

Classify failures as unavailable capability, authentication/authorization,
organization policy, host approval rejection, invalid/conflicting request,
rate limit, or uncertain delivery. Preserve the returned error and request ID
with secrets removed. Do not automatically change credentials, visibility or
transport after a denial. After an uncertain creation response, query the exact
owner/name and reconcile expected identity/settings before any retry; never
create a second suffixed repository or adopt an unrelated name collision.
Persist the returned repository ID and verify private visibility. Local work
must remain possible if remote provisioning is unavailable. Use local project
directories for experiments rather than a new repository for every trial.

### Deeper upstream reuse

| Area | Reuse target | Required adaptation and evidence |
| --- | --- | --- |
| Coordination | Hermes Kanban task graph, dispatcher/ownership and session machinery | Native-session execution must participate in real Hermes coordination. SessionDB alone is insufficient. Pin revisions; test dependency, review, cancellation and restart transitions. |
| Knowledge | ACE `ace/core/{generator,reflector,curator}.py` and playbook operations | Adapt inference calls to exact native routes; retain incremental edits, helpful/harmful evidence and deterministic merging. Measure downstream task performance. |
| Procedures | SkillOpt `skillopt/engine/trainer.py`, optimizer modules and `evaluation/gate.py` | Implement its documented backend contract over durable native calls; preserve rollout/reflect/select/update/evaluate, rejection memory and validation gates. Current synchronous/global backend assumptions require care with concurrent roles. |
| Executable improvement | ShinkaEvolve `shinka/database/{dbase,parents,islands}.py`, edit and evaluation components | Reuse archived candidates, parent selection and executable evaluation. Keep protected evaluators outside writable candidate workspaces. Native proposal transport and allowance accounting replace API-budget assumptions. |
| Reconstruction | ReAgent function manifests, isolated candidate overlays and cumulative build/runtime validation | Preserve independent reverser/checker evidence and dependency ordering. Passing an individual scalar function is not application acceptance. |
| Binary context | GhidrAssist graph storage, summaries and module discovery | Reuse graph/query machinery where practical; invalidate evidence on binary/type/analysis revision changes. API-centric model orchestration is not a native-session adapter. |
| Lifting/recompilation | rev.ng model and artifact/analysis pipeline | Evaluate as an additive specialist backend for supported targets, retaining complete Ghidra/REA. Reuse ABI/type/memory models and dependency-aware invalidation rather than building a universal lifter. |
| LLVM validation | Alive2 | Use for compatible LLVM transformation checks. Its documented lack of interprocedural transformation support prevents treating it as a whole-application proof engine. |
| Matching reconstruction | decompdecomp compiler/scoring and function progress workflows | Useful where the original toolchain and byte matching are meaningful. Current upstream is alpha and Linux-only; it cannot replace Windows/native-browser requirements. Byte matching and behavioral equivalence are separate acceptance modes. |

Additional primary sources:

- [Hermes Kanban](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/kanban.md)
- [SkillOpt backend contract](https://github.com/microsoft/SkillOpt/blob/main/docs/guide/new-backend.md)
- [GhidrAssist](https://github.com/symgraph/GhidrAssist)
- [rev.ng model and artifact pipeline](https://docs.rev.ng/user-manual/key-concepts/artifacts-and-analyses/)
- [Alive2](https://github.com/AliveToolkit/alive2)
- [decompdecomp](https://github.com/n-delic/decompdecomp)
- [decomp.wtf discontinuation](https://decomp.wtf/)
- [Temporal execution-state comparison](https://docs.temporal.io/ai/featured/memory-state-stripe)

Reuse decisions require source revision/license records, an explicit adapter
boundary and an executable comparison on representative project tasks. Preserve
upstream tests and attribution when importing code. Do not infer maturity from a
README or transfer an upstream benchmark result to this application.

### End-to-end completion evidence

Map every authoritative design requirement to implementation and evidence before
declaring feature completion. The integration suite must include:

- One objective through Hermes planning, persistent adviser guidance, worker
  execution, independent review, cumulative build and protected acceptance.
- Multiple dependent functions, shared memory/global effects and platform
  boundaries; readable recovery improves a usable low-level baseline.
- All five exact native routes, separate conversations, artifact transfers,
  exhausted/unknown allowance, reconnect and interrupted delivery.
- Retained executable work continues while reasoning capacity is unavailable;
  restart never blindly repeats an ambiguous external mutation.
- Searchable outputs for every role, malformed/missing-ID replies, partial
  output, trace viewer outage, restart, export and access isolation.
- Knowledge, procedure and executable learning each complete a real proposal,
  evaluation, promotion and rollback cycle. Separate training, selection
  validation and sealed acceptance sets; compare correctness and repeated timing
  on independent task families, including a second project.
- Repository provisioning and reconciliation, tested without assuming a tool
  listing proves write access. Classify live authorization limits separately.
- Windows installation, process ownership, update preservation, database
  migration, recovery and final release packaging.

Keep implementation status, automated integration evidence and live-account
acceptance as separate fields. A fixture, a configured adapter, a green unit
suite or an upstream capability does not establish end-to-end live acceptance.


## Run 2 integration evidence

Checked complete upstream source snapshots before selecting modules:

- Hermes `c0015464f0f40d52c5702a84cf58e70361f4a04c`: use its actual
  Kanban create/link/claim/block/complete/recompute APIs and SessionDB. The
  native transport never launches API inference workers. Real-source dependency
  and restart checks run with `HA_TEST_HERMES`.
- ACE `82709de050e1db6e6ef2f07bcb0393560b94992a`: retained reflection and
  curator prompts, adapted at the host boundary for visible evidence and bounded
  JSON edits. This is not a claim that ACE's API-specific runner is embedded.
- SkillOpt `1a44050fc53aa4938a7a3927b6cca550491bfe51`: retained exact
  patch application and validation gate. Native model proposals and protected
  evaluations surround these pure modules; no global API backend is configured.
- Shinka `8adc053a2ce4511ad2ac310e004c530a73fb974a`: retained parent
  strategies and use beam selection over an asset/engine-filtered measured
  archive. Distributed island execution is not claimed.
- Phoenix/OpenInference: local append-only capture is independent of the viewer.
  Explicit loopback-only OTLP JSON export uses stable trace/span IDs. Export is
  at least once; no managed Phoenix deployment or receiver deduplication is claimed.

Official GitHub documentation confirms OAuth registration's callback field and
Device Flow setting: https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/creating-an-oauth-app
and https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps .
The registration adapter requests `repo`, reads only the public Client ID and
never generates a client secret. The cloud browser reached GitHub's sign-in
page, so current live registration validation remains blocked on authentication.

The program build lane uses a fixed freestanding runtime and independently
compares original/candidate machine images. A source-known multi-file fixture
also executes natively as a separate oracle. Its successful local replay is not
evidence of an unattended provider/Ghidra reconstruction or broad OS support.


Further integration decisions:

- Complete Qiling 1.4.6 supplies ELF loading and Linux file/memory semantics:
  https://github.com/qilingframework/qiling and https://docs.qiling.io/en/latest/hijack/ .
  HA adds a declared environment and effect/permission bounds. Its file/memory
  fixture agrees with separately executed source-known native code; no Windows
  OS emulation or upstream benchmark result is claimed.
- Public WebMCP tools supply native UI actions when the page registers them:
  https://webmachinelearning.github.io/webmcp/ . HA discovers current tools,
  checks exact origin/name/schema, journals intent before dispatch, and never
  changes to another send mechanism after an uncertain action. This is distinct
  from undocumented provider endpoints or inference APIs.
- The enlarged compiler corpus uses actual GCC and Clang outputs and an
  independent native oracle, including an intentionally wrong reconstruction.
  Ghidra's actual native decompiler/context/annotation paths and Hermes's actual
  database modules were also executed. These checks do not replace signed-in
  provider or clean-Windows acceptance.

### Linked Windows function recovery and incremental checkpointing

Reuse pefile/pyelftools for image/symbol parsing and LLVM Clang/LLD for PE linking.
The Win64 call setup follows Microsoft's register, shadow-space and preservation
rules. Neither PE parsing nor a successful bounded call substitutes for the OS
loader, imports, TLS or graphics/audio/input support.

- https://learn.microsoft.com/en-us/cpp/build/x64-calling-convention
- https://learn.microsoft.com/en-us/cpp/build/x64-software-conventions
- https://lld.llvm.org/windows_support.html
- https://docs.github.com/en/rest/guides/using-the-rest-api-to-interact-with-your-git-database
- https://docs.github.com/en/rest/git/trees

GitHub's Git database API rejects empty repositories. The checkpoint publisher
initializes a verified source file through Contents with retained intent, then
uses tree/commit/ref objects for incremental multi-file checkpoints. It never
force-pushes and preserves unrelated files in the base tree.

Qiling's documented argv/env process model is reused for declared CLI inputs:
https://docs.qiling.io/en/latest/howto/ . The pinned 1.4.6 ELF loader encodes
strings as Latin-1, so the adapter preserves declared UTF-8 bytes explicitly
and separates guest argv[0] from the temporary host binary path. No alternate
loader or host environment inheritance is introduced.

The dynamic Linux extension retains Qiling's ELF interpreter loading, memory
mapping and architecture handlers, and uses its ABI-specific stat structure
packer. Inspection of pinned Qiling's two-stage Linux run showed that an early
interpreter stop could otherwise be followed by application execution. HA selects
one explicit initial entry and enforces the budget across both phases. Native
source-known shared-library and glibc/printf fixtures exercise the integration;
this does not establish arbitrary Linux or Windows runtime compatibility.
- https://github.com/qilingframework/qiling
- https://docs.qiling.io/en/latest/memory/
- https://docs.qiling.io/en/latest/hijack/

## Persistent goals and executable validation

- Hermes persistent goals: https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/goals.md . Inspected the pinned local implementation/documentation. HA uses the standing-objective, continuation, pause and turn-budget behavior over its existing native team and acceptance controller. It does not invoke Hermes' auxiliary model API judge. Project children share the root budget; their completion cannot finish the root goal.
- DIFFER: https://github.com/trailofbits/differ . Reuse the paired original/transformed input-and-output testing approach, retaining explicit limits and reproducible failures. Its fuzzing/comparator implementation is a useful future integration; it is not bundled or claimed as implemented here.
- GitHub hosted runners: https://docs.github.com/en/actions/reference/runners/github-hosted-runners . Native Linux/Windows execution is appropriate for supported binaries, toolchains and headless checks.
- Billing: https://docs.github.com/en/billing/managing-billing-for-github-actions/about-billing-for-github-actions . Private repository usage beyond included amounts is billed; dispatch needs an owner-configured spending boundary. Larger runners are not included-quota runners.
- Browser ports: https://emscripten.org/docs/porting/emscripten-runtime-environment.html . Reconstructed C/C++ may be compiled to WebAssembly with supported SDL/WebGL APIs; a browser port is not a native Windows execution oracle.
- Software rendering: https://docs.mesa3d.org/drivers/llvmpipe.html . Headless CPU rendering can exercise graphics functionality; it is not GPU performance or complete driver equivalence.
- Alive2: https://github.com/AliveToolkit/alive2 . LLVM translation validation complements executable testing; it does not establish whole-application/OS equivalence.

- EGL surfaceless specification: https://registry.khronos.org/EGL/extensions/MESA/EGL_MESA_platform_surfaceless.txt . The included source-known probe uses a real pbuffer and OpenGL pixel readback, without substituting synthetic rendering.
- Windows Job Objects: https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects . Use process-tree membership before starting the target, with kill-on-close; test the Windows branch on Windows before claiming platform acceptance.

## Frame and audio observation contracts

- Pixelmatch: https://github.com/mapbox/pixelmatch/blob/main/README.md . Reviewed
  pixel mismatch counts, thresholds and anti-alias handling. Its perceptual
  image comparison is useful for visual regression; HA's raw capture contract
  instead requires explicit channel-error and pixel-count limits, including
  alpha, with no automatic anti-alias exclusions or alignment. This small exact
  arithmetic comparator does not reproduce Pixelmatch's perceptual algorithm.
- SciPy correlation: https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.correlation_lags.html . Correlation can locate time shifts in signals.
  HA retains fixed sample alignment for acceptance because automatically shifting
  captures could conceal an input/replay latency regression. Per-channel absolute
  peak and RMS error are sufficient for this bounded integer PCM contract; no
  signal-processing library, audio decoder or resampler is reimplemented.

Source-known C/Python pulse replay and real EGL readback exercise these contracts.
They are capture checks, not claims of arbitrary game, audio-device or GPU parity.

## Resumable hosted execution

GitHub documents `return_run_details` for workflow dispatch, including a returned
workflow run ID, while an ordinary dispatch can return HTTP 204. HA accepts both,
correlates ambiguous responses through a unique `run-name`, and never resends an
uncertain dispatch. The documented `ref` is a branch or tag, so HA creates a unique
tag at the reviewed SHA and also checks that SHA in the managed workflow before
native execution. Branch publication is unaffected. Existing repository setup
and GitHub authentication are reused; no second CI scheduler is implemented.

- https://docs.github.com/en/rest/actions/workflows
- https://docs.github.com/en/rest/actions/workflow-runs
- https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax

This is an optional owner-authorized execution lane. GitHub's spending boundary
must already be configured. API fixtures establish request recovery and identity
checks, not available quota, real hosted execution or clean Windows acceptance.
