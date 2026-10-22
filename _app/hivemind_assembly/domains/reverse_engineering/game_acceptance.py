"""Protected `game_play` acceptance: sealed original, game contract and trajectories.

Preparation pins the original image, the validated game spec and the owner's
trajectories as protected artifacts, after checking that the original plays every
trajectory within the contract. Verification rebuilds the candidate from the
workspace manifest, replays each sealed trajectory on fresh engines for both images,
ends input, and compares every tick with the pinned tolerances. Static ELF games use
the stepping engine, whose streams, exit status and input consumption are tested to
equal batch replay; it also bounds every tick, so a frozen candidate is reported as a
freeze rather than a wall-clock limit. Windows PE games use batch replay. Candidate
rule violations fail unless the original shows the same violation. Workers see
per-case outcomes only; sealed inputs and observations stay in a protected artifact.
"""

import copy
import hashlib
import json

from hivemind_assembly.core import game_spec as gs
from hivemind_assembly.core import game_testing as gt
from hivemind_assembly.core.common import Blocked, Conflict, ContractError, canonical, file_hash, scoped

from .game_machine import image_kind, open_engine

FIELDS = {"scope", "game_path", "original_path", "manifest_path", "trajectories", "rules"}


def _cases(spec, value):
    if not isinstance(value, list) or not 2 <= len(value) <= 64:
        raise ContractError("game_play acceptance requires 2–64 trajectories")
    cases, ids = [], set()
    record = spec["input"]["record_bytes"]
    for item in value:
        if not isinstance(item, dict) or set(item) - {"id", "inputs_hex", "trajectory", "end"}:
            raise ContractError("Trajectories take id, inputs_hex or trajectory, and end")
        case_id = item.get("id")
        if not isinstance(case_id, str) or not gt.REGRESSION_ID.fullmatch(case_id) or case_id in ids:
            raise ContractError("Trajectory IDs must be unique short names")
        ids.add(case_id)
        if ("inputs_hex" in item) == ("trajectory" in item):
            raise ContractError("Give each trajectory exactly one of inputs_hex or trajectory")
        inputs = (
            gs.decode_token(item["trajectory"], spec)
            if "trajectory" in item
            else gs._hex(item["inputs_hex"], "Trajectory inputs")
        )
        if len(inputs) % record or len(inputs) // record > spec["limits"]["max_ticks"]:
            raise ContractError("Trajectories must be whole records within max_ticks")
        end = item.get("end", True)
        if type(end) is not bool:
            raise ContractError("Trajectory end must be boolean")
        cases.append({"id": case_id, "inputs_hex": inputs.hex(), "end": end})
    if len(canonical(cases)) > 2_000_000:
        raise ContractError("Trajectory corpus exceeds bounds")
    return cases


def _session(spec, image, side, cancel):
    return gt.Session(spec, open_engine(image, spec, cancel=cancel), side)


def _build(root, manifest, platform, context):
    compiler = context.config.get("foundations", {}).get("c_compiler", "")
    if platform == "windows":
        from .windows_program import build

        return build(root, manifest, context.jobs, compiler, context.cancel), "pe_hex"
    from .program import build

    return build(root, manifest, context.jobs, compiler, context.cancel), "elf_hex"


