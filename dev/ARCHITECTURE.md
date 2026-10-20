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

MCP and other harness adapters are future integrations, not prerequisites for
the initial application. The small text-counting test domain only verifies
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
local and inactive pending independent evaluation. The built-in proof workflow
contains generic parameter references and may be offered to native workers
once promoted. It does not expose evaluator cases or private project bytes.

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
Clang/LLD for Windows DLL builds, and Unicorn for bounded calls. Both SysV and
Win64 integer/pointer arguments include stack arguments, aliased caller buffers,
nonvolatile registers, Win64 XMM state and floating-point control registers.
Every caller buffer is compared. Access outside exact buffer ranges fails even
when it stays on a mapped page. Image-global writes, imports, TLS and loader
initialization remain unsupported. Protected `x86_64_linked_calls` acceptance
pins the original, seals cases, independently rebuilds every source and rechecks
source/manifest hashes. This is function reconstruction, not a Windows OS runtime.

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
