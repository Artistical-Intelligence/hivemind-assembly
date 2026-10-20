# Hivemind Assembly architecture

Hivemind Assembly is a modular monolith. One process, one launcher, one release
and one repository compose the current application. Reverse engineering is the
primary goal. A future harness integration must not limit the specialist tools,
weaken their checks or require slower network calls on critical paths.

## Responsibilities

| Package under `_app/hivemind_assembly` | Owns |
| --- | --- |
| `core` | Durable store, controller, operation journal, artifacts, jobs, capability contracts and execution broker |
| `automation` | Native browser sessions, model/allowance policy, team flow, repeated-failure recovery and Hermes session adapter |
| `learning` | Restricted source ingestion/reading obligations and evaluated knowledge, procedure and executable promotion/rollback |
| `domains/reverse_engineering` | Ghidra/REA bridges, specialist tools, P-code execution, independent differential verification, scoped proofs, hybrid fixture and 20 baseline methods |
| `application` | Composition, dashboard, installation and setup |

The core has no reverse engineering, browser or UI dependency. Automation
receives a configured broker, and obtains the selected domain's instructions,
skills and capability names from that broker. The application selects the reverse
engineering domain explicitly. A core-only broker exposes workspace file
operations and checkpoints without importing specialist libraries.

The reverse engineering package depends on the small core contracts and its
own specialist modules, not on Hermes, native chat sessions or the dashboard.
`ToolContext` supplies workspace, configuration, job runner and cancellation.
It does not give a domain ownership of the task database or learning evaluator.

The broker retains the same lease/revision checks before dispatch, durable
operation identity, result artifacts and completion rules. The domain declares
which operations mutate projects and how interrupted operations are reconciled.
Native annotation reconciliation reads Ghidra's retained ledger; the broker
then checks the controller epoch/revision before accepting the saved result.
Uncertain external analysis is not automatically replayed. Domain identifiers
and capabilities are code-selected; untrusted dynamically downloaded plugins
are not loaded by this release.

## Specialist operations remain direct

The existing seven operations are preserved: `inspect_program`, `decompile`,
`export_pcode`, `propose_annotation`, `rea_analyze`, `compare_states` and
`check_equivalence`. Full Ghidra/REA distributions remain intact. Native
headless invocation, semantic libraries and the reopened annotation ledger
remain the implementation, with no compulsory MCP or HTTP intermediate step.

Bidirectional MCP is an optional execution interface supported by the application.
Direct specialist operations remain available without an MCP hop. The small text-counting test domain only verifies
dependency boundaries; it is not a second application or a claim of cross-domain
learning. Selected donor optimizer modules are integrated; broad cross-project improvement remains unverified.

## Independent acceptance and workflow learning

`core.Acceptance` owns immutable task contracts, completion proposals, project
revision/lease checks and evidence retention. The domain supplies the verifier.
The reverse-engineering verifier pins original region bytes as protected
artifacts, reads the actual candidate file, and repeats the scoped proof.
Task acceptance is committed only if ownership, revision and candidate hashes
still match. Arbitrary objectives have no default passing condition.

`learning.WorkflowRunner` executes bounded plans over registered pure functions.
The initial domain adapter registers region equivalence only. Identical
operations may share a result within one invocation; mutations and browser
operations are not eligible. `WorkflowLearning` owns protected suites,
family-disjoint holdouts, alternating repeated measurements, complete-output
comparison, promotion and engine-fingerprint checks. A code/dependency change
requires re-evaluation against the unoptimized fallback before reuse.

Successful task traces become knowledge and procedure candidates. They remain
local and inactive pending independent evaluation. The built-in proof and function-call workflows
contain generic parameter references and may be offered to native workers
once promoted. They do not expose evaluator cases or private project bytes.
Steps may select an earlier result using `{"$step": 0, "path": ["value"]}`;
optional plan outputs select the observed results. Forward references and missing
paths fail explicitly. Function replay refuses host clocks, random CPU instructions,
port I/O and unmodeled OS effects. Native proposals still need the bound protected
suite and must preserve the baseline's complete selected results, including buffers.