class GameAcceptance:
    uses_context = True

    def prepare(self, root, spec, artifacts, project, context):
        if not isinstance(spec, dict) or set(spec) - FIELDS or "trajectories" not in spec:
            raise ContractError("game_play acceptance takes game_path, trajectories and optional original_path, manifest_path and rules")
        game_path = spec.get("game_path", "game.json")
        gs.relative(game_path, "game_path")
        path = scoped(root, game_path)
        if not path.is_file() or path.stat().st_size > 262144:
            raise ContractError("Game spec is missing or exceeds 256 KiB")
        game = gs.validate(json.loads(path.read_text("utf-8")))
        original_path = spec.get("original_path", game.get("original_path"))
        manifest_path = spec.get("manifest_path", game.get("candidate_manifest"))
        if not original_path or not manifest_path:
            raise ContractError("game_play acceptance needs an original image and a candidate build manifest")
        gs.relative(original_path, "original_path")
        gs.relative(manifest_path, "manifest_path")
        scoped(root, manifest_path)
        original = scoped(root, original_path).read_bytes()
        if len(original) > 2_000_000:
            raise Blocked("Original image exceeds bounds")
        if (image_kind(original) == "pe") != (game["platform"] == "windows"):
            raise ContractError("The game spec platform does not match the original image")
        rules = spec.get("rules", True)
        if type(rules) is not bool:
            raise ContractError("rules must be boolean")
        cases = _cases(game, spec["trajectories"])
        for case in cases:
            session = _session(game, original, "original", context.cancel)
            session.feed(bytes.fromhex(case["inputs_hex"]))
            if case["end"]:
                session.end()
            blocking = [p for p in session.problems if p["kind"] in ("crash", "freeze", "limit", "protocol")]
            if blocking:
                diagnostic = artifacts.add(
                    canonical({"case": case["id"], "problems": blocking}),
                    "game-preflight-diagnostic.json",
                    project,
                    "protected",
                )
                raise Blocked(
                    "Original does not play every trajectory within the game contract; protected diagnostic: "
                    + diagnostic["id"]
                )
        pinned = artifacts.add(original, "original-game", project, "protected")
        sealed_spec = artifacts.add(canonical(game), "game-spec.json", project, "protected")
        suite = artifacts.add(canonical(cases), "game-trajectories.json", project, "protected")
        return {
            "scope": spec["scope"],
            "checks": [
                {
                    "candidate_path": manifest_path,
                    "trajectory_count": len(cases),
                    "rules": rules,
                    "original_sha256": pinned["sha256"],
                    "game_sha256": sealed_spec["sha256"],
                }
            ],
            "manifest_path": manifest_path,
            "rules": rules,
            "original_artifact": pinned["id"],
            "original_sha256": pinned["sha256"],
            "spec_artifact": sealed_spec["id"],
            "spec_sha256": sealed_spec["sha256"],
            "cases_artifact": suite["id"],
            "cases_sha256": suite["sha256"],
            "case_count": len(cases),
        }

    def verify(self, root, contract, artifacts, project, context):
        from .program import sources

        original = artifacts.read(contract["original_artifact"], "evaluator", project)
        raw_spec = artifacts.read(contract["spec_artifact"], "evaluator", project)
        raw_cases = artifacts.read(contract["cases_artifact"], "evaluator", project)
        if (
            hashlib.sha256(original).hexdigest() != contract["original_sha256"]
            or hashlib.sha256(raw_spec).hexdigest() != contract["spec_sha256"]
            or hashlib.sha256(raw_cases).hexdigest() != contract["cases_sha256"]
        ):
            raise Conflict("Protected game evidence changed")
        game = gs.validate(json.loads(raw_spec))
        cases = json.loads(raw_cases)
        path = scoped(root, contract["manifest_path"])
        if path.stat().st_size > 128000:
            raise Blocked("Build manifest exceeds bounds")
        manifest = json.loads(path.read_text("utf-8"))
        units = sources(root, manifest)
        checks = [{"candidate_path": contract["manifest_path"], "file_sha256": file_hash(path)}]
        checks.extend({"candidate_path": n, "file_sha256": file_hash(scoped(root, n))} for n in units)
        compiled, key = _build(root, manifest, game["platform"], context)
        if not compiled["passed"]:
            for check in checks:
                check["passed"] = False
            return {"scope": contract["scope"], "passed": False, "checks": checks, "build": compiled, "reason": "Candidate build failed"}
        candidate = bytes.fromhex(compiled.pop(key))
        reports, rows = [], []
        for case in cases:
            if context.cancel.is_set():
                raise Blocked("Acceptance cancelled")
            pair = gt.Pair(
                game,
                _session(game, original, "original", context.cancel),
                _session(game, candidate, "candidate", context.cancel),
            )
            pair.feed(bytes.fromhex(case["inputs_hex"]))
            if case["end"]:
                pair.end()
            report = pair.report()
            findings = [
                f for f in report["findings"] if contract["rules"] or f["kind"] != "invariant"
            ]
            passed = not findings
            reports.append({"id": case["id"], "passed": passed, "report": report})
            rows.append(
                {
                    "id": case["id"],
                    "passed": passed,
                    "outcome": gt.outcome(findings),
                    "first_divergence_tick": (report["divergence"] or {}).get("tick"),
                }
            )
        passed = all(row["passed"] for row in rows)
        for check in checks:
            check["passed"] = passed
        executable = artifacts.add(candidate, "reconstructed-game." + ("exe" if game["platform"] == "windows" else "elf"), project)
        details = artifacts.add(
            canonical({"cases": reports, "game": game["name"]}),
            "game-acceptance-details.json",
            project,
            "protected",
        )
        return {
            "scope": contract["scope"],
            "passed": passed,
            "checks": checks,
            "build": compiled,
            "executable_artifact": executable["id"],
            "protected_details": details["id"],
            "cases": rows,
            "reason": "" if passed else "Sealed game trajectories found divergences or candidate-only problems",
            "claim": "Sealed trajectories replayed on the pinned original and the rebuilt candidate in fresh deterministic engines; every tick compared under the pinned game contract and candidate rules checked against original behavior. Sampled play, not all-input equivalence, GPU or hardware timing.",
        }

    def recheck(self, root, result):
        for check in copy.deepcopy(result["checks"]):
            if "file_sha256" in check and file_hash(scoped(root, check["candidate_path"])) != check["file_sha256"]:
                raise Conflict("Candidate changed before acceptance was committed")
