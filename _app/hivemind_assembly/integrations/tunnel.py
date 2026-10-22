"""Optional official Secure MCP Tunnel setup, with session or OS-vault credentials."""

from __future__ import annotations
from collections import deque
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import signal
import subprocess
import tempfile
import threading
import zipfile
import httpx
from hivemind_assembly.core.common import (
    Blocked,
    ContractError,
    atomic_write,
    canonical,
)
from .github import CredentialVault


class Tunnel:
    def __init__(self, connections):
        self.connections = connections
        self.root = connections.store.root / "private" / "mcp-tunnel"
        self.config = self.root / "profile.json"
        self.installation = self.root / "installation.json"
        self.vault = CredentialVault(connections.store.root, service="MCPTunnel")
        self.secret = None
        self.process = None
        self.reader = None
        self.lock = threading.RLock()
        self.messages = deque(maxlen=100)
        self.closed = False

    def status(self):
        installed = (
            json.loads(self.installation.read_text())
            if self.installation.exists()
            else None
        )
        cfg = json.loads(self.config.read_text()) if self.config.exists() else {}
        return {
            "installed": bool(installed),
            "version": installed.get("version") if installed else None,
            "tunnel_id": cfg.get("control_plane", {}).get("tunnel_id"),
            "process_running": bool(self.process and self.process.poll() is None),
            "exit_code": self.process.poll() if self.process else None,
            "messages": list(self.messages),
            "claim": "A running process is not proof of web-client connectivity.",
        }

    @staticmethod
    def release_asset(release, system=None, machine=None):
        system = (system or platform.system()).lower()
        arch = {
            "x86_64": "amd64",
            "amd64": "amd64",
            "arm64": "arm64",
            "aarch64": "arm64",
        }.get((machine or platform.machine()).lower())
        if system not in ("windows", "linux", "darwin") or not arch:
            raise Blocked("No supported official tunnel binary for this host")
        name = f"tunnel-client-{release['tag_name']}-{system}-{arch}.zip"
        found = [a for a in release["assets"] if a["name"] == name]
        if len(found) != 1 or not re.fullmatch(
            r"sha256:[0-9a-f]{64}", found[0].get("digest", "")
        ):
            raise Blocked(
                "Official release has no uniquely identified, hash-verified host archive"
            )
        return found[0]

    def install(self, progress=None):
        with self.lock:
            if self.closed or (self.process and self.process.poll() is None):
                raise Blocked("Stop the tunnel before installing its runtime")
            with httpx.Client(timeout=60, follow_redirects=True) as client:
                response = client.get(
                    "https://api.github.com/repos/openai/tunnel-client/releases/latest"
                )
                response.raise_for_status()
                release = response.json()
                asset = self.release_asset(release)
                if not asset["browser_download_url"].startswith(
                    "https://github.com/openai/tunnel-client/releases/download/"
                ):
                    raise Blocked("Unexpected release origin")
                self.root.mkdir(parents=True, exist_ok=True)
                if os.name != "nt":
                    self.root.chmod(0o700)
                with tempfile.TemporaryDirectory(dir=self.root) as tmp:
                    archive = Path(tmp) / "download.zip"
                    size = 0
                    h = hashlib.sha256()
                    with client.stream(
                        "GET", asset["browser_download_url"]
                    ) as stream, archive.open("wb") as out:
                        stream.raise_for_status()
                        total = asset.get("size") or None
                        for chunk in stream.iter_bytes():
                            size += len(chunk)
                            if size > 128 * 1024 * 1024:
                                raise Blocked("Tunnel archive exceeds download limit")
                            if progress:
                                progress.download(size, total)
                            h.update(chunk)
                            out.write(chunk)
                    if "sha256:" + h.hexdigest() != asset["digest"]:
                        raise Blocked("Tunnel archive checksum mismatch")
                    executable = (
                        "tunnel-client.exe" if os.name == "nt" else "tunnel-client"
                    )
                    folder = self.root / ("runtime-" + h.hexdigest()[:16])
                    folder.mkdir(exist_ok=True)
                    with zipfile.ZipFile(archive) as z:
                        members = [
                            i
                            for i in z.infolist()
                            if Path(i.filename).name == executable
                        ]
                        if (
                            len(members) != 1
                            or members[0].file_size > 128 * 1024 * 1024
                        ):
                            raise Blocked("Unexpected tunnel archive contents")
                        binary = z.read(members[0])
                        atomic_write(folder / executable, binary)
                        if os.name != "nt":
                            (folder / executable).chmod(0o700)
                        for index, info in enumerate(z.infolist()):
                            if (
                                (
                                    "license" in info.filename.lower()
                                    or "notice" in info.filename.lower()
                                )
                                and info.file_size < 2 * 1024 * 1024
                                and not info.is_dir()
                            ):
                                atomic_write(
                                    folder / f"license-{index}.txt", z.read(info)
                                )
                    record = {
                        "version": release["tag_name"],
                        "binary": str(folder / executable),
                        "binary_sha256": hashlib.sha256(binary).hexdigest(),
                        "archive_sha256": h.hexdigest(),
                        "source": asset["browser_download_url"],
                    }
                    atomic_write(self.installation, canonical(record))
            return self.status()

    def configure(self, tunnel_id, key=None, remember=False):
        if not isinstance(tunnel_id, str) or not re.fullmatch(
            r"tunnel_[A-Za-z0-9]{16,80}", tunnel_id
        ):
            raise ContractError(
                "Enter the tunnel ID from OpenAI Platform tunnel settings"
            )
        if type(remember) is not bool or (
            key is not None
            and (
                not isinstance(key, str)
                or not re.fullmatch(r"[A-Za-z0-9_.-]{10,1000}", key)
            )
        ):
            raise ContractError("Provide a valid runtime credential and storage choice")
        with self.lock:
            if self.process and self.process.poll() is None:
                raise Blocked("Stop the tunnel before changing its connection")
            if key:
                if remember:
                    self.vault.write({"token": key})
                    self.secret = None
                else:
                    self.secret = key
            cfg = self.connections.client_config()["mcpServers"]["hivemind-assembly"]
            command = shlex.join([cfg["command"], *cfg["args"]])
            # JSON is valid YAML. No literal credential enters this profile.
            profile = {
                "config_version": 1,
                "control_plane": {
                    "base_url": "https://api.openai.com",
                    "tunnel_id": tunnel_id,
                    "api_key": "env:CONTROL_PLANE_API_KEY",
                },
                "mcp": {"commands": [{"channel": "main", "command": command}]},
                "health": {"listen_addr": "127.0.0.1:0"},
                "admin_ui": {"open_browser": False},
                "log": {"level": "info", "format": "json"},
            }
            self.root.mkdir(parents=True, exist_ok=True)
            atomic_write(self.config, canonical(profile))
            if os.name != "nt":
                self.config.chmod(0o600)
        return self.status()

    def runtime(self):
        if not self.installation.exists() or not self.config.exists():
            raise Blocked("Install and configure the private tunnel first")
        record = json.loads(self.installation.read_text())
        binary = Path(record["binary"])
        if hashlib.sha256(binary.read_bytes()).hexdigest() != record["binary_sha256"]:
            raise Blocked("Installed tunnel binary checksum changed; reinstall it")
        secret = self.secret
        if not secret:
            saved = self.vault.read()
            secret = saved.get("token") if saved else None
        if not secret:
            raise Blocked(
                "Supply a tunnel runtime key for this session or save it in the OS vault"
            )
        env = {
            k: v
            for k, v in os.environ.items()
            if k
            in (
                "PATH",
                "HOME",
                "USERPROFILE",
                "SystemRoot",
                "WINDIR",
                "TEMP",
                "TMP",
                "LOCALAPPDATA",
            )
        }
        env["CONTROL_PLANE_API_KEY"] = secret
        return str(binary), env, secret

    def doctor(self):
        with self.lock:
            binary, env, _ = self.runtime()
            result = subprocess.run(
                [binary, "doctor", "--config", str(self.config)],
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=45,
            )
            return {
                "passed": result.returncode == 0,
                "exit_code": result.returncode,
                "detail": (
                    "Official tunnel doctor passed"
                    if result.returncode == 0
                    else "Tunnel doctor failed; check the tunnel ID, runtime permissions and network access."
                ),
            }

    def start(self):
        with self.lock:
            if self.closed or not self.connections.settings()["enabled"]:
                raise Blocked("Enable HA MCP access before starting the tunnel")
            if self.process and self.process.poll() is None:
                return self.status()
            binary, env, secret = self.runtime()
            self.messages.clear()
            self.process = subprocess.Popen(
                [binary, "run", "--config", str(self.config)],
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=os.name != "nt",
            )
            process = self.process

            def read():
                # Bounded in-memory diagnostics; credentials never enter retained state.
                while line := process.stdout.readline(16384):
                    text = line.decode("utf-8", errors="replace").replace(
                        secret, "[redacted]"
                    )
                    text = re.sub(r"sk-[A-Za-z0-9_-]+", "[redacted]", text)
                    with self.lock:
                        self.messages.append(text.rstrip())
                process.stdout.close()

            self.reader = threading.Thread(target=read, daemon=True)
            self.reader.start()
            return self.status()

    def stop(self):
        with self.lock:
            process = self.process
            if process and process.poll() is None:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=10,
                    )
                else:
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    if os.name != "nt":
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                    process.wait(timeout=5)
            return self.status()

    def forget(self):
        self.stop()
        self.secret = None
        self.vault.clear()
        return {"forgotten": True}

    def close(self):
        self.stop()
        self.closed = True
        self.secret = None
