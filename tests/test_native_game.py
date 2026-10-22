"""Native play-testing lane: real processes stepped through their adapters.

The SDL2 tests build a small SDL2 program twice (a planted speed change in the
candidate) and play it through the LD_PRELOAD adapter on a virtual X display; they
need Linux, SDL2 development files, a C compiler and Xvfb. The Godot test needs a
Godot 4 executable in HA_TEST_GODOT and runs headless. These exercise real native
processes, not a signed-in model. The seeded-randomness test needs Linux and a C
compiler only.
"""

import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from hivemind_assembly.core import game_spec as gs
from hivemind_assembly.core.common import Blocked
from hivemind_assembly.core.domain import ToolContext
from hivemind_assembly.core.jobs import Jobs
from hivemind_assembly.domains.reverse_engineering import native_game
from hivemind_assembly.domains.reverse_engineering.game_play import GamePlay

GAME = r"""#include <SDL2/SDL.h>
#include <stdlib.h>
#include <time.h>
struct hero { int lives; float x; float y; int score; };
struct hero *player;
int frames;
int main(void) {
    static struct hero hero = {3, 10.0f, 20.0f, 0};
    player = &hero;
    SDL_Init(SDL_INIT_VIDEO);
    SDL_Window *window = SDL_CreateWindow("ha", 0, 0, 64, 48, 0);
    SDL_Renderer *renderer = SDL_CreateRenderer(window, -1, SDL_RENDERER_SOFTWARE);
    srand((unsigned)time(NULL));
    int bonus = rand() % 100;
    Uint32 last = SDL_GetTicks();
    volatile int spin = 1;
    for (;;) {
        SDL_Event event;
        while (SDL_PollEvent(&event)) {
            if (event.type == SDL_QUIT) return 0;
            if (event.type != SDL_KEYDOWN) continue;
            if (event.key.keysym.sym == SDLK_SPACE) hero.score += 1 + bonus;
            if (event.key.keysym.sym == SDLK_c) *(volatile int *)8 = 1;
            if (event.key.keysym.sym == SDLK_f) while (spin) {}
        }
        const Uint8 *keys = SDL_GetKeyboardState(NULL);
        Uint32 now = SDL_GetTicks();
        float step = (float)(now - last) * SPEED;
        last = now;
        if (keys[SDL_SCANCODE_RIGHT]) hero.x += step;
        if (keys[SDL_SCANCODE_LEFT]) hero.x -= step;
        frames++;
        SDL_SetRenderDrawColor(renderer, 0, 0, 0, 255);
        SDL_RenderClear(renderer);
        SDL_Rect body = {(int)hero.x, (int)hero.y, 4, 4};
        SDL_SetRenderDrawColor(renderer, 255, 255, 255, 255);
        SDL_RenderFillRect(renderer, &body);
        SDL_RenderPresent(renderer);
        SDL_Delay(16);
    }
}
"""

SPEC = {
    "version": 1,
    "name": "Native test game",
    "native": {
        "adapter": "sdl2",
        "original": {"executable": "original/game"},
        "candidate": {"executable": "candidate/game"},
        "inputs": [{"key": "Left"}, {"key": "Right"}, {"key": "Space"}, {"key": "C"}, {"key": "F"}],
        "state": [
            {"name": "lives", "type": "i32", "symbol": "player", "pointers": [0]},
            {"name": "x", "type": "f32", "symbol": "player", "pointers": [4]},
            {"name": "score", "type": "i32", "symbol": "player", "pointers": [12]},
            {"name": "frames", "type": "i32", "symbol": "frames"},
        ],
        "frame": {"width": 16, "height": 12},
        "tick_seconds": 3,
        "startup_seconds": 30,
        "action_ticks": 4,
    },
    "rules": [{"id": "lives_kept", "field": "lives", "equals": 3}],
    "cells": {"fields": ["x"], "quantize": {"x": 4}},
    "limits": {"max_ticks": 400},
}


