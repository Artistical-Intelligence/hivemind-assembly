"""Exercise actual native foundations against a source-known small ELF fixture."""

import argparse, json, sys, subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "_app"))
from hivemind_assembly.core.jobs import Jobs
from hivemind_assembly.core.common import digest
from hivemind_assembly.domains.reverse_engineering.bridges import (
    GhidraBridge,
    ReaBridge,
)


def verify(root, ghidra, rea):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    source = root / "fixture.c"
    source.write_text(
        "unsigned state; __attribute__((noinline)) unsigned transform(unsigned a){state=state*3+a;return state;} int main(void){return transform(7)==7?0:1;}"
    )
    binary = root / "fixture"
    subprocess.run(
        ["gcc", "-O1", "-g", "-fno-pie", "-no-pie", str(source), "-o", str(binary)],
        capture_output=True,
        check=True,
    )
    jobs = Jobs()
    bridge = GhidraBridge(ghidra, jobs)
    project = root / "native-project"
    inventory = bridge.run(
        project,
        "fixture",
        {"action": "inventory", "operation_id": "foundation-import"},
        binary,
    )
    address = next(
        f["entry"] for f in inventory["functions"] if f["name"] == "transform"
    )
    decompiled = bridge.run(
        project,
        "fixture",
        {
            "action": "decompile_batch",
            "operation_id": "foundation-decompile",
            "addresses": [address],
        },
    )
    assert "transform" in decompiled["units"][0]["source"]
    contexts = {
        view: bridge.run(
            project,
            "fixture",
            {
                "action": "context_" + view,
                "operation_id": "foundation-" + view,
                "address": address,
                "limit": 20,
                "length": 32,
            },
        )
        for view in ("layout", "function", "references", "strings", "types", "bytes")
    }
    assert contexts["layout"]["items"] and contexts["bytes"]["length"] == 32
    proposal = {
        "address": address,
        "name": "recovered_transform",
        "expected_name": "transform",
        "expected_revision": inventory["revision"],
    }
    renamed = bridge.run(
        project,
        "fixture",
        {
            "action": "annotate",
            "operation_id": "foundation-rename",
            "payload_hash": digest(proposal),
            **proposal,
        },
    )
    assert renamed["status"] == "saved" and renamed["reopened_and_verified"]
    again = bridge.run(
        project,
        "fixture",
        {
            "action": "annotate",
            "operation_id": "foundation-rename",
            "payload_hash": digest(proposal),
            **proposal,
        },
    )
    assert again["revision"] == renamed["revision"] and again["reconciled"]
    native = ReaBridge(rea, jobs, ghidra).run(
        "analyze", binary, root, ("--provider", "ghidra")
    )
    result = {
        "ghidra": {
            "inventory": len(inventory["functions"]),
            "decompiled": len(decompiled["units"]),
            "views": list(contexts),
            "annotation_reopened": True,
            "duplicate_revision_unchanged": True,
        },
        "rea": native,
    }
    (root / "verification.json").write_text(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("root")
    p.add_argument("--ghidra", required=True)
    p.add_argument("--rea", required=True)
    a = p.parse_args()
    print(json.dumps(verify(a.root, a.ghidra, a.rea), indent=2))
