"""Native play-testing lane: real processes stepped through their adapters.

The SDL2 tests build a small SDL2 program twice (a planted speed change in the
candidate) and play it through the LD_PRELOAD adapter on a virtual X display; they
need Linux, SDL2 development files, a C compiler and Xvfb. The Godot test needs a
Godot 4 executable in HA_TEST_GODOT and runs headless. These exercise real native
processes, not a signed-in model.
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
        assert described["sides"][side]["determinism"]["identical"] is True
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


func _ready() -> void:
	luck = randi() % 1000


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
    assert described["sides"]["candidate"]["determinism"]["identical"] is True
    played = games.play(context, {"side": "both", "actions": ["move_right", "wait"]})
    state = played["candidate"]["state"]
    # Fixed 60 fps: thirty pressed frames move exactly thirty units.
    assert played["outcome"] == "pass" and abs(state["x"] - 30.0) < 1e-6
    again = games.play(_context(root, godot=engine), {"actions": ["move_right"]})
    assert again["observation"]["state"]["luck"] == state["luck"]
    games.sessions.clear()
