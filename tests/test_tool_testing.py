import os
import shutil
import sys
import time
import subprocess
from pathlib import Path

import pytest
from hivemind_assembly.core.tool_testing import execute, validate
from hivemind_assembly.core.common import Blocked, ContractError, Conflict
from hivemind_assembly.core.native_process import run
from hivemind_assembly.core.test_acceptance import NativeTestAcceptance
from hivemind_assembly.core.acceptance import Acceptance
from hivemind_assembly.core.controller import Controller
from hivemind_assembly.core.broker import Broker


def suite(original=True):
    programs = {
        "candidate": {"files": ["candidate.py"], "argv": ["{python}", "candidate.py"]}
    }
    if original:
        programs["original"] = {
            "files": ["original.py"],
            "argv": ["{python}", "original.py"],
        }
    return {
        "version": 1,
        "programs": programs,
        "output_paths": ["result.bin"],
        "cases": [
            {
                "id": "binary-input",
                "args": ["suffix"],
                "stdin_hex": "00ff01",
                "files": {"input.bin": "616263"},
                "expected": {
                    "exit_code": 0,
                    "stdout_hex": b"00ff01\n".hex(),
                    "stderr_hex": "",
                    "files": {"result.bin": b"abcsuffix".hex()},
                },
            }
        ],
    }


SOURCE = """import sys
from pathlib import Path
sys.stdout.buffer.write(sys.stdin.buffer.read().hex().encode()+b"\\n")
Path('result.bin').write_bytes(Path('input.bin').read_bytes()+sys.argv[1].encode())
"""


def test_native_differential_and_mutant(tmp_path):
    for name in ("original.py", "candidate.py"):
        (tmp_path / name).write_text(SOURCE)
    with pytest.raises(Blocked):
        execute(tmp_path, suite())
    result = execute(tmp_path, suite(), allow_native=True)
    assert result["passed"] and result["cases"][0]["repeatable"]
    (tmp_path / "candidate.py").write_text(
        SOURCE.replace("+'suffix'", "+'bad'").replace(
            "sys.argv[1].encode()", 'b"wrong"'
        )
    )
    assert not execute(tmp_path, suite(), allow_native=True)["passed"]


def test_repeatability_crash_and_output_limits(tmp_path):
    (tmp_path / "original.py").write_text("import os;print(os.urandom(20).hex())")
    (tmp_path / "candidate.py").write_text('print("constant")')
    spec = suite()
    del spec["cases"][0]["expected"]
    result = execute(tmp_path, spec, allow_native=True)
    assert not result["passed"] and not result["cases"][0]["repeatable"]
    result = run(
        [sys.executable, "-c", 'print("X"*20000)'], tmp_path, output_limit=1024
    )
    assert result["status"] == "output_limit" and len(result["stdout_hex"]) == 2048


def test_process_timeout_tree_and_no_ambient_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("HA_SECRET_TOKEN", "private-value")
    result = run(
        [sys.executable, "-c", 'import os;print(os.getenv("HA_SECRET_TOKEN"))'],
        tmp_path,
    )
    assert bytes.fromhex(result["stdout_hex"]).strip() == b"None"
    marker = tmp_path / "orphan.txt"
    child = (
        "import time;from pathlib import Path;time.sleep(0.8);Path("
        + repr(str(marker))
        + ').write_text("leaked")'
    )
    parent = (
        'import subprocess,sys,time;subprocess.Popen([sys.executable,"-c",'
        + repr(child)
        + "]);time.sleep(20)"
    )
    start = time.monotonic()
    result = run([sys.executable, "-c", parent], tmp_path, timeout=0.2)
    assert result["status"] == "timeout" and time.monotonic() - start < 5
    time.sleep(0.9)
    assert not marker.exists()


def test_native_children_stop_when_controller_exits(tmp_path):
    ready = tmp_path / "ready"
    leaked = tmp_path / "leaked"
    child = f"from pathlib import Path;import time;Path({str(ready)!r}).touch();time.sleep(1.0);Path({str(leaked)!r}).touch()"
    package = str(Path(__file__).resolve().parents[1] / "_app")
    parent = f"""import sys,threading,time,os
sys.path.insert(0, {package!r})
from pathlib import Path
from hivemind_assembly.core.native_process import run
threading.Thread(target=lambda:run([sys.executable,'-c',{child!r}],{str(tmp_path)!r},timeout=20),daemon=True).start()
deadline=time.monotonic()+5
while not Path({str(ready)!r}).exists():
 if time.monotonic()>deadline: os._exit(2)
 time.sleep(0.01)
os._exit(0)
"""
    assert subprocess.run([sys.executable, "-c", parent], timeout=8).returncode == 0
    time.sleep(1.2)
    assert not leaked.exists()


