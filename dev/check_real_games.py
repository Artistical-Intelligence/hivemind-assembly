"""Play-test real free games through HA's native lane and print the evidence.

Reproduces the real-game checks recorded in dev/GAME_TESTING.md on Linux:

* Godot: the official "Dodge the Creeps" demo (GDScript) at a pinned commit, played
  through the Godot adapter, and the same game rebuilt in Rust with godot-rust,
  compared tick by tick against the GDScript original. The Rust port draws on
  operating-system randomness, which the Linux preload seeds.
* C++: Chromium B.S.U. 0.9.16.1. Ubuntu's packaged binary is compared by frames with
  a rebuild of the same source, and the rebuild is compared by memory state with a
  variant that has a planted copy-paste defect (the hero's upper bound uses the
  horizontal limit).
* Rust: sokoban-rs (SDL2, event-driven) at a pinned commit with a small level file
  written here, compared by frames with a variant that has a planted defect (a box
  can be pushed into another box).

Everything is pinned by commit or checksum. Nothing is installed system-wide: when a
prerequisite is missing the script prints the Ubuntu packages to install and stops.
Results are scripted, seeded play by HA's harness, not play by a signed-in model.

    python dev/check_real_games.py --work /tmp/ha-real-games [--godot PATH] [--report out.json]
"""

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "_app"))

from hivemind_assembly.core import game_spec as gs  # noqa: E402
from hivemind_assembly.core.domain import ToolContext  # noqa: E402
from hivemind_assembly.core.jobs import Jobs  # noqa: E402
from hivemind_assembly.domains.reverse_engineering.game_play import GamePlay  # noqa: E402

GODOT_URL = "https://github.com/godotengine/godot/releases/download/4.7.1-stable/Godot_v4.7.1-stable_linux.x86_64.zip"
GODOT_SHA512 = "4ccdab7a48eeccbe8819a2fc1f6262f8d72065d98601bcb3743fcbd7ebd39f373758a788ee3293a05ec5b2c48538266c437404312e372225cd2df273945a2de9"
DEMOS = ("https://github.com/godotengine/godot-demo-projects", "b761b4cd5718a7118f2c95eb55f181d0a5f004f1")
RUST_DEMOS = ("https://github.com/godot-rust/demo-projects", "3b295b36c051cff3239faf0351a8b465f1802520")
GDEXT_REV = "395476db593eb1cd859336fbb43eb113e5ae6cfb"
CBSU_URL = "http://archive.ubuntu.com/ubuntu/pool/universe/c/chromium-bsu/chromium-bsu_0.9.16.1.orig.tar.gz"
CBSU_SHA256 = "a1c141a34d19a59607ae81166a19864eb8c84cf86b155462fed31a6d56e1624a"
SOKOBAN = ("https://github.com/swatteau/sokoban-rs", "6daeee9dcc24f000a19442ed96a328143798b10b")
PACKAGES = (
    "xvfb libsdl2-dev clang git cargo chromium-bsu libalut-dev libglc-dev libglu1-mesa-dev libopenal-dev "
    "libsdl2-image-dev libsdl2-ttf-dev pkg-config"
)

