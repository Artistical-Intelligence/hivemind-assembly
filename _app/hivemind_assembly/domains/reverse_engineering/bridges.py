from __future__ import annotations
import json, os, shutil
from pathlib import Path
from hivemind_assembly.paths import APP_ROOT
from hivemind_assembly.core.common import (
    uid,
    atomic_write,
    canonical,
    Blocked,
    ContractError,
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
    def __init__(self, root, jobs, ghidra_home=None):
        self.root = Path(root).resolve() if root else None
        self.ghidra_home = str(Path(ghidra_home).resolve()) if ghidra_home else None
        self.jobs = jobs

    def query(self, target, cwd, args, cancel=None):
        """Typed static queries; no arbitrary native CLI flags or process attach."""
        if set(args) - {
            "path",
            "action",
            "selector",
            "kind",
            "length",
            "offset",
            "limit",
        }:
            raise ContractError("Unknown REA query field")
        action = args.get("action")
        selector = args.get("selector", "")
        options = ["--provider", "ghidra"]
        selector_flags = {
            "decompile": "procedure",
            "function": "procedure",
            "instructions": "procedure",
            "xrefs": "address",
            "search": "pattern",
        }
        positional = {
            "read-bytes",
            "inspect-native-instruction",
            "resolve-native-call-targets",
            "trace-native-values",
        }
        if action in selector_flags or action in positional:
            if (
                not isinstance(selector, str)
                or not 1 <= len(selector) <= 256
                or "\x00" in selector
            ):
                raise ContractError("REA query needs a bounded selector")
            if action in selector_flags:
                options.append("--" + selector_flags[action] + "=" + selector)
            else:
                if selector.startswith("-"):
                    raise ContractError(
                        "Positional REA selectors cannot start with a dash"
                    )
                options.insert(0, selector)
        elif action != "inspect-native-load-image":
            raise ContractError("Unsupported static REA query")
        if action == "search":
            kind = args.get("kind", "strings")
            if kind not in ("strings", "procedures"):
                raise ContractError("REA search kind must be strings or procedures")
            options += ["--kind", kind, "--mode", "literal"]
        if action == "read-bytes":
            length = args.get("length", 256)
            if type(length) is not int or not 1 <= length <= 16384:
                raise ContractError("REA byte read must be 1–16384 bytes")
            options += ["--length", str(length)]
        if action == "trace-native-values":
            offset, limit = args.get("offset", 0), args.get("limit", 200)
            if (
                type(offset) is not int
                or not 0 <= offset <= 20000
                or type(limit) is not int
                or not 1 <= limit <= 1000
            ):
                raise ContractError("Invalid REA trace page bounds")
            options += [
                "--max-depth",
                "3",
                "--max-functions",
                "16",
                "--max-call-sites",
                "256",
                "--max-nodes",
                "5000",
                "--max-edges",
                "10000",
                "--offset",
                str(offset),
                "--limit",
                str(limit),
            ]
        return self.run(action, target, cwd, options, cancel)

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
            "instructions",
            "inspect-native-load-image",
            "read-bytes",
            "inspect-native-instruction",
            "resolve-native-call-targets",
            "trace-native-values",
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
        options = (
            {"environment": {"GHIDRA_INSTALL_DIR": self.ghidra_home}}
            if self.ghidra_home
            else {}
        )
        job = self.jobs.run(
            uid("rea"), argv, cwd, timeout=600, cancel=cancel, **options
        )
        if job["exit_code"] != 0:
            # The final portion can be a large unrelated provider catalogue.
            # Preserve the full bounded output and show its actual error first.
            error_path = Path(cwd) / (uid("rea-error") + ".json")
            atomic_write(error_path, job["output"])
            raise Blocked(
                "REA failed: "
                + job["output"][:3000]
                + "\nFull local output: "
                + str(error_path)
            )
        return {"evidence": json.loads(job["output"]), "elapsed": job["elapsed"]}
