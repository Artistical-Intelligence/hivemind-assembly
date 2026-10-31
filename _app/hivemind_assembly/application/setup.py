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
    """Prepare built-in analysis from HA's approved local packages.

    No Git clone, npm install, registry resolution, donor setup hook or unrelated
    provider registration is performed. Existing installations and settings are
    retained; a complete release supplies all four required offline packages.
    """
    from .components import Components

    root = Path(root)
    progress = progress or SetupProgress()
    components = Components(root)
    required = ("node", "jdk", "analysis", "ghidra")
    missing = [name for name in required if name not in components.entries]
    if missing:
        raise Blocked(
            "This HA copy does not include its complete built-in analysis package. "
            "Use the complete HA installation or restore its retained component archives. "
            "No external installer was run and existing tools were left unchanged."
        )
    selected = [*required]
    for name in ("compiler", "tunnel", "connect", "execution"):
        if name in components.entries:
            selected.append(name)
    for name in selected:
        progress.expect("Preparing " + components.entries[name].get("label", name), 20)
    progress.expect("Checking HA's capabilities", 15)
    for name in selected:
        progress.begin("Preparing " + components.entries[name].get("label", name), 20)
        components.prepare([name])
    cfg = json.loads(Path(config_path).read_text(encoding="utf-8"))
    # Keep the previous settings before adopting internally owned paths. This
    # recovery copy contains no login credentials and is never a release input.
    previous = root / "private" / "setup" / "before-owned-components.json"
    if not previous.exists():
        previous.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(previous, canonical({"foundations": cfg.get("foundations", {})}))
    cfg["foundations"] = components.effective_foundations(cfg.get("foundations", {}))
    atomic_write(config_path, canonical(cfg))
    from .verification import verify_foundations

    progress.begin("Checking HA's capabilities", 15)
    verification = verify_foundations(root / "private" / "verification", cfg["foundations"])
    progress.finish()
    return {
        "verification": verification,
        "installed": ["HA sessions and tasks", "HA analysis", "HA native runtimes"],
        "restart_required": False,
        "network_used": False,
        "components": components.snapshot(),
        "remaining": "Account sign-in and any explicitly reported live acceptance checks",
    }
