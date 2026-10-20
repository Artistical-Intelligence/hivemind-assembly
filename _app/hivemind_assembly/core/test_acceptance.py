"""Owner-pinned native test recipes for any domain, with protected oracles."""

import hashlib
import json
from .common import Blocked, Conflict, canonical, uid, digest
from . import tool_testing


class NativeTestAcceptance:
    def __init__(self, store):
        self.store = store

    def allow(self, project, allowed):
        self.store.project(project)
        if type(allowed) is not bool:
            raise ValueError("Native execution permission must be boolean")
        self.store.put(
            "native_test_permission:" + project, uid("permission"), {"allowed": allowed}
        )

    def require_permission(self, project):
        rows = self.store.rows(
            "SELECT payload FROM records WHERE kind=? ORDER BY rowid DESC LIMIT 1",
            ("native_test_permission:" + project,),
        )
        if not rows or json.loads(rows[0]["payload"])["allowed"] is not True:
            raise Blocked(
                "Owner has not enabled trusted native test execution for this project"
            )

    def authorize_recipe(self, project, specification):
        tool_testing.validate(specification["suite"])
        self.store.put(
            "native_recipe_authorization",
            project + ":" + digest(specification),
            {"owner_authorized": True},
        )

    def prepare(self, root, specification, artifacts, project, context):
        self.require_permission(project)
        if not self.store.rows(
            "SELECT 1 FROM records WHERE kind='native_recipe_authorization' AND id=?",
            (project + ":" + digest(specification),),
        ):
            raise Blocked("Only an owner-pinned native test recipe may run")
        spec = tool_testing.validate(specification["suite"])
        pinned = {}
        for name in spec["programs"].get("original", {}).get("files", []):
            pinned[name] = artifacts.add(
                tool_testing.read_file(root, name), name, project, "protected"
            )["id"]
        suite = artifacts.add(
            canonical({"spec": spec, "originals": pinned}),
            "test-suite.json",
            project,
            "protected",
        )
        return {
            "scope": "native_tool_tests",
            "suite_artifact": suite["id"],
            "checks": [
                {
                    "kind": "native_tool_tests",
                    "candidate_files": spec["programs"]["candidate"]["files"],
                    "case_count": len(spec["cases"]),
                    "repeats": spec["repeats"],
                    "platforms": spec["platforms"],
                    "claim": "Trusted native execution; sampled streams/exit/selected files, not all-input equivalence",
                }
            ],
        }

    def verify(self, root, contract, artifacts, project, context):
        self.require_permission(project)
        value = json.loads(
            artifacts.read(contract["suite_artifact"], "evaluator", project)
        )
        spec = value["spec"]
        # No worker can replace the original or rewrite the pinned commands/cases.
        original_files = {
            name: artifacts.read(key, "evaluator", project)
            for name, key in value["originals"].items()
        }
        candidate_files = {
            name: tool_testing.read_file(root, name)
            for name in spec["programs"]["candidate"]["files"]
        }
        # Separate names keep original and candidate snapshots unambiguous.
        if set(original_files) & set(candidate_files):
            raise Conflict(
                "Original and candidate native recipes must use separate input paths"
            )
        result = tool_testing.execute(
            root,
            spec,
            allow_native=True,
            compiler=context.config.get("foundations", {}).get("c_compiler"),
            cancel=context.cancel,
            retained_files={**original_files, **candidate_files},
        )
        self.require_permission(project)
        evidence = artifacts.add(
            canonical(result), "native-test-observations.json", project, "protected"
        )
        result_hashes = {
            name: hashlib.sha256(data).hexdigest()
            for name, data in candidate_files.items()
        }
        return {
            "passed": result["passed"],
            "scope": "native_tool_tests",
            "execution_status": result["status"],
            "case_count": len(result.get("cases", [])),
            "failed_cases": [
                r["id"] for r in result.get("cases", []) if not r["passed"]
            ],
            "candidate_hashes": result_hashes,
            "observations_artifact": evidence["id"],
            "reason": (
                "Native sampled observations matched"
                if result["passed"]
                else "Native tests did not pass; inspect retained observations"
            ),
        }

    def recheck(self, root, result):
        for name, expected in result.get("candidate_hashes", {}).items():
            if (
                hashlib.sha256(tool_testing.read_file(root, name)).hexdigest()
                != expected
            ):
                raise Conflict("Candidate changed during native testing")