## Compatibility and persistence

The old `workbench` imports and `python -m workbench` remain compatibility
entry points. The old broker facade chooses reverse engineering by default;
new code composes `core.Broker(..., domain=ReverseEngineeringDomain())`.
The installed application uses only `hivemind_assembly` internally.

The rename does not migrate or reset `%LOCALAPPDATA%/UnifiedWorkbench`, the
Linux `unified-workbench` data folder, database schema, Ghidra project name,
Hermes session IDs, HTTP token header or browser session keys. Those are
persistent identifiers rather than branding. Settings, projects, originals,
evaluation truth, learned assets, profiles and credentials stay outside releases.

The Windows root contains the launcher and README with internals under `_app`.
The source archive additionally includes tests, CI and developer instructions.

## Gates for further changes

Run the existing behavior suite as well as boundary tests. Validate actual
Ghidra/REA/native-session behavior when those changes require integration
evidence. A passing mock or corpus compilation is not live acceptance. Keep
historical integration evidence separate from checks executed on the current
version. Correctness, specialist coverage and measured speed take priority over
portability abstractions.

## Repository provisioning

`core.repositories.Repositories` owns a durable, project-scoped primary
repository record. It is injected into the broker independently of any domain.
`integrations.github` supplies GitHub.com device authorization, OS credential
storage and the repository HTTP client. The application composes them and
exposes sign-in, creation policy and project controls. Native workers use the
same fenced `create_repository` operation as the user-facing project action.

Creation calls GitHub's REST repository endpoint directly, as its official MCP
server does. ChatGPT plugin credentials are not exported or inherited. Local
installations use an owner-controlled OAuth app with Device Flow enabled,
request `repo`, obey the device polling interval and `slow_down`,
and refresh expiring tokens. Only the OS vault contains access/refresh tokens.
The account ID is checked after authorization/refresh and before provisioning;
a request retains the same credential through its external operations.

Before POST, HA reserves the project/name and durably records intent. A random
nonce temporarily accompanies the repository description, allowing a lost
creation response to be distinguished from an unrelated repository. Once the
repository ID is durable, HA removes the nonce and verifies the final metadata.
A lost cleanup response is reconciled by ID without recreating the repository.
The nonce never enters source files or commits. No README is initialized.
Read-back verifies owner/name, numeric identity, private visibility and push
permission. Existing names are never adopted or overwritten. An inaccessible
repository after an uncertain write is not evidence that creation failed.

Successful provisioning advances the project revision and invalidates the
brief. Reconciliation retains writer epoch and revision checks, result artifacts
and immutable operation bindings. Repeated deliveries and concurrent requests
reuse a project's recorded repository. Definite GitHub rejections are distinct
from transport uncertainty. Organization creation is restricted by local
allowlist and GitHub permissions. Automatic public publication, deletion and arbitrary GitHub API access are not
exposed. Verified source checkpoint publication is a separate fenced capability.

References:
- https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps
- https://docs.github.com/en/rest/repos/repos#create-a-repository-for-the-authenticated-user
- https://github.com/github/github-mcp-server/blob/main/docs/host-integration.md
- https://keyring.readthedocs.io/en/latest/


## v0.5 integration additions

`core.traces` retains owner-only transport snapshots before parsing and tool
request/result/error events. Browser turn order associates replies independently
of echoed IDs. The authenticated local UI supports search, annotations and JSONL
exports; optional OTLP export is loopback-only and does not own capture.

`integrations.github_setup` uses a dedicated visible profile, retained registration
intent, unique local app name and explicit GitHub origin/account checks. Only the
public Client ID is persisted in setup metadata. Device credentials remain in the
OS vault. Browser authentication and UI changes remain live acceptance boundaries.

