"""Portable original/candidate and expected-output checks for trusted programs.

Manifests are owner-defined recipes, never model-selected shell commands. Run in
a disposable VM for code which is not trusted with the current host's access.
"""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import sys
import tempfile
import time
from .common import Blocked, ContractError, canonical, digest
from .native_process import run

LIMIT = 2 * 1024 * 1024


def relative(value):
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 240
        or any(c in value for c in ("\\", ":", "\0"))
    ):
        raise ContractError("Test paths must be portable relative paths")
    path = PurePosixPath(value)
    if path.is_absolute() or any(p in ("", ".", "..") for p in value.split("/")):
        raise ContractError("Test path traversal is not allowed")
    if any(
        p.endswith((" ", "."))
        or p.split(".")[0].upper()
        in {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *(f"COM{i}" for i in range(10)),
            *(f"LPT{i}" for i in range(10)),
        }
        for p in path.parts
    ):
        raise ContractError("Test path uses a reserved Windows name")
    return value


def read_file(root, name, limit=32 * LIMIT):
    path = Path(root) / relative(name)
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise ContractError("Test inputs must be regular files without symlinks")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ContractError("Test file exceeds its size limit")
    return data


def hex_bytes(value):
    if not isinstance(value, str) or len(value) > LIMIT * 2:
        raise ContractError("Test bytes require bounded hexadecimal strings")
    try:
        return bytes.fromhex(value)
    except ValueError as error:
        raise ContractError("Invalid hexadecimal test bytes") from error


def argv(value):
    if (
        not isinstance(value, list)
        or not 1 <= len(value) <= 128
        or any(not isinstance(v, str) or "\0" in v or len(v) > 4096 for v in value)
    ):
        raise ContractError("Test commands require bounded argv arrays")
    return value


def validate(spec):
    if not isinstance(spec, dict) or set(spec) - {
        "version",
        "programs",
        "cases",
        "output_paths",
        "diagnostic_paths",
        "repeats",
        "timeout_seconds",
        "platforms",
    }:
        raise ContractError("Unknown test suite fields")
    value = json.loads(canonical(spec))
    if value.get("version") != 1:
        raise ContractError("Expected test suite version 1")
    programs = value.get("programs", {})
    if not isinstance(programs, dict) or set(programs) not in (
        {"candidate"},
        {"candidate", "original"},
    ):
        raise ContractError("Supply candidate and optionally original programs")
    for program in programs.values():
        if not isinstance(program, dict) or set(program) - {"files", "argv", "build"}:
            raise ContractError("Unknown program recipe fields")
        files = program.get("files")
        if not isinstance(files, list) or not 1 <= len(files) <= 128:
            raise ContractError("Each program needs 1–128 explicit files")
        if len(set(x.lower() for x in files if isinstance(x, str))) != len(files):
            raise ContractError("Duplicate/case-colliding input paths")
        for name in files:
            relative(name)
        argv(program.get("argv"))
        build = program.setdefault("build", [])
        if not isinstance(build, list) or len(build) > 8:
            raise ContractError("At most eight build commands")
        for command in build:
            argv(command)
    outputs = value.setdefault("output_paths", [])
    if not isinstance(outputs, list) or len(outputs) > 64:
        raise ContractError("At most 64 observed output files")
    for name in outputs:
        relative(name)
    if len(set(x.lower() for x in outputs)) != len(outputs):
        raise ContractError("Duplicate/case-colliding output paths")
    diagnostics = value.setdefault("diagnostic_paths", [])
    if not isinstance(diagnostics, list) or len(diagnostics) > 16:
        raise ContractError("At most 16 diagnostic files")
    for name in diagnostics:
        relative(name)
    cases = value.get("cases")
    if not isinstance(cases, list) or not 1 <= len(cases) <= 128:
        raise ContractError("Supply 1–128 test cases")
    ids = set()
    for case in cases:
        if not isinstance(case, dict) or set(case) - {
            "id",
            "args",
            "stdin_hex",
            "files",
            "expected",
        }:
            raise ContractError("Unknown case fields")
        if (
            not isinstance(case.get("id"), str)
            or not 1 <= len(case["id"]) <= 120
            or case["id"] in ids
        ):
            raise ContractError("Case IDs must be unique bounded strings")
        ids.add(case["id"])
        args = case.setdefault("args", [])
        if not isinstance(args, list):
            raise ContractError("Case args must be an array")
        argv(["program", *args])
        hex_bytes(case.setdefault("stdin_hex", ""))
        files = case.setdefault("files", {})
        if not isinstance(files, dict) or len(files) > 64:
            raise ContractError("At most 64 case input files")
        for name, content in files.items():
            relative(name)
            hex_bytes(content)
            if any(
                name.lower() == p.lower()
                or name.lower().startswith(p.lower() + "/")
                or p.lower().startswith(name.lower() + "/")
                for program in programs.values()
                for p in program["files"]
            ):
                raise ContractError("Case files cannot replace program inputs")
        if "original" not in programs and "expected" not in case:
            raise ContractError(
                "An expected-output suite needs an oracle for every case"
            )
        if "expected" in case:
            expected = case["expected"]
            if (
                not isinstance(expected, dict)
                or set(expected) != {"exit_code", "stdout_hex", "stderr_hex", "files"}
                or type(expected["exit_code"]) is not int
            ):
                raise ContractError(
                    "Expected results need exact exit, stdout, stderr and observed files"
                )
            hex_bytes(expected["stdout_hex"])
            hex_bytes(expected["stderr_hex"])
            if not isinstance(expected["files"], dict) or set(expected["files"]) != set(
                outputs
            ):
                raise ContractError("Expected files must cover every observed path")
            for content in expected["files"].values():
                if content is not None:
                    hex_bytes(content)
    repeats = value.setdefault("repeats", 2)
    timeout = value.setdefault("timeout_seconds", 30)
    if (
        type(repeats) is not int
        or not 2 <= repeats <= 10
        or type(timeout) not in (int, float)
        or not 0.1 <= timeout <= 300
    ):
        raise ContractError(
            "Use 2–10 repetitions and a 0.1–300 second process deadline"
        )
    platforms = value.setdefault("platforms", ["Linux", "Windows"])
    if (
        not isinstance(platforms, list)
        or not platforms
        or any(p not in ("Linux", "Windows", "Darwin") for p in platforms)
    ):
        raise ContractError("Invalid platform list")
    if len(canonical(value)) > 8 * LIMIT:
        raise ContractError("Suite exceeds 16 MiB")
    return value


