"""ChatGPT Chat Mode-only adaptive execution guidance for native HA requests.

This is a compact operating profile, not a new scheduler, task engine, access grant
or cross-provider prompt. See CHATGPT.md and dev/continuous_execution/PROCESS.md.
An explicit provider AND mode match is required; ambiguous routes get no profile.
"""

POLICY_REVISION = "chatgpt-chat-mode-adaptive-1.3"

CHAT_MODE_GUIDANCE = """
CHATGPT CHAT MODE ADAPTIVE EXECUTION (owner policy 1.3; only this Chat route):
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