def _sdl_game(tmp_path):
    if not sys.platform.startswith("linux"):
        pytest.skip("The SDL2 adapter runs on Linux")
    config = shutil.which("sdl2-config")
    compiler = os.environ.get("HA_TEST_CLANG") or shutil.which("clang") or shutil.which("gcc")
    if not config or not compiler or not shutil.which("Xvfb"):
        pytest.skip("Native SDL2 play needs SDL2 development files, a C compiler and Xvfb")
    flags = subprocess.run([config, "--cflags", "--libs"], capture_output=True, text=True, check=True).stdout.split()
    root = tmp_path / "game"
    for side, speed in (("original", "0.06f"), ("candidate", "0.07f")):
        folder = root / side
        folder.mkdir(parents=True)
        (folder / "game.c").write_text(GAME)
        subprocess.run(
            [compiler, "-O2", "-g", f"-DSPEED={speed}", "-o", str(folder / "game"), str(folder / "game.c"), *flags],
            check=True,
            timeout=120,
        )
        (folder / "game.c").unlink()
    (root / "game.json").write_text(json.dumps(SPEC))
    return root, compiler


def _context(root, compiler="", native=True, cancel=None, godot=""):
    return ToolContext(
        root,
        {"foundations": {"c_compiler": compiler, "godot": godot}},
        Jobs(),
        cancel or threading.Event(),
        native=native,
    )


def test_native_contract_derives_inputs_outputs_and_state():
    spec = gs.validate(SPEC)
    assert spec["input"]["record_bytes"] == 1 and spec["input"]["controls"]["right"] == "02"
    assert spec["actions"]["right"] == [["right", 4]] and spec["actions"]["wait"] == [["none", 4]]
    assert [s["name"] for s in spec["output"]["stdout"]] == ["state", "frame"]
    assert [(f["name"], f["offset"], f["type"]) for f in spec["state"]["fields"]] == [
        ("lives", 0, "i32"), ("x", 4, "f32"), ("score", 8, "i32"), ("frames", 12, "i32")
    ]
    assert gs.validate(spec) == spec
    assert native_game.sdl_key("Left") == (80, 1073741904) and native_game.sdl_key("space") == (44, 32)


def test_native_play_needs_the_owners_permission(tmp_path):
    root = tmp_path / "game"
    root.mkdir()
    (root / "game.json").write_text(json.dumps(SPEC))
    games = GamePlay()
    described = games.describe(_context(root, native=False), {})
    assert described["sides"]["candidate"] == {"available": False, "reason": native_game.PERMISSION}
    with pytest.raises(Blocked, match="trusted native execution"):
        games.play(_context(root, native=False), {"actions": ["right"]})


def test_sdl2_games_play_compare_and_stop_deterministically(tmp_path):
    root, compiler = _sdl_game(tmp_path)
    games = GamePlay()
    context = _context(root, compiler)
    described = games.describe(context, {})
    for side in ("original", "candidate"):
        assert described["sides"][side]["capabilities"]["runtime"] == "native_sdl2"
        probe = described["sides"][side]["determinism"]
        if not probe["identical"]:
            pytest.fail(json.dumps({key: probe.get(key) for key in ("first_difference_tick", "first_difference", "runs")}))
    played = games.play(context, {"side": "original", "actions": ["wait", "space", "right"], "images": 1})
    state = played["observation"]["state"]
    # Memory through a pointer path, the time-seeded bonus and virtual time all agree run to run.
    # Twelve input ticks follow the startup frame, which the game also counts.
    assert played["outcome"] == "pass" and state["lives"] == 3 and state["frames"] == 13
    assert state["score"] > 0 and state["x"] > 10.0
    again = games.play(_context(root, compiler), {"side": "original", "actions": ["wait", "space", "right"]})
    assert again["observation"]["state"] == state
    assert played["_images"][0]["data"][:8] == b"\x89PNG\r\n\x1a\n"
    compared = games.play(context, {"side": "both", "actions": ["wait", "right"]})
    divergence = compared["comparison"]["divergence"]
    # The candidate's planted speed change shows on the first frame that moves.
    assert compared["outcome"] == "divergence" and divergence["signature"] == ["divergence", "state:x"]
    assert divergence["tick"] == 4
    crashed = games.play(context, {"actions": ["wait", "c"]})
    assert crashed["outcome"] == "crash" and crashed["findings"][0]["detail"]["fault"]["signal"] == "SIGSEGV"
    frozen = games.play(context, {"actions": ["f"]})
    assert frozen["outcome"] == "freeze"
    assert frozen["findings"][0]["detail"]["stop_context"]["reason"] == "frame_timeout"
    explored = games.test(context, {"mode": "explore", "side": "both", "steps": 4, "seed": 0, "seconds": 120})
    assert explored["steps_run"] >= 1 and explored["findings"][0]["signature"][0] in ("divergence", "crash", "freeze")
    shrunk = games.test(
        context,
        {"mode": "shrink", "side": "both", "trajectory": compared["trajectory"], "signature": divergence["signature"], "seconds": 120},
    )
    assert shrunk["reproduced"] and shrunk["confirmed"] and shrunk["controls"] == ["right"]
    games.sessions.clear()
    leftover = [engine for engine in native_game._live if engine.process.poll() is None]
    for engine in leftover:
        engine.close()
    # Only the two cached play sessions may hold game processes; all else is closed.
    assert len(leftover) <= 4