`automation.hermes_board` uses the complete pinned Hermes Kanban implementation
for dependencies and claims. HA's per-project writer lease protects the domain
workspace. Plan intent, publication and flow handoff have separate idempotent
records so incomplete cross-database publication can be resumed. The native
state machine is an inference-transport extension; upstream API workers are not
launched. This integration still needs end-to-end native provider acceptance.

`domains.reverse_engineering.program` links cumulative C translation units into
static x86-64 ELF images and replays read/write/exit/clock effects under Unicorn.
`program_acceptance` protects the original and input corpus, rebuilds from the
actual manifest and sources, and rechecks every source hash before committing
acceptance. Detailed sealed observations remain protected artifacts.

`learning.campaigns` integrates ACE prompts and SkillOpt patch application with
native adviser turns. `learning.experiments` accepts trusted host evaluators,
uses family/project-disjoint holdouts and paired timing, and retains measured
candidates for Shinka parent selection. `propose_workflow` evaluates native
workflow revisions only against an already-bound protected suite, with a bounded
evaluation budget. This is not a claim of tested native cross-project improvement.

`core.backups` verifies a portable snapshot of owned workspace data, including
SQLite snapshots for controller and Hermes state. Offline restoration is locked,
requires an empty directory and verifies content while writing. OS credentials,
browser sessions and installed foundations are excluded.


## Native lifecycle and protected rollouts

`automation.providers` discovers exact visible controls, excluding conversation
content from identity evidence. `sessions` journals creation intent, binds only
persistent provider conversation IDs, and verifies upload/download canaries
before committing replacement bindings. Validated old turns are consumed before
renewal. A draft whose send is uncertain is reconciled without another dispatch.
`webmcp` uses a fixed allowlist of current, same-origin public UI tools and never
falls back after a tool dispatch. The DOM transport remains available otherwise.

`learning.native_rollouts` separates treatment/input from local expected output,
uses fresh trial sessions, retains each paired sample, and resumes quota waits.
Trial requests share project usage reservations. Permission revocation prevents
the next send and promotion. Interrupted timings cannot justify speed-only
promotion. Completed trial tabs close; retained messages and traces remain.
Compiler, verifier and corpus identities bind results to an evaluator version.
Provider account-wide memory isolation still needs live acceptance evidence.

`platform_runtime` delegates Linux ELF/OS behavior to complete Qiling 1.4.6.
A dispatcher guard restricts syscalls, paths, guest memory permissions, total
memory/files/I/O and execution. Each run gets a fresh declared rootfs. Unknown
effects stop execution. Protected program acceptance compares file outputs,
memory, stream results and declared effects across original and rebuilt images.
This does not provide dynamic Windows/game/graphics compatibility.

Installation performs source-known native foundation checks and saves partial
results when a foundation is blocked. Ghidra context export and batched
reconstruction do not modify the complete upstream distributions. The Windows
wheel closure includes a hash-verified unmodified unicodecsv wheel and original
source archive so source releases can reproduce the launcher dependencies.

## Linked function images and checkpoint publication

`call_images` uses upstream pefile and pyelftools for linked PE/ELF inspection,
Clang/LLD for cross-compilation, and Unicorn for bounded calls. SysV, Win64 and
AAPCS64/Windows ARM64 integer/pointer arguments include stack arguments, aliased caller buffers,
nonvolatile registers, Win64 XMM state and floating-point control registers.
Every caller buffer is compared. Access outside exact buffer ranges fails even
when it stays on a mapped page. Image-global writes, unresolved imports, TLS and loader
initialization remain unsupported. `pe_dependencies` reuses pefile relocation and
export metadata to link explicit supplied DLLs, including ordinal imports and
forwarders. It never discovers or downloads DLLs, and pins every dependency in
protected acceptance. Protected `linked_calls` acceptance (with the legacy
`x86_64_linked_calls` scope retained)
pins the original, seals cases, independently rebuilds every source and rechecks
source/manifest hashes. The AArch64 adapter pins a Cortex-A57 CPU, admits static
little-endian ELF and standard ARM64 PE, checks x19-x29/SP and the low halves of v8-v15, and reserves x18.
System instructions are rejected before execution; ordinary BR/BLR/RET and NOP
remain supported. Static whole-program Linux replay selects x86-64 or AArch64 from validated ELF headers; the x86-64-only loader default is preserved for callers that request it. ARM uses the existing Cortex-A57 instruction policy with Linux SVC #0 routed to bounded stream/exit/clock handling. Unknown calls never reach the host. Shared process setup, protected acceptance and cross-architecture comparisons remain in the existing program lane.
The workflow engine fingerprint includes the ARM adapter. This is function
reconstruction, not a Windows or ARM OS runtime.

