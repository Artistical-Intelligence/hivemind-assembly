"""Native play-testing lane: real games stepped one frame per input record.

Godot 4 projects and SDL2 programs (C, C++, Rust or any language that calls SDL2)
run as ordinary native processes with a small adapter that HA adds at launch: an
autoload script in a runtime copy of a Godot project, or an LD_PRELOAD library for
SDL2 programs on Linux. The adapter speaks HA's tick protocol over a localhost socket
guarded by a per-launch token: HA sends one input record, the game runs one frame
with it, and the adapter returns that frame's declared state values and a scaled
frame. For SDL2 programs HA reads declared state from the paused process's memory by
symbol and pointer path. `NativeEngine` presents this as the harness's live stepping
protocol, so play, comparison, exploration, shrinking and regressions are unchanged.

Determinism comes from the adapters: Godot's fixed-fps mode, or virtual clocks for
the game's own code (SDL2), and seeded randomness. Games that read wall-clock time or
unseeded entropy some other way can still differ between runs; snapshots restore by
replaying the input log from a fresh launch and record any replay that differs.
Frames render on a virtual X display (Xvfb) with software OpenGL on Linux.

Native execution runs the game's own code on this computer with a credential-free
environment and a fresh home folder, bounded per frame and cancellable. It is not a
sandbox: the owner enables it per project, as for native test recipes.
"""

import atexit
import base64
import functools
import hashlib
import json
import os
import secrets
import select
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from hivemind_assembly.core import game_spec as gs
from hivemind_assembly.core.common import Blocked, ContractError, scoped

from .game_machine import Stream, elf_symbols

PROTOCOL = 1
MAGIC = b"HATK"
ADAPTERS = Path(__file__).with_name("native_adapters")
PERMISSION = (
    "Native play-testing runs the game's own code on this computer; the owner must "
    "enable trusted native execution for this project first"
)
MAX_FILES = 20000
MAX_BYTES = 2 * 1024**3
LOG_TAIL = 4096

# SDL2 scancodes and keycodes for key names (SDL_GetScancodeName spellings, case-insensitive).
_SCAN = {
    **{chr(c): 4 + c - 97 for c in range(97, 123)},
    **{str(d): 30 + (d - 1) for d in range(1, 10)},
    "0": 39,
    "return": 40,
    "enter": 40,
    "escape": 41,
    "backspace": 42,
    "tab": 43,
    "space": 44,
    "-": 45,
    "=": 46,
    "[": 47,
    "]": 48,
    "\\": 49,
    ";": 51,
    "'": 52,
    "`": 53,
    ",": 54,
    ".": 55,
    "/": 56,
    **{f"f{n}": 57 + n for n in range(1, 13)},
    "insert": 73,
    "home": 74,
    "pageup": 75,
    "delete": 76,
    "end": 77,
    "pagedown": 78,
    "right": 79,
    "left": 80,
    "down": 81,
    "up": 82,
    "keypad +": 87,
    "keypad enter": 88,
    **{f"keypad {d}": 89 + (d - 1) for d in range(1, 10)},
    "keypad 0": 98,
    "left ctrl": 224,
    "left shift": 225,
    "left alt": 226,
    "right ctrl": 228,
    "right shift": 229,
    "right alt": 230,
}
_ASCII = {"return": 13, "enter": 13, "escape": 27, "backspace": 8, "tab": 9, "space": 32, "delete": 127}


def sdl_key(name):
    """SDL2 (scancode, keycode) for a key name such as Left, Space, Return or Z."""
    key = name.strip().lower()
    if key not in _SCAN:
        raise ContractError("Unknown SDL2 key name: " + name[:40])
    scancode = _SCAN[key]
    if key in _ASCII:
        return scancode, _ASCII[key]
    if len(key) == 1:
        return scancode, ord(key)
    return scancode, scancode | (1 << 30)


