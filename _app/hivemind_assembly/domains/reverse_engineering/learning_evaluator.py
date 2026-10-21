"""Independent compiler-backed verifier for native reconstruction rollouts."""

import hashlib
from pathlib import Path
from .reconstruction import compile_function, compare_functions, vectors
from hivemind_assembly.core.common import Blocked, digest, file_hash


class FunctionEvaluator:
    def __init__(self, jobs, compiler="", allow_native=None):
        import shutil

        self.jobs = jobs
        # Callable returning the owner's permission for native benchmark runs.
        self.allow_native = allow_native or (lambda: False)
        self.compiler = (
            shutil.which(compiler)
            if compiler
            else (shutil.which("clang") or shutil.which("gcc"))
        )
        if not self.compiler:
            raise Blocked("Native reconstruction evaluation requires Clang or GCC")
        self.fingerprint = digest(
            {
                "lane": "native-function-rollout-v1",
                "compiler": file_hash(self.compiler),
                "sources": {
                    name: file_hash(Path(__file__).with_name(name))
                    for name in (
                        "learning_evaluator.py",
                        "reconstruction.py",
                        "semantics.py",
                        "guest_cpu.py",
                        "external_benchmarks.py",
                    )
                },
            }
        )

    def __call__(self, output, expected):
        if expected.get("kind") == "humaneval_decompile":
            from .external_benchmarks import evaluate

            return evaluate(
                output, expected, self.jobs, "", allow_native=self.allow_native() is True
            )
        if not isinstance(output, dict) or set(output) != {"source"}:
            return False
        result = compile_function(output["source"], "target", self.jobs, self.compiler)
        if not result["passed"]:
            return False
        return compare_functions(
            bytes.fromhex(expected["original_hex"]),
            bytes.fromhex(result["machine_hex"]),
            expected["vectors"],
            expected["output_bits"],
        )["passed"]

    def build_corpus(self, experiments, root):
        import shutil
        from .benchmarks import generate

        available = tuple(name for name in ("gcc", "clang") if shutil.which(name))
        if not available:
            raise Blocked("A compiler is required to prepare native evaluation tasks")
        result = generate(root, compilers=available)
        if result["blocked"]:
            raise Blocked("Compiler corpus did not finish")
        return self.protect_manifest(experiments, root)

    def import_benchmark(self, experiments, root, limit=None):
        """Protect HumanEval-Decompile C cases as an independent holdout corpus."""
        from .external_benchmarks import cases, fetch

        path = fetch(Path(root), self.jobs)
        return experiments.protect(cases(path, self.jobs, limit=limit))

    def protect_manifest(self, experiments, root):
        """Import the independently generated compiler corpus through owner UI.

        Expected source is never delivered to a native conversation. Original
        machine bytes are the problem input; secret vectors remain evaluator-only.
        """
        import json
        from .reconstruction import extract_function
        from hivemind_assembly.core.common import scoped

        root = Path(root)
        manifest = json.loads((root / "manifest.json").read_text())
        cases = []
        for row in manifest["cases"]:
            if row["status"] != "compiled":
                raise Blocked("All corpus compiler variants must be available")
            path = scoped(root, row["object"])
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != row["sha256"]:
                raise Blocked("Corpus object hash changed")
            code = extract_function(data, "target").hex()
            cases.append(
                {
                    "id": row["id"],
                    "family": row["family"],
                    "project": "family-" + row["family"],
                    "split": "holdout" if row["split"] == "holdout" else "regression",
                    "inputs": {
                        "objective": "Recover the behavior of the supplied SysV x86-64 function. Return output {source: freestanding C defining unsigned target(unsigned a,unsigned b)}. No includes or inline assembly.",
                        "original_hex": code,
                        "argument_bits": [32, 32],
                        "output_bits": 32,
                    },
                    "expected": {
                        "original_hex": code,
                        "vectors": vectors([32, 32], row["sha256"]),
                        "output_bits": 32,
                    },
                }
            )
        return experiments.protect(cases)
