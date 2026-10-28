"""Release gate for push early, check later: fails while anything in the repository is
still marked "checks pending" (a CHECKS_STATUS.md row or a STATUS.md line).

Usage: python dev/checks_gate.py [repository folder]
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parents[1])
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "_app"))
from hivemind_assembly.core.checks import LEDGER, MARK, STATUS, parse_ledger  # noqa: E402


def tracked(pattern):
    out = subprocess.run(["git", "ls-files", "--", pattern, "*/" + pattern], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    return [line for line in out.splitlines() if line]


def pending():
    found = []
    ledger = ROOT / LEDGER
    if ledger.is_file():
        found += [f"{LEDGER}: {row['item']} ({row['waiting']})" for row in parse_ledger(ledger.read_text("utf-8", errors="replace"))]
    for rel in tracked(STATUS):
        for line in (ROOT / rel).read_text("utf-8", errors="replace").splitlines():
            if line.startswith(MARK):
                found.append(f"{rel}: {line}")
    return found


if __name__ == "__main__":
    items = pending()
    if items:
        print("Not released: these are still waiting for an independent check:")
        print("\n".join("  " + item for item in items))
        sys.exit(1)
    print("Nothing is waiting for a check.")
