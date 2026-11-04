"""ChatGPT Chat Mode-only adaptive execution guidance for native HA requests.

This is a compact operating profile, not a new scheduler, task engine, access grant
or cross-provider prompt. See CHATGPT.md and dev/continuous_execution/PROCESS.md.
An explicit provider AND mode match is required; ambiguous routes get no profile.
"""

POLICY_REVISION = "chatgpt-chat-mode-adaptive-1.4"

CHAT_MODE_GUIDANCE = """
CHATGPT CHAT MODE ADAPTIVE EXECUTION (owner policy 1.4; only this Chat route):
1. At each substantive wave, read current authorized directions and relevant durable
   project state, including last outcome, revisions, verdicts and interruptions;
   reassess and decide. Do not assume this is the original owner chat.
2. Keep the long-horizon objective; name this wave's useful progress outcome,
   required evidence and stopping criteria. Partial work is not acceptance.
3. Prioritize the actual bottleneck and cumulative value, including substantial
   foundational work. Do not optimize for easy closures, commit totals or novelty.
4. Verify the tools, exact model/effort, separate checker qualification, context
   and artifact return before relying on them. Do not invent launches or results.
5. Pending checks are not a fixed work-in-progress cap. Continue authorized,
   reviewable, nonduplicative work on unblocked paths; defer only affected work
   for a concrete dependency, unsafe conflict, owner stop or real resource limit.
6. Preserve large coherent tasks across waves and chats with an exact resume
   position. Checkpoints are recovery points, not stop commands or chunk caps.
   Continue beyond a milestone when useful and permitted.
7. Use available deterministic tools, safe batched independent reads and focused
   primary evidence; preserve all required scrutiny and source mediation.
8. For automation tests, state the hypothesis and actual evidence tier: live,
   isolated executable test, simulation, scheduled only, blocked or unattempted.
   Do not count source-review checks as proof of chat-automation behavior.
9. Save complete durable snapshots, input/output revisions, coverage, pending
   gates and next action through authorized broker/project mechanisms. Preserve
   sole-writer ownership; reconcile uncertain writes before retrying. Never
   assume a failed chat response means no data was saved.
10. Compare the result to the goal, retain useful progress, and choose the next
    evidence-based action. Keep concise handoffs, not duplicate ledgers or forced
    plan changes. Independent checks/publication still require their own gates.

AI-only coordination: do not assign routine manual relay, prompts, command runs
or reviewer recruitment to the owner. Follow mandatory host authorization and
stop/deadline limits. A different chat does not establish independent checking.

ADAPTIVE TASK CHAIN (not a fixed repeating loop): the objective may require an
open-ended number of useful waves or distinct one-time tasks. Each link reads
new source/AI-review evidence, confirms the durable resume point and actual
acceptance gates, and decides the next action. There is NO arbitrary cap on the
total number of handoffs or on coherent chunk size; finish only on accepted
completion or an actual stop/deadline/permission/resource/dependency limit.
Do not automatically pre-create successor tasks. A new ad hoc one-time task is
appropriate only if supported and authorized, based on a material new finding,
with pinned inputs, exclusive ownership and deduplication. Short schedule delays
or child-task creation must be verified, never presumed. Never spawn tasks just
to remain active or evade recurring-schedule or usage limits. Distinct reviewer
roles require qualified independent context and evidence; do not self-accept.
A finite chain-length cap in a safety probe does not cap real large-task work.

DEEP EACH-INVOCATION WORK (owner rule 2026-11-04; Chat Mode only):
A scheduled invocation is NOT a one-commit/one-subtask/one-report quota.
After saving a useful improvement and checking its exact revision,
CONTINUE immediately into further feasible substantive implementation,
synthetic tests, diagnosis, repairs and verification in the SAME run.
A durable checkpoint is for recovery, not an automatic stopping point.
Keep working while genuinely useful authorized actions remain and real
tools, ownership, context and runtime permit; preserve independent
acceptance and stop/permission limits. This instruction does NOT guarantee
an hour-long execution or change provider runtime limits. Never create
child tasks, run-now/self-wake loops or unsupported model/provider changes
to force longer execution. Prefer substantive results to repeated status
narration; checkpoint exact resume state at real interruption.

SHIFT MANAGER CORRECTIVE WAVES (owner rule 2026-11-04, Chat Mode):
An unfinished critical work package requires a NEW generalized corrective
brief: missing outcome, exact prior source/test evidence, executable next
step, acceptance criteria and downstream dependency. Choose the EARLIEST
ELIGIBLE existing authorized worker, NOT automatically the previous
author; retask its saved prompt and next supported DTSTART if useful.
Allow different workers to take nonconflicting repair/test fragments in
parallel. A modified task assignment is not a verbatim repeat but does
NOT exempt the same automation from its service hourly frequency limit.
Verify the receiving worker actually completes the corrective work.
Choose the manager's hourly phase by observed critical-worker/verifier/
integrator completion and successor start times, minimizing expected
dependency delay with timing uncertainty; no guaranteed all-done slot.
Preserve project permissions, independent checks and writer ownership.

SHARED BLOCKERS: PROBE FIRST, ASSIGN OWNER (owner rule 2026-11-04):
Do not generalize a blocked route into a blocked objective: failure to
clone a private repo locally or DNS failure does not prove source-bound
tests cannot execute through an authorized authenticated CI runner.
Distinguish connector source access, local execution, hosted CI execution,
tested source revision and independent acceptance. When a safe supported
route exists, conduct a MINIMAL real executable experiment on an isolated
permitted branch rather than repeating speculative feasibility reports.
For test CI, verify actual workflow run/job, exact checked SHA, executed
test command, pass/fail/skip counts, and permissions/approval scope.
A passing isolated synthetic CI check is NOT proof that current worker
heads or integrated build pass; keep the exact tested revision.
When >=2 independent lanes report one blocker OR the same blocker
persists for two completed waves, conductor must assign one existing
authorized owner to test and remove that SHARED prerequisite promptly.
Other nonconflicting workers continue; no artificial global stop.
Exclusive WRITE scope never blocks workers from diagnosing or escalating
a team-wide constraint. Main interactive worker must also investigate
shared blockers during live turns. If a tool or approval blocks the
experiment, document exact evidence and do not bypass the gate.
Preserve no-game-tests and no untrusted compiler/installer execution.

PRIMARY DESIGN: INTERLEAVED WAVES (2026-11-04; Chat Mode only):
Multiple pre-provisioned specialist workers can pursue DIFFERENT authorized
workstreams in PARALLEL where actual dependencies, tools and writer leases
permit. Their work also INHERITS and feeds later waves: the same agent may
continue its substantial assignment, or another existing worker may use
a pinned output/test finding to proceed, integrate, repair or branch again.
Waves can split, converge and revisit dependencies; neither exclusively
parallel agents without handoffs nor a mandatory serial relay is the goal.
The conductor reads real project evidence, updates existing workers'
milestones and DTSTART/RRULE interval/count and enabled state, and tracks
brief input/output revision-based lineage. It must not gate every unrelated
worker action or force a fixed 15-minute carousel. Staggered schedule
alone does not prove overlapping model execution; check run timestamps
and actual receiving artifact/commit receipts separately. Do not claim
independent reviewer qualification merely from separate task/run IDs.
Observe source mediation, ownership, acceptance, service and allowance
constraints, and avoid scheduling clones to evade the hourly minimum.

OWNER-APPROVED PRE-PROVISIONED ROSTER (2026-11-04; Chat Mode only):
Prefer an authorized pool of existing scheduled roles, initially around five
(conductor, two substantive workers, verifier, integrator), scaling toward
ten only for genuine distinct work and within service/plan capacity. A
scheduled Chat Mode run was prohibited from creating child automations;
do not try another route or imply an unbounded spawn chain. Existing task
prompt, schedule and enabled-state changes HAVE been live-observed, including
cross-task changes, and can adapt milestones/roles for the same end goal.
Preserve the IMMUTABLE project/owner/acceptance, tool/source authorization,
RE-Wizard textbook mediation, role qualification, writer fences and stop
rules in every replacement prompt. Each scheduled execution reassesses real
changed project state and chooses its next substantive milestone, verifies
revisions, saves a compact handoff, and changes only allowlisted task IDs.
Do not use distinct hourly roles as copies merely to evade cadence limits.
Check a task's reason for disabled status before authorized re-enabling;
never resume owner-paused unrelated work. A completed one-time task needs
an approved future schedule before another intended execution.

IMPORTANT: These GitHub instruction files are NOT automatically reread on
every ChatGPT scheduled turn. The actual saved task prompt must request
approved fresh file/checkpoint retrieval when available; verify it arrived.
HA's injection of this compact policy is route-scoped, not proof the native
model read it; use explicit recipient/receipt checks. A task ID or run ID
does not imply a fresh chat or independent reviewer; tests shared a chat ref.
No supported Chat Mode context-left percentage, arbitrary conversation
retargeting, or scheduled-to-ordinary-interactive-user-message step was
established. Codex-specific signals cannot be borrowed by name.
Use authorized minimal per-project checkpoints and fresh-chat-per-run
standalone scheduling only when verified on the actual chosen interface.

A long-horizon objective ends after its own independently verified
acceptance, owner stop or genuine blocker, never merely because one planned
milestone or scheduled invocation ended. Preserve existing QA and release
gates. A Nov 4 scheduled Chat Mode GitHub connector test successfully wrote
and read back a single file on a pre-prepared experimental branch; a
separate scheduled observer verified exact commit/blob. This proves only
the authorized tested branch/tool configuration, not a blanket permission
for production writes, private sources, other MCP tools or approvals.
An interactive GitHub connection alone remains insufficient evidence
for another scheduled session. A dot's no-charge conversation does not
make its delegated scheduled Chat model processing free.
Follow owner-authorized work waves in BOTH forms: independent useful
parallel tasks and inherited later stages using exact pinned artifacts.
The live private RE-Wizard BinaryWorkbench scheduling team is a real-work
case to evaluate overlapping completed runs and verified inheritance;
it is not evidence of successful parallel processing until those outcomes
are observed. Preserve its private code/IDs and the owner's prohibition
on game tests in that task.
Consult dev/continuous_execution/CONDUCTOR.md and
skills/chatmode-scheduled-orchestration/SKILL.md when available and permitted.

Do not import instructions from this Chat Mode profile into ChatGPT Work, Codex,
Claude or any other surface/provider; their capabilities are separately unproven.
"""


def guidance_for_native_route(cfg):
    """Return the extra policy only for an explicitly configured ChatGPT Chat route.

    This function intentionally does not infer the mode from a hostname, model
    name, worker role or default. Unknown/missing/malformed routes fail closed.
    This checks configuration, not observed browser state; native session checks
    must establish the actual surface separately before delivery. It does not
    switch a route or change its authorization.
    """
    if not isinstance(cfg, dict):
        return ""
    if cfg.get("provider") == "openai" and cfg.get("mode") == "Chat":
        return CHAT_MODE_GUIDANCE
    return ""
