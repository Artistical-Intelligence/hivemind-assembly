"""Source-known play-testing example: a small platformer and its reconstruction.

`Coin cavern` reads one controller byte per tick and writes a 16-byte state record
plus a 16x12 RGBA frame to stdout and eight PCM samples to stderr. The original has
a quirk: falling through the floor gap reports y=12 for one tick before respawning,
which violates the declared world-bounds rule in both builds. The editable C
reconstruction has two planted defects that the supplied scripted route does not
reach: it computes ground contact before moving horizontally (a divergence at
platform edges) and its spike knockback never ends when the player lands without
moving (a freeze). Exploration finds both; shrinking reduces them to a few inputs.
Creating or passing this example is not evidence that a model reconstructed it.
"""

import json
import tempfile
from pathlib import Path

from hivemind_assembly.core.common import Blocked

DECLARATIONS = """struct state {
    unsigned short tick;
    signed char x, y;
    unsigned char air, coins, lives, flags;
    unsigned short score;
    unsigned char input, room, pad[4];
};
struct rgba { unsigned char r, g, b, a; };
struct frame { struct state s; struct rgba pixels[12][16]; };
enum { W = 16, H = 12, START_X = 2, START_Y = 10, JUMP = 4, COINS = 4 };
extern struct state game;
extern char level[12][16];
extern short samples[8];
extern struct frame out;
"""

MAP = """static const char *const MAP[12] = {
    "XXXXXXXXXXXXXXXX",
    "X..............X",
    "X..........c...X",
    "X........XXXXX.X",
    "X..............X",
    "X..............X",
    "X.....c........X",
    "X....XXXX......X",
    "X.c............X",
    "X..............X",
    "X........^^..c.X",
    "XXXXXXXXXXXXXX.X",
};
"""

PALETTE = """static const struct rgba PALETTE[4] = {
    {16, 24, 48, 255}, {90, 90, 110, 255}, {250, 210, 40, 255}, {220, 40, 40, 255},
};
static const unsigned char KIND[128] = {['X'] = 1, ['c'] = 2, ['^'] = 3};
"""

ORIGINAL = (
    DECLARATIONS
    + MAP
    + PALETTE
    + r"""struct state game;
char level[12][16];
short samples[8];
struct frame out;

char tile(int x, int y) {
    if (x < 0 || x >= W || y < 0) return 'X';
    if (y >= H) return '.';
    return level[y][x];
}
int solid(int x, int y) { return tile(x, y) == 'X'; }

void respawn(void) {
    game.x = START_X;
    game.y = START_Y;
    game.air = 0;
}

void tone(int amplitude, int period) {
    for (int i = 0; i < 8; ++i)
        samples[i] = (short)(((game.tick * 8 + i) % (2 * period)) < period ? amplitude : -amplitude);
}

void hurt(int dx) {
    int push = dx ? -dx : -1;
    int nx = game.x;
    while (tile(nx, game.y) == '^') nx += push;
    game.x = (signed char)nx;
    game.lives -= 1;
    game.flags |= 4;
    tone(4000, 4);
}

void step(unsigned char input) {
    int dx = ((input & 2) ? 1 : 0) - ((input & 1) ? 1 : 0);
    for (int i = 0; i < 8; ++i) samples[i] = 0;
    game.flags &= (unsigned char)~(4 | 8);
    game.input = input;
    if (game.y >= H) respawn();
    if (dx && !solid(game.x + dx, game.y)) game.x = (signed char)(game.x + dx);
    int ground = solid(game.x, game.y + 1);
    if ((input & 4) && ground && game.air == 0) {
        game.air = JUMP;
        tone(1500, 2);
    }
    if (game.air > 0) {
        if (!solid(game.x, game.y - 1)) {
            game.y = (signed char)(game.y - 1);
            game.air -= 1;
        } else {
            game.air = 0;
        }
    } else if (!ground) {
        game.y = (signed char)(game.y + 1);
    }
    if (solid(game.x, game.y + 1) && game.air == 0) game.flags |= 8;
    if (tile(game.x, game.y) == 'c') {
        level[game.y][game.x] = '.';
        game.coins += 1;
        game.score += 10;
        tone(3000, 3 + game.coins);
    }
    if (tile(game.x, game.y) == '^') hurt(dx);
    if (game.y >= H) {
        game.lives -= 1;
        game.flags |= 4;
    }
}

void render(void) {
    for (int y = 0; y < H; ++y)
        for (int x = 0; x < W; ++x)
            out.pixels[y][x] = PALETTE[KIND[(unsigned char)level[y][x] & 127]];
    for (int i = 0; i < game.coins && i < 6; ++i) out.pixels[0][1 + i] = PALETTE[2];
    for (int i = 0; i < game.lives && i < 3; ++i) out.pixels[0][14 - i] = PALETTE[3];
    if (game.y >= 0 && game.y < H && game.x >= 0 && game.x < W) {
        struct rgba *p = &out.pixels[game.y][game.x];
        p->r = 240;
        p->g = (game.flags & 4) ? 120 : 240;
        p->b = (game.flags & 4) ? 120 : 240;
    }
}

int ha_main(void) {
    for (int y = 0; y < H; ++y)
        for (int x = 0; x < W; ++x)
            level[y][x] = MAP[y][x];
    game.lives = 3;
    respawn();
    for (;;) {
        unsigned char input;
        if (ha_read(&input, 1) != 1) break;
        game.tick += 1;
        step(input);
        out.s = game;
        render();
        if (ha_write(&out, sizeof out) != sizeof out) return 3;
        if (ha_file_write(2, samples, sizeof samples) != sizeof samples) return 4;
        if (game.lives == 0) return 64 + game.coins;
        if (game.coins == COINS) return 128 + game.coins;
    }
    return game.coins;
}
"""
)

