"""Behavioral checks for the modular boundary and preserved RE integration."""

import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest

from hivemind_assembly.core.broker import Broker, CORE_CAPABILITIES
from hivemind_assembly.core.common import ContractError, Conflict
from hivemind_assembly.core.domain import Capability
from hivemind_assembly.domains.reverse_engineering.domain import (
    ReverseEngineeringDomain,
)
from hivemind_assembly.domains.reverse_engineering.bridges import GhidraBridge

APP = Path(__file__).parents[1] / "_app"


def request(task, epoch, tool, args=None):
    return {
        "id": "boundary1",
        "task_id": task["id"],
        "owner": "worker.opus",
        "epoch": epoch,
        "revision": 0,
        "tool": tool,
        "args": args or {},
    }


class TextDomain:
    """A small test domain, not a second product or a claimed new integration."""

    id = "text_fixture"
    instructions = "Count characters deterministically."
    capabilities = (Capability("count_text", recovery="discard"),)

    def skills(self):
        return []

    def execute(self, context, request):
        return {"characters": len(request["args"]["text"])}


def test_reusable_layers_import_without_specialist_dependencies(tmp_path):
    code = """
import importlib.abc, sys
class RejectSpecialists(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.startswith(("hivemind_assembly.domains", "hivemind_assembly.application")) or fullname.split(".")[0] in {"pypcode", "unicorn", "z3", "playwright"}:
            raise AssertionError("Unexpected dependency: " + fullname)
sys.meta_path.insert(0, RejectSpecialists())
from hivemind_assembly.core.store import Store
from hivemind_assembly.core.controller import Controller
from hivemind_assembly.core.broker import Broker
from hivemind_assembly.learning.engine import Learning
from hivemind_assembly.automation.team import NativeTeam
s = Store(sys.argv[1])
c = Controller(s)
b = Broker(c, {})
assert {'list_files', 'read_file', 'write_file', 'checkpoint', 'read_artifact', 'run_workflow', 'propose_workflow'} == set(b.capabilities)
assert NativeTeam(c, b, None, {"routes": {}}).skill_manifest() == []
s.close()
"""
    subprocess.run(
        [sys.executable, "-c", code, str(tmp_path / "core")],
        env={**os.environ, "PYTHONPATH": str(APP)},
        check=True,
        timeout=20,
    )


def test_other_domain_uses_same_durable_execution(ready):
    c, t, epoch = ready
    broker = Broker(c, {}, domain=TextDomain())
    r = request(t, epoch, "count_text", {"text": "hivemind"})
    result = broker.execute(r)
    assert result["characters"] == 8
    assert result["result_artifact"]
    assert broker.execute(r) == result
    assert c.store.project(t["project_id"])["revision"] == 0
    assert "decompile" not in broker.capabilities


def test_domain_cannot_override_core_operations(ready):
    c, _, _ = ready
    domain = TextDomain()
    domain.capabilities = (Capability("write_file"),)
    with pytest.raises(ContractError, match="collides"):
        Broker(c, {}, domain)


def test_mutations_cannot_be_marked_discardable(ready):
    c, _, _ = ready
    domain = TextDomain()
    domain.capabilities = (Capability("change", True, "discard"),)
    with pytest.raises(ContractError, match="mutation"):
        Broker(c, {}, domain)


def test_original_specialist_capabilities_and_proof_are_preserved(ready):
    c, t, epoch = ready
    domain = ReverseEngineeringDomain()
    broker = Broker(c, {"foundations": {}}, domain)
    assert set(broker.capabilities) == {c.name for c in CORE_CAPABILITIES} | {
        "inspect_program",
        "decompile",
        "decompile_batch",
        "program_context",
        "export_pcode",
        "propose_annotation",
        "rea_analyze",
        "rea_query",
        "compare_states",
        "check_equivalence",
        "validate_c_function",
        "build_linked_function",
        "compare_linked_function",
        "build_program",
        "compare_program",
    }
    assert len(domain.skills()) == 20
    result = broker.execute(
        request(
            t,
            epoch,
            "check_equivalence",
            {"original_hex": "89f801f0", "candidate_hex": "8d0437"},
        )
    )
    assert result["status"] == "region_proved"


def test_ghidra_script_location_and_reopen_contract(tmp_path):
    home = tmp_path / "ghidra"
    headless = (
        home
        / "support"
        / ("analyzeHeadless.bat" if os.name == "nt" else "analyzeHeadless")
    )
    headless.parent.mkdir(parents=True)
    headless.touch()

    class SimulatedJobs:
        calls = []

        def run(self, key, args, cwd, **kwargs):
            self.calls.append(args)
            script = Path(args[args.index("-scriptPath") + 1]) / "WorkbenchBridge.java"
            assert script.is_file()
            # Native project name is deliberately stable across the branding change.
            assert args[2] == "Workbench"
            pos = args.index("-postScript")
            incoming = json.loads(Path(args[pos + 2]).read_text())
            result = {"revision": 1}
            if incoming["action"] == "reconcile":
                result["recorded_payload_hash"] = "retained-hash"
            Path(args[pos + 3]).write_text(json.dumps(result))
            return {"exit_code": 0, "elapsed": 0.1, "output": ""}

    jobs = SimulatedJobs()
    result = GhidraBridge(home, jobs).run(
        tmp_path / "project",
        "fixture",
        {"action": "annotate", "operation_id": "op1", "payload_hash": "retained-hash"},
    )
    assert result["reopened_and_verified"]
    assert result["status"] == "saved"
    assert len(jobs.calls) == 2


@pytest.mark.parametrize("change_epoch", [False, True])
def test_domain_mutation_reconciliation_retains_revision_fence(
    ready, monkeypatch, change_epoch
):
    c, t, epoch = ready

    class MutationDomain(TextDomain):
        capabilities = (Capability("change", True, "reconcile"),)

        def execute(self, context, request):
            return {"status": "saved"}

        def reconcile(self, context, operation):
            return {"status": "saved", "evidence": "fixture ledger"}

    b = Broker(c, {}, MutationDomain())
    monkeypatch.setattr(
        c, "finish", lambda *a: (_ for _ in ()).throw(RuntimeError("lost response"))
    )
    with pytest.raises(RuntimeError):
        b.execute(request(t, epoch, "change"))
    if change_epoch:
        with c.store.tx() as db:
            db.execute("UPDATE tasks SET epoch=epoch+1 WHERE id=?", (t["id"],))
        with pytest.raises(Conflict):
            b.reconcile_domain("boundary1")
        assert c.store.project(t["project_id"])["revision"] == 0
    else:
        assert b.reconcile_domain("boundary1")["reconciled"]
        assert c.store.project(t["project_id"])["revision"] == 1
        with pytest.raises(ContractError):
            b.reconcile_domain("boundary1")


def test_architectural_import_boundaries():
    base = APP / "hivemind_assembly"
    for group in ("core", "learning", "automation", "domains/reverse_engineering"):
        for path in (base / group).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                names = (
                    [node.module or ""]
                    if isinstance(node, ast.ImportFrom)
                    else (
                        [a.name for a in node.names]
                        if isinstance(node, ast.Import)
                        else []
                    )
                )
                for name in names:
                    assert not name.startswith("workbench"), path
                    if group != "domains/reverse_engineering":
                        assert not name.startswith(
                            (
                                "hivemind_assembly.domains",
                                "hivemind_assembly.application",
                            )
                        ), path
                    else:
                        assert not name.startswith(
                            (
                                "hivemind_assembly.automation",
                                "hivemind_assembly.application",
                            )
                        ), path
