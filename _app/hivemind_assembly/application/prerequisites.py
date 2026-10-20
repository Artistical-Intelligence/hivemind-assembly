"""Install missing Windows prerequisites through the system package manager."""

import os
import shutil
import subprocess
import re
import ntpath
from pathlib import Path
from hivemind_assembly.core.common import Blocked

PACKAGES = {
    "git": "Git.Git",
    "gh": "GitHub.cli",
    "node": "OpenJS.NodeJS.LTS",
    "java": "EclipseAdoptium.Temurin.21.JDK",
    "clang": "LLVM.LLVM",
}


def refresh_windows_path():
    if os.name != "nt":
        return
    import winreg

    # Preserve working explicit/tool-runner selections; a registry default must
    # not downgrade a usable Node/JDK while refreshing an unrelated installation.
    working = []
    for name in ("git", "node", "java", "clang", "gh"):
        if available(name):
            executable = shutil.which(name)
            if name == "java" and os.environ.get("JAVA_HOME"):
                working.append(str(Path(os.environ["JAVA_HOME"]) / "bin"))
            elif executable:
                working.append(str(Path(executable).resolve().parent))
    paths = []
    homes = []
    for hive, key in (
        (
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
        ),
        (winreg.HKEY_CURRENT_USER, r"Environment"),
    ):
        try:
            with winreg.OpenKey(hive, key) as handle:
                try:
                    paths.append(winreg.QueryValueEx(handle, "Path")[0])
                except OSError:
                    pass
                try:
                    homes.append(winreg.QueryValueEx(handle, "JAVA_HOME")[0])
                except OSError:
                    pass
        except OSError:
            pass
    # A just-installed JDK can update JAVA_HOME and PATH in the registry while
    # this running process still sees an older JRE. Apply fresh registry values
    # before expanding references, with the user value taking precedence.
    if homes and not available("java"):
        os.environ["JAVA_HOME"] = ntpath.expandvars(homes[-1])
    paths = [*working, *paths, os.environ.get("PATH", "")]
    unique = {}
    for path in paths:
        for entry in ntpath.expandvars(path).split(";"):
            if entry:
                unique.setdefault(entry.casefold(), entry)
    os.environ["PATH"] = ";".join(unique.values())


def available(name):
    path = shutil.which(name)
    if name == "java" and os.environ.get("JAVA_HOME"):
        path = str(Path(os.environ["JAVA_HOME"]) / "bin" / ("java.exe" if os.name == "nt" else "java"))
    if not path:
        return False
    if name not in ("node", "java"):
        return True
    try:
        result = subprocess.run(
            [path, "--version" if name == "node" else "-version"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        text = result.stdout + result.stderr
        match = re.search(r"(?:v|version\s+\"?)(\d+)(?:\.(\d+))?", text)
        valid = (
            result.returncode == 0
            and match is not None
            and int(match.group(1)) >= (24 if name == "node" else 21)
        )
        if name == "node" and valid:
            major, minor = int(match.group(1)), int(match.group(2) or 0)
            # HA standardizes on the supported 24.x LTS line or 26+. REA 6.7
            # requires 24.11+, and does not support the intervening 25.x line.
            valid = (major == 24 and minor >= 11) or major >= 26
        if name == "java" and valid:
            # A separate javac found on PATH cannot turn an old/runtime-only
            # Java installation into the full JDK that Ghidra will actually use.
            compiler = str(Path(path).resolve().with_name("javac.exe" if os.name == "nt" else "javac"))
            if not compiler or not Path(compiler).is_file():
                return False
            checked = subprocess.run(
                [compiler, "-version"], capture_output=True, text=True, timeout=15
            )
            version = re.search(r"javac\s+(\d+)", checked.stdout + checked.stderr)
            valid = (
                checked.returncode == 0
                and version is not None
                and int(version.group(1)) >= 21
                and int(version.group(1)) == int(match.group(1))
            )
        return valid
    except (OSError, subprocess.TimeoutExpired):
        return False


def install_missing(extra=()):
    if set(extra) - {"gh"}:
        raise Blocked("Unknown optional prerequisite")
    required = ["git", "node", "java", *extra]
    # Windows MinGW GCC cannot supply the Linux ELF/PE cross-target lanes.
    # LLVM includes Clang and LLD; Unix hosts may use their existing native GCC.
    if not shutil.which("clang") and (os.name == "nt" or not shutil.which("gcc")):
        required.append("clang")
    missing = [name for name in required if not available(name)]
    if missing and os.name == "nt":
        refresh_windows_path()
        missing = [name for name in required if not available(name)]
    if not missing:
        return {"installed": []}
    if os.name != "nt":
        raise Blocked("Install the missing system prerequisites: " + ", ".join(missing))
    manager = shutil.which("winget")
    if not manager:
        raise Blocked(
            "Windows App Installer (winget) is unavailable. Install or enable it, then restart setup; completed work is retained."
        )
    installed = []
    for name in missing:
        result = subprocess.run(
            [
                manager,
                "install",
                "--id",
                PACKAGES[name],
                "--exact",
                "--source",
                "winget",
                "--silent",
                "--accept-package-agreements",
                "--accept-source-agreements",
                "--disable-interactivity",
            ],
            capture_output=True,
            text=True,
            timeout=1800,
        )
        refresh_windows_path()
        if result.returncode or not available(name):
            raise Blocked(
                "Windows could not finish installing "
                + PACKAGES[name]
                + ". A system authorization or application restart may be required. Completed installations are retained."
            )
        installed.append(PACKAGES[name])
    return {"installed": installed}
