"""ChatGPT Chat Mode-only adaptive execution guidance for native HA requests.

This is a compact operating profile, not a new scheduler, task engine, access grant
or cross-provider prompt. See CHATGPT.md and dev/continuous_execution/PROCESS.md.
An explicit provider AND mode match is required; ambiguous routes get no profile.
"""

POLICY_REVISION = "chatgpt-chat-mode-adaptive-1.2"

CHAT_MODE_GUIDANCE = """
CHATGPT CHAT MODE ADAPTIVE EXECUTION (owner policy 1.2; only this Chat route):
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
Do not import instructions from this Chat Mode profile into ChatGPT Work, Codex,
Claude or any other surface/provider; their capabilities are separately unproven.
"""


def guidance_for_native_route(cfg):
    """Return the extra policy only for a verified, explicit ChatGPT Chat route.

    This function intentionally does not infer the mode from a hostname, model
    name, worker role or default. Unknown/missing/malformed routes fail closed.
    It does not switch a route or change its authorization.
    """
    if not isinstance(cfg, dict):
        return ""
    if cfg.get("provider") == "openai" and cfg.get("mode") == "Chat":
        return CHAT_MODE_GUIDANCE
    return ""
