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
    if kind not in ("registers", "native_python", "native_frames", "linked_arm64", "program_arm64", "program_windows", "program_frames", "autonomous_program", "project_game"):
        raise ValueError("Unknown starter project")
    if kind in ("native_python", "native_frames") and allow_native is not True:
        raise Blocked(
            "Authorize the supplied native recipes before creating this native starter"
        )
    objective = "Reconstruct the supplied example and verify its behavior independently."
    if kind == "autonomous_program":
        from .reconstruction_trial import OBJECTIVE

        objective = OBJECTIVE
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
                "native_frames": "Frame replay reconstruction",
                "linked_arm64": "AArch64 function reconstruction",
                "program_arm64": "AArch64 program reconstruction",
                "program_windows": "Windows console reconstruction",
                "program_frames": "Emulated frame reconstruction",
                "autonomous_program": "Autonomous reconstruction trial",
                "project_game": "Game project reconstruction",
            }[kind],
            objective,
            paused=True,
            continuation=True,
        )
        app.store.put("starter_request", request_id, {"kind": kind, "task": task["id"]})
    if app.store.rows(
        "SELECT id FROM records WHERE kind='starter_ready' AND id=?", (request_id,)
    ):
        return task
    image = None
    if kind == "autonomous_program":
        from .reconstruction_trial import example

        files, contract, image = example(app)
    elif kind == "project_game":
        files, contract, image = project_game_example(app)
    elif kind == "linked_arm64":
        files, contract, image = arm64_example(app)
    elif kind == "program_arm64":
        files, contract, image = arm64_program_example(app)
    elif kind == "program_frames":
        from .program_frame_example import example

        files, contract, image = example(app)
    elif kind == "program_windows":
        files, contract, image = windows_program_example(app)
    elif kind == "native_frames":
        from pathlib import Path

        example = Path(__file__).resolve().parents[2] / "examples" / "frame_replay"
        files = {name: (example / name).read_text(encoding="utf-8") for name in ("original.py", "candidate.c", "suite.json", "README.txt")}
        contract = {"scope": "native_tool_tests", "suite": json.loads(files["suite.json"])}
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
            name = "original.exe" if kind in ("program_windows", "program_frames") else "original.elf"
            path = Path(folder) / name
            path.write_bytes(image)
            app.workspace.install(task["id"], name, path)
    if kind in ("native_python", "native_frames"):
        from hivemind_assembly.core.test_acceptance import NativeTestAcceptance

        verifier = NativeTestAcceptance(app.store)
        verifier.authorize_recipe(task["project_id"], contract)
        verifier.allow(task["project_id"], True)
    Acceptance(app.controller, app.broker).configure(task["id"], contract)
    app.store.put("starter_ready", request_id, {"task": task["id"]})
    return app.store.task(task["id"])


def project_game_example(app):
    """Hybrid game target: recovered state/audio regions over original rendering."""
    from hivemind_assembly.application import project_targets
    from hivemind_assembly.domains.reverse_engineering.planning import plan

    target = project_targets.target(
        "game", app.broker.jobs, app.config.get("foundations", {}).get("c_compiler", "")
    )
    files = dict(target["files"])
    unit, before, after = target["mutants"]["right_wall"]
    files[unit] = files[unit].replace(before, after)
    development = target["cases"][:2]
    files["development.json"] = json.dumps(development, indent=2) + "\n"
    files["README.txt"] = (
        "A small game loop (original.elf) updates persistent state, renders one 8x6 RGBA "
        "frame per tick to stdout and mixes 16 PCM samples per tick to stderr. The candidate "
        "recovers input, physics, audio and the main loop in C; render_frame is not "
        "recovered and keeps running the original machine code. Run checks: physics passes "
        "its function cases but the composed program diverges at the right wall, so the check "
        "rejects that region and runs the original physics instead. In logic.c, change "
        "'g->x < 0 ? 0 : 6' to 'g->x < 0 ? 0 : 7' and rerun. Protected function and program "
        "cases are sealed outside the workspace. All execution is emulated; this is not a GPU, "
        "window system or game engine.\n"
    )
    contract = {
        "scope": "linux_project",
        "original_path": "original.elf",
        "manifest_path": "project.json",
        "cases": target["cases"],
        "function_checks": target["function_checks"],
        "required_functions": ["apply_input", "step_physics", "mix_audio"],
        "minimum_recovered": 4,
        "plan": plan(target["plan_pages"]),
    }
    return files, contract, target["original"]


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


def windows_program_example(app):
    """A complete PE console program; target execution stays in the emulator."""
    import tempfile
    from pathlib import Path
    from hivemind_assembly.domains.reverse_engineering.windows_program import build

    original = '''int ha_main(void){
  ha_dword n=0,k=0,old=0;long long size=0;
  void *input=CreateFileA("input.bin",0x80000000UL,1,0,3,128,0);
  if(input==(void*)-1||!GetFileSizeEx(input,&size)||size<0||size>8192)return 1;
  unsigned char *b=VirtualAlloc(0,size?size:1,0x3000,4);
  if(!b||!ReadFile(input,b,(ha_dword)size,&n,0)||n!=size)return 1;
  CloseHandle(input);
  for(ha_dword i=0;i<n;i++)b[i]=(unsigned char)(b[i]*3+17);
  if(!VirtualProtect(b,size?size:1,2,&old))return 3;
  void *output=CreateFileA("output.bin",0x40000000UL,0,0,2,128,0);
  if(output==(void*)-1||!WriteFile(output,b,n,&k,0)||k!=n)return 2;
  CloseHandle(output);ha_write(b,n);VirtualFree(b,0,0x8000);ha_error("done",4);return 7;
}'''
    candidate = original.replace("b[i]*3", "b[i]+b[i]+b[i]") + "\n"
    with tempfile.TemporaryDirectory(prefix="ha-windows-example-") as folder:
        root = Path(folder)
        (root / "original.c").write_text(original, encoding="utf-8")
        built = build(
            root,
            {"sources": ["original.c"], "optimization": "O0"},
            app.broker.jobs,
            app.config.get("foundations", {}).get("c_compiler", ""),
        )
        if not built["passed"]:
            raise Blocked("Could not compile Windows example: " + canonical(built))
    manifest = {
        "sources": ["candidate.c"],
        "architecture": "x86_64",
        "optimization": "O2",
    }
    files = {
        "candidate.c": candidate,
        "build.json": json.dumps(manifest, indent=2) + "\n",
        "README.txt": "The original is a real x64 Windows console executable, compiled with Clang/LLD. It sizes input.bin, allocates a private buffer, transforms bytes, protects the buffer read-only, replaces output.bin, prints the result and releases the buffer. Cases include data crossing a page boundary. Each sealed case supplies its own in-memory files; no host files are read or written by replay. Run checks, change +17 to +18, and rerun. Protected originals and inputs survive workspace edits. No Windows DLLs or native target execution are required. CRT, GUI, threads and arbitrary Windows compatibility are outside this contract.\n",
    }
    cases = [
        {"id": "empty", "files": {"input.bin": "", "output.bin": "ffff"}},
        {"id": "text", "files": {"input.bin": b"hivemind\n".hex()}},
        {"id": "all-bytes", "files": {"input.bin": bytes(range(256)).hex()}},
        {"id": "page-crossing", "files": {"input.bin": (bytes(range(256)) * 16 + b"!").hex()}},
    ]
    return (
        files,
        {
            "scope": "windows_program",
            "original_path": "original.exe",
            "manifest_path": "build.json",
            "cases": cases,
        },
        bytes.fromhex(built["pe_hex"]),
    )
