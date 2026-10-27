"""Owner controls for optional native improvement experiments, separate from reuse."""

import time
from dataclasses import replace
from hivemind_assembly.core.common import Blocked, ContractError

# Capability preference, not a benchmark claim. Every option must be observed
# in the native account UI. Source: OpenAI model/effort documentation, 2026-10-20.
CHAT_PREFERENCES = [
    {"model": "GPT-6", "effort": "Pro"},
    {"model": "GPT-5.6 Sol", "effort": "Pro"},
    {"model": "GPT-6", "effort": "Extra High"},
    {"model": "GPT-6", "effort": "High"},
    {"model": "GPT-5.6 Sol", "effort": "Extra High"},
    {"model": "GPT-5.6 Sol", "effort": "High"},
    {"model": "GPT-6", "effort": "Medium"},
    {"model": "GPT-5.6 Sol", "effort": "Medium"},
    {"model": "GPT-6", "effort": "Instant"},
    {"model": "GPT-5.6 Sol", "effort": "Instant"},
]
DEFAULTS = {
    "enabled": False,
    "chat_only": True,
    "route_override": None,
    "model_override": None,
    "effort_override": None,
    "max_turns_per_evaluation": None,
    "allow_unknown_allowance": True,
    # Owner choice: lessons captured from accepted tasks may be sent to native
    # trial conversations for evaluation. Off by default (private task evidence).
    "share_captured_lessons": False,
    # Owner choice: external benchmark cases compile and run candidate code
    # natively on this computer. Off by default.
    "allow_native_benchmarks": False,
}


def validate(value):
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise ContractError("Unknown experimental-learning setting")
    result = {**DEFAULTS, **value}
    for field in ("enabled", "chat_only", "allow_unknown_allowance", "share_captured_lessons", "allow_native_benchmarks"):
        if type(result[field]) is not bool:
            raise ContractError(field + " must be boolean")
    if result["route_override"] not in (
        None,
        "worker.extra",
        "worker.opus",
        "worker.astra",
    ):
        raise ContractError("Choose an existing worker route or automatic selection")
    for field in ("model_override", "effort_override"):
        if result[field] is not None and (
            not isinstance(result[field], str)
            or not 1 <= len(result[field].strip()) <= 100
        ):
            raise ContractError(
                "Manual model and effort labels must be 1–100 characters"
            )
    if bool(result["model_override"]) != bool(result["effort_override"]):
        raise ContractError("A manual model override also requires its exact effort")
    limit = result["max_turns_per_evaluation"]
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ContractError(
            "Evaluation turn limit must be positive, or null for unlimited"
        )
    return result


class ExperimentalLearning:
    def __init__(self, store, config, availability):
        self.store, self.config, self.availability = store, config, availability

    def settings(self):
        return validate(self.config.get("experimental_learning", {}))

    def require(self, route=None):
        settings = self.settings()
        if not settings["enabled"]:
            raise Blocked(
                "Experimental learning is off; stored knowledge reuse remains available"
            )
        if route:
            cfg = self.config.get("routes", {}).get(route)
            if not cfg or not route.startswith("worker."):
                raise Blocked("Experimental learning requires a configured worker")
            if settings["chat_only"] and cfg.get("mode") != "Chat":
                raise Blocked(
                    "Chat-only learning excludes Work and token-limited worker routes"
                )
        return settings

    def eligible(self, route, observation):
        settings = self.require(route)
        if observation is None or not observation.ready or observation.blocked:
            return False
        if observation.eligible():
            return True
        fresh = 0 <= time.time() - observation.observed <= 86400
        unknown = not observation.allowance_known or not fresh
        # Unknown is not exhaustion. Explicitly enabled unlimited work may
        # proceed until a real provider block; known low allowance still stops it.
        return bool(settings["allow_unknown_allowance"] and unknown)

    def choose(self, requested=None):
        settings = self.require()
        override = requested or settings["route_override"]
        configured = self.config.get("routes", {})
        workers = [r for r in ("worker.extra", "worker.opus", "worker.astra") if r in configured]
        if settings["chat_only"]:
            # Saved setups may put ChatGPT Chat on any worker; use whichever have it.
            workers = [r for r in workers if configured[r].get("mode") == "Chat"]
        routes = [override] if override else workers
        if not routes:
            raise Blocked(
                "No worker uses ChatGPT Chat. Set one to a ChatGPT Chat model,"
                " or untick Only use workers on ChatGPT Chat."
            )
        for route in routes:
            self.require(route)
            if self.eligible(route, self.availability(route)):
                return route
        raise Blocked("No permitted experimental worker has verified session readiness")

    def reservation_observation(self, observation):
        settings = self.require(observation.route)
        unknown = (
            not observation.allowance_known
            or not 0 <= time.time() - observation.observed <= 86400
        )
        if unknown and settings["allow_unknown_allowance"]:
            return replace(observation, windows=[])
        return observation

    def selection(self, route):
        settings = self.require(route)
        if settings["model_override"]:
            return {
                "target": {
                    "model": settings["model_override"],
                    "effort": settings["effort_override"],
                }
            }
        cfg = self.config["routes"][route]
        if cfg.get("mode") == "Chat" and cfg.get("provider") == "openai":
            return {"preferences": CHAT_PREFERENCES}
        return {"target": {"model": cfg["model"], "effort": cfg["effort"]}}

    def reserve(self, evaluation, message):
        settings = self.require()
        with self.store.tx() as db:
            if db.execute(
                "SELECT 1 FROM records WHERE kind='experimental_turn' AND id=?",
                (message,),
            ).fetchone():
                return
            used = db.execute(
                "SELECT COUNT(*) FROM records WHERE kind='experimental_turn' AND json_extract(payload,'$.evaluation')=?",
                (evaluation,),
            ).fetchone()[0]
            limit = settings["max_turns_per_evaluation"]
            if limit is not None and used >= limit:
                raise Blocked("The owner's evaluation turn limit is reached")
            self.store.put("experimental_turn", message, {"evaluation": evaluation}, db)
