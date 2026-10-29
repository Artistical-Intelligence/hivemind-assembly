"""Model-requested fresh native context, journaled at a completed turn boundary."""

from hivemind_assembly.core.common import (
    AllowanceUnavailable, Blocked, ContractError, Retryable, digest,
)


class ContextResetYield(Exception):
    """A durable reset resumed the same phase; yield until the next tick."""


async def reset_context(team, task, flow, route, payload, response):
    if flow["phase"] not in ("intent", "execute", "brief", "brief_reading", "recovery"):
        raise ContractError("Context reset is unavailable during this phase")
    method = response.get("method", "auto")
    reason, handoff = response.get("reason"), response.get("handoff")
    if method not in ("auto", "new_chat", "clear") or any(
        not isinstance(value, str) or not value.strip() or len(value) > limit
        for value, limit in ((reason, 500), (handoff, 4000))
    ):
        raise ContractError("Context reset requires a method, reason (1–500), and handoff (1–4000)")
    if flow.get("context_reset_resume", {}).get("route") == route:
        raise Blocked("A fresh context must produce a substantive phase response before another reset")
    if team.sessions is None:
        raise Blocked("Native session renewal is unavailable")
    context = team.scopes.fingerprint(task["id"])
    identity = "reset_" + digest({"task": task["id"], "route": route,
                                   "request": response["request_id"]})[:32]
    # An in-progress renewal owns its own canary delivery. All work deliveries
    # and project mutations must have drained before any conversation is moved.
    if any(m["id"] != identity for m in team.sessions.pending(route)) or team.store.rows(
        "SELECT o.id FROM operations o JOIN tasks t ON t.id=o.task_id "
        "WHERE t.project_id=? AND o.state IN ('running','uncertain','applied')",
        (task["project_id"],),
    ):
        raise Retryable("Context reset waits for unresolved native deliveries or mutations")
    observation = team.observations.get(route)
    if observation is None or not observation.eligible():
        raise AllowanceUnavailable("Context reset requires verified sufficient allowance")
    # These facts describe the implemented runtime, not speculative UI actions.
    binding = {k: team.config["routes"][route].get(k) for k in
               ("provider", "profile", "account_label", "model", "mode", "effort")}
    request = {"request_id": response["request_id"], "route": route, "binding": binding,
               "knowledge_scope": context, "requested_method": method,
               "effective_method": "new_chat", "clear_supported": False,
               "fallback": "clear is not verified; using a fresh chat" if method == "clear" else None,
               "reason": reason, "handoff": handoff, "phase": flow["phase"]}
    with team.store.tx() as db:
        team.controller._fence(db, task["id"], task["owner"], task["epoch"])
        team.store.put("context_reset", identity, request, db)
    # Sessions journals intent, delivery and exact binding, and reconciles a
    # committed identity after a crash without sending another bootstrap.
    await team.sessions.renew(task["id"], route, identity=identity)
    if team.scopes.fingerprint(task["id"]) != context:
        raise Blocked("Knowledge permissions changed during context renewal; rebrief required")
    cfg = team.config["routes"][route]
    if any(cfg.get(k) != value for k, value in binding.items()):
        raise Blocked("Context renewal changed the configured native identity")
    team.store.put("session_knowledge_scope", digest({"route": route,
                   "conversation": cfg.get("conversation_url")}),
                   {"context": context, "task": task["id"]})
    flow.update(seq=flow["seq"] + 1, context_reset_resume={
        **request, "payload": payload, "identity": identity,
    })
    team.save_flow(task["id"], flow, task["owner"], task["epoch"])
    raise ContextResetYield()