GitHub is optional. A project can remain local, connect an existing private
repository, or explicitly create one. Creation permission does not gate existing
repository connections. Connecting an existing repository is an owner action.

`core.publication` records exact source hashes after successful host comparisons.
The native controller queues publication before its next model turn. Only the
checked source/manifest snapshot is uploaded; compilation alone is insufficient.
Checkpoint state is append-only. The Git data API retains unrelated remote files,
uses the observed parent and never force-pushes. Concurrent remote changes block
publication. Lost ref-update responses reconcile the saved commit instead of
creating a second visible commit. Empty repositories require one initial verified
source-file Contents API commit before Git tree publication is possible.

Publication excludes runtime/private paths, binaries, detected credentials,
protected artifact copies and recognized verbatim restricted source passages.
This is bounded filtering, not a guarantee of semantic data-loss prevention.
Remote checkpoint evidence and local model logs remain separate. Local-only
projects do not require a GitHub connection or repository creation.

`planning` consumes complete, contiguous Ghidra callgraph pages from one binary
and native revision. Iterative strongly connected components group mutual
recursion without Python recursion-depth limits; the standard-library topological
sorter orders groups by dependencies. External targets remain explicit. Native
Ghidra inventory/callgraph pagination and a complete 13-function plan were tested
on the installed distribution. Static callgraphs do not establish runtime closure.

Process inputs are explicit UTF-8 `argv`/`env` values bounded to 64 KiB. The
Unicorn lane constructs the initial ELF stack; Qiling retains its upstream
loader, with a narrow process subclass separating the staged host path from
the guest program name. Both lanes use the same external-CPU-state rejection
policy and the recovered C startup exposes arguments/environment without host
headers. Protected suites retain these inputs without exposing them to workers.

## Declared dynamic Linux applications

`linux_dependencies` preflights bounded ELF64 images and their supplied
interpreter/library closure. Qiling loads and relocates the actual ELF
interpreter and libraries. The adapter pins the guest CPU model, supplies a
fixed timestamp counter, and reuses upstream stat packing and validated TLS/
memory handlers. Metadata, thread identity and resource limits describe the
declared guest; host process identity and filesystem metadata are not forwarded.
The guest has one thread, rseq returns ENOSYS, and nonempty robust-list cleanup
is unsupported. Executable mappings require supplied dependencies; fixed mapping
replacement is confined to previous mmap regions. Dependencies stay read-only.

One bounded Qiling run spans loader and application; a stopped interpreter cannot
be followed by an unconditional jump to the application. Startup I/O side effects
are rejected. Owner-selected strict/observable comparison policy is sealed in
the protected corpus. Observable comparison retains files, directories, streams,
exit, input consumption and selected memory, while syscall/allocation traces
remain evidence rather than an identical-implementation requirement. The legacy
static acceptance scope remains supported. Guest file handles are closed before
removing the isolated filesystem, including when the target fails to close them.

## Persistent goals and native tool verification

`core.goals` adds a project-wide standing objective over existing tasks and Hermes
planning. SQLite owns one root goal and unique native request reservations. All
roles and children consume the same explicit budget; retries reuse reservations.
Pause/clear stop dispatch at step boundaries. Root acceptance updates goal status
inside its existing fenced transaction. Repeated failed completion proposals route
to the existing reviewer; review-request identity survives retries. There is no
new inference runtime or model API judge.