DODGE_INPUTS = [{"action": a} for a in ("move_left", "move_right", "move_up", "move_down", "start_game")]
DODGE_STATE = [
    {"name": "x", "type": "f32", "node": "Main/Player", "property": "position:x"},
    {"name": "y", "type": "f32", "node": "Main/Player", "property": "position:y"},
    {"name": "alive", "type": "u8", "node": "Main/Player", "property": "visible"},
    {"name": "mobs", "type": "u16", "group": "mobs"},
]
DODGE_RULES = [
    {"id": "inside_x", "field": "x", "min": 0, "max": 480},
    {"id": "inside_y", "field": "y", "min": 0, "max": 720},
    {"id": "finite_x", "field": "x", "finite": True},
    {"id": "finite_y", "field": "y", "finite": True},
]
CBSU_ARGS = ["--window", "--vidmode", "0", "--noaudio"]
CBSU_INPUTS = [{"key": k} for k in ("Left", "Right", "Up", "Down", "Space", "Return", "Escape")]
CBSU_STATE = [
    {"name": "mode", "type": "i32", "symbol": "_ZN6Global8gameModeE"},
    {"name": "level", "type": "i32", "symbol": "_ZN6Global9gameLevelE"},
    {"name": "lives", "type": "i32", "symbol": "_ZN6Global4heroE", "pointers": [188]},
    {"name": "score", "type": "f32", "symbol": "_ZN6Global4heroE", "pointers": [244]},
    {"name": "x", "type": "f32", "symbol": "_ZN6Global4heroE", "pointers": [8]},
    {"name": "y", "type": "f32", "symbol": "_ZN6Global4heroE", "pointers": [12]},
]
SOKOBAN_ARGS = ["levels.slc", "--width", "320", "--height", "240"]
SOKOBAN_MOVES = ("left", "right", "up", "down", "r", "n")
# sokoban-rs ships without levels; these two are written for this check.
SOKOBAN_LEVELS = """<?xml version="1.0" encoding="UTF-8"?>
<SokobanLevels>
  <Title>HA play-testing levels</Title>
  <LevelCollection>
    <Level Id="Two boxes" Width="9" Height="5">
      <L>#########</L>
      <L>#   .   #</L>
      <L>#  $ $  #</L>
      <L># @  .  #</L>
      <L>#########</L>
    </Level>
    <Level Id="One push" Width="5" Height="3">
      <L>#####</L>
      <L>#@$.#</L>
      <L>#####</L>
    </Level>
  </LevelCollection>
</SokobanLevels>
"""
CBSU_RULES = [
    {"id": "hero_inside_y", "field": "y", "min": -7.5, "max": 7.5, "when": [{"field": "mode", "op": "==", "value": 0}]},
    {"id": "hero_inside_x", "field": "x", "min": -10, "max": 10, "when": [{"field": "mode", "op": "==", "value": 0}]},
    {"id": "lives_range", "field": "lives", "min": 0, "max": 9},
    {"id": "finite_position", "field": "y", "finite": True},
]


def run(command, cwd=None, env=None, timeout=3600):
    print("+", " ".join(str(c) for c in command), flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True, timeout=timeout)


def sha(path, kind="sha256"):
    digest = hashlib.new(kind)
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def download(url, target, expected, kind):
    if not target.is_file() or sha(target, kind) != expected:
        print("download", url, flush=True)
        with urllib.request.urlopen(url, timeout=600) as response, open(target, "wb") as out:
            shutil.copyfileobj(response, out)
    if sha(target, kind) != expected:
        raise SystemExit(f"Checksum mismatch for {url}")
    return target


def checkout(url, commit, folder, sparse=()):
    if not (folder / ".git").is_dir():
        run(["git", "clone", "--filter=blob:none", "--no-checkout", url, str(folder)])
    if sparse:
        run(["git", "-C", str(folder), "sparse-checkout", "set", *sparse])
    run(["git", "-C", str(folder), "checkout", "--quiet", commit])
    return folder


def _pkg_config(*names):
    if not shutil.which("pkg-config"):
        return False
    return subprocess.run(["pkg-config", "--exists", *names], check=False).returncode == 0


def prerequisites():
    missing = [
        name
        for name, present in (
            ("Linux", sys.platform.startswith("linux")),
            ("Xvfb", shutil.which("Xvfb")),
            ("SDL2 development files", shutil.which("sdl2-config")),
            ("a C compiler", shutil.which("clang") or shutil.which("gcc")),
            ("git", shutil.which("git")),
            ("cargo", shutil.which("cargo")),
            ("the chromium-bsu package", Path("/usr/games/chromium-bsu").is_file()),
            ("SDL2_image and SDL2_ttf development files", _pkg_config("SDL2_image", "SDL2_ttf")),
        )
        if not present
    ]
    if missing:
        raise SystemExit("Missing: " + ", ".join(missing) + f"\nOn Ubuntu: sudo apt-get install {PACKAGES}")


def godot_engine(work, given):
    if given:
        return Path(given).resolve()
    archive = download(GODOT_URL, work / "godot.zip", GODOT_SHA512, "sha512")
    folder = work / "godot"
    if not (folder / "Godot_v4.7.1-stable_linux.x86_64").is_file():
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(folder)
    engine = folder / "Godot_v4.7.1-stable_linux.x86_64"
    engine.chmod(0o755)
    return engine


