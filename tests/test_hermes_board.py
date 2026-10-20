"""Integration with an actual pinned Hermes checkout, not a replacement scheduler."""

import os
import pytest
from hivemind_assembly.automation.hermes_board import HermesBoard

pytestmark = pytest.mark.skipif(
    not os.environ.get("HA_TEST_HERMES"),
    reason="Set HA_TEST_HERMES to the pinned complete Hermes checkout",
)


def test_dependency_plan_restart_and_claims(store, monkeypatch):
    monkeypatch.syspath_prepend(os.environ["HA_TEST_HERMES"])
    board = HermesBoard(store.root)
    root = store.create_project("dependency", "Integrate recovered components")
    assert board.claim(root)
    nodes = [
        {"objective": "Recover component A", "parents": [], "acceptance": {}},
        {"objective": "Integrate component B", "parents": [0], "acceptance": {}},
    ]
    calls = []

    def configure(task, contract):
        calls.append(task)
        if len(calls) == 2:
            raise ConnectionError("fixture interruption")
        store.put("acceptance_contract", task, contract)

    with pytest.raises(ConnectionError):
        board.plan(store, root, nodes, configure)
    restarted = HermesBoard(store.root)
    result = restarted.plan(
        store, root, nodes, lambda t, c: store.put("acceptance_contract", t, c)
    )
    assert len(restarted.status()) == 3
    a, b = [store.task(key) for key in result["children"]]
    assert not restarted.claim(root) and not restarted.claim(b)
    assert restarted.claim(a)
    restarted.complete(a, {"accepted": "protected checks passed"})
    assert restarted.claim(b) and not restarted.claim(root)
    restarted.complete(b, {"accepted": "protected checks passed"})
    assert restarted.claim(root)
    assert store.get("hermes_plan_published", root["id"]) == result