def snapshot(root, spec):
    files = {
        name: read_file(root, name)
        for program in spec["programs"].values()
        for name in program["files"]
    }
    if sum(map(len, files.values())) > 128 * LIMIT:
        raise ContractError("Program snapshot exceeds 256 MiB")
    return files


def command(values, root, tools):
    values = list(values)
    if values[0] in tools:
        values[0] = tools[values[0]]
    else:
        name = values[0].removeprefix("./")
        read_file(root, name)
        values[0] = str(Path(root) / name)
        if os.name != "nt":
            Path(values[0]).chmod(0o700)
    return values


def expected_observation(expected):
    return {
        "status": "completed",
        "exit_code": expected["exit_code"],
        "stdout_hex": hex_bytes(expected["stdout_hex"]).hex(),
        "stderr_hex": hex_bytes(expected["stderr_hex"]).hex(),
        "files": {
            p: hashlib.sha256(hex_bytes(v)).hexdigest() if v is not None else None
            for p, v in expected["files"].items()
        },
    }


def execute(
    root,
    specification,
    *,
    allow_native=False,
    compiler=None,
    cancel=None,
    deadline_seconds=900,
    retained_files=None,
):
    if allow_native is not True:
        raise Blocked(
            "Native testing requires owner authorization for this host or a disposable runner"
        )
    spec = validate(specification)
    if platform.system() not in spec["platforms"]:
        return {
            "passed": False,
            "status": "unsupported_platform",
            "platform": platform.system(),
        }
    files = snapshot(root, spec) if retained_files is None else retained_files
    hashes = {p: hashlib.sha256(data).hexdigest() for p, data in files.items()}
    tools = {"{python}": sys.executable}
    if compiler:
        tools["{cc}"] = str(Path(shutil.which(compiler) or compiler).resolve())
    started = time.monotonic()
    deadline = started + min(max(deadline_seconds, 1), 3600)
    results, builds, built_files = [], [], {}
    evidence_bytes = 0
    for case in spec["cases"]:
        runs = {kind: [] for kind in spec["programs"]}
        for repeat in range(spec["repeats"]):
            # Alternate order to reduce timing/order bias; correctness uses every run.
            kinds = list(spec["programs"])
            if repeat % 2:
                kinds.reverse()
            for kind in kinds:
                if (
                    cancel is not None and cancel.is_set()
                ) or time.monotonic() >= deadline:
                    return {
                        "passed": False,
                        "status": (
                            "cancelled"
                            if cancel is not None and cancel.is_set()
                            else "suite_timeout"
                        ),
                        "cases": results,
                        "builds": builds,
                        "input_hashes": hashes,
                    }
                program = spec["programs"][kind]
                with tempfile.TemporaryDirectory(prefix="ha-test-") as temp:
                    stage = Path(temp)
                    if kind not in built_files:
                        for name in program["files"]:
                            path = stage / name
                            path.parent.mkdir(parents=True, exist_ok=True)
                            path.write_bytes(files[name])
                        for build in program["build"]:
                            result = run(
                                command(build, stage, tools),
                                stage,
                                timeout=min(
                                    spec["timeout_seconds"],
                                    max(0.01, deadline - time.monotonic()),
                                ),
                                cancel=cancel,
                            )
                            builds.append({"program": kind, **result})
                            if (
                                result["status"] != "completed"
                                or result["exit_code"] != 0
                            ):
                                return {
                                    "passed": False,
                                    "status": "build_failed",
                                    "builds": builds,
                                    "cases": results,
                                    "input_hashes": hashes,
                                }
                        compiled = {}
                        size = 0
                        for path in stage.rglob("*"):
                            if path.is_symlink():
                                raise ContractError(
                                    "Build outputs cannot contain symlinks"
                                )
                            if path.is_dir():
                                continue
                            name = path.relative_to(stage).as_posix()
                            data = read_file(stage, name)
                            size += len(data)
                            if len(compiled) >= 512 or size > 128 * LIMIT:
                                raise ContractError(
                                    "Built snapshot exceeds file or size bound"
                                )
                            compiled[name] = data
                        built_files[kind] = compiled
                    else:
                        for name, data in built_files[kind].items():
                            path = stage / name
                            path.parent.mkdir(parents=True, exist_ok=True)
                            path.write_bytes(data)
                    for name, content in case["files"].items():
                        path = stage / name
                        if (
                            path.exists()
                            or path.is_symlink()
                            or any(p.is_symlink() for p in path.parents)
                        ):
                            raise ContractError("Case input collides with build output")
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(hex_bytes(content))
                    result = run(
                        command(program["argv"], stage, tools) + case["args"],
                        stage,
                        stdin=hex_bytes(case["stdin_hex"]),
                        timeout=min(
                            spec["timeout_seconds"],
                            max(0.01, deadline - time.monotonic()),
                        ),
                        cancel=cancel,
                    )
                    observed, contents, diagnostics = {}, {}, {}
                    for name in spec["output_paths"]:
                        path = stage / name
                        try:
                            data = (
                                read_file(stage, name, LIMIT)
                                if path.exists() or path.is_symlink()
                                else None
                            )
                            observed[name] = (
                                hashlib.sha256(data).hexdigest()
                                if data is not None
                                else None
                            )
                            contents[name] = data.hex() if data is not None else None
                        except ContractError:
                            result["status"] = "invalid_output_file"
                            observed[name] = None
                    for name in spec["diagnostic_paths"]:
                        try:
                            diagnostics[name] = read_file(stage, name, LIMIT).hex()
                        except ContractError:
                            result["status"] = "invalid_diagnostic_file"
                    row = {
                        **result,
                        "files": observed,
                        "file_contents_hex": contents,
                        "diagnostics_hex": diagnostics,
                    }
                    evidence_bytes += len(canonical(row))
                    if evidence_bytes > 16 * LIMIT:
                        return {
                            "passed": False,
                            "status": "evidence_limit",
                            "cases": results,
                            "builds": builds,
                            "input_hashes": hashes,
                        }
                    runs[kind].append(row)
        comparisons = {
            kind: [
                {
                    k: v
                    for k, v in r.items()
                    if k
                    not in ("elapsed_seconds", "file_contents_hex", "diagnostics_hex")
                }
                for r in rows
            ]
            for kind, rows in runs.items()
        }
        stable = all(all(r == rows[0] for r in rows) for rows in comparisons.values())
        expected = (
            expected_observation(case["expected"])
            if "expected" in case
            else comparisons["original"][0]
        )
        passed = stable and all(
            r.get("status") == "completed"
            and 0 <= r["exit_code"] < 0xC0000000
            and r == expected
            for rows in comparisons.values()
            for r in rows
        )
        results.append(
            {
                "id": case["id"],
                "passed": passed,
                "repeatable": stable,
                "runs": runs,
                "reason": (
                    "matched"
                    if passed
                    else (
                        "nonrepeatable"
                        if not stable
                        else "observation_mismatch_or_execution_failure"
                    )
                ),
            }
        )
    return {
        "passed": all(r["passed"] for r in results),
        "status": "completed",
        "suite_hash": digest(spec),
        "input_hashes": hashes,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cases": results,
        "builds": builds,
        "elapsed_seconds": time.monotonic() - started,
        "claim": "Repeated sampled native observations only; selected files and streams, not all-input equivalence. Native execution is not a security sandbox.",
    }