def godot_games(work):
    demos = checkout(*DEMOS, work / "godot-demo-projects", sparse=("2d/dodge_the_creeps",))
    rust = checkout(*RUST_DEMOS, work / "godot-rust-demos")
    manifest = rust / "dodge-the-creeps" / "rust" / "Cargo.toml"
    text = manifest.read_text()
    pinned = f'godot = {{ git = "https://github.com/godot-rust/gdext.git", rev = "{GDEXT_REV}", features = ["register-docs"]}}'
    if GDEXT_REV not in text:
        manifest.write_text(text.replace('godot = { git = "https://github.com/godot-rust/gdext.git", features = ["register-docs"]}', pinned))
    env = dict(os.environ, CARGO_NET_GIT_FETCH_WITH_CLI="true")
    run(["cargo", "build", "--release", "-p", "dodge-the-creeps"], cwd=rust, env=env)
    workspace = work / "ws-dodge"
    shutil.rmtree(workspace, ignore_errors=True)
    shutil.copytree(demos / "2d" / "dodge_the_creeps", workspace / "gdscript")
    shutil.copytree(rust / "dodge-the-creeps" / "godot", workspace / "rust")
    (workspace / "rust" / "bin").mkdir()
    shutil.copy2(rust / "target" / "release" / "libdodge_the_creeps.so", workspace / "rust" / "bin")
    extension = workspace / "rust" / "rust.gdextension"
    extension.write_text(
        extension.read_text()
        .replace("res://../../target/release/libdodge_the_creeps.so", "res://bin/libdodge_the_creeps.so")
        .replace("res://../../target/debug/libdodge_the_creeps.so", "res://bin/libdodge_the_creeps.so")
    )
    return workspace


def dodge_spec(name, original, candidate):
    spec = {
        "version": 1,
        "name": name,
        "native": {
            "adapter": "godot",
            "original": {"project": original},
            "candidate": {"project": candidate},
            "inputs": DODGE_INPUTS,
            "state": DODGE_STATE,
            "frame": {"width": 48, "height": 72},
            "seed": 7,
            "action_ticks": 10,
        },
        "rules": DODGE_RULES,
        "cells": {"fields": ["x", "y", "alive"], "quantize": {"x": 60, "y": 90}},
        # Frames are shown, not compared: the ports draw different interface text.
        "compare": {"segments": {"frame": {"max_channel_error": 255, "max_bad_pixels": 48 * 72}}},
        "limits": {"max_ticks": 1500},
    }
    playing = gs.expand(gs.validate(spec), ["wait", "start_game"] + ["wait"] * 16)
    spec["starts"] = {"playing": {"inputs_hex": playing.hex(), "expect": [{"field": "alive", "op": "==", "value": 1}]}}
    return spec


