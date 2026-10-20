"""Reusable, bounded specialist execution with no shell or model inference."""

import importlib.metadata
from pathlib import Path
from hivemind_assembly.core.common import digest, file_hash, ContractError
from hivemind_assembly.learning.workflows import WorkflowRunner, WorkflowLearning
from .proof import prove


def equivalence(args):
    if set(args) - {"original_hex", "candidate_hex", "inputs", "outputs"}:
        raise ContractError("Unknown equivalence workflow arguments")
    for key in ("original_hex", "candidate_hex"):
        value = args.get(key)
        if not isinstance(value, str) or not 1 <= len(bytes.fromhex(value)) <= 4096:
            raise ContractError("Workflow requires bounded machine-code regions")
    for key, default in (("inputs", ["RDI", "RSI"]), ("outputs", ["RAX"])):
        values = args.get(key, default)
        if (
            not isinstance(values, list)
            or not (0 if key == "inputs" else 1) <= len(values) <= 32
            or any(not isinstance(v, str) for v in values)
        ):
            raise ContractError("Workflow requires explicit register lists")
    return prove(
        args["original_hex"],
        args["candidate_hex"],
        tuple(args.get("inputs", ["RDI", "RSI"])),
        tuple(args.get("outputs", ["RAX"])),
    )


def runner():
    from hivemind_assembly.learning import workflows

    folder = Path(__file__).parent
    fingerprint = digest(
        {
            "proof": file_hash(folder / "proof.py"),
            "adapter": file_hash(Path(__file__)),
            "workflow": file_hash(Path(workflows.__file__)),
            "dependencies": {
                k: importlib.metadata.version(k) for k in ("pypcode", "z3-solver")
            },
        }
    )
    return WorkflowRunner({"check_equivalence": equivalence}, fingerprint)


def optimize_repeated_proofs(store):
    """Execute a real local benchmark of the bounded duplicate-proof optimizer."""
    service = WorkflowLearning(store, runner())
    import json

    existing = store.rows(
        "SELECT id,payload FROM lessons WHERE asset_key='repeated-region-proofs' AND status='active'"
    )
    if (
        existing
        and json.loads(existing[0]["payload"]).get("engine")
        == service.runner.fingerprint
    ):
        return {
            "candidate": existing[0]["id"],
            "promoted": True,
            "already_active": True,
        }
    step = {
        "tool": "check_equivalence",
        "args": {
            "original_hex": {"$input": "original"},
            "candidate_hex": {"$input": "candidate"},
        },
    }
    baseline = {"steps": [step, step, step], "reuse_identical": False}
    cases = []
    # Families are separated by arithmetic operation, not random input rows.
    for name, family, split, original, candidate, result in (
        ("add_equal", "add", "regression", "89f801f0", "8d0437", "UNSAT"),
        ("add_wrong", "add", "regression", "89f801f0", "89f829f0", "SAT"),
        ("xor_equal", "xor", "holdout", "89f831f0", "89f031f8", "UNSAT"),
        ("xor_wrong", "xor", "holdout", "89f831f0", "89f809f0", "SAT"),
    ):
        cases.append(
            {
                "id": name,
                "family": family,
                "split": split,
                "inputs": {"original": original, "candidate": candidate},
                "expected": [{"result": result}] * 3,
            }
        )
    binding = "repeated-region-proofs:" + service.runner.fingerprint
    retained = store.rows(
        "SELECT payload FROM records WHERE kind='workflow_suite' AND id=?", (binding,)
    )
    suite = (
        json.loads(retained[0]["payload"])["artifact"]
        if retained
        else service.protect_suite(cases)
    )
    if not retained:
        store.put("workflow_suite", binding, {"artifact": suite})
    candidate = service.propose(
        "repeated-region-proofs", baseline, [suite], external_allowed=True
    )
    result = service.evaluate(candidate, suite)
    if result["eligible"]:
        service.learning.promote(candidate, result["evaluation"], "evaluator")
    return {
        **result,
        "candidate": candidate,
        "promoted": result["eligible"],
        "scope": "Repeated identical region proofs within one workflow; measured on four local cases",
    }
