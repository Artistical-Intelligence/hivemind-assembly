"""Dependency-first reconstruction groups from complete paginated static graphs."""

from graphlib import TopologicalSorter
from hivemind_assembly.core.common import Blocked, ContractError, Conflict


def plan(pages):
    if not isinstance(pages, list) or not 1 <= len(pages) <= 10000:
        raise ContractError("Supply complete Ghidra callgraph pages")
    nodes = {}
    offset = 0
    identity = None
    edge_count = 0
    for index, page in enumerate(pages):
        if not isinstance(page, dict):
            raise ContractError("Graph page must be an object")
        observed = (
            page.get("program"),
            page.get("executable_sha256"),
            page.get("revision"),
            page.get("total_functions"),
        )
        if identity is None:
            identity = observed
        if not all(v is not None for v in observed) or observed != identity:
            raise Conflict("Graph pages belong to different program revisions")
        rows = page.get("items")
        if (
            not isinstance(rows, list)
            or len(rows) > 2000
            or page.get("offset") != offset
        ):
            raise ContractError("Graph pages must be contiguous and bounded")
        for node in rows:
            if (
                not isinstance(node, dict)
                or not isinstance(node.get("id"), str)
                or not node["id"]
                or node["id"] in nodes
            ):
                raise ContractError("Unique function addresses are required")
            if node.get("calls_truncated") is not False:
                raise Blocked(
                    "Truncated or unverified call lists cannot form a complete plan"
                )
            callees = node.get("callees")
            if not isinstance(callees, list) or any(
                not isinstance(v, str) or not v for v in callees
            ):
                raise ContractError("Callees must be function addresses")
            nodes[node["id"]] = node
            edge_count += len(callees)
        offset += len(rows)
        if page.get("next_offset") != offset or page.get("has_more") is not (
            index < len(pages) - 1
        ):
            raise ContractError("Missing pages or inconsistent continuation state")
        if len(nodes) > 10000 or edge_count > 100000:
            raise Blocked("Reconstruction graph exceeds 10000 functions / 100000 edges")
    if type(identity[3]) is not int or len(nodes) != identity[3]:
        raise Blocked("Not all program functions are represented")
    adjacency = {
        key: sorted(set(n["callees"]) & nodes.keys()) for key, n in nodes.items()
    }
    reverse = {key: [] for key in nodes}
    for key, targets in adjacency.items():
        for target in targets:
            reverse[target].append(key)
    # Iterative Kosaraju avoids Python recursion limits on large call graphs.
    visited = set()
    finished = []
    for start in sorted(nodes):
        if start in visited:
            continue
        visited.add(start)
        stack = [(start, iter(adjacency[start]))]
        while stack:
            current, children = stack[-1]
            child = next(children, None)
            if child is None:
                finished.append(current)
                stack.pop()
            elif child not in visited:
                visited.add(child)
                stack.append((child, iter(adjacency[child])))
    groups = []
    owner = {}
    for start in reversed(finished):
        if start in owner:
            continue
        group = []
        pending = [start]
        key = len(groups)
        owner[start] = key
        while pending:
            node = pending.pop()
            group.append(node)
            for parent in reverse[node]:
                if parent not in owner:
                    owner[parent] = key
                    pending.append(parent)
        groups.append(sorted(group))
    dependencies = {i: set() for i in range(len(groups))}
    for node, targets in adjacency.items():
        dependencies[owner[node]].update(
            owner[t] for t in targets if owner[t] != owner[node]
        )
    order = list(TopologicalSorter(dependencies).static_order())
    ids = {old: index for index, old in enumerate(order)}
    result = []
    for key in order:
        members = groups[key]
        result.append(
            {
                "id": ids[key],
                "functions": members,
                "depends_on": sorted(ids[d] for d in dependencies[key]),
                "recursive": len(members) > 1
                or any(n in adjacency[n] for n in members),
                "external_targets": sorted(
                    {c for n in members for c in nodes[n]["callees"] if c not in nodes}
                ),
                "names": {n: nodes[n].get("name", n) for n in members},
            }
        )
    return {
        "program": identity[0],
        "executable_sha256": identity[1],
        "revision": identity[2],
        "function_count": len(nodes),
        "groups": result,
        "claim": "Dependency order for the supplied static callgraph only. Indirect/runtime calls, data dependencies and platform behavior require separate evidence; groups do not replace project acceptance.",
    }