WAITING_GAME = r"""#include <SDL2/SDL.h>
#include <unistd.h>
int x, presses;
int main(void) {
#ifdef SLOW_START
    sleep(SLOW_START); /* a long load before the first frame */
#endif
    SDL_Init(SDL_INIT_VIDEO);
    SDL_Window *window = SDL_CreateWindow("ha", 0, 0, 64, 48, SDL_WINDOW_SHOWN);
    SDL_Renderer *renderer = SDL_CreateRenderer(window, -1, SDL_RENDERER_SOFTWARE);
    for (;;) {
        SDL_SetRenderDrawColor(renderer, 0, 0, 0, 255);
        SDL_RenderClear(renderer);
        SDL_Rect body = {x * 4, 20, 4, 4};
        SDL_SetRenderDrawColor(renderer, 255, 255, 255, 255);
        SDL_RenderFillRect(renderer, &body);
        SDL_RenderPresent(renderer);
        SDL_Event event;
        if (!SDL_WaitEvent(&event)) return 1;
        if (event.type == SDL_QUIT) return 0;
        if (event.type == SDL_KEYDOWN && event.key.keysym.sym == SDLK_RIGHT) { x++; presses++; }
        /* Window-system events arrive at times that differ between runs. */
        if (event.type == SDL_WINDOWEVENT || event.type == SDL_MOUSEMOTION) x += 100;
    }
}
"""


def test_event_driven_sdl2_games_see_each_press_on_its_tick(tmp_path):
    root, compiler = _sdl_game(tmp_path)
    flags = subprocess.run(["sdl2-config", "--cflags", "--libs"], capture_output=True, text=True, check=True).stdout.split()
    (root / "waiting.c").write_text(WAITING_GAME)
    subprocess.run([compiler, "-O2", "-g", "-o", str(root / "waiting"), str(root / "waiting.c"), *flags], check=True, timeout=120)
    spec = {
        "version": 1,
        "name": "Event-driven test game",
        "native": {
            "adapter": "sdl2",
            "original": {"executable": "waiting"},
            "candidate": {"executable": "waiting"},
            "inputs": [{"key": "Right"}],
            "state": [{"name": "x", "type": "i32", "symbol": "x"}, {"name": "presses", "type": "i32", "symbol": "presses"}],
            "frame": {"width": 16, "height": 12},
            "action_ticks": 1,
        },
        # A turn-based press: down for one tick, up for the next.
        "actions": {"right": [["right", 1], ["none", 1]], "wait": [["none", 1]]},
        "limits": {"max_ticks": 100},
    }
    (root / "waiting.json").write_text(json.dumps(spec))
    games = GamePlay()
    context = _context(root, compiler)
    described = games.describe(context, {"game_path": "waiting.json"})
    assert described["sides"]["original"]["determinism"]["identical"] is True
    played = games.play(context, {"game_path": "waiting.json", "side": "both", "actions": ["right", "right", "wait", "right"]})
    # Each press lands on its own tick and no window-system event reaches the game.
    assert played["outcome"] == "pass" and played["original"]["state"] == {"x": 3, "presses": 3}
    assert played["original"]["ticks"] == played["original"]["input_ticks"] == played["comparison"]["compared_ticks"] == 7
    games.sessions.clear()