def chromium(work):
    archive = download(CBSU_URL, work / "chromium-bsu_0.9.16.1.orig.tar.gz", CBSU_SHA256, "sha256")
    source = work / "chromium-bsu-0.9.16.1"
    if not (source / "src" / "chromium-bsu").is_file():
        with tarfile.open(archive) as bundle:
            bundle.extractall(work, filter="data")
        run(["./configure", "--datadir=/usr/share/games", "--disable-glpng", "CXXFLAGS=-O2 -g -Wall"], cwd=source)
        run(["make", "-j2", "-C", "src"], cwd=source)
    variant = work / "chromium-bsu-variant"
    if not (variant / "src" / "chromium-bsu").is_file():
        shutil.rmtree(variant, ignore_errors=True)
        run(["cp", "-a", str(source), str(variant)])
        hero = variant / "src" / "HeroAircraft.cpp"
        text = hero.read_text()
        defect = text.replace(
            "else if\t(pos[1] > bound[1][1])\tpos[1] = bound[1][1];",
            "else if\t(pos[1] > bound[0][1])\tpos[1] = bound[0][1];",
        )
        if defect == text:
            raise SystemExit("The planted defect no longer applies to HeroAircraft.cpp")
        hero.write_text(defect)
        run(["make", "-j2", "-C", "src"], cwd=variant)
    workspace = work / "ws-chromium"
    shutil.rmtree(workspace, ignore_errors=True)
    for folder, binary in (
        ("ubuntu", Path("/usr/games/chromium-bsu")),
        ("rebuild", source / "src" / "chromium-bsu"),
        ("defect", variant / "src" / "chromium-bsu"),
    ):
        (workspace / folder).mkdir(parents=True)
        shutil.copy2(binary, workspace / folder / "chromium-bsu")
    common = {"adapter": "sdl2", "inputs": CBSU_INPUTS, "frame": {"width": 64, "height": 48}, "seed": 5, "action_ticks": 8}
    frames = {
        "version": 1,
        "name": "Chromium B.S.U.: Ubuntu build vs rebuild (frames)",
        "native": common | {
            "original": {"executable": "ubuntu/chromium-bsu", "args": CBSU_ARGS},
            "candidate": {"executable": "rebuild/chromium-bsu", "args": CBSU_ARGS},
        },
        "limits": {"max_ticks": 1500},
    }
    state = {
        "version": 1,
        "name": "Chromium B.S.U.: rebuild vs planted defect (state)",
        "native": common | {
            "original": {"executable": "rebuild/chromium-bsu", "args": CBSU_ARGS},
            "candidate": {"executable": "defect/chromium-bsu", "args": CBSU_ARGS},
            "state": CBSU_STATE,
        },
        "rules": CBSU_RULES,
        "cells": {"fields": ["mode", "x", "y"], "quantize": {"x": 2, "y": 2}},
        "limits": {"max_ticks": 1500},
    }
    playing = gs.expand(gs.validate(state), ["wait", "wait", "return", "wait", "wait", "wait"])
    state["starts"] = {"playing": {"inputs_hex": playing.hex(), "expect": [{"field": "mode", "op": "==", "value": 0}]}}
    (workspace / "frames.json").write_text(json.dumps(frames, indent=2))
    (workspace / "state.json").write_text(json.dumps(state, indent=2))
    package = subprocess.run(["dpkg-query", "-W", "-f=${Version}", "chromium-bsu"], capture_output=True, text=True)
    return workspace, {
        "ubuntu_package": package.stdout.strip(),
        "binaries": {f: sha(workspace / f / "chromium-bsu") for f in ("ubuntu", "rebuild", "defect")},
    }


def sokoban(work):
    source = checkout(*SOKOBAN, work / "sokoban-rs")
    run(["cargo", "build", "--release"], cwd=source)
    variant = work / "sokoban-rs-variant"
    if not (variant / "target" / "release" / "sokoban-rs").is_file():
        shutil.rmtree(variant, ignore_errors=True)
        run(["cp", "-a", str(source), str(variant)])
        game = variant / "src" / "game.rs"
        text = game.read_text()
        defect = text.replace(
            "let next_to_box = next_to_player.neighbor(dir);\n            if self.is_free(&next_to_box) {",
            "let next_to_box = next_to_player.neighbor(dir);\n            if !self.is_wall(&next_to_box) {",
        )
        if defect == text:
            raise SystemExit("The planted defect no longer applies to src/game.rs")
        game.write_text(defect)
        run(["cargo", "build", "--release"], cwd=variant)
    workspace = work / "ws-sokoban"
    shutil.rmtree(workspace, ignore_errors=True)
    for folder, tree in (("upstream", source), ("defect", variant)):
        shutil.copytree(tree / "assets", workspace / folder / "assets", ignore=shutil.ignore_patterns("Makefile", "screenshot.png"))
        shutil.copy2(tree / "target" / "release" / "sokoban-rs", workspace / folder / "sokoban-rs")
        (workspace / folder / "levels.slc").write_text(SOKOBAN_LEVELS)
    spec = {
        "version": 1,
        "name": "sokoban-rs (Rust, SDL2): upstream vs planted push defect",
        "native": {
            "adapter": "sdl2",
            "original": {"executable": "upstream/sokoban-rs", "folder": "upstream", "args": SOKOBAN_ARGS},
            "candidate": {"executable": "defect/sokoban-rs", "folder": "defect", "args": SOKOBAN_ARGS},
            "inputs": [{"key": k} for k in ("Left", "Right", "Up", "Down", "R", "N")],
            "frame": {"width": 128, "height": 96},
            "seed": 1,
            "action_ticks": 1,
        },
        # Turn-based moves: a key goes down for one tick and up for the next.
        "actions": {m: [[m, 1], ["none", 1]] for m in SOKOBAN_MOVES} | {"wait": [["none", 1]]},
        "limits": {"max_ticks": 600},
    }
    (workspace / "sokoban.json").write_text(json.dumps(spec, indent=2))
    return workspace, {"binaries": {f: sha(workspace / f / "sokoban-rs") for f in ("upstream", "defect")}}


