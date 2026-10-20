"""Fresh pinned-foundation installation and real source-known checks for CI.

Uses the product installer and verifier. No account sign-in, model inference,
provider fallback, relaxed REA host checks, or retained credentials are involved.
"""

import argparse
import json
import platform
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "_app"))
from hivemind_assembly.application.setup import install_foundations, PINS
from hivemind_assembly.paths import APP_ROOT


def check(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise ValueError("Use an empty data directory to verify a fresh installation")
    config = json.loads((APP_ROOT / "config/default.json").read_text())
    compiler = shutil.which("clang")
    if compiler:
        config["foundations"]["c_compiler"] = compiler
    config_path = root / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    report = {
        "passed": False,
        "host": platform.platform(),
        "pins": PINS,
        "model_inference": False,
        "fresh_data_directory": True,
    }
    try:
        report["installation"] = install_foundations(root, config_path)
        report["passed"] = (
            report["installation"].get("verification", {}).get("passed") is True
        )
    except Exception as error:
        report["error"] = str(error)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return report["passed"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    raise SystemExit(0 if check(args.root, args.output) else 1)
