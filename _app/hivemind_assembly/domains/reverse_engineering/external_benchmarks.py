"""Independent holdouts from a public decompilation benchmark (HumanEval-Decompile).

HA's own corpora are generated and verified by HA. To measure whether learning
helps on work HA did not author, this module imports the C subset of
HumanEval-Decompile from LLM4Decompile (MIT licence), pinned by commit and hash.
The data file is fetched on demand and is not vendored.

Each case gives a native trial the original function compiled by this host's
compiler; the benchmark's own test program and dependency source stay sealed in
the protected suite. A candidate passes when the benchmark test, compiled with
the candidate's function, exits successfully: the benchmark's re-executability
criterion. Running candidate code is native execution on this computer, so it
requires the owner's explicit permission, like other native test recipes.
"""

import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path

from hivemind_assembly.core.common import Blocked, ContractError, file_hash, uid

PIN = {
    "name": "HumanEval-Decompile",
    "repository": "https://github.com/albertan017/LLM4Decompile",
    "commit": "85b364bf093eb2ee4f3687cfe38a203fca89f23e",
    "path": "decompile-bench/data/humaneval-decompile.json",
    "sha256": "95bc5ebc6ea64905386b29ca416a0730582c7f00d720c5b977aaf0d3a6058dd7",
    "license": "MIT",
}
KIND = "humaneval_decompile"
OBJECTIVE = (
    "Recover the C source of func0 from the supplied x86-64 object file "
    "(hexadecimal). Return output {source: C defining func0}; standard headers "
    "are already included by the evaluator. Do not include main."
)


def fetch(destination, jobs):
    """Sparse-clone the pinned commit and verify the data file's hash."""
    destination = Path(destination)
    target = destination / Path(PIN["path"]).name
    if target.is_file() and file_hash(target) == PIN["sha256"]:
        return target
    git = shutil.which("git")
    if not git:
        raise Blocked("Git is required to fetch the benchmark")
    with tempfile.TemporaryDirectory(prefix="ha-benchmark-") as tmp:
        stage = Path(tmp) / "repo"
        steps = [
            [git, "init", "-q", str(stage)],
            [git, "-C", str(stage), "remote", "add", "origin", PIN["repository"]],
            [git, "-C", str(stage), "sparse-checkout", "set", str(Path(PIN["path"]).parent)],
            [git, "-C", str(stage), "fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", PIN["commit"]],
            [git, "-C", str(stage), "checkout", "-q", "FETCH_HEAD"],
        ]
        for argv in steps:
            result = jobs.run(uid("benchmark"), argv, Path(tmp), timeout=600)
            if result["status"] != "completed" or result["exit_code"] != 0:
                raise Blocked("Benchmark fetch failed: " + result.get("output", "")[-500:])
        source = stage / PIN["path"]
        if not source.is_file() or file_hash(source) != PIN["sha256"]:
            raise Blocked("Benchmark data does not match the pinned hash")
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return target


def load(path):
    path = Path(path)
    if file_hash(path) != PIN["sha256"]:
        raise Blocked("Benchmark data does not match the pinned hash")
    rows = json.loads(path.read_text("utf-8"))
    return [r for r in rows if r.get("language") == "c"]


def _compiler(compiler=""):
    found = shutil.which(compiler) if compiler else (shutil.which("gcc") or shutil.which("clang"))
    if not found:
        raise Blocked("A native C compiler is required for benchmark cases")
    return found


def compile_object(row, jobs, compiler=""):
    """Compile the benchmark function at its optimization level; return object bytes."""
    executable = _compiler(compiler)
    if row["opt"] not in ("O0", "O1", "O2", "O3"):
        raise ContractError("Unknown benchmark optimization level")
    with tempfile.TemporaryDirectory(prefix="ha-benchmark-") as tmp:
        stage = Path(tmp)
        (stage / "func.c").write_text(row["func_dep"] + "\n" + row["func"], encoding="utf-8")
        result = jobs.run(
            uid("benchmark"),
            [executable, "-" + row["opt"], "-c", "func.c", "-o", "func.o"],
            stage,
            timeout=120,
        )
        if result["status"] != "completed" or result["exit_code"] != 0:
            raise Blocked("Benchmark function did not compile on this host")
        return (stage / "func.o").read_bytes()


def cases(path, jobs, compiler="", optimizations=("O0", "O2"), limit=None):
    """Experiment cases. Families are problems; every fourth problem is holdout,
    so regression and holdout cases never share a problem or a project label."""
    # `index` numbers rows, not problems: the same function appears once per
    # optimization level. Group by source so a problem never spans both splits.
    problem_of = {}
    for row in load(path):
        problem_of.setdefault(row["func"], len(problem_of))
    rows = [r for r in load(path) if r["opt"] in optimizations]
    if limit is not None:
        rows = [r for r in rows if problem_of[r["func"]] < limit]
    result = []
    for row in rows:
        index = problem_of[row["func"]]
        holdout = index % 4 == 0
        obj = compile_object(row, jobs, compiler)
        result.append(
            {
                "id": "humaneval-" + str(index) + "-" + row["opt"],
                "family": "problem-" + str(index),
                "project": ("holdout-" if holdout else "regression-") + str(index // 8),
                "split": "holdout" if holdout else "regression",
                "inputs": {"objective": OBJECTIVE, "object_hex": obj.hex(), "optimization": row["opt"]},
                "expected": {
                    "kind": KIND,
                    "func_dep": row["func_dep"],
                    "test": row["test"],
                    "benchmark": PIN["name"] + "@" + PIN["commit"][:12],
                },
            }
        )
    return result


def evaluate(output, expected, jobs, compiler="", allow_native=False, timeout=10):
    """Benchmark re-executability: the sealed test exits 0 with the candidate."""
    if not isinstance(output, dict) or set(output) != {"source"} or not isinstance(output["source"], str):
        return False
    source = output["source"]
    if len(source) > 64000 or re.search(r"\bmain\s*\(", source):
        return False
    if allow_native is not True:
        raise Blocked("Benchmark evaluation runs candidate code natively; owner permission is required")
    executable = _compiler(compiler)
    with tempfile.TemporaryDirectory(prefix="ha-benchmark-run-") as tmp:
        stage = Path(tmp)
        (stage / "case.c").write_text(
            expected["func_dep"] + "\n" + source + "\n" + expected["test"], encoding="utf-8"
        )
        built = jobs.run(
            uid("benchmark"),
            [executable, "-O0", "case.c", "-o", "case.exe", "-lm"],
            stage,
            timeout=120,
        )
        if built["status"] != "completed" or built["exit_code"] != 0:
            return False
        ran = jobs.run(uid("benchmark"), [str(stage / "case.exe")], stage, timeout=timeout)
        return ran["status"] == "completed" and ran["exit_code"] == 0


def fingerprint(compiler=""):
    return hashlib.sha256(
        (PIN["sha256"] + file_hash(_compiler(compiler)) + file_hash(Path(__file__))).encode()
    ).hexdigest()