PROTOTYPES = """char tile(int x, int y);
int solid(int x, int y);
void respawn(void);
void tone(int amplitude, int period);
void hurt(int dx);
void step(unsigned char input);
void render(void);
void load_level(void);
"""

CANDIDATE = {
    "world.c": MAP
    + """struct state game;
char level[12][16];

char tile(int x, int y) {
    if (x < 0 || x >= W || y < 0) return 'X';
    if (y >= H) return '.';
    return level[y][x];
}

int solid(int x, int y) {
    return tile(x, y) == 'X';
}

void respawn(void) {
    game.x = START_X;
    game.y = START_Y;
    game.air = 0;
}

void load_level(void) {
    for (int row = 0; row < H; ++row)
        for (int col = 0; col < W; ++col)
            level[row][col] = MAP[row][col];
}
""",
    "physics.c": """void step(unsigned char input) {
    int dx = 0;
    if (input & 2) dx += 1;
    if (input & 1) dx -= 1;
    for (int i = 0; i < 8; ++i) samples[i] = 0;
    game.flags &= (unsigned char)~12;
    game.input = input;
    if (game.y >= H) respawn();
    int ground = solid(game.x, game.y + 1);
    if (dx != 0 && !solid(game.x + dx, game.y)) game.x = (signed char)(game.x + dx);
    if ((input & 4) && ground && game.air == 0) {
        game.air = JUMP;
        tone(1500, 2);
    }
    if (game.air > 0) {
        if (solid(game.x, game.y - 1)) {
            game.air = 0;
        } else {
            game.y = (signed char)(game.y - 1);
            game.air -= 1;
        }
    } else if (!ground) {
        game.y = (signed char)(game.y + 1);
    }
    if (game.air == 0 && solid(game.x, game.y + 1)) game.flags |= 8;
    if (tile(game.x, game.y) == 'c') {
        level[game.y][game.x] = '.';
        game.coins += 1;
        game.score += 10;
        tone(3000, 3 + game.coins);
    }
    if (tile(game.x, game.y) == '^') hurt(dx);
    if (game.y >= H) {
        game.lives -= 1;
        game.flags |= 4;
    }
}
""",
    "effects.c": """short samples[8];

void tone(int amplitude, int period) {
    for (int i = 0; i < 8; ++i) {
        int phase = (game.tick * 8 + i) % (2 * period);
        samples[i] = (short)(phase < period ? amplitude : -amplitude);
    }
}

void hurt(int dx) {
    int push = -dx;
    int nx = game.x;
    while (tile(nx, game.y) == '^') nx += push;
    game.x = (signed char)nx;
    game.lives -= 1;
    game.flags |= 4;
    tone(4000, 4);
}
""",
    "render.c": PALETTE
    + """struct frame out;

void render(void) {
    for (int y = 0; y < H; ++y)
        for (int x = 0; x < W; ++x)
            out.pixels[y][x] = PALETTE[KIND[(unsigned char)level[y][x] & 127]];
    for (int i = 0; i < game.coins && i < 6; ++i) out.pixels[0][1 + i] = PALETTE[2];
    for (int i = 0; i < game.lives && i < 3; ++i) out.pixels[0][14 - i] = PALETTE[3];
    if (game.y >= 0 && game.y < H && game.x >= 0 && game.x < W) {
        struct rgba *p = &out.pixels[game.y][game.x];
        int hurt_flash = (game.flags & 4) != 0;
        p->r = 240;
        p->g = hurt_flash ? 120 : 240;
        p->b = hurt_flash ? 120 : 240;
    }
}
""",
    "main.c": """int ha_main(void) {
    load_level();
    game.lives = 3;
    respawn();
    while (1) {
        unsigned char input;
        if (ha_read(&input, 1) != 1) break;
        game.tick += 1;
        step(input);
        out.s = game;
        render();
        if (ha_write(&out, sizeof out) != sizeof out) return 3;
        if (ha_file_write(2, samples, sizeof samples) != sizeof samples) return 4;
        if (game.lives == 0) return 64 + game.coins;
        if (game.coins == COINS) return 128 + game.coins;
    }
    return game.coins;
}
""",
}

