"""Protected project-level acceptance: sealed function and program corpora.

The original image, the program corpus and every declared function corpus are
pinned as protected artifacts before work starts. Verification rebuilds each
function from the candidate's own project manifest, compares it with the pinned
original, composes the recovered regions with original-code fallback and replays
the program corpus. When the manifest names a complete build, the source-only
program must pass as well. Required functions must be recovered and validated,
not merely left on fallback code.
"""

import copy
import hashlib
import json

from hivemind_assembly.core.common import Blocked, ContractError, Conflict, canonical, file_hash, scoped
from . import call_images, project_reconstruction
from .program_acceptance import ProgramAcceptance


class ProjectAcceptance(ProgramAcceptance):
    def prepare(self, root, spec, artifacts, project, context):
        allowed = {
            "scope",
            "original_path",
            "manifest_path",
            "cases",
            "function_checks",
            "required_functions",
            "minimum_recovered",
            "plan",
        }
        if set(spec) - allowed or "function_checks" not in spec:
            raise ContractError(
                "Project contract requires original_path, manifest_path, cases and function_checks"
            )
        base = super().prepare(
            root,
            {k: spec[k] for k in ("scope", "original_path", "manifest_path", "cases")},
            artifacts,
            project,
            context,
        )
        checks = copy.deepcopy(spec["function_checks"])
        if not isinstance(checks, dict) or len(checks) > project_reconstruction.MAX_FUNCTIONS:
            raise ContractError("Supply at most 128 protected function checks")
        original = scoped(root, spec["original_path"]).read_bytes()
        for name, item in checks.items():
            call_images.function_name(name)
            if not isinstance(item, dict) or set(item) - {"original_symbol", "original_address", "cases"}:
                raise ContractError("Function checks allow original_symbol/address and cases")
            cases = item.get("cases")
            if not isinstance(cases, list) or not 1 <= len(cases) <= 256:
                raise ContractError("Each protected function check needs 1–256 cases")
            loaded = project_reconstruction.original_function(original, name, item)
            for case in cases:
                call_images.validate_case(case)
                observed = call_images.execute(loaded, case, context.cancel)
                if observed["status"] != "completed" or not observed["abi_ok"]:
                    raise Blocked("Original function does not complete a declared case: " + name)
        required = spec.get("required_functions", sorted(checks))
        if (
            not isinstance(required, list)
            or len(required) != len(set(required))
            or not all(isinstance(n, str) for n in required)
        ):
            raise ContractError("Required functions must be distinct names")
        for name in required:
            call_images.function_name(name)
        minimum = spec.get("minimum_recovered", max(1, len(required)))
        if type(minimum) is not int or not 0 <= minimum <= project_reconstruction.MAX_FUNCTIONS:
            raise ContractError("Minimum recovered regions must be 0–128")
        plan = spec.get("plan")
        if plan is not None:
            project_reconstruction.order(checks, plan)
        if len(canonical(checks)) > 4_000_000:
            raise ContractError("Function corpus exceeds bounds")
        sealed = artifacts.add(
            canonical({"checks": checks, "plan": plan}),
            "project-function-holdouts.json",
            project,
            "protected",
        )
        base["checks"][0]["function_count"] = len(checks)
        return base | {
            "functions_artifact": sealed["id"],
            "functions_sha256": sealed["sha256"],
            "required_functions": sorted(required),
            "minimum_recovered": minimum,
        }

    def verify(self, root, contract, artifacts, project, context):
        original = artifacts.read(contract["original_artifact"], "evaluator", project)
        raw = artifacts.read(contract["cases_artifact"], "evaluator", project)
        sealed = artifacts.read(contract["functions_artifact"], "evaluator", project)
        if (
            hashlib.sha256(original).hexdigest() != contract["original_sha256"]
            or hashlib.sha256(raw).hexdigest() != contract["cases_sha256"]
            or hashlib.sha256(sealed).hexdigest() != contract["functions_sha256"]
        ):
            raise Conflict("Protected project evidence changed")
        held = json.loads(sealed)
        manifest, build, _, units = project_reconstruction.read_manifest(
            root, contract["manifest_path"]
        )
        checks = [
            {
                "candidate_path": contract["manifest_path"],
                "file_sha256": file_hash(scoped(root, contract["manifest_path"])),
            },
            *(
                [
                    {
                        "candidate_path": manifest["build"],
                        "file_sha256": file_hash(scoped(root, manifest["build"])),
                    }
                ]
                if build is not None
                else []
            ),
            *({"candidate_path": n, "file_sha256": file_hash(scoped(root, n))} for n in units),
        ]
        required = set(contract["required_functions"])
        missing = required - set(manifest.get("functions", {}))
        if missing:
            for item in checks:
                item["passed"] = False
            return {
                "scope": contract["scope"],
                "passed": False,
                "checks": checks,
                "missing_functions": sorted(missing),
            }
        # Protected checks for functions the candidate declares; a declared function
        # without its protected check would otherwise pass as program-only.
        protected = {n: held["checks"][n] for n in held["checks"] if n in manifest["functions"]}
        result = project_reconstruction.check(
            root,
            contract["manifest_path"],
            original,
            protected,
            json.loads(raw),
            context.jobs,
            context.config.get("foundations", {}).get("c_compiler", ""),
            context.cancel,
            held.get("plan"),
        )
        image = result.pop("image", None)
        composition = result["composition"]
        validated = {f["function"] for f in result["functions"] if f["passed"]}
        if composition.get("applicable"):
            recovered = set(composition.get("recovered") or ())
            exercised = recovered - set(composition.get("unexercised") or ())
            accepted = recovered & (validated | exercised)
        else:
            accepted = validated if result.get("program", {}).get("passed") else set()
        passed = (
            result["passed"]
            and required <= accepted
            and len(accepted) >= contract.get("minimum_recovered", 1)
        )
        for item in checks:
            item["passed"] = passed
        details = artifacts.add(
            canonical(result), "project-acceptance-details.json", project, "protected"
        )
        report = {
            "scope": contract["scope"],
            "passed": passed,
            "checks": checks,
            "protected_details": details["id"],
            "functions": [
                {"function": f["function"], "group": f["group"], "passed": f["passed"]}
                for f in result["functions"]
            ],
            "verified_prefix": result["verified_prefix"],
            "composition": {
                k: composition.get(k)
                for k in ("applicable", "passed", "recovered", "fallback", "rejected", "unexercised")
                if k in composition
            },
            "accepted_regions": sorted(accepted),
            "required_functions": sorted(required),
        }
        # Rejected-region details stay protected; only names and stages are released.
        if report["composition"].get("rejected"):
            report["composition"]["rejected"] = [
                {"function": r["function"], "stage": r["stage"]}
                for r in report["composition"]["rejected"]
            ]
        if "program" in result:
            report["program"] = {
                "passed": result["program"]["passed"],
                "cases": [
                    {"id": r["id"], "passed": r["passed"], "differences": r["differences"]}
                    for r in result["program"].get("cases", [])
                ],
            }
        if image is not None:
            report["executable_artifact"] = artifacts.add(image, self.image_name, project)["id"]
        report["claim"] = result["claim"]
        return report
