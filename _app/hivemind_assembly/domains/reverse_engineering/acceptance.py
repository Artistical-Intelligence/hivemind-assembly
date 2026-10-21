"""Independent checks of pinned original bytes against files produced by a task."""

import hashlib
import json
import secrets
from hivemind_assembly.core.common import (
    scoped,
    file_hash,
    Blocked,
    ContractError,
    Conflict,
    canonical,
)
from .proof import prove
from .reconstruction import (
    compile_function,
    compare_functions,
    vectors,
    execute_function,
)


class ReconstructionAcceptance:
    def prepare(self, root, spec, artifacts, project, context):
        checks = spec.get("checks")
        if not isinstance(checks, list) or not 1 <= len(checks) <= 8:
            raise ContractError("Function acceptance requires 1–8 checks")
        retained = []
        allowed = {
            "original_path",
            "original_format",
            "original_offset",
            "original_size",
            "candidate_path",
            "function",
            "argument_bits",
            "output_bits",
        }
        for item in checks:
            if not isinstance(item, dict) or set(item) - allowed:
                raise ContractError("Unknown function acceptance field")
            check = dict(item)
            if check.get("original_format", "binary") not in ("hex", "binary"):
                raise ContractError("Original format must be hex or binary")
            scoped(root, check["candidate_path"])
            original = region(root, check, "original")
            widths = check.get("argument_bits", [32, 32])
            cases = vectors(widths, secrets.randbits(128))
            output = check.get("output_bits", 32)
            # Validate original behavior before accepting the objective contract.
            for arguments in cases:
                result = execute_function(original, arguments, output)
                if result["status"] != "completed" or not result["abi_ok"]:
                    raise Blocked(
                        "Original function is outside the scalar SysV execution scope"
                    )
            import re

            if not isinstance(check.get("function"), str) or not re.fullmatch(
                r"[A-Za-z_][A-Za-z_0-9]{0,99}", check["function"]
            ):
                raise ContractError("A valid candidate C function name is required")
            pinned = artifacts.add(
                original, "original-function.bin", project, "protected"
            )
            suite = artifacts.add(
                canonical({"cases": cases}), "function-cases.json", project, "protected"
            )
            check.update(
                original_artifact=pinned["id"],
                original_sha256=pinned["sha256"],
                cases_artifact=suite["id"],
                cases_sha256=suite["sha256"],
                argument_bits=widths,
                output_bits=output,
                case_count=len(cases),
            )
            retained.append(check)
        return {"scope": spec["scope"], "checks": retained}

    def verify(self, root, contract, artifacts, project, context):
        results = []
        for check in contract["checks"]:
            result = {"candidate_path": check["candidate_path"], "passed": False}
            try:
                path = scoped(root, check["candidate_path"])
                if path.stat().st_size > 128000:
                    raise Blocked("Candidate source exceeds 128 KB")
                result["file_sha256"] = file_hash(path)
                original = artifacts.read(
                    check["original_artifact"], "evaluator", project
                )
                suite = artifacts.read(check["cases_artifact"], "evaluator", project)
                if (
                    hashlib.sha256(original).hexdigest() != check["original_sha256"]
                    or hashlib.sha256(suite).hexdigest() != check["cases_sha256"]
                ):
                    raise Conflict("Protected function evidence changed")
                built = compile_function(
                    path.read_text("utf-8"),
                    check["function"],
                    context.jobs,
                    context.config.get("foundations", {}).get("c_compiler", ""),
                    context.cancel,
                )
                result["compilation"] = built
                if built["passed"]:
                    compared = compare_functions(
                        original,
                        bytes.fromhex(built["machine_hex"]),
                        json.loads(suite)["cases"],
                        check["output_bits"],
                        context.cancel,
                    )
                    result.update(passed=compared["passed"], comparison=compared)
                if file_hash(path) != result["file_sha256"]:
                    raise Conflict("Candidate changed during compilation")
            except Conflict:
                raise
            except (OSError, ValueError) as error:
                result["reason"] = str(error)
            results.append(result)
        passed = all(r["passed"] for r in results)
        return {
            "scope": contract["scope"],
            "passed": passed,
            "checks": results,
            "reason": (
                ""
                if passed
                else "Independent compiled function checks did not all pass"
            ),
            "claim": "Compiled freestanding C, SysV x86-64 unsigned scalar inputs and return value, preserved registers and stack balance on the retained cases only; no all-input or whole-program equivalence claim",
        }


from .program_acceptance import ProgramAcceptance
from .call_acceptance import CallAcceptance


class AcceptanceSuite:
    def verifier(self, scope):
        if scope in ("linked_calls", "x86_64_linked_calls"):
            return CallAcceptance()
        if scope in ("linux_program", "static_x86_64_linux_program", "x86_64_linux_program"):
            return ProgramAcceptance()
        if scope == "windows_program":
            from .windows_acceptance import WindowsAcceptance

            return WindowsAcceptance()
        if scope == "linux_project":
            from .project_acceptance import ProjectAcceptance

            return ProjectAcceptance()
        if scope == "x86_64_register_regions":
            return RegionAcceptance()
        if scope == "x86_64_c_functions":
            return ReconstructionAcceptance()
        raise ContractError(
            "Supported acceptance scopes: x86_64_register_regions, x86_64_c_functions, linked_calls, linux_program, linux_project, windows_program (legacy linked-call/program scopes also supported)"
        )

    def prepare(self, root, spec, artifacts, project, context):
        if not isinstance(spec, dict):
            raise ContractError("Acceptance specification must be an object")
        verifier = self.verifier(spec.get("scope"))
        args = (root, spec, artifacts, project)
        return (
            verifier.prepare(*args, context)
            if isinstance(
                verifier, (ReconstructionAcceptance, ProgramAcceptance, CallAcceptance)
            )
            else verifier.prepare(*args)
        )

    def verify(self, root, contract, artifacts, project, context):
        verifier = self.verifier(contract["scope"])
        args = (root, contract, artifacts, project)
        return verifier.verify(*args, context)

    def recheck(self, root, result):
        return RegionAcceptance().recheck(root, result)


