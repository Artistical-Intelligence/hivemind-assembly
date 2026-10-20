import pytest
from hivemind_assembly.core.common import Blocked, ContractError, Conflict
from hivemind_assembly.domains.reverse_engineering.planning import plan


def page(nodes, offset=0, total=None, more=False):
    return {
        "program": "target",
        "executable_sha256": "abc",
        "revision": 0,
        "total_functions": total or len(nodes),
        "offset": offset,
        "next_offset": offset + len(nodes),
        "has_more": more,
        "items": [
            {"id": key, "callees": calls, "calls_truncated": False}
            for key, calls in nodes
        ],
    }


def test_dependency_order_recursion_and_external_targets():
    result = plan(
        [
            page([("main", ["a", "lib"]), ("a", ["b"])], total=4, more=True),
            page([("b", ["a", "leaf"]), ("leaf", [])], offset=2, total=4),
        ]
    )
    groups = result["groups"]
    assert [g["functions"] for g in groups] == [["leaf"], ["a", "b"], ["main"]]
    assert groups[1]["recursive"] and groups[1]["depends_on"] == [0]
    assert groups[2]["external_targets"] == ["lib"]


def test_large_chain_does_not_hit_recursion_limit():
    nodes = [(str(i), [str(i + 1)] if i < 3999 else []) for i in range(4000)]
    result = plan(
        [
            page(nodes[:2000], total=4000, more=True),
            page(nodes[2000:], offset=2000, total=4000),
        ]
    )
    assert (
        result["groups"][0]["functions"] == ["3999"] and len(result["groups"]) == 4000
    )


def test_partial_truncated_and_changed_graphs_rejected():
    a = page([("a", ["b"])], total=2, more=True)
    with pytest.raises(ContractError):
        plan([a])
    b = page([("b", [])], offset=1, total=2)
    b["revision"] = 1
    with pytest.raises(Conflict):
        plan([a, b])
    b["revision"] = 0
    b["items"][0]["calls_truncated"] = True
    with pytest.raises(Blocked):
        plan([a, b])
