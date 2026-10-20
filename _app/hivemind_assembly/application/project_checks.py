"""Owner-run independent project checks; never substitute for native team acceptance."""

import json
import threading
from hivemind_assembly.core.acceptance import Acceptance
from hivemind_assembly.core.common import Blocked, Conflict, canonical, uid


def run_checks(app, task_id, expected_revision=None):
    service = Acceptance(app.controller, app.broker)
    rows = app.store.rows(
        "SELECT payload FROM records WHERE kind='acceptance_contract' AND id=?",
        (task_id,),
    )
    if not rows:
        raise Blocked("Configure an independent check before running it")
    contract = json.loads(rows[0]["payload"])
    if contract["scope"] == "native_tool_tests":
        return app.run_native_tests(task_id, expected_revision=expected_revision)
    with app.store.lock:
        app.workspace.guard(task_id)
        task = app.store.task(task_id)
        if expected_revision is not None and app.store.project(task["project_id"])["revision"] != expected_revision:
            raise Conflict("Project changed before the requested check started")
        app.store.state(task_id, "queued")
        try:
            epoch = app.controller.acquire(task_id, "user.checking", seconds=1200)
        except BaseException:
            app.store.state(task_id, "paused")
            raise
    try:
        revision = app.store.project(task["project_id"])["revision"]
        app.broker.cancel.setdefault(task_id, threading.Event()).clear()
        if app.shutdown:
            app.broker.cancel[task_id].set()
            raise Blocked("HA is shutting down")
        verifier = service.verifier(contract["scope"])
        result = verifier.verify(
            app.broker.workspace(task_id),
            contract,
            app.broker.artifacts,
            task["project_id"],
            app.broker.context(task_id),
        )
        with app.store.tx() as db:
            app.controller._fence(db, task_id, "user.checking", epoch)
            if app.store.project(task["project_id"])["revision"] != revision:
                raise Conflict("Project changed while checks were running")
            verifier.recheck(app.broker.workspace(task_id), result)
        artifact = app.broker.artifacts.add(
            canonical(result), "manual-check.json", task["project_id"], "protected"
        )
        report = {
            "task": task_id,
            "revision": revision,
            "artifact": artifact["id"],
            "result": result,
            "task_accepted": False,
        }
        app.store.put("manual_check:" + task_id, uid("check"), report)
        app.store.event(
            task_id,
            "manual_check_finished",
            {
                "passed": result.get("passed", False),
                "artifact": artifact["id"],
                "revision": revision,
            },
        )
        return report
    finally:
        with app.store.tx() as db:
            db.execute(
                "UPDATE tasks SET status=CASE WHEN status='cancelled' THEN status ELSE 'paused' END,owner=NULL,lease_until=0,brief_id=NULL WHERE id=? AND epoch=? AND owner='user.checking'",
                (task_id, epoch),
            )


