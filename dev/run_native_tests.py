"""Dependency-free entry point for disposable Linux/Windows CI runners."""

import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "_app"))
from hivemind_assembly.core.tool_testing import execute


def main():
    parser = argparse.ArgumentParser(
        description="Run an owner-reviewed native test recipe"
    )
    parser.add_argument("--suite", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--compiler")
    parser.add_argument("--allow-native", action="store_true", required=True)
    args = parser.parse_args()
    path = Path(args.suite)
    if path.stat().st_size > 16 * 1024 * 1024:
        parser.error("Suite exceeds 16 MiB")
    spec = json.loads(path.read_text(encoding="utf-8"))
    try:
        result = execute(
            args.workspace, spec, allow_native=args.allow_native, compiler=args.compiler
        )
    except Exception as error:
        result = {"passed": False, "status": "runner_error", "reason": str(error)}
    result["ci"] = {
        k: os.environ[k]
        for k in (
            "GITHUB_SHA",
            "GITHUB_RUN_ID",
            "GITHUB_RUN_ATTEMPT",
            "RUNNER_OS",
            "RUNNER_ARCH",
        )
        if k in os.environ
    }
    Path(args.output).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "passed": result["passed"],
                "status": result["status"],
                "cases": len(result.get("cases", [])),
                "output": args.output,
            }
        )
    )
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
