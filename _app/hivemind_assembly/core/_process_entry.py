"""Cooperative native launcher; Windows job assignment and Unix parent monitoring."""

import json
import os
import signal
from pathlib import Path
import subprocess
import sys
import time

if __name__ == "__main__":
    meta = Path(sys.argv[1])
    request = json.loads((meta / "request.json").read_text(encoding="utf-8"))
    deadline = time.monotonic() + 10
    while not (meta / "start").exists():
        if time.monotonic() >= deadline or (
            os.name != "nt" and os.getppid() != request["parent_pid"]
        ):
            raise SystemExit(124)
        time.sleep(0.01)
    process = subprocess.Popen(request["argv"], cwd=request["cwd"])
    while process.poll() is None:
        if os.name != "nt" and os.getppid() != request["parent_pid"]:
            os.killpg(os.getpid(), signal.SIGKILL)
        time.sleep(0.02)
    (meta / "result.json").write_text(
        json.dumps({"exit_code": process.returncode}), encoding="utf-8"
    )
