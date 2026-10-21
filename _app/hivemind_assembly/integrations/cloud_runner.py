"""Standalone Codespaces worker. Receives explicit files; retains results for reconnection."""

import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import subprocess
import sys
import time


TOKEN_PATTERNS = (
    r"gh[pousr]_[A-Za-z0-9]{20,255}",
    r"github_pat_[A-Za-z0-9_]{20,255}",
    r"(?i)(authorization:\s*(?:bearer|token|basic)\s+)[^\s]+",
    r"(?i)(password=)[^\s&]+",
)


def scrub(text):
    """Remove token-shaped values from output returned to the project."""
    for value in {os.environ.get(k, "") for k in ("GITHUB_TOKEN", "GH_TOKEN")}:
        if len(value) >= 8:
            text = text.replace(value, "[redacted]")
    for pattern in TOKEN_PATTERNS:
        text = re.sub(pattern, lambda m: (m.group(1) if m.lastindex else "") + "[redacted]", text)
    return text


def main():
    request = json.loads(sys.stdin.read(24 * 1024 * 1024))
    job = request["id"]
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", job):
        raise ValueError("Invalid job ID")
    root = Path.home() / ".hivemind-assembly-jobs" / job
    result_file = root / "result.json"
    action = request.get("action", "run")
    if result_file.exists() and action in ("run", "status"):
        print(result_file.read_text())
        return
    if action == "status":
        state = {"status": "unknown", "id": job}
        if (root / "state.json").exists():
            state = json.loads((root / "state.json").read_text())
        print(json.dumps(state))
        return
    if action == "probe":
        gpu = shutil.which("nvidia-smi")
        output = ""
        if gpu:
            r = subprocess.run(
                [gpu, "--query-gpu=name,memory.total", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            output = r.stdout.strip() if r.returncode == 0 else ""
        print(
            json.dumps(
                {
                    "os": sys.platform,
                    "cpu_count": os.cpu_count(),
                    "gpu": output or None,
                    "python": sys.version.split()[0],
                    "tools": {
                        x: shutil.which(x)
                        for x in (
                            "git",
                            "cc",
                            "gcc",
                            "clang",
                            "c++",
                            "cmake",
                            "make",
                            "ninja",
                            "python3",
                            "node",
                            "java",
                            "nvidia-smi",
                        )
                    },
                }
            )
        )
        return
    if action == "cancel":
        root.mkdir(parents=True, exist_ok=True)
        (root / "cancel").touch()
        print(json.dumps({"id": job, "status": "cancel_requested"}))
        return
    try:
        root.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        print(
            json.dumps(
                {
                    "id": job,
                    "status": "uncertain",
                    "reason": "Job already exists; inspect status instead of replaying",
                }
            )
        )
        return
    workspace = root / "workspace"
    workspace.mkdir()

    def save(path, value):
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value))
        temporary.replace(path)

    save(
        root / "state.json",
        {"id": job, "status": "running", "request_hash": request["request_hash"]},
    )
    try:
        for name, encoded in request["files"].items():
            path = PurePosixPath(name)
            if (
                path.is_absolute()
                or any(p in (".", "..", ".git") for p in path.parts)
                or str(path) != name
                or "\\" in name
            ):
                raise ValueError("Invalid file path")
            target = workspace / name
            target.parent.mkdir(parents=True, exist_ok=True)
            data = base64.b64decode(encoded, validate=True)
            if hashlib.sha256(data).hexdigest() != request["hashes"][name]:
                raise ValueError("File snapshot hash mismatch")
            target.write_bytes(data)
        requirements = request.get("requires", {})
        if requirements.get("gpu"):
            gpu = shutil.which("nvidia-smi")
            if (
                not gpu
                or subprocess.run(
                    [gpu, "-L"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                ).returncode
            ):
                raise ValueError("Required GPU is unavailable on this runner")
        if any(not shutil.which(tool) for tool in requirements.get("tools", [])):
            raise ValueError("Required tool is unavailable on this runner")
        env = {
            k: v
            for k, v in os.environ.items()
            if k in ("PATH", "HOME", "LANG", "JAVA_HOME")
        }
        # No git credential helpers or global/system git config: model-authored
        # commands must not be able to ask the Codespace for its GitHub token.
        env.update(
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_TERMINAL_PROMPT="0",
            GIT_ASKPASS="",
            SSH_ASKPASS="",
        )
        started = time.monotonic()
        records = []
        for index, argv in enumerate(request["commands"]):
            log = root / f"command-{index}.log"
            state = "completed"
            with log.open("wb") as out:
                proc = subprocess.Popen(
                    argv,
                    cwd=workspace,
                    stdin=subprocess.DEVNULL,
                    stdout=out,
                    stderr=subprocess.STDOUT,
                    env=env,
                    start_new_session=True,
                )
                try:
                    while proc.poll() is None:
                        if (root / "cancel").exists():
                            state = "cancelled"
                        elif time.monotonic() - started > request["timeout"]:
                            state = "timeout"
                        elif log.stat().st_size > 4 * 1024 * 1024:
                            state = "output_limit"
                        if state != "completed":
                            break
                        time.sleep(0.1)
                finally:
                    # Also terminate descendants that survived the main process.
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    proc.wait()
            text = scrub(log.read_bytes()[-512000:].decode("utf-8", errors="replace"))
            records.append(
                {
                    "argv": argv,
                    "status": state,
                    "exit_code": proc.returncode,
                    "output": text,
                }
            )
            if state != "completed" or proc.returncode != 0:
                break
        result = {
            "id": job,
            "request_hash": request["request_hash"],
            "status": "completed",
            "passed": len(records) == len(request["commands"])
            and all(
                r["status"] == "completed" and r["exit_code"] == 0 for r in records
            ),
            "commands": records,
            "elapsed": time.monotonic() - started,
            "outputs": {},
        }
        total = 0
        for name in request.get("outputs", []):
            path = workspace / name
            if (
                not path.resolve().is_relative_to(workspace.resolve())
                or path.is_symlink()
            ):
                raise ValueError("Output leaves workspace")
            if not path.is_file():
                continue
            total += path.stat().st_size
            if total > 8 * 1024 * 1024:
                raise ValueError("Output files exceed 8 MiB")
            result["outputs"][name] = base64.b64encode(path.read_bytes()).decode()
    except Exception as error:
        result = {
            "id": job,
            "request_hash": request["request_hash"],
            "status": "failed",
            "passed": False,
            "error": str(error),
        }
    save(result_file, result)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
