"""Scoped straight-line bit-vector proof over real Ghidra raw P-code."""

from __future__ import annotations
import hashlib, importlib.metadata, threading
from hivemind_assembly.domains.reverse_engineering.semantics import Unsupported

_SOLVER_LOCK = threading.RLock()


def prove(
    original_hex,
    candidate_hex,
    inputs=("RDI", "RSI"),
    outputs=("RAX",),
    timeout_ms=5000,
):
    # Z3's default context is shared; concurrent native tasks must not use it
    # from separate threads at once. Each proof still creates a fresh solver.
    with _SOLVER_LOCK:
        try:
            if not outputs or not 0 < timeout_ms <= 30000:
                raise ValueError(
                    "Explicit observations and a bounded timeout are required"
                )
            for code in (original_hex, candidate_hex):
                if not 1 <= len(bytes.fromhex(code)) <= 4096:
                    raise ValueError("Proof regions must contain 1–4096 bytes")
            return _prove(original_hex, candidate_hex, inputs, outputs, timeout_ms)
        except (KeyError, ValueError, TypeError) as error:
            return {"status": "unsupported", "result": "UNKNOWN", "reason": str(error)}


def _prove(
    original_hex,
    candidate_hex,
    inputs=("RDI", "RSI"),
    outputs=("RAX",),
    timeout_ms=5000,
):
    import pypcode, z3

    if set(inputs) & {"RIP", "EIP", "IP", "AF"} or set(outputs) & {
        "RIP",
        "EIP",
        "IP",
        "AF",
    }:
        return {
            "status": "unsupported",
            "result": "UNKNOWN",
            "reason": "Instruction-pointer effects and auxiliary carry are not modeled by this proof subset",
        }

    zctx = z3.Context()
    ctx = pypcode.Context("x86:LE:64:default")
    initial = {
        name: z3.BitVec(name, ctx.registers[name].size * 8, ctx=zctx) for name in inputs
    }
    assumptions = "Straight-line x86-64 integer register regions; input registers unconstrained; other registers and flags initially zero; no memory, calls, exceptions, FP or vector effects modeled."
    provenance = {
        "original_sha256": hashlib.sha256(bytes.fromhex(original_hex)).hexdigest(),
        "candidate_sha256": hashlib.sha256(bytes.fromhex(candidate_hex)).hexdigest(),
        "inputs": list(inputs),
        "outputs": list(outputs),
        "assumptions": assumptions,
        "solver": z3.get_version_string(),
        "pypcode": importlib.metadata.version("pypcode"),
        "timeout_ms": timeout_ms,
    }

    def run(code):
        slots = {}

        def read(n):
            if n.space.name == "const":
                return z3.BitVecVal(n.offset, n.size * 8, ctx=zctx)
            if n.space.name not in ("register", "unique"):
                raise Unsupported("Proof address space " + n.space.name)
            bs = [
                slots.get((n.space.name, n.offset + i), z3.BitVecVal(0, 8, ctx=zctx))
                for i in range(n.size)
            ]
            return bs[0] if len(bs) == 1 else z3.Concat(*reversed(bs))

        def write(n, v):
            if n.space.name not in ("register", "unique"):
                raise Unsupported("Proof memory output")
            for i in range(n.size):
                slots[(n.space.name, n.offset + i)] = z3.Extract(8 * i + 7, 8 * i, v)

        def width(v, bits):
            return (
                z3.ZeroExt(bits - v.size(), v)
                if v.size() < bits
                else z3.Extract(bits - 1, 0, v) if v.size() > bits else v
            )

        for name, v in initial.items():
            write(ctx.registers[name], v)
        for op in ctx.translate(bytes.fromhex(code), 0x1000).ops:
            name = op.opcode.name
            if name == "IMARK":
                continue
            if op.output is None:
                raise Unsupported("Proof effect " + name)
            vs = [read(n) for n in op.inputs]
            a = vs[0]
            b = vs[1] if len(vs) > 1 else None
            bits = op.output.size * 8
            n = a.size()
            pred = None
            if name in ("COPY", "INT_ZEXT"):
                v = width(a, bits)
            elif name == "INT_SEXT":
                v = z3.SignExt(bits - n, a)
            elif name == "INT_ADD":
                v = a + b
            elif name == "INT_SUB":
                v = a - b
            elif name == "INT_MULT":
                v = a * b
            elif name == "INT_AND":
                v = a & b
            elif name == "INT_OR":
                v = a | b
            elif name == "INT_XOR":
                v = a ^ b
            elif name == "INT_NEGATE":
                v = ~a
            elif name == "INT_2COMP":
                v = -a
            elif name == "INT_EQUAL":
                pred = a == b
            elif name == "INT_NOTEQUAL":
                pred = a != b
            elif name == "INT_LESS":
                pred = z3.ULT(a, b)
            elif name == "INT_LESSEQUAL":
                pred = z3.ULE(a, b)
            elif name == "INT_SLESS":
                pred = a < b
            elif name == "INT_SLESSEQUAL":
                pred = a <= b
            elif name == "INT_CARRY":
                pred = z3.ULT(a + b, a)
            elif name == "INT_SCARRY":
                pred = z3.And((a < 0) == (b < 0), (a + b < 0) != (a < 0))
            elif name == "INT_SBORROW":
                pred = z3.And((a < 0) != (b < 0), (a - b < 0) != (a < 0))
            elif name == "BOOL_NEGATE":
                pred = a == 0
            elif name == "BOOL_AND":
                pred = z3.And(a != 0, b != 0)
            elif name == "BOOL_OR":
                pred = z3.Or(a != 0, b != 0)
            elif name == "BOOL_XOR":
                pred = z3.Xor(a != 0, b != 0)
            elif name == "POPCOUNT":
                v = sum(z3.ZeroExt(bits - 1, z3.Extract(i, i, a)) for i in range(n))
            elif name == "SUBPIECE" and op.inputs[1].space.name == "const":
                v = z3.Extract(
                    op.inputs[1].offset * 8 + bits - 1, op.inputs[1].offset * 8, a
                )
            elif name == "PIECE":
                v = z3.Concat(a, b)
            else:
                raise Unsupported("Proof operation " + name)
            if pred is not None:
                v = z3.If(
                    pred,
                    z3.BitVecVal(1, bits, ctx=zctx),
                    z3.BitVecVal(0, bits, ctx=zctx),
                )
            write(op.output, width(v, bits))
        return {name: read(ctx.registers[name]) for name in outputs}

    try:
        left, right = run(original_hex), run(candidate_hex)
        if not outputs:
            raise Unsupported("No observations selected")
        solver = z3.Solver(ctx=zctx)
        solver.set(timeout=timeout_ms)
        solver.add(z3.Or(*(left[k] != right[k] for k in outputs)))
        result = solver.check()
        if result == z3.unsat:
            return {
                **provenance,
                "status": "region_proved",
                "result": "UNSAT",
                "claim": "Equivalent only for listed outputs under the recorded model and assumptions",
            }
        if result == z3.sat:
            m = solver.model()
            return {
                **provenance,
                "status": "counterexample",
                "result": "SAT",
                "witness": {
                    k: m.eval(v, model_completion=True).as_long()
                    for k, v in initial.items()
                },
            }
        return {
            **provenance,
            "status": "unknown",
            "result": "UNKNOWN",
            "reason": solver.reason_unknown(),
        }
    except (Unsupported, KeyError, ValueError) as e:
        return {
            **provenance,
            "status": "unsupported",
            "result": "UNKNOWN",
            "reason": str(e),
        }
