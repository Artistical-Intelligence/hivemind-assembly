"""Run with the extracted release's embedded Python, never the CI Python."""

import json
import sys
from pathlib import Path

release, data, phase = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
sys.path.insert(0, str(release / "_app"))
from hivemind_assembly.application.app import Application
from hivemind_assembly.application.project_checks import starter, run_checks
from hivemind_assembly.core.backups import snapshot, restore

app = Application(data)
try:
    if phase == "prepare":
        task = starter(app, "registers", "packaged_windows_starter")
        app.workspace.write(task["id"], "notes.txt", "Keep across a drop-in update.\n")
        app.store.put("package_probe", "preserve", {"task": task["id"]})
        assert run_checks(app, task["id"])["result"]["passed"]
        native = starter(app, "native_python", "packaged_native_starter", True)
        assert run_checks(app, native["id"])["passed"]
    else:
        record = app.store.get("package_probe", "preserve")
        assert (
            app.workspace.read(record["task"], "notes.txt")["text"]
            == "Keep across a drop-in update.\n"
        )
        assert run_checks(app, record["task"])["result"]["passed"]
        backup = data.parent / "package-backup.zip"
        snapshot(app.store, backup)
finally:
    app.close()
if phase == "verify-update":
    destination = data.parent / "restored data"
    restore(backup, destination)
    restored = Application(destination)
    try:
        assert (
            restored.workspace.read(record["task"], "notes.txt")["text"]
            == "Keep across a drop-in update.\n"
        )
        assert run_checks(restored, record["task"])["result"]["passed"]
    finally:
        restored.close()
print(json.dumps({"phase": phase, "passed": True, "runtime": sys.executable}))
