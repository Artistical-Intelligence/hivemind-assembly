from __future__ import annotations
import json, os, shutil, subprocess, threading, time, urllib.request, zipfile
from pathlib import Path
from hivemind_assembly.core.common import (
    atomic_write,
    canonical,
    file_hash,
    Blocked,
    ContractError,
)

PINS = {
    "hermes": {
        "url": "https://github.com/NousResearch/hermes-agent.git",
        "commit": "c0015464f0f40d52c5702a84cf58e70361f4a04c",
    },
    "rea": {
        "url": "https://github.com/morluto/rea.git",
        "commit": "ca71e91d23672646af917ede8ae82c7fea395341",
        "npm_version": "6.7.0",
    },
    "ghidra": {
        "source": "https://github.com/NationalSecurityAgency/ghidra.git",
        "tag": "Ghidra_12.1.4_build",
        "url": "https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_12.1.4_build/ghidra_12.1.4_PUBLIC_20260921.zip",
        "sha256": "ddac49f903da9d5bac833e5cc79395098b9c33cfd3279be5f31bd00387d2d4db",
        "folder": "ghidra_12.1.4_PUBLIC",
    },
}


class SetupProgress:
    """Progress of the one-step tool installation, as the dashboard shows it.

    Steps are planned with rough weights (about their download size in MB) so the
    overall percentage moves at a sensible rate; downloads HA makes itself also
    report bytes. Time left is a linear estimate from the elapsed time.
    """

    def __init__(self, publish=None):
        self.publish = publish or (lambda state: None)
        self.plan = {}
        self.done = set()
        self.current = None
        self.fraction = 0.0
        self.download_state = None
        self.started = time.monotonic()
        self.lock = threading.Lock()

    def expect(self, label, weight):
        with self.lock:
            self.plan.setdefault(label, max(1, weight))

    def begin(self, label, weight=10):
        with self.lock:
            if self.current:
                self.done.add(self.current)
            self.plan.setdefault(label, weight)
            self.current, self.fraction, self.download_state = label, 0.0, None
        self.emit(force=True)

    def download(self, done, total):
        with self.lock:
            if total and total > 0:
                self.fraction = min(1.0, done / total)
            self.download_state = {"done_bytes": done, "total_bytes": total if total and total > 0 else None}
        self.emit()

    def finish(self):
        with self.lock:
            if self.current:
                self.done.add(self.current)
            self.current, self.fraction, self.download_state = None, 0.0, None
        self.emit(force=True)

    def snapshot(self):
        with self.lock:
            total = sum(self.plan.values()) or 1
            finished = sum(w for label, w in self.plan.items() if label in self.done)
            current = self.plan.get(self.current, 0) * self.fraction if self.current else 0
            fraction = min(1.0, (finished + current) / total)
            elapsed = time.monotonic() - self.started
            remaining = None
            if fraction >= 0.03 and elapsed >= 10:
                remaining = round(elapsed * (1 - fraction) / fraction)
            labels = list(self.plan)
            return {
                "label": self.current,
                "step": labels.index(self.current) + 1 if self.current in labels else len(self.done),
                "steps": len(labels),
                "percent": round(fraction * 100, 1),
                "seconds_left": remaining,
                "download": dict(self.download_state) if self.download_state else None,
            }

    def emit(self, force=False):
        # Publishing only stores a small dict for the next status poll, so every
        # update is published; the dashboard polls every few seconds.
        self.publish(self.snapshot())


def checked(argv, cwd=None):
    p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=900)
    if p.returncode:
        raise Blocked("Setup command failed: " + p.stderr[-1800:])
    return p.stdout.strip()


