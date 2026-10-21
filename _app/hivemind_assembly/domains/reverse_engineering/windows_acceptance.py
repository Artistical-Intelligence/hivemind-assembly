"""Sealed Windows PE originals and cases, independently rebuilt at acceptance."""

import copy
from .program_acceptance import ProgramAcceptance
from .windows_program import build, compare, image_info, replay, validate_case
from hivemind_assembly.core.common import Blocked, ContractError, canonical, scoped


class WindowsAcceptance(ProgramAcceptance):
    build = staticmethod(build)
    compare = staticmethod(compare)
    image_key = "pe_hex"
    image_name = "reconstructed-program.exe"

    def prepare(self, root, spec, artifacts, project, context):
        required = {"scope", "original_path", "manifest_path", "cases"}
        if set(spec) != required:
            raise ContractError(
                "Windows contract requires scope, original_path, manifest_path and cases"
            )
        path = scoped(root, spec["original_path"])
        if path.stat().st_size > 2_000_000:
            raise Blocked("Original Windows image exceeds 2 MB")
        original = path.read_bytes()
        image_info(original)
        scoped(root, spec["manifest_path"])
        cases = copy.deepcopy(spec["cases"])
        if (
            not isinstance(cases, list)
            or not 2 <= len(cases) <= 256
            or len(canonical(cases)) > 2_000_000
        ):
            raise ContractError("Windows acceptance requires 2–256 bounded cases")
        inputs = [validate_case(c) for c in cases]
        for case, data in zip(cases, inputs):
            case.setdefault("effect_policy", "strict")
            result = replay(
                original,
                data,
                files=case.get("files", {}),
                command_line=case.get("command_line", "program.exe"),
                env=case.get("env", {}),
                clock_ms=case.get("clock_ms", 0),
                max_instructions=case.get("max_instructions", 1_000_000),
                cancel=context.cancel,
            )
            if result["status"] != "completed":
                diagnostic = artifacts.add(
                    canonical(result),
                    "windows-preflight-diagnostic.json",
                    project,
                    "protected",
                )
                raise Blocked(
                    "Original Windows program did not complete; protected diagnostic: "
                    + diagnostic["id"]
                )
        pinned = artifacts.add(original, "original-program.exe", project, "protected")
        corpus = artifacts.add(
            canonical(cases), "windows-holdouts.json", project, "protected"
        )
        return {
            "scope": "windows_program",
            "dependencies": {},
            "checks": [
                {
                    "candidate_path": spec["manifest_path"],
                    "case_count": len(cases),
                    "effect_policies": sorted({c["effect_policy"] for c in cases}),
                    "original_sha256": pinned["sha256"],
                }
            ],
            "manifest_path": spec["manifest_path"],
            "original_artifact": pinned["id"],
            "original_sha256": pinned["sha256"],
            "cases_artifact": corpus["id"],
            "cases_sha256": corpus["sha256"],
            "case_count": len(cases),
        }
