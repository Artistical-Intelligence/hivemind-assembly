import copy, random
import pytest
from workbench.semantics import (
    smoke_cases,
    differential,
    compare_states,
    fixture,
    PcodeMachine,
)
from workbench.proof import prove


@pytest.mark.parametrize("case", smoke_cases(), ids=lambda c: c["name"])
def test_independent_smoke(case):
    assert differential(case)["comparison"]["passed"]


@pytest.mark.parametrize("field", ["registers", "flags", "writes", "fault", "status"])
def test_seeded_fault_detection(field):
    r = differential(smoke_cases()[0])
    bad = copy.deepcopy(r["candidate"])
    if field == "registers":
        bad[field]["RAX"] ^= 1
    elif field == "flags":
        bad[field]["CF"] ^= 1
    elif field == "writes":
        bad[field]["12288"] = 1
    elif field == "fault":
        bad[field] = {"kind": "r", "address": 123}
    else:
        bad[field] = "fault"
    assert not compare_states(r["reference"], bad, flags=["CF"])["passed"]


def test_randomized_arithmetic():
    rng = random.Random(20261019)
    for _ in range(100):
        c = fixture(
            "add", "89f801f0", {"RDI": rng.getrandbits(64), "RSI": rng.getrandbits(64)}
        )
        assert differential(c)["comparison"]["passed"]


def test_proof_equivalent():
    assert prove("89f801f0", "8d0437")["result"] == "UNSAT"


def test_proof_wrong():
    assert prove("89f801f0", "89f829f0")["result"] == "SAT"


def test_proof_flags_not_equivalent():
    assert (
        prove("89f801f0", "8d0437", outputs=("RAX", "CF", "OF", "ZF"))["result"]
        == "SAT"
    )


@pytest.mark.parametrize("code", ["8b07", "0f05", "e800000000", "f30f58c1"])
def test_unsupported_proof_not_pass(code):
    assert prove(code, code)["result"] == "UNKNOWN"


def test_unsupported_userop_not_noop():
    c = fixture("syscall", "0f05")
    r = PcodeMachine(c).run()
    assert r["status"] == "unsupported"


def test_unmapped_memory_fault():
    c = fixture("fault", "8937", {"RDI": 0x9000, "RSI": 1}, [])
    assert differential(c)["comparison"]["passed"]


@pytest.mark.parametrize("observation", ["RIP", "EIP", "AF"])
def test_unmodeled_observation_cannot_prove(observation):
    assert prove("89f801f0", "8d0437", outputs=(observation,))["result"] == "UNKNOWN"
