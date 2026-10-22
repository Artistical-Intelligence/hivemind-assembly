"""Run with the extracted release's embedded Python, never the CI Python."""

import asyncio
import json
import shutil
import threading
import sys
from pathlib import Path

release, data, phase = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]

import sqlite3

# The launcher must replace Python 3.12.10's SQLite 3.49.1 (WAL-reset corruption bug).
version = tuple(int(part) for part in sqlite3.sqlite_version.split("."))
assert version >= (3, 51, 3), "Bundled runtime still uses SQLite " + sqlite3.sqlite_version
sys.path.insert(0, str(release / "_app"))
from hivemind_assembly.application.app import Application, make_server
from hivemind_assembly.application.project_checks import starter, run_checks
from hivemind_assembly.core.backups import snapshot, restore


def check_packaged_mcp(app, task_id):
    from mcp import Client, StdioServerParameters

    cfg = app.connections.settings()
    cfg.update(enabled=True, projects=[app.store.task(task_id)["project_id"]])
    app.connections.save(cfg)
    server = make_server(app)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    async def exercise():
        entry = app.connections.client_config()["mcpServers"]["hivemind-assembly"]
        assert Path(entry["command"]) == Path(sys.executable)
        async with Client(
            StdioServerParameters(command=entry["command"], args=entry["args"])
        ) as client:
            result = await client.call_tool(
                "ha_read_file", {"task": task_id, "path": "notes.txt"}
            )
            assert not result.is_error
            assert (
                result.structured_content["text"] == "Keep across a drop-in update.\n"
            )

    try:
        asyncio.run(exercise())
    finally:
        server.shutdown()
        server.server_close()


app = Application(data)
try:
    compiler = shutil.which("clang") or shutil.which("cc")
    if not compiler:
        raise RuntimeError("Packaged frame replay verification requires a C compiler")
    app.config["foundations"]["c_compiler"] = compiler
    if phase == "prepare":
        task = starter(app, "registers", "packaged_windows_starter")
        app.workspace.write(task["id"], "notes.txt", "Keep across a drop-in update.\n")
        app.store.put("package_probe", "preserve", {"task": task["id"]})
        assert run_checks(app, task["id"])["result"]["passed"]
        native = starter(app, "native_python", "packaged_native_starter", True)
        assert run_checks(app, native["id"])["passed"]
        frames = starter(app, "native_frames", "packaged_frame_starter", True)
        assert run_checks(app, frames["id"])["passed"]
        app.store.put("package_probe", "frames", {"task": frames["id"]})
        windows = starter(app, "program_windows", "packaged_pe_starter")
        assert run_checks(app, windows["id"])["result"]["passed"]
        app.store.put("package_probe", "windows", {"task": windows["id"]})
        emulated = starter(app, "program_frames", "packaged_emulated_frames")
        assert run_checks(app, emulated["id"])["result"]["passed"]
        assert app.action("/api/project/captures", {"task": emulated["id"]})["passed"]
        app.store.put("package_probe", "emulated", {"task": emulated["id"]})
        check_packaged_mcp(app, task["id"])
    else:
        record = app.store.get("package_probe", "preserve")
        assert (
            app.workspace.read(record["task"], "notes.txt")["text"]
            == "Keep across a drop-in update.\n"
        )
        assert run_checks(app, record["task"])["result"]["passed"]
        windows = app.store.get("package_probe", "windows")
        assert run_checks(app, windows["task"])["result"]["passed"]
        frames = app.store.get("package_probe", "frames")
        assert run_checks(app, frames["task"])["passed"]
        assert app.action("/api/native-tests/results", {"task": frames["task"]})["passed"]
        emulated = app.store.get("package_probe", "emulated")
        assert run_checks(app, emulated["task"])["result"]["passed"]
        check_packaged_mcp(app, record["task"])
        backup = data.parent / "package-backup.zip"
        snapshot(app.store, backup)
finally:
    app.close()
if phase == "verify-update":
    destination = data.parent / "restored data"
    restore(backup, destination)
    restored = Application(destination)
    try:
        restored.config["foundations"]["c_compiler"] = compiler
        assert (
            restored.workspace.read(record["task"], "notes.txt")["text"]
            == "Keep across a drop-in update.\n"
        )
        assert run_checks(restored, record["task"])["result"]["passed"]
        assert run_checks(restored, frames["task"])["passed"]
        assert run_checks(restored, windows["task"])["result"]["passed"]
        assert run_checks(restored, emulated["task"])["result"]["passed"]
        assert restored.action("/api/project/captures", {"task": emulated["task"]})["passed"]
    finally:
        restored.close()
print(json.dumps({"phase": phase, "passed": True, "runtime": sys.executable}))
