"""Direct specialist operations, independent of sessions and the dashboard.

Complete Ghidra/REA installations and native verification paths are preserved.
Only execution context is passed in; this package does not own controller state.
"""

import json
from pathlib import Path
from hivemind_assembly.core.common import (
    scoped,
    digest,
    Blocked,
    ContractError,
    Conflict,
)
from hivemind_assembly.core.domain import Capability, ToolContext
from .bridges import GhidraBridge, ReaBridge
from .semantics import differential
from .proof import prove
from .acceptance import AcceptanceSuite


class ReverseEngineeringDomain:
    id = "reverse_engineering"

    def __init__(self):
        self.acceptance = AcceptanceSuite()

    instructions = (
        "Reverse engineering is the primary task. Use original program behavior "
        "as independent evidence. Preserve complete Ghidra and REA capabilities. "
        "A scoped proof or passing fixture does not certify a whole application. "
        "Retain unsupported semantics, unresolved platform effects and reconstruction gaps."
    )
    capabilities = (
        Capability("inspect_program"),
        Capability("decompile"),
        Capability("export_pcode"),
        Capability("propose_annotation", True, "reconcile"),
        Capability("rea_analyze"),
        Capability("compare_states", recovery="discard"),
        Capability("check_equivalence", recovery="discard"),
        Capability("validate_c_function", recovery="discard"),
    )

    def skills(self):
        return json.loads((Path(__file__).parent / "skills/catalogue.json").read_text())

    def workflow_runner(self):
        from .workflows import runner

        return runner()

    def execute(self, context: ToolContext, request: dict):
        tool, args = request["tool"], request["args"]
        root = context.workspace
        if tool in {
            "inspect_program",
            "decompile",
            "export_pcode",
            "propose_annotation",
        }:
            bridge = GhidraBridge(
                context.config["foundations"].get("ghidra_home"), context.jobs
            )
            action = {
                "inspect_program": "inventory",
                "decompile": "decompile",
                "export_pcode": "pcode",
                "propose_annotation": "annotate",
            }[tool]
            native_request = {
                "action": action,
                "operation_id": request["id"],
                "payload_hash": digest(args),
                **{
                    k: v
                    for k, v in args.items()
                    if k
                    in (
                        "address",
                        "name",
                        "expected_name",
                        "expected_revision",
                        "limit",
                    )
                },
            }
            binary = scoped(root, args["binary"]) if args.get("binary") else None
            return bridge.run(
                root.parent / "ghidra",
                args["program"],
                native_request,
                binary,
                context.cancel,
            )
        if tool == "rea_analyze":
            bridge = ReaBridge(
                context.config["foundations"].get("rea_home"), context.jobs
            )
            return bridge.run(
                "analyze",
                scoped(root, args["path"]),
                root,
                ("--provider", "ghidra"),
                context.cancel,
            )
        if tool == "compare_states":
            return differential(args["case"])
        if tool == "validate_c_function":
            from .reconstruction import compile_function, compare_functions, vectors

            path = scoped(root, args["candidate_path"])
            if path.stat().st_size > 128000:
                raise Blocked("Candidate source exceeds 128 KB")
            built = compile_function(
                path.read_text("utf-8"),
                args["function"],
                context.jobs,
                context.config.get("foundations", {}).get("c_compiler", ""),
                context.cancel,
            )
            if built["passed"]:
                built["comparison"] = compare_functions(
                    bytes.fromhex(args["original_hex"]),
                    bytes.fromhex(built["machine_hex"]),
                    vectors(args.get("argument_bits", [32, 32]), 0),
                    args.get("output_bits", 32),
                    context.cancel,
                )
                built["passed"] = built["comparison"]["passed"]
            built["claim"] = (
                "Development samples only; completion independently rebuilds against protected original evidence"
            )
            return built
        if tool == "check_equivalence":
            return prove(
                args["original_hex"],
                args["candidate_hex"],
                tuple(args.get("inputs", ["RDI", "RSI"])),
                tuple(args.get("outputs", ["RAX"])),
                min(args.get("timeout_ms", 5000), 30000),
            )
        raise Blocked("Unknown reverse engineering capability")

    def reconcile(self, context: ToolContext, operation: dict):
        if operation["tool"] != "propose_annotation":
            raise ContractError("Not a reconcilable reverse engineering mutation")
        args = json.loads(operation["args"])
        bridge = GhidraBridge(
            context.config["foundations"].get("ghidra_home"), context.jobs
        )
        observed = bridge.run(
            context.workspace.parent / "ghidra",
            args["program"],
            {"action": "reconcile", "operation_id": operation["id"]},
        )
        recorded = observed.get("recorded_payload_hash")
        if not recorded and observed["revision"] == args["expected_revision"]:
            return {"status": "not_applied"}
        if recorded != digest(args):
            raise Conflict("Native ledger differs from the retained operation payload")
        return {
            **observed,
            "status": "saved",
            "reconciled": True,
            "operation_id": operation["id"],
        }
