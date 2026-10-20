from __future__ import annotations
import math, time
from dataclasses import dataclass, field
from hivemind_assembly.core.common import Blocked, ContractError

PREFERENCE = ("worker.opus", "worker.astra", "worker.extra")
TARGETS = {
    "worker.opus": ("claude", "native", "Opus 5.5", "High"),
    "worker.astra": ("openai", "Work", "GPT-6 Astra", "High"),
    "worker.extra": ("openai", "Chat", "GPT-6", "Extra High"),
    "adviser.extra": ("openai", "Chat", "GPT-6", "Extra High"),
    "reviewer.high": ("openai", "Chat", "GPT-6", "High"),
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

    def claim_poll(self, scope, now=None):
        now = time.time() if now is None else now
        with self.store.tx() as c:
            r = c.execute(
                "SELECT last_attempt FROM polls WHERE scope=?", (scope,)
            ).fetchone()
            # Backward wall-clock jumps hold the poll; never create a second fetch.
            if r and now - r[0] < 86400:
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
    github = config.get("github", {})
    if not isinstance(github, dict) or set(github) - {
        "allow_repository_creation",
        "automatic_checkpoints",
        "allowed_organizations",
    }:
        raise ContractError(
            "GitHub settings accept creation permission, automatic checkpoints and allowed organizations only; credentials belong in the OS credential store."
        )
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
        expected_hosts = (
            ["claude.ai"] if TARGETS[key][0] == "claude" else ["chatgpt.com"]
        )
        if route.get("allowed_hosts") != expected_hosts:
            raise ContractError("Native route host must match its designated provider")
        if (
            tuple(route.get(x) for x in ("provider", "mode", "model", "effort"))
            != TARGETS[key]
        ):
            raise ContractError("Exact route target changed")
        binding = route.get("conversation_url")
        if binding:
            if binding in seen:
                raise ContractError("Each role requires a distinct conversation")
            seen.add(binding)
        if route.get("inference_transport") != "native_browser":
            raise ContractError("Only native browser transport is enabled")
    return config