FIXES = {
    # Defect 1: ground contact must be computed after the horizontal move.
    "edge": (
        "physics.c",
        "    int ground = solid(game.x, game.y + 1);\n    if (dx != 0 && !solid(game.x + dx, game.y)) game.x = (signed char)(game.x + dx);\n",
        "    if (dx != 0 && !solid(game.x + dx, game.y)) game.x = (signed char)(game.x + dx);\n    int ground = solid(game.x, game.y + 1);\n",
    ),
    # Defect 2: standing still on spikes pushes the player left.
    "knockback": ("effects.c", "    int push = -dx;\n", "    int push = dx ? -dx : -1;\n"),
}

SPEC = {
    "version": 1,
    "name": "Coin cavern",
    "original_path": "original.elf",
    "candidate_manifest": "build.json",
    "input": {
        "record_bytes": 1,
        "neutral": "00",
        "controls": {
            "none": "00",
            "left": "01",
            "right": "02",
            "jump": "04",
            "left_jump": "05",
            "right_jump": "06",
        },
    },
    "actions": {
        "step_left": [["left", 1]],
        "step_right": [["right", 1]],
        "run_left": [["left", 4]],
        "run_right": [["right", 4]],
        "jump": [["jump", 1], ["none", 3]],
        "jump_left": [["left_jump", 1], ["left", 5]],
        "jump_right": [["right_jump", 1], ["right", 5]],
        "wait": [["none", 4]],
    },
    "output": {
        "stdout": [
            {"name": "state", "bytes": 16},
            {"name": "frame", "format": "rgba8", "width": 16, "height": 12},
        ],
        "stderr": [
            {"name": "audio", "format": "pcm_s16le", "channels": 1, "samples": 8, "sample_rate": 480}
        ],
    },
    "state": {
        "segment": "state",
        "fields": [
            {"name": "tick", "offset": 0, "type": "u16"},
            {"name": "x", "offset": 2, "type": "i8"},
            {"name": "y", "offset": 3, "type": "i8"},
            {"name": "air", "offset": 4, "type": "u8"},
            {"name": "coins", "offset": 5, "type": "u8"},
            {"name": "lives", "offset": 6, "type": "u8"},
            {"name": "flags", "offset": 7, "type": "u8"},
            {"name": "score", "offset": 8, "type": "u16"},
            {"name": "input", "offset": 10, "type": "u8"},
        ],
    },
    "rules": [
        {"id": "inside_world_x", "field": "x", "min": 0, "max": 15},
        {"id": "inside_world_y", "field": "y", "min": 0, "max": 11},
        {"id": "lives_range", "field": "lives", "min": 0, "max": 3},
        {"id": "score_never_drops", "field": "score", "monotonic": "nondecreasing"},
        {"id": "no_teleport_x", "field": "x", "max_step": 2},
    ],
    "cells": {"fields": ["x", "y", "coins"]},
    "limits": {
        "max_ticks": 600,
        "freeze_tick_instructions": 200000,
        "slow_tick_instructions": 100000,
    },
    "allowed_exit_codes": [0, 1, 2, 3, 4, 64, 65, 66, 67, 68, 132],
}

# Routes as action lists; the harness expands them into input records.
ROUTES = {
    "coin_route": [
        "jump",
        "wait",
        "run_right",
        {"control": "right", "ticks": 2},
        {"control": "right_jump", "ticks": 1},
        {"control": "right", "ticks": 4},
        "wait",
    ],
}
ROUTES["hole_quirk"] = ROUTES["coin_route"] + [
    "step_left",
    {"control": "right_jump", "ticks": 1},
    {"control": "right", "ticks": 2},
    "wait",
    "wait",
]
ROUTES["platform_edge"] = ["step_right", "step_right", "jump", "step_right", "wait", "step_left", "wait"]
ROUTES["spike_landing"] = ROUTES["coin_route"] + ["step_left", "step_left", "jump", "step_left", "wait"]
STARTS = {
    "upper_platform": (["step_right", "step_right", "jump", "step_right"], [{"field": "y", "op": "==", "value": 6}]),
    "past_spikes": (ROUTES["coin_route"], [{"field": "x", "op": "==", "value": 13}]),
}
# Sealed acceptance routes reach the same situations along other paths, so passing
# them is not a matter of replaying the routes and starts that workers can read.
SEALED = {
    "coins_detour": ["step_right", "step_right", "jump_left", "jump_right", "jump", "step_right", "jump_right", "step_right", "jump_left", "step_right"],
    "gap_fall": ["jump_left", "jump_right", "step_left", "jump_right", "run_right", "jump_right", "wait"],
    "edge_drop": ["run_left", "jump_right", "run_left", "jump_left", "run_right", "wait", "step_left"],
    "spike_drop": ["run_right", "step_right", "step_right", {"control": "right_jump", "ticks": 1}, "wait", "wait"],
}