def region(root, check, side):
    path = scoped(root, check[side + "_path"])
    if path.stat().st_size > 2_000_000:
        raise Blocked("Region input exceeds 2 MB; import a bounded region")
    raw = path.read_bytes()
    if check.get(side + "_format", "binary") == "hex":
        try:
            raw = bytes.fromhex(raw.decode("ascii"))
        except (ValueError, UnicodeDecodeError) as error:
            raise ContractError("Region file is not hexadecimal bytes") from error
    start = check.get(side + "_offset", 0)
    size = check.get(side + "_size", len(raw) - start)
    if (
        type(start) is not int
        or type(size) is not int
        or start < 0
        or not 1 <= size <= 4096
        or start + size > len(raw)
    ):
        raise ContractError("Region must select 1–4096 existing bytes")
    return raw[start : start + size]


class RegionAcceptance:
    def prepare(self, root, spec, artifacts, project):
        if not isinstance(spec, dict) or spec.get("scope") != "x86_64_register_regions":
            raise ContractError("Supported acceptance scope: x86_64_register_regions")
        checks = spec.get("checks")
        if not isinstance(checks, list) or not 1 <= len(checks) <= 16:
            raise ContractError("Acceptance requires 1–16 region checks")
        result = []
        allowed = {
            "original_path",
            "candidate_path",
            "original_format",
            "candidate_format",
            "original_offset",
            "candidate_offset",
            "original_size",
            "candidate_size",
            "inputs",
            "outputs",
        }
        for item in checks:
            if not isinstance(item, dict) or set(item) - allowed:
                raise ContractError("Unknown region acceptance fields")
            check = dict(item)
            for side in ("original", "candidate"):
                if not isinstance(check.get(side + "_path"), str):
                    raise ContractError("Original and candidate paths are required")
                scoped(root, check[side + "_path"])
                if check.get(side + "_format", "binary") not in ("hex", "binary"):
                    raise ContractError("Region format must be hex or binary")
                for suffix in ("offset", "size"):
                    key = side + "_" + suffix
                    if key in check and (
                        type(check[key]) is not int
                        or check[key] < (1 if suffix == "size" else 0)
                    ):
                        raise ContractError("Invalid region bounds")
            for field, default in (("inputs", ["RDI", "RSI"]), ("outputs", ["RAX"])):
                values = check.setdefault(field, default)
                if (
                    not isinstance(values, list)
                    or not (0 if field == "inputs" else 1) <= len(values) <= 32
                    or any(not isinstance(v, str) or not v for v in values)
                    or len(set(values)) != len(values)
                ):
                    raise ContractError(
                        "Explicit, unique input and output registers required"
                    )
            original = region(root, check, "original")
            # Reject unsupported original scopes before admitting task execution.
            supported = prove(
                original.hex(),
                original.hex(),
                tuple(check["inputs"]),
                tuple(check["outputs"]),
            )
            if supported.get("result") != "UNSAT":
                raise Blocked("Original region is outside the supported proof scope")
            saved = artifacts.add(original, "original-region.bin", project, "protected")
            check.update(original_artifact=saved["id"], original_sha256=saved["sha256"])
            result.append(check)
        return {"scope": spec["scope"], "checks": result}

    def verify(self, root, contract, artifacts, project, context=None):
        results = []
        for check in contract["checks"]:
            if context is not None and context.cancel.is_set():
                raise Blocked("Acceptance cancelled")
            try:
                original = artifacts.read(
                    check["original_artifact"], "evaluator", project
                )
                if hashlib.sha256(original).hexdigest() != check["original_sha256"]:
                    raise ContractError("Original evidence changed")
                path = scoped(root, check["candidate_path"])
                before = file_hash(path)
                candidate = region(root, check, "candidate")
                proof = prove(
                    original.hex(),
                    candidate.hex(),
                    tuple(check["inputs"]),
                    tuple(check["outputs"]),
                )
                if file_hash(path) != before:
                    raise Conflict("Candidate changed during verification")
                results.append(
                    {
                        "candidate_path": check["candidate_path"],
                        "file_sha256": before,
                        "passed": proof.get("result") == "UNSAT",
                        "proof": proof,
                    }
                )
            except (OSError, ValueError) as error:
                results.append(
                    {
                        "candidate_path": check["candidate_path"],
                        "passed": False,
                        "reason": str(error),
                    }
                )
        passed = all(r["passed"] for r in results)
        return {
            "scope": contract["scope"],
            "passed": passed,
            "checks": results,
            "reason": "" if passed else "Independent region checks did not all pass",
            "claim": "Listed register outputs only, under each proof's recorded assumptions; no whole-program equivalence claim",
        }

    def recheck(self, root, result):
        for check in result["checks"]:
            if (
                "file_sha256" in check
                and file_hash(scoped(root, check["candidate_path"]))
                != check["file_sha256"]
            ):
                raise Conflict("Candidate changed before acceptance was committed")
