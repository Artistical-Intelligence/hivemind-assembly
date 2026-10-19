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
learning. Donor optimizer grafting and broad cross-project improvement remain unfinished.

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