`core.tool_testing` builds owner-declared recipes and repeatedly executes original
and candidate snapshots with identical explicit inputs. It is domain-independent.
`core.test_acceptance` seals recipes and original files, requires project permission
and a separate owner authorization for the exact recipe, and rechecks candidate
hashes at acceptance. Child planning cannot authorize new native commands. Detailed
observations remain protected from workers; owner controls expose them for debugging.
Successful source checks enter the existing append-only publication journal.

`native_process` uses file-backed streams, deadlines, output bounds and process-tree
cleanup. Windows assigns a Job Object before its cooperative launcher starts target
code; Unix monitors parent lifetime and cleans the process group. These are process
management controls, not security isolation. Native recipes must be trusted with
host access or run in a disposable, suitably isolated environment. All programs are
executed as argument arrays without a shell; no inherited model/GitHub credentials
are passed through the environment. This does not hide host files from native code.

The standalone source runner also works in the manually dispatched GitHub workflow.
It records commit/run/runner identity and observations. Remote results are not trusted
automatically as local acceptance. Account billing policy is external to the workflow.
The Mesa fixture compares actual offscreen GL readback with independent expected
pixels; it does not emulate arbitrary games or establish hardware performance.


## Tag-first knowledge and isolated classification

`learning.scopes` stores a category catalog, material assignments and task grants.
The classifier sees task/project objectives and category metadata only. It cannot
create tags or request content. A source/lesson/skill must match a selected tag;
source permissions, lesson export permissions and evaluator/dependency validity
continue to apply. Unclassified legacy content remains private. Selecting no tags
is a durable valid decision, not a signal to retrieve everything.

Native message envelopes and retained tool requests bind the knowledge fingerprint.
Scope or material-access changes invalidate briefing context. Route-level locking
covers session selection through response delivery; sessions renew on context changes,
including task changes, regardless of remaining context capacity. Unresolved sends
or operations must reconcile before a scope change can discard old working context.

`learning.curation` uses a separate isolated native adviser session. Only material
already authorized for external processing can enter it. The curator may reuse or
create bounded category metadata and assign it to the selected stored item; permission
and content hashes are checked again before applying its response. It cannot change
project grants. Full source reading is never inferred from the bounded tagging excerpt.


`learning.policy` separates optional experimentation from ordinary lesson reuse.
The application defaults experiments off and Chat-only on. Optional durable turn
reservations count bootstrap and trial requests once; unlimited means no added HA
turn ceiling. Existing protected-corpus exposure bounds remain evaluation-validity
checks. Native trials retain a model/effort binding after observed selection in their
first isolated session, reuse it across paired arms, and never rebind main routes.
Provider identity/allowance blocks remain effective. Unknown allowance can proceed
under the owner's selected policy; it is not treated as proof of unlimited service.

External HTTP MCP authorization uses the pinned official SDK rather than a second
OAuth implementation. HA supplies a dedicated browser profile, a state-bound loopback
callback, private storage and per-server serialization. Tokens, client secrets,
absolute expiry and SDK-validated discovery metadata stay in memory or the OS vault.
The SDK 2.3 adapter restores deadlines and token endpoints when loading a new client.
Normal worker calls may refresh authorization but cannot launch interactive consent;
that remains an owner-started Connections action. Endpoint/storage changes, forgetting
and shutdown invalidate pending writes. Tool/project grants remain independent.

Static AArch64 Linux files/memory replay also uses the complete Qiling engine.
The adapter verifies its Cortex-A72 CPU and maps Linux asm-generic syscall IDs
to the existing guarded operation contract. Qiling receives original ARM syscall
registers, except CWD-only mkdirat/renameat/unlinkat forms normalized to upstream
mkdir/rename/unlink/rmdir after the same path checks. This supplies missing pinned
upstream handlers and respects removal flags. Dynamic ARM images and dependencies
remain unsupported. Both architectures share deterministic guest metadata,
resource bounds, filesystem isolation, cancellation and protected acceptance.