def test_general_tool_against_installed_gzip(tmp_path):
    import gzip

    original = shutil.which("gzip")
    if not original or os.name == "nt":
        pytest.skip("Native Unix gzip oracle unavailable")
    shutil.copyfile(original, tmp_path / "original")
    (tmp_path / "recovered.py").write_text(
        "import gzip,sys;sys.stdout.buffer.write(gzip.decompress(sys.stdin.buffer.read()))"
    )
    cases = []
    for i, data in enumerate((b"", bytes(range(256)), b"reconstructed utility\n" * 20)):
        cases.append(
            {
                "id": str(i),
                "stdin_hex": gzip.compress(data, mtime=0).hex(),
                "expected": {
                    "exit_code": 0,
                    "stdout_hex": data.hex(),
                    "stderr_hex": "",
                    "files": {},
                },
            }
        )
    spec = {
        "version": 1,
        "programs": {
            "original": {"files": ["original"], "argv": ["original", "-dc"]},
            "candidate": {
                "files": ["recovered.py"],
                "argv": ["{python}", "recovered.py"],
            },
        },
        "cases": cases,
    }
    assert execute(tmp_path, spec, allow_native=True)["passed"]


def test_native_compiled_reconstruction(tmp_path):
    compiler = (
        os.environ.get("HA_TEST_CLANG") or shutil.which("clang") or shutil.which("gcc")
    )
    if not compiler:
        pytest.skip("Native C compiler unavailable")
    (tmp_path / "original.c").write_text(
        '#include <stdio.h>\n#ifdef _WIN32\n#include <io.h>\n#include <fcntl.h>\n#define BINARY _setmode(_fileno(stdout),_O_BINARY)\n#else\n#define BINARY ((void)0)\n#endif\nint main(void){BINARY;int x=0;while(scanf("%d",&x)==1)printf("%d\\n",x*3+1);return 0;}'
    )
    (tmp_path / "candidate.c").write_text(
        '#include <stdio.h>\n#ifdef _WIN32\n#include <io.h>\n#include <fcntl.h>\n#define BINARY _setmode(_fileno(stdout),_O_BINARY)\n#else\n#define BINARY ((void)0)\n#endif\nint main(void){BINARY;int v;while(scanf("%d",&v)==1)printf("%d\\n",v+v+v+1);return 0;}'
    )
    spec = {
        "version": 1,
        "programs": {
            kind: {
                "files": [kind + ".c"],
                "build": [["{cc}", kind + ".c", "-o", "run.exe"]],
                "argv": ["run.exe"],
            }
            for kind in ("original", "candidate")
        },
        "cases": [
            {
                "id": "integers",
                "stdin_hex": b"-100\n0\n77\n".hex(),
                "expected": {
                    "exit_code": 0,
                    "stdout_hex": b"-299\n1\n232\n".hex(),
                    "stderr_hex": "",
                    "files": {},
                },
            }
        ],
    }
    result = execute(tmp_path, spec, allow_native=True, compiler=compiler)
    assert result["passed"], result
    (tmp_path / "candidate.c").write_text(
        (tmp_path / "candidate.c").read_text().replace("v+v+v+1", "v+v+v+2")
    )
    assert not execute(tmp_path, spec, allow_native=True, compiler=compiler)["passed"]


def test_protected_native_acceptance_and_revocation(store):
    c = Controller(store)
    broker = Broker(c, {})  # No reverse-engineering domain required.
    task = store.create_project("native", "Reconstruct a utility", paused=True)
    root = broker.workspace(task["id"])
    for name in ("original.py", "candidate.py"):
        (root / name).write_text(SOURCE)
    spec = {"scope": "native_tool_tests", "suite": suite()}
    verifier = NativeTestAcceptance(store)
    verifier.allow(task["project_id"], True)
    with pytest.raises(Blocked, match="owner-pinned"):
        Acceptance(c, broker).configure(task["id"], spec)
    verifier.authorize_recipe(task["project_id"], spec)
    Acceptance(c, broker).configure(task["id"], spec)
    (root / "original.py").write_text('raise RuntimeError("oracle replaced")')
    store.state(task["id"], "queued")
    epoch = c.acquire(task["id"], "worker.opus")
    c.brief(
        task["id"],
        {"revision": 0},
        {"procedure": "test", "acceptance": "Pinned sampled results must match"},
        {"critical_gaps": []},
        [],
    )
    result = broker.execute(
        {
            "id": "native-check",
            "task_id": task["id"],
            "owner": "worker.opus",
            "epoch": epoch,
            "revision": 0,
            "tool": "test_programs",
            "args": {},
        }
    )
    assert result["passed"]
    with pytest.raises(Blocked, match="Protected"):
        broker.artifacts.read(
            result["observations_artifact"], "worker", task["project_id"]
        )
    verifier.allow(task["project_id"], False)
    with pytest.raises(Blocked, match="Owner"):
        Acceptance(c, broker).evaluate(
            store.task(task["id"]),
            {"result_operations": ["native-check"], "summary": "done"},
        )
    verifier.allow(task["project_id"], True)
    accepted = Acceptance(c, broker).evaluate(
        store.task(task["id"]),
        {"result_operations": ["native-check"], "summary": "done"},
    )
    assert accepted["passed"] and store.task(task["id"])["status"] == "accepted"
    (root / "candidate.py").write_text("different")
    with pytest.raises(Conflict, match="changed"):
        verifier.recheck(root, result)


@pytest.mark.parametrize(
    "name",
    ["../escape", "/absolute", "a\\b", "file:stream", "CON.txt", "trailing.", "a/../b"],
)
def test_nonportable_paths_rejected(name):
    spec = suite()
    spec["programs"]["candidate"]["files"] = [name]
    with pytest.raises(ContractError):
        validate(spec)
