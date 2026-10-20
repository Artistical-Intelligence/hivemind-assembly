"""Protected linked-function acceptance, independent of worker-supplied scores."""

import hashlib
import json
from . import call_images, pe_dependencies
from .program import sources
from hivemind_assembly.core.common import (
    Blocked,
    ContractError,
    Conflict,
    canonical,
    scoped,
    file_hash,
)


class CallAcceptance:
    def prepare(self, root, spec, artifacts, project, context):
        allowed = {
            "scope",
            "original_path",
            "original_symbol",
            "original_address",
            "original_dependencies",
            "manifest_path",
            "function",
            "candidate_abi",
            "cases",
        }
        if set(spec) - allowed or not {
            "original_path",
            "manifest_path",
            "function",
            "candidate_abi",
            "cases",
        } <= set(spec):
            raise ContractError(
                "Linked-call contract requires original image/entry, manifest, function, candidate ABI and cases"
            )
        call_images.function_name(spec["function"])
        if spec["candidate_abi"] not in call_images.ABIS:
            raise ContractError("Candidate ABI must be sysv or win64")
        path = scoped(root, spec["original_path"])
        if path.stat().st_size > call_images.MAX_IMAGE:
            raise Blocked("Original image exceeds bounds")
        original = path.read_bytes()
        dependencies = pe_dependencies.read_dependencies(
            root, spec.get("original_dependencies", {})
        )
        image = pe_dependencies.load(
            original,
            spec.get("original_symbol"),
            spec.get("original_address"),
            dependencies,
        )

        scoped(root, spec["manifest_path"])
        cases = spec["cases"]
        if (
            not isinstance(cases, list)
            or not 2 <= len(cases) <= 256
            or len(canonical(cases)) > 2_000_000
        ):
            raise ContractError("Use 2–256 cases totaling at most 2 MB")
        for case in cases:
            if context.cancel.is_set():
                raise Blocked("Acceptance preparation cancelled")
            result = call_images.execute(image, case)
            if result["status"] != "completed" or not result["abi_ok"]:
                raise Blocked(
                    "Original call is outside the declared linked-function contract"
                )
        pinned = artifacts.add(
            original, "original-call-image.bin", project, "protected"
        )
        suite = artifacts.add(
            canonical(cases), "call-holdouts.json", project, "protected"
        )
        retained_dependencies = {}
        for name, data in dependencies.items():
            item = artifacts.add(data, name, project, "protected")
            retained_dependencies[name] = {
                "artifact": item["id"],
                "sha256": item["sha256"],
            }
        public = {
            "candidate_path": spec["manifest_path"],
            "function": spec["function"],
            "candidate_abi": spec["candidate_abi"],
            "original_abi": image["abi"],
            "original_entry": image["entry"],
            "original_symbol": spec.get("original_symbol"),
            "case_count": len(cases),
        }
        return {
            "scope": spec["scope"],
            "dependencies": retained_dependencies,
            "checks": [public],
            "original_artifact": pinned["id"],
            "original_sha256": pinned["sha256"],
            "cases_artifact": suite["id"],
            "cases_sha256": suite["sha256"],
        }

    def verify(self, root, contract, artifacts, project, context):
        check = contract["checks"][0]
        original = artifacts.read(contract["original_artifact"], "evaluator", project)
        raw = artifacts.read(contract["cases_artifact"], "evaluator", project)
        if (
            hashlib.sha256(original).hexdigest() != contract["original_sha256"]
            or hashlib.sha256(raw).hexdigest() != contract["cases_sha256"]
        ):
            raise Conflict("Protected linked-call evidence changed")
        dependencies = {}
        for name, retained in contract.get("dependencies", {}).items():
            data = artifacts.read(retained["artifact"], "evaluator", project)
            if hashlib.sha256(data).hexdigest() != retained["sha256"]:
                raise Conflict("Protected DLL dependency changed")
            dependencies[name] = data
        path = scoped(root, check["candidate_path"])
        if path.stat().st_size > 128000:
            raise Blocked("Build manifest exceeds bounds")
        manifest_bytes = path.read_bytes()
        manifest = json.loads(manifest_bytes)
        units = sources(root, manifest)
        checks = [
            {
                "candidate_path": check["candidate_path"],
                "file_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            }
        ]
        # Hash file bytes, not newline-normalized source text.
        checks += [
            {"candidate_path": name, "file_sha256": file_hash(scoped(root, name))}
            for name in units
        ]
        built = call_images.build(
            root,
            manifest,
            check["function"],
            check["candidate_abi"],
            context.jobs,
            context.config.get("foundations", {}).get("c_compiler", ""),
            context.cancel,
        )
        compared = {"passed": False}
        executable = None
        if built["passed"]:
            machine = bytes.fromhex(built.pop("image_hex"))
            compared = call_images.compare(
                pe_dependencies.load(
                    original, address=check["original_entry"], dependencies=dependencies
                ),
                call_images.load(machine, symbol=check["function"]),
                json.loads(raw),
                context.cancel,
            )
            executable = artifacts.add(
                machine,
                "reconstructed-call."
                + ("dll" if check["candidate_abi"] == "win64" else "elf"),
                project,
            )["id"]
        for item in checks:
            if file_hash(scoped(root, item["candidate_path"])) != item["file_sha256"]:
                raise Conflict(
                    "Candidate source or manifest changed during verification"
                )
            item["passed"] = compared["passed"]
        detail = artifacts.add(
            canonical(compared), "call-acceptance-details.json", project, "protected"
        )
        return {
            "scope": contract["scope"],
            "passed": compared["passed"],
            "checks": checks,
            "build": built,
            "protected_details": detail["id"],
            "executable_artifact": executable,
            "tested": compared.get("tested", 0),
            "claim": compared.get("claim", "Compilation failed"),
        }
