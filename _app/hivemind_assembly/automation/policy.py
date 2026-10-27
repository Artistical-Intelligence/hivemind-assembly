from __future__ import annotations
import math, time
from dataclasses import dataclass, field
from hivemind_assembly.core.common import Blocked, ContractError

PREFERENCE = ("worker.opus", "worker.astra", "worker.extra")
# The five assistant slots and the setup HA started with (saved as the "Default" setup).
# The owner can give each slot any model a signed-in service offers; HA then keeps to
# exactly that choice.
TARGETS = {
    "worker.opus": ("claude", "native", "Opus 5.5", "High"),
    "worker.astra": ("openai", "Work", "GPT-6 Astra", "High"),
    "worker.extra": ("openai", "Chat", "GPT-6", "Extra High"),
    "adviser.extra": ("openai", "Chat", "GPT-6", "Extra High"),
    "reviewer.high": ("openai", "Chat", "GPT-6", "High"),
}
FIELDS = ("provider", "mode", "model", "effort")
PROVIDERS = {
    "openai": {"name": "ChatGPT", "hosts": ["chatgpt.com"], "modes": ("Chat", "Work"), "profile": "openai"},
    "claude": {"name": "Claude", "hosts": ["claude.ai"], "modes": ("native",), "profile": "claude"},
}


def usage_scope(provider, mode):
    """Usage limits are per account and surface: ChatGPT Chat and Work are counted apart."""
    return "claude.native" if provider == "claude" else provider + "." + mode.lower()


def valid_target(target):
    """One assistant's choice: service, mode, model and thinking level (empty when the
    model has no thinking setting)."""
    if not isinstance(target, dict) or set(target) != set(FIELDS):
        raise ContractError("Each assistant needs a service, mode, model and thinking level")
    info = PROVIDERS.get(target["provider"])
    if info is None:
        raise ContractError("Unknown AI service")
    if target["mode"] not in info["modes"]:
        raise ContractError(info["name"] + " has no " + str(target["mode"]) + " mode")
    if not isinstance(target["model"], str) or not 1 <= len(target["model"].strip()) <= 100:
        raise ContractError("Choose a model")
    if not isinstance(target["effort"], str) or len(target["effort"]) > 100:
        raise ContractError("Thinking level is too long")
    return target


def default_presets(config):
    """The setup the owner has now, saved as "Default"."""
    return {
        "Default": {
            route: {k: cfg.get(k) for k in FIELDS}
            for route, cfg in config.get("routes", {}).items()
        }
    }


@dataclass
class Window:
    name: str
    remaining: float
    task: float = 0
    handoff: float = 2
    reserve: float = 3
    uncertainty: float = 2
    reservations: float = 0

    def eligible(self):
        vals = (
            self.remaining,
            self.task,
            self.handoff,
            self.reserve,
            self.uncertainty,
            self.reservations,
        )
        if any(not math.isfinite(x) or x < 0 for x in vals) or self.remaining > 100:
            return False
        return self.remaining >= 10 and self.remaining >= sum(vals[1:])


@dataclass
class Availability:
    route: str
    ready: bool = False
    allowance_known: bool = False
    no_numeric_limit: bool = False
    observed: float = 0
    windows: list[Window] = field(default_factory=list)
    blocked: str = ""
    blocked_kind: str = ""

    def eligible(self, now=None):
        now = time.time() if now is None else now
        return (
            self.ready
            and self.allowance_known
            and not self.blocked
            and 0 <= now - self.observed <= 86400
            and (bool(self.windows) or self.no_numeric_limit)
            and all(w.eligible() for w in self.windows)
        )


