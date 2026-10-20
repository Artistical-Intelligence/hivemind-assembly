"""Run installed foundations on source-known fixtures without model inference."""

import json
import os
from pathlib import Path
from hivemind_assembly.core.common import atomic_write, canonical, digest, uid, Blocked
from hivemind_assembly.core.jobs import Jobs
from hivemind_assembly.domains.reverse_engineering.bridges import (
    GhidraBridge,
    ReaBridge,
)
from hivemind_assembly.domains.reverse_engineering.program import build, replay


def build_analysis_fixture(root, foundations, jobs, host=None):
    """Use a source-known native PE on Windows, ELF elsewhere.

    REA's Windows P0 provider does not admit ELF. The ordinary x86 Linux runtime
    probe remains independent and must still execute successfully on every host.
    """
    from hivemind_assembly.domains.reverse_engineering import call_images

    root = Path(root)
    source = "unsigned state; __attribute__((noinline)) unsigned transform(unsigned a){state=state*3+a;return state;} int ha_main(void){return transform(7)==7?0:1;}"
    (root / "fixture.c").write_text(source, encoding="utf-8")
    manifest = {"sources": ["fixture.c"]}
    compiler = foundations.get("c_compiler", "")
    built = build(root, manifest, jobs, compiler)
    if not built["passed"]:
        raise Blocked("Source-known fixture compilation failed: " + json.dumps(built))
    raw = bytes.fromhex(built["elf_hex"])
    executed = replay(raw)
    if executed["status"] != "completed" or executed["exit_code"] != 0:
        raise Blocked("Source-known fixture execution failed")
    windows = (host or os.name) == "nt"
    binary = root / ("fixture.dll" if windows else "fixture")
    if windows:
        pe = call_images.build(root, manifest, "transform", "win64", jobs, compiler)
        if not pe["passed"]:
            raise Blocked(
                "Windows PE analysis fixture compilation failed: " + json.dumps(pe)
            )
        raw = bytes.fromhex(pe["image_hex"])
    binary.write_bytes(raw)
    return binary, {
        "passed": True,
        "compiler_sha256": built["compiler_sha256"],
        "analysis_fixture": binary.name,
        "analysis_format": "PE" if windows else "ELF",
    }


def verify_foundations(root, foundations, jobs=None):
    root = Path(root).resolve() / ("foundation-check-" + uid("run"))
    root.mkdir(parents=True)
    jobs = jobs or Jobs()
    result = {"passed": False, "checks": {}, "evidence_directory": str(root)}

    def save():
        atomic_write(root / "verification.json", canonical(result))

    binary = None
    try:
        binary, result["checks"]["compiler_runtime"] = build_analysis_fixture(
            root, foundations, jobs
        )
    except Exception as error:
        result["checks"]["compiler_runtime"] = {"passed": False, "reason": str(error)}
    save()
    from .runtime_verification import verify_runtime_lanes

    result["checks"].update(
        verify_runtime_lanes(root / "runtime-probes", foundations, jobs)
    )
    save()
    if binary is not None and binary.is_file():
        try:
            bridge = GhidraBridge(foundations.get("ghidra_home"), jobs)
            project = root / "ghidra"
            inventory = bridge.run(
                project,
                binary.name,
                {"action": "inventory", "operation_id": "import"},
                binary,
            )
            address = next(
                f["entry"] for f in inventory["functions"] if f["name"] == "transform"
            )
            decompiled = bridge.run(
                project,
                binary.name,
                {
                    "action": "decompile_batch",
                    "operation_id": "decompile",
                    "addresses": [address],
                },
            )
            if "transform" not in decompiled["units"][0]["source"]:
                raise Blocked("Ghidra did not decompile the known fixture")
            contexts = {
                view: bridge.run(
                    project,
                    binary.name,
                    {
                        "action": "context_" + view,
                        "operation_id": view,
                        "address": address,
                        "limit": 20,
                        "length": 32,
                    },
                )
                for view in (
                    "layout",
                    "function",
                    "references",
                    "strings",
                    "types",
                    "bytes",
                )
            }
            if not contexts["layout"]["items"] or contexts["bytes"]["length"] != 32:
                raise Blocked("Ghidra context evidence is incomplete")
            proposal = {
                "address": address,
                "name": "recovered_transform",
                "expected_name": "transform",
                "expected_revision": inventory["revision"],
            }
            request = {
                "action": "annotate",
                "operation_id": "rename",
                "payload_hash": digest(proposal),
                **proposal,
            }
            renamed = bridge.run(project, binary.name, request)
            again = bridge.run(project, binary.name, request)
            if (
                not renamed.get("reopened_and_verified")
                or again["revision"] != renamed["revision"]
                or not again.get("reconciled")
            ):
                raise Blocked("Ghidra durable annotation reconciliation failed")
            result["checks"]["ghidra"] = {
                "passed": True,
                "inventory": len(inventory["functions"]),
                "context_views": list(contexts),
                "annotation_reopened": True,
                "duplicate_revision_unchanged": True,
            }
        except Exception as error:
            result["checks"]["ghidra"] = {"passed": False, "reason": str(error)}
        save()
        try:
            evidence = ReaBridge(
                foundations.get("rea_home"), jobs, foundations.get("ghidra_home")
            ).run("analyze", binary, root, ("--provider", "ghidra"))
            if not evidence.get("evidence"):
                raise Blocked("REA returned no evidence")
            result["checks"]["rea"] = {"passed": True, "result": evidence}
        except Exception as error:
            result["checks"]["rea"] = {"passed": False, "reason": str(error)}
        save()
    try:
        from hivemind_assembly.automation.hermes import HermesHost

        host = HermesHost(foundations.get("hermes_home"), root)
        try:
            task = {
                "id": "fixture",
                "project_id": "foundation-check",
                "objective": "Verify installed Hermes claim and completion",
            }
            if not host.board.claim(task):
                raise Blocked("Hermes did not claim a ready fixture")
            host.record(
                "worker.fixture",
                "fixture:local",
                "user",
                "Source-known foundation check",
                "fixture-request",
            )
            host.board.complete(task, {"passed": True})
            if host.board.claim(task):
                raise Blocked("Hermes reclaimed a completed fixture")
            result["checks"]["hermes"] = {
                "passed": True,
                "native_inference_invoked": False,
            }
        finally:
            host.close()
    except Exception as error:
        result["checks"]["hermes"] = {"passed": False, "reason": str(error)}
    result["passed"] = set(result["checks"]) == {
        "compiler_runtime",
        "arm64_program",
        "qiling_runtime",
        "linked_functions",
        "ghidra",
        "rea",
        "hermes",
    } and all(c["passed"] for c in result["checks"].values())
    save()
    return result
