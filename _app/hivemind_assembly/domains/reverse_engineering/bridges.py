from __future__ import annotations
import json, os, shutil
from pathlib import Path
from hivemind_assembly.paths import APP_ROOT
from hivemind_assembly.core.common import (
    uid,
    atomic_write,
    canonical,
    Blocked,
    identifier,
)


class GhidraBridge:
    def __init__(self, home, jobs):
        self.home = Path(home).resolve() if home else None
        self.jobs = jobs

    def run(self, root, program, request, binary=None, cancel=None):
        if not self.home:
            raise Blocked("Ghidra installation is not configured")
        headless = (
            self.home
            / "support"
            / ("analyzeHeadless.bat" if os.name == "nt" else "analyzeHeadless")
        )
        if not headless.is_file():
            raise Blocked("Complete Ghidra installation not found")
        identifier(program)
        key = identifier(request["operation_id"])
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        inp = root / (key + ".request.json")
        out = root / (key + ".result.json")
        atomic_write(inp, canonical(request))
        out.unlink(missing_ok=True)
        script = APP_ROOT / "integrations" / "ghidra"
        args = [
            str(headless),
            str(root),
            "Workbench",
            "-scriptPath",
            str(script),
            "-postScript",
            "WorkbenchBridge.java",
            str(inp),
            str(out),
        ]
        if binary:
            args += ["-import", str(Path(binary).resolve())]
        else:
            args += ["-process", program, "-noanalysis"]
        job = self.jobs.run(key, args, root, timeout=600, cancel=cancel)
        if job["exit_code"] != 0 or not out.exists():
            raise Blocked(
                "Ghidra did not produce a durable result: " + job["output"][-3000:]
            )
        result = json.loads(out.read_text())
        if request["action"] == "annotate":
            check = self.run(
                root,
                program,
                {"action": "reconcile", "operation_id": key},
                cancel=cancel,
            )
            if (
                check.get("recorded_payload_hash") != request["payload_hash"]
                or check["revision"] != result["revision"]
            ):
                raise Blocked("Native commit was not confirmed after project reopen")
            result["status"] = "saved"
            result["reopened_and_verified"] = True
        result["execution"] = {"exit_code": job["exit_code"], "elapsed": job["elapsed"]}
        return result


class ReaBridge:
    def __init__(self, root, jobs):
        self.root = Path(root).resolve() if root else None
        self.jobs = jobs

    def run(self, command, target, cwd, args=(), cancel=None):
        allowed = {
            "analyze",
            "decompile",
            "function",
            "search",
            "xrefs",
            "analyze-javascript-application",
            "inspect-managed-artifact",
            "inspect-go-binary",
        }
        if command not in allowed:
            raise Blocked(
                "REA command not in broker capability set; complete native CLI remains available separately"
            )
        if not self.root:
            raise Blocked("REA is not installed")
        entry = self.root / "node_modules" / "rea-agents" / "scripts" / "rea.mjs"
        if not entry.exists():
            entry = self.root / "scripts" / "rea.mjs"
        if not entry.exists():
            raise Blocked("Complete REA package not found")
        node = shutil.which("node")
        if not node:
            raise Blocked("Node.js is required by REA")
        argv = [node, str(entry), command, str(target), *args, "--json"]
        job = self.jobs.run(uid("rea"), argv, cwd, timeout=600, cancel=cancel)
        if job["exit_code"] != 0:
            raise Blocked("REA failed: " + job["output"][-3000:])
        return {"evidence": json.loads(job["output"]), "elapsed": job["elapsed"]}