class UsagePolicy:
    def __init__(self, store):
        self.store = store

    # While an account has usage left, HA re-reads its usage page this often during
    # work, so it notices running out. Once an account is out, the 24-hour policy
    # applies: one check a day until the provider refreshes it.
    ACTIVE_INTERVAL = 600
    EXHAUSTED_INTERVAL = 86400

    def claim_poll(self, scope, now=None, interval=EXHAUSTED_INTERVAL):
        now = time.time() if now is None else now
        with self.store.tx() as c:
            r = c.execute(
                "SELECT last_attempt FROM polls WHERE scope=?", (scope,)
            ).fetchone()
            # Backward wall-clock jumps hold the poll; never create a second fetch.
            if r and now - r[0] < interval:
                return False
            c.execute(
                "INSERT INTO polls VALUES(?,?) ON CONFLICT(scope) DO UPDATE SET last_attempt=excluded.last_attempt",
                (scope, now),
            )
            self.store.event(scope, "poll_attempt_reserved", {"at": now}, c)
            return True

    def reserve(self, scope, task, windows):
        with self.store.tx() as c:
            for w in windows:
                held = c.execute(
                    "SELECT COALESCE(SUM(amount),0) FROM reservations WHERE scope=? AND window=? AND task!=?",
                    (scope, w.name, task),
                ).fetchone()[0]
                check = Window(
                    w.name,
                    w.remaining,
                    w.task,
                    w.handoff,
                    w.reserve,
                    w.uncertainty,
                    w.reservations + held,
                )
                if not check.eligible():
                    raise Blocked(
                        "Shared usage pool cannot cover concurrent reservations"
                    )
            c.execute("DELETE FROM reservations WHERE task=?", (task,))
            for w in windows:
                amount = w.task + w.handoff + w.reserve + w.uncertainty
                c.execute(
                    "INSERT INTO reservations VALUES(?,?,?,?)",
                    (scope, task, w.name, amount),
                )

    def release(self, task):
        with self.store.tx() as c:
            c.execute("DELETE FROM reservations WHERE task=?", (task,))

    @staticmethod
    def choose(observations, current=None, now=None):
        now = time.time() if now is None else now
        eligible = [
            r for r in PREFERENCE if r in observations and observations[r].eligible(now)
        ]
        best = eligible[0] if eligible else None
        if current and current in observations and not observations[current].blocked:
            observation = observations[current]
            unknown = (
                not observation.allowance_known
                or not 0 <= now - observation.observed <= 86400
            )
            can_continue = (
                unknown
                or (bool(observation.windows) or observation.no_numeric_limit)
                and all(
                    w.remaining > 5
                    and w.remaining
                    >= w.task + w.handoff + w.reserve + w.uncertainty + w.reservations
                    for w in observation.windows
                )
            )
            if can_continue and (
                best is None or PREFERENCE.index(best) >= PREFERENCE.index(current)
            ):
                return current
        return best


def validate_config(config):
    from hivemind_assembly.learning.policy import validate as validate_learning

    validate_learning(config.get("experimental_learning", {}))
    github = config.get("github", {})
    if not isinstance(github, dict) or set(github) - {
        "allow_repository_creation",
        "automatic_checkpoints",
        "allowed_organizations",
        "default_visibility",
    }:
        raise ContractError(
            "GitHub settings accept creation permission, automatic checkpoints, allowed organizations and the default for new repositories only; credentials belong in the OS credential store."
        )
    if github.get("default_visibility", "private") not in ("private", "public"):
        raise ContractError("New repositories are Private or Public.")
    if type(github.get("automatic_checkpoints", True)) is not bool:
        raise ContractError("automatic_checkpoints must be a boolean")
    if type(github.get("allow_repository_creation", False)) is not bool:
        raise ContractError(
            "GitHub repository creation permission must be true or false."
        )
    orgs = github.get("allowed_organizations", [])
    import re

    if not isinstance(orgs, list) or any(
        not isinstance(o, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", o)
        for o in orgs
    ):
        raise ContractError(
            "Allowed GitHub organizations must be a list of organization names."
        )
    if config.get("profile") != "native_autonomous":
        raise ContractError("Expected native_autonomous profile")
    if (
        config.get("model_api_inference") is not False
        or config.get("paid_overage") is not False
    ):
        raise ContractError("Model API inference and paid overage must remain disabled")
    if config.get("poll_interval_hours") != 24:
        raise ContractError("Scheduled quota checks must use the 24-hour policy")
    seen = set()
    if set(config.get("routes", {})) != set(TARGETS):
        raise ContractError("All five designated roles must remain configured")
    for key, route in config["routes"].items():
        if key not in TARGETS:
            raise ContractError("Unknown route")
        target = valid_target({x: route.get(x) for x in FIELDS})
        expected_hosts = PROVIDERS[target["provider"]]["hosts"]
        if route.get("allowed_hosts") != expected_hosts:
            raise ContractError("Native route host must match its designated provider")
        binding = route.get("conversation_url")
        if binding:
            from urllib.parse import urlsplit

            parts = urlsplit(binding)
            if (
                parts.scheme != "https"
                or parts.hostname not in expected_hosts
                or parts.username
                or parts.password
            ):
                raise ContractError("Conversation URL must be on the route's provider host")
            if binding in seen:
                raise ContractError("Each role requires a distinct conversation")
            seen.add(binding)
        if route.get("inference_transport") != "native_browser":
            raise ContractError("Only native browser transport is enabled")
    presets = config.get("presets", {})
    if not isinstance(presets, dict) or len(presets) > 50:
        raise ContractError("Keep at most 50 saved assistant setups")
    for name, preset in presets.items():
        if not isinstance(name, str) or name != name.strip() or not 1 <= len(name) <= 60:
            raise ContractError("Setup names need 1–60 characters")
        if not isinstance(preset, dict) or set(preset) != set(TARGETS):
            raise ContractError("A saved setup names all five assistants")
        for target in preset.values():
            valid_target(target)
    active = config.get("active_preset")
    if active is not None and active not in presets:
        raise ContractError("The setup in use must be a saved setup")
    return config
