import random
import pytest
from workbench.hybrid import HybridScore
from workbench.recovery import Recovery
from workbench.common import Blocked


def test_hybrid_transition_and_rollback():
    h = HybridScore()
    low = HybridScore(False)
    r = random.Random(42)
    for _ in range(50):
        score, points = r.getrandbits(32), r.getrandbits(32)
        expected = h.reference(score, points)
        assert {
            k: v for k, v in h.play(score, points).items() if k != "mode"
        } == expected
        assert {
            k: v for k, v in low.play(score, points).items() if k != "mode"
        } == expected


def test_repeated_reasoning_triggers_reviewer(store):
    r = Recovery(store)
    assert not r.record_attempt("task", "method", {"rev": 1}, {"error": "bad"})[
        "needs_reviewer"
    ]
    assert not r.record_attempt("task", "method", {"rev": 1}, {"error": "bad"})[
        "needs_reviewer"
    ]
    assert r.record_attempt("task", "method", {"rev": 1}, {"error": "bad"})[
        "needs_reviewer"
    ]
    assert not r.record_attempt("task", "different", {"rev": 1}, {"error": "bad"})[
        "needs_reviewer"
    ]
    r.request("task", "loop", [])
    r.request("task", "loop", [])
    with pytest.raises(Blocked):
        r.request("task", "loop", [])


def test_generic_continue_is_not_recovery():
    with pytest.raises(Blocked):
        Recovery.validate({"suspected_cause": "try again"})