def starter(app, kind, request_id, allow_native=False):
    import re

    if not isinstance(request_id, str) or not re.fullmatch(
        "[A-Za-z0-9_-]{16,80}", request_id
    ):
        raise ValueError("A stable starter request ID is required")
    if kind not in ("registers", "native_python", "linked_arm64", "program_arm64"):
        raise ValueError("Unknown starter project")
    if kind == "native_python" and allow_native is not True:
        raise Blocked(
            "Authorize the supplied Python recipes before creating this native starter"
        )
    # Retry resumes the same new project instead of creating duplicates.
    rows = app.store.rows(
        "SELECT payload FROM records WHERE kind='starter_request' AND id=?",
        (request_id,),
    )
    if rows:
        retained = json.loads(rows[0]["payload"])
        if retained["kind"] != kind:
            raise Conflict("Starter request already belongs to a different example")
        task = app.store.task(retained["task"])
    else:
        task = app.store.create_project(
            {
                "registers": "Register reconstruction",
                "native_python": "Native tool reconstruction",
                "linked_arm64": "AArch64 function reconstruction",
                "program_arm64": "AArch64 program reconstruction",
            }[kind],
            "Reconstruct the supplied example and verify its behavior independently.",
            paused=True,
            continuation=True,
        )
        app.store.put("starter_request", request_id, {"kind": kind, "task": task["id"]})
    if app.store.rows(
        "SELECT id FROM records WHERE kind='starter_ready' AND id=?", (request_id,)
    ):
        return task
    image = None
    if kind == "linked_arm64":
        files, contract, image = arm64_example(app)
    elif kind == "program_arm64":
        files, contract, image = arm64_program_example(app)
    elif kind == "registers":
        files = {
            "original.hex": "89f801f0\n",
            "candidate.hex": "8d0437\n",
            "README.txt": "The original computes a 32-bit sum. The candidate uses LEA. Run checks, change candidate.hex to 89f829f0 (subtraction), and rerun to see the counterexample. Originals are pinned separately. This proves only the configured register region, not an entire application.\n",
        }
        contract = {
            "scope": "x86_64_register_regions",
            "checks": [
                {
                    "original_path": "original.hex",
                    "candidate_path": "candidate.hex",
                    "original_format": "hex",
                    "candidate_format": "hex",
                    "inputs": ["RDI", "RSI"],
                    "outputs": ["RAX"],
                }
            ],
        }
    else:
        files = {
            "original.py": "import sys\nsys.stdout.buffer.write(bytes((x ^ 0x55) for x in sys.stdin.buffer.read()))\n",
            "candidate.py": "import sys\ndata = sys.stdin.buffer.read()\ntable = bytes(i ^ 85 for i in range(256))\nsys.stdout.buffer.write(data.translate(table))\n",
            "README.txt": "The original transforms bytes with XOR 0x55. The candidate uses a lookup table. Run checks, edit candidate.py, and rerun. Native execution uses this computer. Independent cases and the original are pinned outside the editable workspace.\n",
        }
        suite = {
            "version": 1,
            "programs": {
                key: {"files": [key + ".py"], "argv": ["{python}", key + ".py"]}
                for key in ("original", "candidate")
            },
            "cases": [
                {"id": "empty", "stdin_hex": ""},
                {"id": "text", "stdin_hex": b"hivemind\n".hex()},
                {"id": "bytes", "stdin_hex": bytes(range(256)).hex()},
            ],
            "repeats": 3,
        }
        files["suite.json"] = json.dumps(suite, indent=2) + "\n"
        contract = {"scope": "native_tool_tests", "suite": suite}
    for name, text in files.items():
        app.workspace.write(task["id"], name, text)
    if image is not None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory(prefix="ha-example-image-") as folder:
            path = Path(folder) / "original.elf"
            path.write_bytes(image)
            app.workspace.install(task["id"], "original.elf", path)
    if kind == "native_python":
        from hivemind_assembly.core.test_acceptance import NativeTestAcceptance

        verifier = NativeTestAcceptance(app.store)
        verifier.authorize_recipe(task["project_id"], contract)
        verifier.allow(task["project_id"], True)
    Acceptance(app.controller, app.broker).configure(task["id"], contract)
    app.store.put("starter_ready", request_id, {"task": task["id"]})
    return app.store.task(task["id"])