README = """Coin cavern: play-testing a rebuilt game

original.elf is a small compiled platformer. Each tick it reads one controller byte
(bit 0 left, bit 1 right, bit 2 jump), then writes a 16-byte state record and a 16x12
RGBA frame to stdout and eight PCM samples to stderr. game.json is the play-testing
contract: controls, named actions, the per-tick output layout, state fields, rules,
exploration cells, limits and two named starts. The C files are an editable
reconstruction built from build.json. Everything runs in HA's deterministic emulator;
no native execution permission, GPU or model account is needed.

Try it in Project files -> Play and test the game:
1. Load game, then press the action buttons to play the candidate, the original or
   both compared tick by tick. Every input is recorded; the trajectory replays exactly.
2. Run saved regressions: the scripted coin route and the floor-gap quirk both pass.
   Falling through the gap reports y=12 for one tick in the original as well, so it is
   original behavior, not a reconstruction defect.
3. Choose Both and Explore. Exploration returns to situations it has reached and tries
   new actions, comparing every tick. It soon finds a state divergence that the
   scripted route never reaches. Shrink it to a few inputs and open its bug package to
   compare frames and state at the failing tick. The cause is in physics.c.
4. Fix it, save, and explore again: the next finding is a freeze (the candidate stops
   responding). Exploring the candidate alone also finds it; problems the original
   shares are listed separately. The cause is in effects.c.
5. Save shrunk findings as regressions, rerun them after every change, and run tests.
   The pinned game_play checks replay sealed trajectories on both builds and pass only
   when no divergence or candidate-only problem remains.

Native workers use the same operations: describe_game, play_game and test_game. The
sealed trajectories take different paths from the routes and starts in this folder,
and they and the original source are kept outside the workspace. This example
verifies sampled deterministic play under a declared contract, not a GPU, window
system, hardware timing or all possible inputs.
"""


def records(steps):
    from hivemind_assembly.core import game_spec as gs

    return gs.expand(gs.validate(SPEC), steps)


def build_original(jobs, compiler=""):
    from hivemind_assembly.domains.reverse_engineering import program

    with tempfile.TemporaryDirectory(prefix="ha-game-example-") as folder:
        root = Path(folder)
        (root / "original.c").write_text(ORIGINAL, encoding="utf-8")
        built = program.build(root, {"sources": ["original.c"], "optimization": "O2"}, jobs, compiler)
    if not built["passed"]:
        raise Blocked("The game example requires a C compiler (Clang or GCC): " + str(built.get("build")))
    return bytes.fromhex(built["elf_hex"])


def files(fixed=()):
    """Workspace files; `fixed` names defects to repair (for tests)."""
    units = dict(CANDIDATE)
    for name in fixed:
        unit, before, after = FIXES[name]
        if before not in units[unit]:
            raise ValueError("Fix does not apply: " + name)
        units[unit] = units[unit].replace(before, after)
    spec = dict(SPEC)
    spec["starts"] = {
        name: {"inputs_hex": records(steps).hex(), "expect": expect}
        for name, (steps, expect) in STARTS.items()
    }
    result = dict(units)
    result["build.json"] = json.dumps(
        {
            "sources": list(CANDIDATE),
            "declarations": DECLARATIONS + PROTOTYPES,
            "optimization": "O2",
        },
        indent=2,
    ) + "\n"
    result["game.json"] = json.dumps(spec, indent=2) + "\n"
    result["game-regressions.json"] = json.dumps(
        {
            "version": 1,
            "regressions": [
                {
                    "id": "coin_route",
                    "inputs_hex": records(ROUTES["coin_route"]).hex(),
                    "expect": "match_original",
                    "note": "Scripted route: collect two coins and jump the spikes.",
                },
                {
                    "id": "hole_quirk",
                    "inputs_hex": records(ROUTES["hole_quirk"]).hex(),
                    "expect": "match_original",
                    "note": "Original behavior: y=12 for one tick when falling through the gap.",
                },
            ],
        },
        indent=2,
    ) + "\n"
    result["README.txt"] = README
    return result


def contract():
    return {
        "scope": "game_play",
        "game_path": "game.json",
        "trajectories": [
            {"id": name, "inputs_hex": records(steps).hex()} for name, steps in SEALED.items()
        ],
    }


def example(app):
    image = build_original(app.broker.jobs, app.config.get("foundations", {}).get("c_compiler", ""))
    return files(), contract(), image
