"""Reusable, bounded specialist execution with no shell or model inference."""

import importlib.metadata
import json
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


def function_call(args):
    from .call_images import execute, ABIS

    if set(args) - {"machine_hex", "abi", "case"}:
        raise ContractError("Unknown function-call workflow argument")
    code = args.get("machine_hex")
    if not isinstance(code, str) or not 1 <= len(bytes.fromhex(code)) <= 16384:
        raise ContractError("Function workflow requires 1–16384 code bytes")
    abi = args.get("abi", "sysv")
    if abi not in ABIS:
        raise ContractError("Unknown function-call ABI")
    image = {
        "abi": abi,
        "entry": 0x10000,
        "segments": [
            {
                "address": 0x10000,
                "size": len(bytes.fromhex(code)),
                "hex": code,
                "permissions": "rx",
            }
        ],
    }
    return execute(image, args.get("case", {}))


def linked_call(args):
    from .call_images import load, execute

    if set(args) - {"image_hex", "symbol", "address", "case"}:
        raise ContractError("Unknown linked-call workflow argument")
    raw = args.get("image_hex")
    if not isinstance(raw, str) or not 1 <= len(raw) <= 180000:
        raise ContractError("Workflow linked image exceeds bounds")
    return execute(
        load(bytes.fromhex(raw), args.get("symbol"), args.get("address")),
        args.get("case", {}),
    )


def runner():
    from hivemind_assembly.learning import workflows

    folder = Path(__file__).parent
    fingerprint = digest(
        {
            "proof": file_hash(folder / "proof.py"),
            "calls": file_hash(folder / "call_images.py"),
            "arm64": file_hash(folder / "arm64.py"),
            "semantics": file_hash(folder / "semantics.py"),
            "cpu_boundary": file_hash(folder / "guest_cpu.py"),
            "image_loader": file_hash(folder / "program.py"),
            "adapter": file_hash(Path(__file__)),
            "workflow": file_hash(Path(workflows.__file__)),
            "dependencies": {
                k: importlib.metadata.version(k)
                for k in ("pypcode", "z3-solver", "unicorn", "pefile", "pyelftools")
            },
        }
    )
    return WorkflowRunner(
        {
            "check_equivalence": equivalence,
            "function_call": function_call,
            "linked_call": linked_call,
        },
        fingerprint,
    )


def optimize_repeated_proofs(store):
    """Execute a real local benchmark of the bounded duplicate-proof optimizer."""
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
    return _optimize(
        store,
        "repeated-region-proofs",
        baseline,
        cases,
        "Repeated identical region proofs within one workflow; four local cases",
    )


def optimize_repeated_calls(store):
    """Measure replay reuse against separate scalar and pointer-call families."""
    step = {
        "tool": "function_call",
        "args": {"machine_hex": {"$input": "code"}, "case": {"$input": "case"}},
    }
    baseline = {
        "steps": [step, step, step],
        "reuse_identical": False,
        "outputs": [{"$step": 2}],
    }
    cases = []
    # Expected results are independently specified arithmetic and memory effects,
    # never obtained by copying the baseline's replay output.
    for name, family, split, code, call, expected in (
        (
            "add",
            "scalar",
            "regression",
            "89f801f0c3",
            {"arguments": [7, 19], "output_bits": 32},
            {"value": 26},
        ),
        (
            "wrap",
            "scalar",
            "regression",
            "89f801f0c3",
            {"arguments": [4294967295, 2], "output_bits": 32},
            {"value": 1},
        ),
        (
            "store",
            "pointer",
            "holdout",
            "8b0701f08907c3",
            {
                "arguments": [{"buffer": "data"}, 5],
                "output_bits": 32,
                "buffers": [{"id": "data", "hex": "07000000"}],
            },
            {"value": 12, "buffers": {"data": "0c000000"}},
        ),
        (
            "offset",
            "pointer",
            "holdout",
            "8b0701f08907c3",
            {
                "arguments": [{"buffer": "data", "offset": 4}, 2],
                "output_bits": 32,
                "buffers": [{"id": "data", "hex": "efbeaddeffffffff"}],
            },
            {"value": 1, "buffers": {"data": "efbeadde01000000"}},
        ),
    ):
        cases.append(
            {
                "id": name,
                "family": family,
                "split": split,
                "inputs": {"code": code, "case": call},
                "expected": [{"status": "completed", "abi_ok": True, **expected}],
            }
        )
    return _optimize(
        store,
        "repeated-function-calls",
        baseline,
        cases,
        "Repeated deterministic function calls; four local scalar/pointer cases",
    )


def _optimize(store, key, baseline, cases, scope):
    service = WorkflowLearning(store, runner())
    existing = store.rows(
        "SELECT id,payload FROM lessons WHERE asset_key=? AND status='active'", (key,)
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
            "scope": scope,
        }
    binding = key + ":" + service.runner.fingerprint
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
    candidate = service.propose(key, baseline, [suite], external_allowed=True)
    result = service.evaluate(candidate, suite)
    if result["eligible"]:
        service.learning.promote(candidate, result["evaluation"], "evaluator")
    return {
        **result,
        "candidate": candidate,
        "promoted": result["eligible"],
        "scope": scope,
    }
