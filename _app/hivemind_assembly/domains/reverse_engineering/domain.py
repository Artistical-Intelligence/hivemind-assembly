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
        Capability("plan_reconstruction", recovery="discard"),
        Capability("decompile"),
        Capability("decompile_batch"),
        Capability("program_context"),
        Capability("export_pcode"),
        Capability("propose_annotation", True, "reconcile"),
        Capability("rea_analyze"),
        Capability("rea_query"),
        Capability("compare_states", recovery="discard"),
        Capability("check_equivalence", recovery="discard"),
        Capability("validate_c_function", recovery="discard"),
        Capability("build_linked_function", recovery="discard"),
        Capability("compare_linked_function", recovery="discard"),
        Capability("build_windows_program", recovery="discard"),
        Capability("compare_windows_program", recovery="discard"),
        Capability("build_program", recovery="discard"),
        Capability("compare_program", recovery="discard"),
        Capability("compare_project", recovery="discard"),
    )

    def skills(self):
        return json.loads((Path(__file__).parent / "skills/catalogue.json").read_text())

    def workflow_runner(self):
        from .workflows import runner

        return runner()

    def execute(self, context: ToolContext, request: dict):
        tool, args = request["tool"], request["args"]
        root = context.workspace
        if tool == "plan_reconstruction":
            from .planning import plan

            path = scoped(root, args["graph_path"])
            if path.stat().st_size > 8_000_000:
                raise Blocked("Callgraph input exceeds 8 MB")
            return plan(json.loads(path.read_text()))
        if tool in {
            "inspect_program",
            "decompile",
            "decompile_batch",
            "program_context",
            "export_pcode",
            "propose_annotation",
        }:
            bridge = GhidraBridge(
                context.config["foundations"].get("ghidra_home"), context.jobs
            )
            action = {
                "inspect_program": "inventory",
                "decompile": "decompile",
                "decompile_batch": "decompile_batch",
                "program_context": "context_" + str(args.get("view", "layout")),
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
                        "offset",
                        "length",
                        "addresses",
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
        if tool in ("rea_analyze", "rea_query"):
            bridge = ReaBridge(
                context.config["foundations"].get("rea_home"),
                context.jobs,
                context.config["foundations"].get("ghidra_home"),
            )
            if tool == "rea_query":
                return bridge.query(
                    scoped(root, args["path"]), root, args, context.cancel
                )
            return bridge.run(
                "analyze",
                scoped(root, args["path"]),
                root,
                ("--provider", "ghidra"),
                context.cancel,
            )
        if tool in ("build_linked_function", "compare_linked_function"):
            from . import call_images, pe_dependencies

            path = scoped(root, args["manifest_path"])
            if path.stat().st_size > 128000:
                raise Blocked("Build manifest exceeds bounds")
            built = call_images.build(
                root,
                json.loads(path.read_text()),
                args["function"],
                args["candidate_abi"],
                context.jobs,
                context.config.get("foundations", {}).get("c_compiler", ""),
                context.cancel,
            )
            if built["passed"]:
                machine = bytes.fromhex(built.pop("image_hex"))
                built["_artifact"] = {
                    "data": machine,
                    "name": "reconstructed-call."
                    + (
                        "dll" if args["candidate_abi"] in call_images.PE_ABIS else "elf"
                    ),
                }
                if tool == "compare_linked_function":
                    original_path = scoped(root, args["original_path"])
                    if original_path.stat().st_size > call_images.MAX_IMAGE:
                        raise Blocked("Original image exceeds bounds")
                    original = pe_dependencies.load(
                        original_path.read_bytes(),
                        args.get("original_symbol"),
                        args.get("original_address"),
                        pe_dependencies.read_dependencies(
                            root, args.get("original_dependencies", {})
                        ),
                    )
                    built["comparison"] = call_images.compare(
                        original,
                        call_images.load(machine, symbol=args["function"]),
                        args["cases"],
                        context.cancel,
                    )
                    built["passed"] = built["comparison"]["passed"]
                built["claim"] = (
                    "Development evidence only; completion independently rebuilds against the pinned image and protected cases"
                )
            return built
        if tool in ("build_program", "compare_program", "build_windows_program", "compare_windows_program"):
            from .program import build, compare
            from .linux_dependencies import read_dependencies

            windows = tool in ("build_windows_program", "compare_windows_program")
            if windows:
                from .windows_program import build, compare

            manifest_path = scoped(root, args["manifest_path"])
            if manifest_path.stat().st_size > 128000:
                raise Blocked("Build manifest exceeds bounds")
            manifest = json.loads(manifest_path.read_text())
            built = build(
                root,
                manifest,
                context.jobs,
                context.config.get("foundations", {}).get("c_compiler", ""),
                context.cancel,
            )
            if built["passed"]:
                machine = bytes.fromhex(built.pop("pe_hex" if windows else "elf_hex"))
                built["_artifact"] = {
                    "data": machine,
                    "name": "reconstructed-program.exe" if windows else "reconstructed-program.elf",
                }
                if tool in ("compare_program", "compare_windows_program"):
                    original_path = scoped(root, args["original_path"])
                    if original_path.stat().st_size > 2_000_000:
                        raise Blocked("Original image exceeds bounds")
                    built["comparison"] = compare(
                        original_path.read_bytes(),
                        machine,
                        args["cases"],
                        context.cancel,
                        (args.get("original_dependencies") or {}) if windows else read_dependencies(root, args.get("original_dependencies", {})),
                    )
                    built["passed"] = built["comparison"]["passed"]
                built["claim"] = (
                    "Development evidence; completion independently rebuilds against the pinned original and protected corpus"
                )
            return built
        if tool == "compare_project":
            from .project_reconstruction import check

            original_path = scoped(root, args["original_path"])
            if original_path.stat().st_size > 2_000_000:
                raise Blocked("Original image exceeds bounds")
            plan = None
            if args.get("plan_path"):
                plan_file = scoped(root, args["plan_path"])
                if plan_file.stat().st_size > 8_000_000:
                    raise Blocked("Plan exceeds 8 MB")
                plan = json.loads(plan_file.read_text())
            result = check(
                root,
                args["manifest_path"],
                original_path.read_bytes(),
                args.get("function_checks", {}),
                args["cases"],
                context.jobs,
                context.config.get("foundations", {}).get("c_compiler", ""),
                context.cancel,
                plan,
                verified=context.verified,
            )
            image = result.pop("image", None)
            if image is not None:
                result["_artifact"] = {"data": image, "name": "reconstructed-program.elf"}
            return result
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