def arm64_example(app):
    """Compile a source-known ARM original; all target execution is emulated."""
    import tempfile
    from pathlib import Path
    from hivemind_assembly.domains.reverse_engineering.call_images import build

    original = """typedef unsigned long long U;
U recovered(unsigned *p, U count, U salt) {
    U sum = 0;
    for (U i = 0; i < count; ++i) {
        p[i] = (p[i] ^ (unsigned)salt) * 33u;
        sum += p[i];
    }
    return sum;
}
"""
    candidate = """typedef unsigned long long U;
U recovered(unsigned *p, U count, U salt) {
    U sum = 0;
    while (count--) {
        unsigned x = *p ^ (unsigned)salt;
        *p = (x << 5) + x;
        sum += *p++;
    }
    return sum;
}
"""
    with tempfile.TemporaryDirectory(prefix="ha-arm64-example-") as folder:
        root = Path(folder)
        (root / "original.c").write_text(original, encoding="utf-8")
        built = build(
            root,
            {"sources": ["original.c"], "optimization": "O0"},
            "recovered",
            "aapcs64",
            app.broker.jobs,
            app.config.get("foundations", {}).get("c_compiler", ""),
        )
        if not built["passed"]:
            raise Blocked(
                "AArch64 example compilation failed; check the configured Clang/LLD installation: "
                + str(built.get("build"))
            )
    cases = []
    for index, (values, count, salt) in enumerate(
        [
            ([0], 0, 0),
            ([1], 1, 2),
            ([0, 1, 0xFFFFFFFF, 0x80000000], 4, 19),
            ([7, 13, 37], 2, 0xFFFFFFFF),
        ]
    ):
        cases.append(
            {
                "id": "case-" + str(index),
                "arguments": [{"buffer": "data"}, count, salt],
                "buffers": [
                    {
                        "id": "data",
                        "hex": b"".join(v.to_bytes(4, "little") for v in values).hex(),
                    }
                ],
            }
        )
    files = {
        "original.c": original,
        "candidate.c": candidate,
        "manifest.json": json.dumps(
            {"sources": ["candidate.c"], "optimization": "O2"}, indent=2
        )
        + "\n",
        "README.txt": "This source-known AArch64 original transforms a buffer and returns its sum. The candidate is compiled for x86-64. Run checks, replace (x << 5) + x with (x << 4) + x in candidate.c, save, and rerun to see a mismatch. Original bytes and cases are pinned separately. Clang and LLD are required; target code executes only in Unicorn. The check covers declared integer/pointer calls, not a complete application or all possible inputs.\n",
    }
    contract = {
        "scope": "linked_calls",
        "original_path": "original.elf",
        "original_symbol": "recovered",
        "manifest_path": "manifest.json",
        "function": "recovered",
        "candidate_abi": "sysv",
        "cases": cases,
    }
    return files, contract, bytes.fromhex(built["image_hex"])


def arm64_program_example(app):
    """A full static source-known ARM program and an editable x64 reconstruction."""
    import tempfile
    from pathlib import Path
    from hivemind_assembly.domains.reverse_engineering.program import build

    original = """unsigned char state;
int ha_main(void) {
    unsigned char input[32]; long n;
    while ((n = ha_read(input, 32)) > 0) {
        for (long i = 0; i < n; ++i) {
            state = (state * 3 + input[i]) % 251;
            input[i] = state;
        }
        ha_write(input, n);
    }
    return 0;
}
"""
    candidate = original.replace("state * 3", "state + state + state")
    with tempfile.TemporaryDirectory(prefix="ha-arm-program-example-") as folder:
        root = Path(folder)
        (root / "original.c").write_text(original, encoding="utf-8")
        built = build(root, {"sources": ["original.c"], "architecture": "aarch64", "optimization": "O0"}, app.broker.jobs, app.config.get("foundations", {}).get("c_compiler", ""))
        if not built["passed"]:
            raise Blocked("AArch64 program example needs working Clang/LLD: " + str(built.get("build")))
    files = {
        "original.c": original,
        "candidate.c": candidate,
        "manifest.json": json.dumps({"sources": ["candidate.c"], "architecture": "x86_64", "optimization": "O2"}, indent=2) + "\n",
        "README.txt": "The original is a complete static AArch64 Linux program. The editable reconstruction targets x86-64 and processes the same input stream across multiple reads. Run checks, change state + state + state to state + state, save and rerun to see a mismatch. Set architecture to aarch64 in manifest.json to rebuild for ARM. Original bytes and cases remain protected. Target execution is emulated: streams, exit, explicit argv/env and clock only; no ARM filesystem, dynamic loader or OS services.\n",
    }
    contract = {
        "scope": "linux_program", "original_path": "original.elf", "manifest_path": "manifest.json",
        "cases": [{"id": "case-" + str(i), "input_hex": data.hex()} for i, data in enumerate((b"", b"Hivemind Assembly", bytes(range(256)), b"\xff" * 129))],
    }
    return files, contract, bytes.fromhex(built["elf_hex"])