def test_sdl2_startup_limit_covers_loading_before_the_first_frame(tmp_path):
    root, compiler = _sdl_game(tmp_path)
    flags = subprocess.run(["sdl2-config", "--cflags", "--libs"], capture_output=True, text=True, check=True).stdout.split()
    (root / "slow.c").write_text(WAITING_GAME)
    subprocess.run([compiler, "-O2", "-g", "-DSLOW_START=3", "-o", str(root / "slow"), str(root / "slow.c"), *flags], check=True, timeout=120)
    spec = {
        "version": 1,
        "name": "Slow-loading test game",
        "native": {
            "adapter": "sdl2",
            "original": {"executable": "slow"},
            "candidate": {"executable": "slow"},
            "inputs": [{"key": "Right"}],
            "state": [{"name": "x", "type": "i32", "symbol": "x"}],
            "tick_seconds": 1,
            "startup_seconds": 30,
            "action_ticks": 1,
        },
        "actions": {"right": [["right", 1], ["none", 1]], "wait": [["none", 1]]},
        "limits": {"max_ticks": 20},
    }
    (root / "slow.json").write_text(json.dumps(spec))
    games = GamePlay()
    # Loading takes longer than a frame may; it counts against the startup limit.
    played = games.play(_context(root, compiler), {"game_path": "slow.json", "side": "original", "actions": ["right"]})
    assert played["outcome"] == "pass" and played["observation"]["state"] == {"x": 1}
    games.sessions.clear()


ENTROPY_PROGRAM = r"""#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <sys/random.h>
#include <sys/resource.h>
#include <sys/syscall.h>
#include <unistd.h>
int main(int argc, char **argv) {
    unsigned char a[8], b[8], c[8];
    if (argc < 2 || getrandom(a, sizeof a, 0) != 8 || syscall(SYS_getrandom, b, sizeof b, 0) != 8 || getentropy(c, sizeof c)) return 2;
    void *library = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL | RTLD_DEEPBIND);
    unsigned long long (*draw)(void) = library ? (unsigned long long (*)(void))dlsym(library, "draw") : 0;
    if (!draw) return 3;
    struct rlimit core;
    getrlimit(RLIMIT_CORE, &core);
    printf("%02x%02x%02x%02x %02x%02x%02x%02x %02x%02x%02x%02x %llx %llu\n", a[0], a[1], a[2], a[3], b[0], b[1], b[2], b[3], c[0], c[1], c[2], c[3], draw(),
           (unsigned long long)core.rlim_cur);
    return 0;
}
"""
ENTROPY_EXTENSION = r"""#include <sys/random.h>
unsigned long long draw(void) {
    unsigned long long value = 0;
    getrandom(&value, sizeof value, 0);
    return value;
}
"""


def test_seeded_randomness_reaches_deep_bound_libraries(tmp_path):
    if not sys.platform.startswith("linux"):
        pytest.skip("The randomness preload runs on Linux")
    compiler = os.environ.get("HA_TEST_CLANG") or shutil.which("clang") or shutil.which("gcc")
    if not compiler:
        pytest.skip("Seeded randomness needs a C compiler")
    (tmp_path / "program.c").write_text(ENTROPY_PROGRAM)
    (tmp_path / "extension.c").write_text(ENTROPY_EXTENSION)
    subprocess.run([compiler, "-O2", "-o", str(tmp_path / "program"), str(tmp_path / "program.c"), "-ldl"], check=True, timeout=120)
    subprocess.run(
        [compiler, "-O2", "-shared", "-fPIC", "-o", str(tmp_path / "extension.so"), str(tmp_path / "extension.c")], check=True, timeout=120
    )
    library = native_game._library("ha_entropy", compiler, tuple(native_game._stamp(compiler)))

    import resource

    hard = resource.getrlimit(resource.RLIMIT_CORE)[1]

    def allow_core_dumps():
        resource.setrlimit(resource.RLIMIT_CORE, (hard, hard))

    def draw(**extra):
        environment = {"PATH": os.environ.get("PATH", ""), "LD_PRELOAD": library, **extra}
        completed = subprocess.run(
            [str(tmp_path / "program"), str(tmp_path / "extension.so")],
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
            preexec_fn=allow_core_dumps,
        )
        assert completed.returncode == 0, completed.stderr
        *values, core = completed.stdout.split()
        # While HA drives a game, a crash must not wait for a core dump.
        allowed = (1 << 64) - 1 if hard == resource.RLIM_INFINITY else hard
        assert int(core) == (min(allowed, 1) if extra else allowed)
        return values

    seeded = draw(HA_TICK_PORT="1", HA_TICK_SEED="3")
    # getrandom, syscall(SYS_getrandom), getentropy and a library Godot-style opened with
    # RTLD_DEEPBIND all repeat for a seed, and change with it.
    assert draw(HA_TICK_PORT="1", HA_TICK_SEED="3") == seeded
    changed = draw(HA_TICK_PORT="1", HA_TICK_SEED="4")
    assert all(a != b for a, b in zip(seeded, changed))
    # The program's own requests and the library's come from separate streams.
    assert len(set(seeded)) == 4
    # Outside an HA run the preload forwards to the operating system.
    assert draw() != draw()