class Display:
    """One shared virtual X display (Xvfb) for every native game on this host."""

    lock = threading.Lock()
    process = None
    name = None

    @classmethod
    def get(cls):
        with cls.lock:
            if cls.process is not None and cls.process.poll() is None:
                return cls.name
            xvfb = shutil.which("Xvfb")
            if not xvfb:
                raise Blocked(
                    "Native frames on Linux need a virtual display: install Xvfb (package xvfb), "
                    "or use display headless for Godot state-only play"
                )
            for number in range(87, 200):
                if Path(f"/tmp/.X11-unix/X{number}").exists() or Path(f"/tmp/.X{number}-lock").exists():
                    continue
                process = subprocess.Popen(
                    [xvfb, f":{number}", "-screen", "0", "1280x1024x24", "-nolisten", "tcp"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline and process.poll() is None:
                    if Path(f"/tmp/.X11-unix/X{number}").exists():
                        cls.process, cls.name = process, f":{number}"
                        atexit.register(cls.close)
                        return cls.name
                    time.sleep(0.05)
                process.kill()
            raise Blocked("Could not start a virtual X display (Xvfb)")

    @classmethod
    def close(cls):
        with cls.lock:
            if cls.process is not None and cls.process.poll() is None:
                cls.process.kill()
            cls.process = None


def runtime_root():
    root = Path(os.environ.get("HA_NATIVE_GAME_CACHE") or Path(tempfile.gettempdir()) / "ha-native-games")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _files(folder):
    """Regular files under a folder (no symlinks), bounded."""
    found, total = [], 0
    for path in sorted(folder.rglob("*")):
        relative = path.relative_to(folder)
        if any(part in (".godot", ".git", "__pycache__", ".import") for part in relative.parts):
            continue
        if path.is_symlink():
            raise ContractError("Native game folders cannot contain symbolic links: " + relative.as_posix())
        if path.is_dir():
            continue
        info = path.stat()
        total += info.st_size
        found.append((relative.as_posix(), info.st_size, info.st_mtime_ns))
        if len(found) > MAX_FILES or total > MAX_BYTES:
            raise Blocked("Native game folder exceeds 20,000 files or 2 GiB")
    return found


_preparing = {}
_preparing_lock = threading.Lock()


def _prepared(key, build):
    """A runtime folder made once per key; concurrent requests wait for the first."""
    target = runtime_root() / key
    with _preparing_lock:
        lock = _preparing.setdefault(key, threading.Lock())
    with lock:
        if (target / "ready.json").is_file():
            return target
        stage = Path(tempfile.mkdtemp(prefix=key[:12] + "-", dir=runtime_root()))
        try:
            build(stage)
            (stage / "ready.json").write_text(json.dumps({"key": key}), encoding="utf-8")
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            stage.rename(target)
        finally:
            if stage.exists():
                shutil.rmtree(stage, ignore_errors=True)
    return target


def _environment(home, extra):
    environment = {k: os.environ[k] for k in ("PATH", "SystemRoot", "WINDIR", "LANG") if k in os.environ}
    environment.update(
        HOME=str(home),
        USERPROFILE=str(home),
        APPDATA=str(home),
        LOCALAPPDATA=str(home),
        XDG_DATA_HOME=str(home / "data"),
        XDG_CONFIG_HOME=str(home / "config"),
        XDG_CACHE_HOME=str(home / "cache"),
        TEMP=str(home),
        TMP=str(home),
        TZ="UTC",
        LC_ALL="C.UTF-8",
    )
    environment.update(extra)
    return environment


def godot_engine(root, item, config):
    """The Godot editor/runtime executable for a project launch."""
    if item.get("engine", "godot") != "godot":
        path = scoped(root, item["engine"])
        if not path.is_file():
            raise ContractError("Godot engine not found: " + item["engine"])
        return path
    configured = (config.get("foundations") or {}).get("godot", "") or os.environ.get("HA_GODOT", "")
    located = shutil.which(configured) if configured else (shutil.which("godot") or shutil.which("godot4"))
    if not located:
        raise Blocked("Install Godot 4 and set foundations.godot (or HA_GODOT) to its executable")
    return Path(located)


def _stamp(path):
    info = Path(path).stat()
    return [str(Path(path).resolve()), info.st_size, info.st_mtime_ns]


def _godot_plan(root, spec, item, config):
    native = spec["native"]
    folder = scoped(root, item["project"])
    if not (folder / "project.godot").is_file():
        raise ContractError("No project.godot in " + item["project"])
    engine = godot_engine(root, item, config)
    adapter = (ADAPTERS / "ha_tick.gd").read_bytes()
    key = hashlib.sha256(
        json.dumps(
            {"files": _files(folder), "engine": _stamp(engine), "adapter": hashlib.sha256(adapter).hexdigest(), "protocol": PROTOCOL},
            sort_keys=True,
        ).encode()
    ).hexdigest()[:32]

    def build(stage):
        game = stage / "game"
        shutil.copytree(folder, game, ignore=shutil.ignore_patterns(".godot", ".git", "__pycache__"))
        (game / "ha_tick.gd").write_bytes(adapter)
        override = game / "override.cfg"
        existing = override.read_text(encoding="utf-8") if override.is_file() else ""
        override.write_text(existing + '\n[autoload]\n\nHATick="*res://ha_tick.gd"\n', encoding="utf-8")
        home = stage / "import-home"
        home.mkdir()
        try:
            completed = subprocess.run(
                [str(engine), "--headless", "--path", str(game), "--import"],
                cwd=str(game),
                env=_environment(home, {}),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=max(120, native["startup_seconds"] * 5),
            )
        except subprocess.TimeoutExpired as error:
            raise Blocked("Godot asset import timed out") from error
        if completed.returncode != 0 or not (game / ".godot").is_dir():
            tail = completed.stdout[-600:].decode("utf-8", "replace").replace(str(stage), "<runtime>")
            raise Blocked("Godot could not import the project: " + tail)

    runtime = _prepared("godot-" + key, build)
    game = runtime / "game"
    frame = native.get("frame")
    segments = []
    if spec.get("state"):
        fields = []
        for declared, laid in zip(native["state"], spec["state"]["fields"]):
            fields.append({k: v for k, v in declared.items() if k in ("node", "property", "group", "missing")} | {"type": laid["type"], "offset": laid["offset"]})
        segments.append({"kind": "state", "bytes": spec["output"]["stdout"][0]["bytes"], "fields": fields})
    if frame:
        segments.append({"kind": "frame", "width": frame["width"], "height": frame["height"]})
    config_value = {
        "seed": native["seed"],
        "record_bytes": spec["input"]["record_bytes"],
        "inputs": native["inputs"],
        "segments": segments,
    }
    argv = [str(engine), "--path", str(game), "--fixed-fps", str(native["fps"]), "--audio-driver", "Dummy"]
    extra = {"HA_TICK_CONFIG": base64.b64encode(json.dumps(config_value).encode()).decode()}
    if native["display"] == "headless":
        argv.append("--headless")
    elif sys.platform.startswith("linux"):
        argv += ["--rendering-driver", "opengl3"]
        extra.update(LIBGL_ALWAYS_SOFTWARE="1", MESA_SHADER_CACHE_DISABLE="true")
    argv += item["args"]
    return {
        "adapter": "godot",
        "argv": argv,
        "cwd": str(game),
        "env": extra,
        "display": native["display"] != "headless" and sys.platform.startswith("linux"),
        "payload": sum(gs.record_sizes(spec).values()),
        "runtime": str(runtime),
        "digest": "godot:" + key + ":" + hashlib.sha256(json.dumps(argv[1:]).encode()).hexdigest()[:16],
    }


@functools.lru_cache(maxsize=4)
def _shim(compiler, stamp):
    """Build the SDL2 adapter library once per compiler."""
    source = (ADAPTERS / "ha_sdl_tick.c").read_bytes()
    key = hashlib.sha256(source + json.dumps(stamp).encode()).hexdigest()[:32]

    def build(stage):
        completed = subprocess.run(
            [compiler, "-O2", "-shared", "-fPIC", "-o", str(stage / "ha_sdl_tick.so"), str(ADAPTERS / "ha_sdl_tick.c"), "-ldl"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=120,
        )
        if completed.returncode != 0:
            raise Blocked("Could not build the SDL2 adapter: " + completed.stdout[-600:].decode("utf-8", "replace"))

    return str(_prepared("sdl2-adapter-" + key, build) / "ha_sdl_tick.so")


def _sdl2_plan(root, spec, item, config):
    native = spec["native"]
    if not sys.platform.startswith("linux"):
        raise Blocked("The SDL2 adapter runs on Linux")
    executable = scoped(root, item["executable"])
    if not executable.is_file():
        raise ContractError("Native executable not found: " + item["executable"])
    if "folder" in item:
        folder = scoped(root, item["folder"])
        inside = Path(item["executable"]).relative_to(item["folder"].rstrip("/")).as_posix()
    else:
        folder, inside = None, executable.name
    configured = (config.get("foundations") or {}).get("c_compiler", "") or ""
    compiler = shutil.which(configured) if configured else (shutil.which("clang") or shutil.which("gcc") or shutil.which("cc"))
    if not compiler:
        raise Blocked("The SDL2 adapter needs a C compiler (Clang or GCC)")
    shim = _shim(compiler, tuple(_stamp(compiler)))
    listing = _files(folder) if folder else [(executable.name, executable.stat().st_size, executable.stat().st_mtime_ns)]
    key = hashlib.sha256(json.dumps({"files": listing, "protocol": PROTOCOL}, sort_keys=True).encode()).hexdigest()[:32]

    def build(stage):
        game = stage / "game"
        if folder:
            shutil.copytree(folder, game, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        else:
            game.mkdir()
            shutil.copy2(executable, game / inside)
        (game / inside).chmod(0o700)

    runtime = _prepared("sdl2-" + key, build)
    game = runtime / "game"
    keys = [sdl_key(entry["key"]) for entry in native["inputs"]]
    frame = native.get("frame")
    extra = {
        "LD_PRELOAD": shim,
        "SDL_AUDIODRIVER": "dummy",
        "ALSOFT_DRIVERS": "null",
        "SDL_VIDEODRIVER": "x11",
        "LIBGL_ALWAYS_SOFTWARE": "1",
        "MESA_SHADER_CACHE_DISABLE": "true",
        "HA_TICK_RECORD": str(spec["input"]["record_bytes"]),
        "HA_TICK_FRAME": f"{frame['width']},{frame['height']}" if frame else "0,0",
        "HA_TICK_FRAME_NS": str(native["frame_ns"]),
        "HA_TICK_SEED": str(native["seed"]),
        "HA_TICK_KEYS": ",".join(f"{scan}:{code}" for scan, code in keys),
        **item["env"],
    }
    argv = [str(game / inside), *item["args"]]
    return {
        "adapter": "sdl2",
        "argv": argv,
        "cwd": str(game),
        "env": extra,
        "display": True,
        "payload": frame["width"] * frame["height"] * 4 if frame else 0,
        "executable": str(game / inside),
        "runtime": str(runtime),
        "digest": "sdl2:" + key + ":" + hashlib.sha256(json.dumps(argv[1:] + sorted(item["env"].items())).encode()).hexdigest()[:16],
    }


def plan(root, spec, side, context):
    """Prepare one side of a native game and describe how to launch it."""
    if not getattr(context, "native", False):
        raise Blocked(PERMISSION)
    native = spec["native"]
    if side not in native:
        raise Blocked(f"This native game names no {side}")
    if native["adapter"] == "godot":
        return _godot_plan(Path(root), spec, native[side], context.config)
    return _sdl2_plan(Path(root), spec, native[side], context.config)


class _Stop(Exception):
    def __init__(self, status, detail=None):
        super().__init__(status)
        self.status, self.detail = status, detail or {}


class NativeEngine:
    """A native game process behind the harness's live stepping protocol."""

    def __init__(self, launch, spec, *, cancel=None):
        native = spec["native"]
        self.launch, self.spec, self.cancel = launch, spec, cancel
        self.record = spec["input"]["record_bytes"]
        self.sizes = gs.record_sizes(spec)
        self.tick_seconds = native["tick_seconds"]
        self.startup_seconds = native["startup_seconds"]
        self.memory_state = launch["adapter"] == "sdl2" and bool(native["state"])
        self.capabilities = {
            "runtime": "native_" + launch["adapter"],
            "stepping": "live",
            "snapshots": "replay",
            "memory": launch["adapter"] == "sdl2" and sys.platform.startswith("linux"),
            "coverage": "none",
            "deterministic": "adapter_controlled",
            "frame_exact_input": True,
            "observations": "per_frame",
        }
        self.symbols = elf_symbols(Path(launch["executable"]).read_bytes()) if launch.get("executable") else {}
        self.replay_mismatches = 0
        self.process = self.connection = self.server = self.home = None
        self._reset()
        self._start()

    # Lifecycle.
    def _reset(self):
        self.inputs = bytearray()
        self.ended = False
        self.status = "ready"
        self.exit_code = None
        self.ticks = 0
        self.stdout, self.stderr = Stream(), Stream()
        self.fault = None
        self.stop_context = None
        self.base = None
        self.tick_times = []

    def _check(self, deadline):
        if self.cancel is not None and self.cancel.is_set():
            raise _Stop("cancelled")
        if time.monotonic() >= deadline:
            raise _Stop("freeze")

    def _start(self):
        self.home = Path(tempfile.mkdtemp(prefix="ha-native-home-"))
        for name in ("data", "config", "cache"):
            (self.home / name).mkdir()
        token = secrets.token_bytes(16)
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(4)
        extra = dict(self.launch["env"])
        extra.update(
            HA_TICK_PORT=str(self.server.getsockname()[1]),
            HA_TICK_TOKEN=token.hex(),
            HA_TICK_TOKEN_B64=base64.b64encode(token).decode(),
        )
        if self.launch["display"]:
            extra["DISPLAY"] = Display.get()
        log = open(self.home / "game.log", "wb")
        options = {"start_new_session": True} if os.name != "nt" else {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        try:
            self.process = subprocess.Popen(
                self.launch["argv"],
                cwd=self.launch["cwd"],
                env=_environment(self.home, extra),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                **options,
            )
        finally:
            log.close()
        _live.add(self)
        deadline = time.monotonic() + self.startup_seconds
        try:
            while True:
                self._check(deadline)
                if self.process.poll() is not None:
                    raise _Stop("exited")
                ready, _, _ = select.select([self.server], [], [], 0.1)
                if not ready:
                    continue
                connection, _ = self.server.accept()
                connection.settimeout(5)
                try:
                    hello = self._recv_from(connection, 5 + len(token))
                except (OSError, EOFError):
                    connection.close()
                    continue
                if hello != MAGIC + bytes([PROTOCOL]) + token:
                    connection.close()
                    continue
                connection.settimeout(None)
                connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self.connection = connection
                break
            self.server.close()
            self.server = None
            self.status = "awaiting_input"
        except _Stop as stop:
            self._stopped(stop, phase="startup")

    @staticmethod
    def _recv_from(connection, size):
        data = b""
        while len(data) < size:
            chunk = connection.recv(size - len(data))
            if not chunk:
                raise EOFError
            data += chunk
        return data

    def _recv(self, size, deadline):
        data = bytearray()
        while len(data) < size:
            self._check(deadline)
            ready, _, _ = select.select([self.connection], [], [], 0.1)
            if not ready:
                continue
            chunk = self.connection.recv(min(size - len(data), 1 << 20))
            if not chunk:
                raise _Stop("exited")
            data += chunk
        return bytes(data)

    def _stopped(self, stop, phase="play"):
        """Record why play ended and leave no process behind."""
        status = stop.status
        if status == "exited":
            try:
                code = self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                code = None
            if code is None:
                status = "freeze"
            elif code == 70 and phase == "startup":
                status, self.fault = "adapter_error", {"reason": "The adapter could not reach HA"}
            elif code < 0 or (os.name == "nt" and code >= 0xC0000000):
                signal_name = signal.Signals(-code).name if code < 0 and -code in signal.valid_signals() else hex(code)
                status, self.fault = "crash", {"signal": signal_name}
            else:
                status, self.exit_code = "completed", code
        self.status = status
        if status != "completed":
            self.stop_context = {
                "phase": phase,
                "reason": {"freeze": "frame_timeout" if phase == "play" else "startup_timeout"}.get(status, status),
                "tick": self.ticks,
                "seconds": self.tick_seconds if phase == "play" else self.startup_seconds,
                **stop.detail,
                **({"fault": self.fault} if self.fault else {}),
                "log_tail": self._log_tail(),
            }
        self._kill()

    def _log_tail(self):
        try:
            with open(self.home / "game.log", "rb") as stream:
                stream.seek(0, 2)
                stream.seek(max(0, stream.tell() - LOG_TAIL))
                text = stream.read().decode("utf-8", "replace")
        except OSError:
            return ""
        for path, label in ((self.launch.get("runtime"), "<game>"), (str(self.home), "<home>")):
            if path:
                text = text.replace(path, label)
        return text

    def _kill(self):
        _live.discard(self)
        for item in (self.connection, self.server):
            if item is not None:
                try:
                    item.close()
                except OSError:
                    pass
        self.connection = self.server = None
        if self.process is not None and self.process.poll() is None:
            try:
                if os.name != "nt":
                    os.killpg(self.process.pid, signal.SIGKILL)
                else:
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.process.pid)], capture_output=True, timeout=10)
            except (ProcessLookupError, OSError, subprocess.TimeoutExpired):
                pass
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass

    def close(self):
        self._kill()
        if self.home is not None:
            shutil.rmtree(self.home, ignore_errors=True)
            self.home = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def rebind(self, cancel):
        self.cancel = cancel

    # Harness protocol.
    def feed(self, data):
        if self.ended:
            raise ContractError("Input has already ended for this game session")
        if len(data) % self.record:
            raise ContractError("Inputs must be whole input records")
        for offset in range(0, len(data), self.record):
            if self.status != "awaiting_input":
                return
            record = bytes(data[offset : offset + self.record])
            self.inputs += record
            started = time.monotonic()
            try:
                self.connection.sendall(b"I" + record)
                header = self._recv(9, started + self.tick_seconds)
                tick, length = struct.unpack("<II", header[1:])
                if header[:1] != b"T" or tick != self.ticks or length != self.launch["payload"]:
                    raise _Stop("adapter_error", {"expected": [self.ticks, self.launch["payload"]], "received": [tick, length]})
                payload = self._recv(length, started + self.tick_seconds)
            except _Stop as stop:
                self._stopped(stop)
                return
            except OSError:
                self._stopped(_Stop("exited"))
                return
            if self.memory_state:
                payload = self._state_bytes() + payload
            self.stdout.append(payload[: self.sizes["stdout"]])
            self.stderr.append(payload[self.sizes["stdout"] :])
            self.ticks += 1
            self.tick_times.append(round(time.monotonic() - started, 4))

    def end(self):
        if self.ended:
            return
        self.ended = True
        if self.status != "awaiting_input":
            return
        try:
            self.connection.sendall(b"E")
        except OSError:
            pass
        deadline = time.monotonic() + self.tick_seconds
        while self.process.poll() is None and time.monotonic() < deadline:
            if self.cancel is not None and self.cancel.is_set():
                self._stopped(_Stop("cancelled"))
                return
            time.sleep(0.02)
        self._stopped(_Stop("exited"))

    def output_size(self, stream):
        return (self.stdout if stream == "stdout" else self.stderr).size

    def output_tail(self, stream, start):
        return (self.stdout if stream == "stdout" else self.stderr).tail(start)

    @property
    def input_consumed(self):
        return len(self.inputs)

    instructions = 0
    costs = ()

    def coverage(self):
        return {}

    # Memory of a paused SDL2 game (Linux).
    def _base(self):
        if self.base is None:
            executable = os.path.realpath(self.launch["executable"])
            with open(f"/proc/{self.process.pid}/maps", encoding="utf-8") as maps:
                for line in maps:
                    parts = line.split()
                    if len(parts) >= 6 and parts[5] == executable and int(parts[2], 16) == 0:
                        start = int(parts[0].split("-")[0], 16)
                        # Position-independent executables load at a base; others at their addresses.
                        self.base = start if _position_independent(executable) else 0
                        break
                else:
                    raise ContractError("The game's executable mapping was not found")
        return self.base

    def symbol(self, name):
        item = self.symbols.get(name)
        if item is None or not self.capabilities["memory"]:
            return None
        try:
            return self._base() + item["address"]
        except (OSError, ContractError):
            return None

    def read_memory(self, address, size):
        if not self.capabilities["memory"] or self.status != "awaiting_input":
            raise ContractError("Memory is readable only while the native game waits for input")
        if type(address) is not int or type(size) is not int or not 0 < size <= 4096 or address <= 0:
            raise ContractError("Memory read outside the game process")
        try:
            with open(f"/proc/{self.process.pid}/mem", "rb", buffering=0) as memory:
                memory.seek(address)
                data = memory.read(size)
        except (OSError, ValueError, OverflowError) as error:
            raise ContractError("Memory read outside the game process") from error
        if len(data) != size:
            raise ContractError("Memory read outside the game process")
        return data

    def _state_bytes(self):
        native, fields = self.spec["native"], self.spec["state"]["fields"]
        data = bytearray(self.spec["output"]["stdout"][0]["bytes"])
        for declared, laid in zip(native["state"], fields):
            try:
                address = declared["address"] if "address" in declared else self.symbol(declared["symbol"])
                if address is None:
                    continue
                address += declared["offset"]
                for step in declared["pointers"]:
                    address = int.from_bytes(self.read_memory(address, 8), "little") + step
                width = gs.FIELD_TYPES[laid["type"]][1]
                data[laid["offset"] : laid["offset"] + width] = self.read_memory(address, width)
            except ContractError:
                continue  # Unreadable values (for example a null pointer) stay zero.
        return bytes(data)

    def diagnostics(self):
        return {
            "fault": self.fault,
            "stop_context": self.stop_context,
            "replay_mismatches": self.replay_mismatches,
            "frame_seconds": self.tick_times[-8:],
        }

    # Snapshots replay the input log from a fresh launch.
    def _digest(self):
        return hashlib.sha256(self.stdout.tail(0) + b"|" + self.stderr.tail(0)).hexdigest()

    def snapshot(self):
        return {"inputs": bytes(self.inputs), "ended": self.ended, "digest": self._digest(), "status": self.status}

    def restore(self, snapshot):
        target = snapshot["inputs"]
        extend = (
            not self.ended
            and not snapshot["ended"]
            and self.status == "awaiting_input"
            and target.startswith(bytes(self.inputs))
        )
        if not extend:
            self._kill()
            if self.home is not None:
                shutil.rmtree(self.home, ignore_errors=True)
            self._reset()
            self._start()
        if len(target) > len(self.inputs):
            self.feed(target[len(self.inputs) :])
        if snapshot["ended"]:
            self.end()
        if self._digest() != snapshot["digest"] or self.status != snapshot["status"]:
            # The same inputs produced different frames or state: the game reads
            # time or entropy that the adapter does not control.
            self.replay_mismatches += 1
            self.capabilities = dict(self.capabilities, deterministic="replay_differed")

    @staticmethod
    def snapshot_bytes(snapshot):
        return len(snapshot["inputs"]) + 128


@functools.lru_cache(maxsize=32)
def _position_independent(executable):
    with open(executable, "rb") as stream:
        header = stream.read(18)
    return len(header) == 18 and header[:4] == b"\x7fELF" and struct.unpack_from("<H", header, 16)[0] == 3


_live = set()


@atexit.register
def _close_all():
    for engine in list(_live):
        try:
            engine.close()
        except Exception:
            pass


def determinism(make_runner, spec, ticks=30):
    """Play the neutral input twice from fresh launches and compare every frame."""
    neutral = bytes.fromhex(spec["input"]["neutral"]) * min(ticks, spec["limits"]["max_ticks"])
    observed = []
    for _ in range(2):
        runner = make_runner()
        try:
            runner.feed(neutral)
            observed.append((runner.engine.stdout.tail(0), runner.engine.stderr.tail(0), runner.status))
        finally:
            runner.engine.close()
    first, second = observed
    identical = first == second
    difference = None
    if not identical:
        size = gs.record_sizes(spec)["stdout"] or 1
        for index in range(0, min(len(first[0]), len(second[0])), size):
            if first[0][index : index + size] != second[0][index : index + size]:
                difference = index // size
                break
    return {"ticks": len(neutral) // spec["input"]["record_bytes"], "identical": identical, "first_difference_tick": difference}
