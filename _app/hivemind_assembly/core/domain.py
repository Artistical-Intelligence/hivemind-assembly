"""Small in-process domain boundary; no network, discovery or agent runtime."""

from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Protocol, Literal
from .jobs import Jobs


@dataclass(frozen=True)
class Capability:
    name: str
    mutates_project: bool = False
    # Discard only for computations without durable external effects.
    recovery: Literal["discard", "reconcile", "external"] = "external"


@dataclass(frozen=True)
class ToolContext:
    workspace: Path
    config: dict
    jobs: Jobs
    cancel: Event


class Domain(Protocol):
    id: str
    instructions: str
    capabilities: tuple[Capability, ...]

    def execute(self, context: ToolContext, request: dict) -> dict: ...
    def reconcile(self, context: ToolContext, operation: dict) -> dict: ...
    def skills(self) -> list[dict]: ...
