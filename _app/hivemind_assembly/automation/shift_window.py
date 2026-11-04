"""Pure, bounded HA Chat Mode shift-manager phase optimizer.

This module does NOT schedule, invoke, pause, or update a service automation.
Use it as a deterministic planning aid *only* for an owner-authorized Chat Mode
manager. See dev/continuous_execution/SHIFT_MANAGER.md. A next worker wave is
an opportunity for the manager to finish planning, never a gate workers await.

Inputs are observed offsets in MINUTES relative to the same reference
cohort hour. E.g. :56 completion is 56.0; next-hour :20 is 80.0.
Do not substitute scheduled-for timestamps for actual completion evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil, floor, isfinite
from typing import Iterable


@dataclass(frozen=True)
class ShiftWindow:
    """A deterministic recommendation, not a promised service dispatch."""

    minute_of_hour: int | None
    planned_offset_minutes: float | None
    evidence_ready_offset_minutes: float
    next_cohort_offset_minutes: float
    usable_runway_minutes: float
    status: str
    explanation: str


def _real_nonnegative(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    number = float(value)
    if not isfinite(number) or number < 0:
        raise ValueError(f"{name} must be finite and nonnegative")
    return number


def best_shift_manager_phase(
    critical_completion_offsets: Iterable[float],
    next_cohort_offset: float,
    *,
    readiness_quantile: float = 0.90,
    readiness_buffer: float = 2.0,
    possible_early_start: float = 0.0,
    possible_late_start: float = 0.0,
    update_buffer: float = 1.0,
) -> ShiftWindow:
    """Maximize available manager work runway after relevant evidence arrives.

    Only *critical* input completions belong in the sample, not an arbitrarily
    late nonblocking reporter. The caller supplies observed latest-completion
    offsets for comparable prior waves; the nearest-rank sample quantile is a
    conservative estimator, NOT an estimate of an actual service guarantee.

    Scan each of the 60 allowable hourly minute phases. Align each candidate
    to its earliest occurrence at/after the evidence-readiness threshold.
    A candidate is feasible if its latest plausible start + update margin
    precedes the next independent worker cohort start.

    Workers need not wait for the manager. The next cohort is only a useful
    coordination horizon, not a runtime deadline. An absent window returns
    status="no_pre_wave_window" rather than pausing anybody.
    """
    samples = tuple(
        _real_nonnegative("critical completion", item)
        for item in critical_completion_offsets
    )
    if not samples:
        raise ValueError("at least one observed critical completion is required")
    deadline = _real_nonnegative("next cohort offset", next_cohort_offset)
    q = float(readiness_quantile)
    if not isfinite(q) or not 0 < q <= 1:
        raise ValueError("readiness_quantile must be in (0, 1]")
    buffer = _real_nonnegative("readiness_buffer", readiness_buffer)
    early = _real_nonnegative("possible_early_start", possible_early_start)
    late = _real_nonnegative("possible_late_start", possible_late_start)
    propagation = _real_nonnegative("update_buffer", update_buffer)

    ranked = sorted(samples)
    kth = max(0, ceil(q * len(ranked)) - 1)
    # If the service starts early, schedule later so the model is not likely
    # to inspect incomplete evidence at the beginning of its shift.
    ready = ranked[kth] + buffer + early
    best: tuple[float, float, int] | None = None

    for phase in range(60):
        cycle = floor(ready / 60.0)
        offset = cycle * 60.0 + phase
        if offset < ready:
            offset += 60.0
        runway = deadline - offset - late - propagation
        if runway <= 0:
            continue
        # Find the maximum pre-next-wave runway, with deterministic earliest
        # offset/phase tie breaks. None of this stops a live worker.
        candidate = (runway, -offset, -phase)
        if best is None or candidate > best:
            best = candidate

    if best is None:
        return ShiftWindow(
            minute_of_hour=None,
            planned_offset_minutes=None,
            evidence_ready_offset_minutes=ready,
            next_cohort_offset_minutes=deadline,
            usable_runway_minutes=0.0,
            status="no_pre_wave_window",
            explanation=(
                "Relevant evidence cannot be confidently ready early enough "
                "for a pre-cohort manager window; independent workers continue."
            ),
        )

    runway, neg_offset, neg_phase = best
    return ShiftWindow(
        minute_of_hour=-neg_phase,
        planned_offset_minutes=-neg_offset,
        evidence_ready_offset_minutes=ready,
        next_cohort_offset_minutes=deadline,
        usable_runway_minutes=runway,
        status="provisional_recommendation",
        explanation=(
            "Earliest eligible hourly phase after observed evidence readiness "
            "maximizes manager planning runway before the next cohort. "
            "Not a guarantee of service start, actual run length, or receipt."
        ),
    )
