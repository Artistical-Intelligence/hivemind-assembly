from __future__ import annotations
import json, os, shutil, subprocess, urllib.request, zipfile
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


def checked(argv, cwd=None):
    p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=900)
    if p.returncode:
        raise Blocked("Setup command failed: " + p.stderr[-1800:])
    return p.stdout.strip()


def install_foundations(root, config_path):
    root = Path(root)
    destination = root / "foundations"
    destination.mkdir(exist_ok=True)
    from .prerequisites import install_missing

    prerequisites = install_missing()
    if not shutil.which("git"):
        raise Blocked("Install Git for Windows, then retry foundation setup")
    if not shutil.which("node") or not shutil.which("npm"):
        raise Blocked("Install Node.js 24 LTS, then retry foundation setup")
    # Separate immutable checkouts preserve full native entry points and upstream history.
    for name in ("hermes", "rea"):
        pin = PINS[name]
        path = destination / (name + "-" + pin["commit"][:12])
        if not path.exists():
            checked(["git", "clone", pin["url"], str(path)])
        head = checked(["git", "-C", str(path), "rev-parse", "HEAD"])
        if head != pin["commit"]:
            if checked(["git", "-C", str(path), "status", "--porcelain"]):
                raise Blocked("Foundation checkout has local changes; preserving it")
            checked(["git", "-C", str(path), "fetch", "origin", pin["commit"]])
            checked(["git", "-C", str(path), "checkout", "--detach", pin["commit"]])
        if checked(["git", "-C", str(path), "rev-parse", "HEAD"]) != pin["commit"]:
            raise ContractError("Foundation revision mismatch")
    ghidra = PINS["ghidra"]
    archive = destination / "ghidra-pinned.zip"
    installed = destination / ghidra["folder"]
    if not installed.exists():
        if not archive.exists() or file_hash(archive) != ghidra["sha256"]:
            temporary = archive.with_suffix(".download")
            urllib.request.urlretrieve(ghidra["url"], temporary)
            if file_hash(temporary) != ghidra["sha256"]:
                temporary.unlink()
                raise ContractError("Ghidra archive hash mismatch")
            os.replace(temporary, archive)
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
