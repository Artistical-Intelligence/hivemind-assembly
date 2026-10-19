"""A small executable guest/native boundary, exercised against the original runner.
This is a finite scalar demo, not a complete game/platform fallback.
"""

from __future__ import annotations
from hivemind_assembly.domains.reverse_engineering.semantics import (
    fixture,
    PcodeMachine,
    run_reference,
)
from hivemind_assembly.core.common import ContractError


class HybridScore:
    """Recover the score-add region natively; keep the bonus region in P-code.

    Contract: unsigned 32-bit score/points, RDI input and RAX output; caller does
    not observe flags, temporaries or memory. Both regions have no memory effects.
    """

    ADD = "89f801f0"  # eax = edi + esi
    BONUS = "8d047f"  # eax = edi * 3

    def __init__(self, use_recovered=True):
        self.use_recovered = use_recovered

    def play(self, score, points):
        if not all(isinstance(n, int) and 0 <= n < 2**32 for n in (score, points)):
            raise ContractError("Score inputs must be uint32")
        if self.use_recovered:
            updated = (score + points) & 0xFFFFFFFF
        else:
            r = PcodeMachine(
                fixture("add", self.ADD, {"RDI": score, "RSI": points}, [])
            ).run()
            if r["status"] != "completed":
                raise ContractError("Fallback failed")
            updated = r["registers"]["RAX"]
        # Real fallback invocation and guest register mapping, rather than retained bytes alone.
        case = fixture("bonus", self.BONUS, {"RDI": updated}, [])
        result = PcodeMachine(case).run()
        if result["status"] != "completed":
            raise ContractError("Bonus fallback failed")
        return {
            "score": updated,
            "bonus": result["registers"]["RAX"],
            "mode": "hybrid" if self.use_recovered else "pcode",
        }

    def reference(self, score, points):
        a = run_reference(fixture("add", self.ADD, {"RDI": score, "RSI": points}, []))[
            "registers"
        ]["RAX"]
        b = run_reference(fixture("bonus", self.BONUS, {"RDI": a}, []))["registers"][
            "RAX"
        ]
        return {"score": a, "bonus": b}
