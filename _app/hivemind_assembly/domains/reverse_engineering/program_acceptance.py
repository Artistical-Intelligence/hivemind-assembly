"""Pinned original-image oracle and sealed deterministic program cases."""

import hashlib
import json
from .program import build, compare, replay, sources
from hivemind_assembly.core.common import (
    scoped,
    canonical,
    file_hash,
    Blocked,
    ContractError,
    Conflict,
)


class ProgramAcceptance:
    def prepare(self, root, spec, artifacts, project, context):
        if set(spec) != {"scope", "original_path", "manifest_path", "cases"}:
            raise ContractError(
                "Program contract requires original_path, manifest_path and cases"
            )
        original = scoped(root, spec["original_path"]).read_bytes()
        scoped(root, spec["manifest_path"])
        cases = spec["cases"]
        if not isinstance(cases, list) or not 2 <= len(cases) <= 256:
            raise ContractError("Program acceptance requires 2–256 input cases")
        if len(canonical(cases)) > 2_000_000:
            raise ContractError("Program corpus exceeds bounds")
        for case in cases:
            if set(case) - {
                "id",
                "input_hex",
                "clock_ns",
                "max_instructions",
                "original_memory",
                "candidate_memory",
                "runtime", "files", "random_hex",
            }:
                raise ContractError("Unknown program case field")
            runner = replay
            extra = {}
            if case.get("runtime") == "qiling_linux":
                from .platform_runtime import replay as qiling_replay
                runner = qiling_replay
                extra = {"files":case.get("files",{}), "random_hex":case.get("random_hex","")}
            elif case.get("runtime", "unicorn_linux") != "unicorn_linux":
                raise ContractError("Unknown program runtime")
            result = runner(
                original,
                bytes.fromhex(case.get("input_hex", "")),
                clock_ns=case.get("clock_ns", 0),
                max_instructions=case.get("max_instructions", 1_000_000),
                observations=case.get("original_memory", ()),
                **extra,
            )
            if result["status"] != "completed":
                raise Blocked(
                    "Original program does not complete within the declared replay contract"
                )
        pinned = artifacts.add(original, "original-program.elf", project, "protected")
        suite = artifacts.add(
            canonical(cases), "program-holdouts.json", project, "protected"
        )
        return {
            "scope": spec["scope"],
            "checks": [
                {
                    "candidate_path": spec["manifest_path"],
                    "case_count": len(cases),
                    "original_sha256": pinned["sha256"],
                }
            ],
            "manifest_path": spec["manifest_path"],
            "original_artifact": pinned["id"],
            "original_sha256": pinned["sha256"],
            "cases_artifact": suite["id"],
            "cases_sha256": suite["sha256"],
            "case_count": len(cases),
        }

    def verify(self, root, contract, artifacts, project, context):
        checks = []
        original = artifacts.read(contract["original_artifact"], "evaluator", project)
        raw = artifacts.read(contract["cases_artifact"], "evaluator", project)
        if (
            hashlib.sha256(original).hexdigest() != contract["original_sha256"]
            or hashlib.sha256(raw).hexdigest() != contract["cases_sha256"]
        ):
            raise Conflict("Protected program evidence changed")
        path = scoped(root, contract["manifest_path"])
        if path.stat().st_size > 128000:
            raise Blocked("Build manifest exceeds bounds")
        manifest = json.loads(path.read_text())
        units = sources(root, manifest)
        checks.append(
            {
                "candidate_path": contract["manifest_path"],
                "file_sha256": file_hash(path),
            }
        )
        checks.extend(
            {"candidate_path": n, "file_sha256": hashlib.sha256(s.encode()).hexdigest()}
            for n, s in units.items()
        )
        compiled = build(
            root,
            manifest,
            context.jobs,
            context.config.get("foundations", {}).get("c_compiler", ""),
            context.cancel,
        )
        if not compiled["passed"]:
            return {
                "scope": contract["scope"],
                "passed": False,
                "checks": checks,
                "build": compiled,
            }
        candidate = bytes.fromhex(compiled.pop("elf_hex"))
        compared = compare(original, candidate, json.loads(raw), context.cancel)
        executable = artifacts.add(candidate, "reconstructed-program.elf", project)
        for check in checks:
            check["passed"] = compared["passed"]
        # Keep sealed inputs and full original observations out of worker-visible
        # results. The owner retains detailed evidence in a protected artifact.
        details = artifacts.add(
            canonical(compared), "program-acceptance-details.json", project, "protected"
        )
        return {
            "scope": contract["scope"],
            "passed": compared["passed"],
            "checks": checks,
            "build": compiled,
            "executable_artifact": executable["id"],
            "protected_details": details["id"],
            "cases": [
                {"id": r["id"], "passed": r["passed"], "differences": r["differences"]}
                for r in compared["cases"]
            ],
            "claim": compared["claim"],
        }
