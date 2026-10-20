"""Pinned original-image oracle and sealed deterministic program cases."""

import copy
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
        required = {"scope", "original_path", "manifest_path", "cases"}
        if not required <= set(spec) or set(spec) - required - {
            "original_dependencies"
        }:
            raise ContractError(
                "Program contract requires original_path, manifest_path and cases"
            )
        original = scoped(root, spec["original_path"]).read_bytes()
        scoped(root, spec["manifest_path"])
        from .linux_dependencies import read_dependencies, validate

        dependencies = read_dependencies(root, spec.get("original_dependencies", {}))
        info = validate(original, dependencies)
        if info["dynamic"] and spec["scope"] == "static_x86_64_linux_program":
            raise ContractError(
                "Dynamic images require x86_64_linux_program acceptance"
            )
        cases = spec["cases"]
        if not isinstance(cases, list) or not 2 <= len(cases) <= 256:
            raise ContractError("Program acceptance requires 2–256 input cases")
        from .process_inputs import normalize

        cases = copy.deepcopy(cases)
        for case in cases:
            if not isinstance(case, dict):
                raise ContractError("Program cases must be objects")
            case["argv"], case["env"] = normalize(case.get("argv"), case.get("env"))
            case.setdefault("effect_policy", "strict")
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
                "runtime",
                "files",
                "random_hex",
                "argv",
                "env",
                "effect_policy",
            }:
                raise ContractError("Unknown program case field")
            if case.get("effect_policy", "strict") not in ("strict", "observable"):
                raise ContractError("Unknown program effect comparison policy")
            runner = replay
            extra = {}
            if case.get("runtime") == "qiling_linux":
                from .platform_runtime import replay as qiling_replay

                runner = qiling_replay
                extra = {
                    "files": case.get("files", {}),
                    "random_hex": case.get("random_hex", ""),
                    "dependencies": dependencies,
                }
            elif info["dynamic"]:
                raise ContractError("Dynamic images require qiling_linux cases")
            elif case.get("runtime", "unicorn_linux") != "unicorn_linux":
                raise ContractError("Unknown program runtime")
            result = runner(
                original,
                bytes.fromhex(case.get("input_hex", "")),
                clock_ns=case.get("clock_ns", 0),
                argv=case.get("argv"),
                env=case.get("env"),
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
        pinned_dependencies = {}
        for name, value in dependencies.items():
            artifact = artifacts.add(value, "elf-dependency", project, "protected")
            pinned_dependencies[name] = {
                "artifact": artifact["id"],
                "sha256": artifact["sha256"],
            }
        return {
            "dependencies": pinned_dependencies,
            "scope": spec["scope"],
            "checks": [
                {
                    "candidate_path": spec["manifest_path"],
                    "case_count": len(cases),
                    "effect_policies": sorted(
                        {c.get("effect_policy", "strict") for c in cases}
                    ),
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
        dependencies = {}
        for name, item in contract.get("dependencies", {}).items():
            value = artifacts.read(item["artifact"], "evaluator", project)
            if hashlib.sha256(value).hexdigest() != item["sha256"]:
                raise Conflict("Protected ELF dependency changed")
            dependencies[name] = value
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
            {"candidate_path": n, "file_sha256": file_hash(scoped(root, n))}
            for n in units
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
        compared = compare(
            original, candidate, json.loads(raw), context.cancel, dependencies
        )
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