def summary(result, keys):
    return {key: result.get(key) for key in keys}


def finding(item):
    return {"signature": item["signature"], "tick": item["tick"], "trajectory_ticks": item.get("trajectory_ticks")}


def evaluate(games, context, game, report, name, modes, start="playing", script=None):
    """Describe, optionally play a script, then explore (both builds and/or one alone),
    shrinking the first finding."""
    base = {"game_path": game}
    described = games.describe(context, base)
    report[name] = {
        "determinism": {s: described["sides"][s].get("determinism") for s in described["sides"]},
        "os_randomness": {s: (described["sides"][s].get("capabilities") or {}).get("os_randomness") for s in described["sides"]},
    }
    if script:
        played = games.play(context, base | {"side": "both", "actions": script})
        divergence = played["comparison"]["divergence"]
        report[name]["scripted"] = {
            "actions": script,
            "outcome": played["outcome"],
            "divergence": divergence and {"signature": divergence["signature"], "tick": divergence["tick"]},
        }
    for side in modes:
        started = time.monotonic()
        request = base | {"mode": "explore", "side": side, "steps": 30, "seed": 3, "seconds": 600}
        if start:
            request["start"] = start
        explored = games.test(context, request)
        key = "explore_" + ("both" if side == "both" else "single")
        report[name][key] = summary(explored, ("outcome", "steps_run", "cells", "ticks_executed", "stopped")) | {
            "findings": [finding(f) for f in explored["findings"]],
            "original_behavior": [q["signature"] for q in explored["original_behavior"]],
            "seconds": round(time.monotonic() - started, 1),
        }
        if side == "both" and explored["findings"]:
            first = explored["findings"][0]
            shrunk = games.test(
                context,
                base | {"mode": "shrink", "side": "both", "trajectory": first["trajectory"], "signature": first["signature"], "seconds": 600},
            )
            report[name]["shrink"] = summary(shrunk, ("reproduced", "confirmed", "original_ticks", "minimized_ticks", "tests", "controls", "stopped"))
    print(json.dumps({name: report[name]}, indent=1), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--work", required=True, help="Folder for downloads, builds and workspaces")
    parser.add_argument("--godot", help="Use this Godot 4 executable instead of the pinned 4.7.1 download")
    parser.add_argument("--report", help="Write the JSON report here")
    args = parser.parse_args()
    prerequisites()
    work = Path(args.work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    report = {"host": platform.platform(), "python": platform.python_version(), "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    engine = godot_engine(work, args.godot)
    report["godot"] = {"executable": engine.name, "sha256": sha(engine)}
    games = GamePlay()

    dodge = godot_games(work)
    (dodge / "gdscript.json").write_text(json.dumps(dodge_spec("Dodge the Creeps (GDScript)", "gdscript", "gdscript"), indent=2))
    (dodge / "ports.json").write_text(json.dumps(dodge_spec("Dodge the Creeps: GDScript original vs Rust port", "gdscript", "rust"), indent=2))
    context = ToolContext(dodge, {"foundations": {"godot": str(engine)}}, Jobs(), threading.Event(), native=True)
    evaluate(games, context, "gdscript.json", report, "godot_gdscript", ["candidate"])
    evaluate(games, context, "ports.json", report, "godot_gdscript_vs_rust", ["both"])
    games.sessions.clear()

    chromium_workspace, built = chromium(work)
    report["chromium_bsu"] = built
    compiler = shutil.which("clang") or shutil.which("gcc")
    context = ToolContext(chromium_workspace, {"foundations": {"c_compiler": compiler}}, Jobs(), threading.Event(), native=True)
    evaluate(games, context, "frames.json", report, "cpp_ubuntu_vs_rebuild", ["both"], start=None)
    evaluate(games, context, "state.json", report, "cpp_rebuild_vs_defect", ["both", "candidate"])
    games.sessions.clear()

    sokoban_workspace, built = sokoban(work)
    report["sokoban_rs"] = built
    context = ToolContext(sokoban_workspace, {"foundations": {"c_compiler": compiler}}, Jobs(), threading.Event(), native=True)
    evaluate(games, context, "sokoban.json", report, "rust_upstream_vs_defect", ["both", "original"], start=None, script=["up", "right", "right"])
    games.sessions.clear()
    report["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    text = json.dumps(report, indent=2, default=str)
    if args.report:
        Path(args.report).write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