def install_foundations(root, config_path, progress=None):
    root = Path(root)
    destination = root / "foundations"
    destination.mkdir(exist_ok=True)
    from .prerequisites import install_missing, missing, WEIGHTS

    progress = progress or SetupProgress()
    # Plan every step first so the overall percentage is meaningful from the start.
    if os.name == "nt":
        for name in missing():
            progress.expect(f"Installing {WEIGHTS[name][0]}", WEIGHTS[name][1])
    ghidra = PINS["ghidra"]
    archive = destination / "ghidra-pinned.zip"
    installed = destination / ghidra["folder"]
    for name, label, weight in (("hermes", "Downloading Hermes", 60), ("rea", "Downloading REA", 20)):
        if not (destination / (name + "-" + PINS[name]["commit"][:12])).exists():
            progress.expect(label, weight)
    if not installed.exists():
        if not archive.exists():
            progress.expect("Downloading Ghidra", 480)
        progress.expect("Unpacking Ghidra", 60)
    progress.expect("Installing the REA package", 30)
    progress.expect("Checking the installed tools", 15)
    prerequisites = install_missing(progress=progress)
    if not shutil.which("git"):
        raise Blocked("Install Git for Windows, then retry foundation setup")
    if not shutil.which("node") or not shutil.which("npm"):
        raise Blocked("Install Node.js 24 LTS, then retry foundation setup")
    # Separate immutable checkouts preserve full native entry points and upstream history.
    for name in ("hermes", "rea"):
        pin = PINS[name]
        path = destination / (name + "-" + pin["commit"][:12])
        if not path.exists():
            progress.begin("Downloading Hermes" if name == "hermes" else "Downloading REA")
            checked(["git", "clone", pin["url"], str(path)])
        head = checked(["git", "-C", str(path), "rev-parse", "HEAD"])
        if head != pin["commit"]:
            if checked(["git", "-C", str(path), "status", "--porcelain"]):
                raise Blocked("Foundation checkout has local changes; preserving it")
            checked(["git", "-C", str(path), "fetch", "origin", pin["commit"]])
            checked(["git", "-C", str(path), "checkout", "--detach", pin["commit"]])
        if checked(["git", "-C", str(path), "rev-parse", "HEAD"]) != pin["commit"]:
            raise ContractError("Foundation revision mismatch")
    if not installed.exists():
        if not archive.exists() or file_hash(archive) != ghidra["sha256"]:
            temporary = archive.with_suffix(".download")
            progress.begin("Downloading Ghidra", 480)
            urllib.request.urlretrieve(
                ghidra["url"],
                temporary,
                reporthook=lambda blocks, size, total: progress.download(blocks * size, total),
            )
            if file_hash(temporary) != ghidra["sha256"]:
                temporary.unlink()
                raise ContractError("Ghidra archive hash mismatch")
            os.replace(temporary, archive)
        progress.begin("Unpacking Ghidra", 60)
        stage = destination / "ghidra-staging"
        stage.mkdir(exist_ok=True)
        with zipfile.ZipFile(archive) as z:
            for member in z.infolist():
                p = (stage / member.filename).resolve()
                if not p.is_relative_to(stage.resolve()):
                    raise ContractError("Unsafe archive member")
            z.extractall(stage)
            if os.name != "nt":
                for member in z.infolist():
                    mode = (member.external_attr >> 16) & 0o777
                    if mode and (stage / member.filename).is_file():
                        (stage / member.filename).chmod(mode)
        os.replace(stage / ghidra["folder"], installed)
        stage.rmdir()
    rea_package = destination / "rea-package"
    rea_package.mkdir(exist_ok=True)
    npm = shutil.which("npm")
    prefix = [npm]
    if os.name == "nt":
        npm_cli = Path(npm).parent / "node_modules/npm/bin/npm-cli.js"
        if not npm_cli.exists():
            raise Blocked("Cannot locate the installed Node.js npm CLI")
        prefix = [shutil.which("node"), str(npm_cli)]
    argv = [
        *prefix,
        "install",
        "--prefix",
        str(rea_package),
        "--omit=optional",
        "rea-agents@" + PINS["rea"]["npm_version"],
    ]
    progress.begin("Installing the REA package", 30)
    checked(argv)
    cfg = json.loads(Path(config_path).read_text())
    cfg["foundations"].update(
        hermes_home=str(destination / ("hermes-" + PINS["hermes"]["commit"][:12])),
        rea_home=str(rea_package),
        ghidra_home=str(installed),
    )
    atomic_write(config_path, canonical(cfg))
    atomic_write(destination / "pins.json", canonical(PINS))
    from .verification import verify_foundations

    progress.begin("Checking the installed tools", 15)
    verification = verify_foundations(
        root / "private" / "verification", cfg["foundations"]
    )
    return {
        "verification": verification,
        "installed": [
            "Hermes full source",
            "REA full source and package",
            "Ghidra complete distribution",
        ],
        "restart_required": True,
        "prerequisites": prerequisites,
        "remaining": "Native sign-in, exact route calibration and live acceptance",
    }