GODOT_PROJECT = """config_version=5

[application]

config/name="HA adapter test"
run/main_scene="res://main.tscn"

[input]

move_right={
"deadzone": 0.5,
"events": [Object(InputEventKey,"resource_local_to_scene":false,"resource_name":"","device":-1,"window_id":0,"alt_pressed":false,"shift_pressed":false,"ctrl_pressed":false,"meta_pressed":false,"pressed":false,"keycode":0,"physical_keycode":4194321,"key_label":0,"unicode":0,"location":0,"echo":false,"script":null)
]
}
"""
GODOT_SCENE = """[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://main.gd" id="1"]

[node name="Main" type="Node2D"]
script = ExtResource("1")
"""
GODOT_SCRIPT = """extends Node2D

var x := 0.0
var luck := 0
var token := 0


func _ready() -> void:
	luck = randi() % 1000
	token = Crypto.new().generate_random_bytes(4).decode_u32(0)


func _physics_process(delta: float) -> void:
	if Input.is_action_pressed("move_right"):
		x += 60.0 * delta
"""


def test_godot_projects_step_one_physics_frame_per_input(tmp_path):
    engine = os.environ.get("HA_TEST_GODOT")
    if not engine or not Path(engine).is_file():
        pytest.skip("Set HA_TEST_GODOT to a Godot 4 executable")
    root = tmp_path / "game"
    project = root / "project"
    project.mkdir(parents=True)
    (project / "project.godot").write_text(GODOT_PROJECT)
    (project / "main.tscn").write_text(GODOT_SCENE)
    (project / "main.gd").write_text(GODOT_SCRIPT)
    spec = {
        "version": 1,
        "name": "Godot adapter test",
        "native": {
            "adapter": "godot",
            "original": {"project": "project"},
            "candidate": {"project": "project"},
            "inputs": [{"action": "move_right"}],
            "state": [
                {"name": "x", "type": "f64", "node": "Main", "property": "x"},
                {"name": "luck", "type": "i32", "node": "Main", "property": "luck"},
                {"name": "token", "type": "u32", "node": "Main", "property": "token"},
            ],
            "display": "headless",
            "seed": 3,
            "action_ticks": 30,
        },
        "limits": {"max_ticks": 200},
    }
    (root / "game.json").write_text(json.dumps(spec))
    games = GamePlay()
    context = _context(root, godot=engine)
    described = games.describe(context, {})
    # The adapter seeds Godot's own generator; Crypto draws operating-system randomness,
    # which the Linux preload seeds when a C compiler is available.
    seeded = described["sides"]["candidate"]["capabilities"]["os_randomness"] == "seeded"
    assert seeded == (sys.platform.startswith("linux") and bool(shutil.which("clang") or shutil.which("gcc") or shutil.which("cc")))
    assert described["sides"]["candidate"]["determinism"]["identical"] is seeded
    played = games.play(context, {"side": "both", "actions": ["move_right", "wait"]})
    state = played["candidate"]["state"]
    # Fixed 60 fps: thirty pressed frames move exactly thirty units.
    assert played["outcome"] == ("pass" if seeded else "divergence")
    assert abs(state["x"] - 30.0) < 1e-6
    again = games.play(_context(root, godot=engine), {"actions": ["move_right"]})
    assert again["observation"]["state"]["luck"] == state["luck"]
    games.sessions.clear()
