"""Fixed source-known project-level reconstruction suite (Stop 3).

Three targets exercise project checks rather than isolated functions:

* ``utility``: a multi-function x86-64 stream packer. Its candidate recovers four
  functions and leaves ``pack`` on original machine code.
* ``arm64_to_x64``: the same utility compiled for AArch64, reconstructed as a
  complete x86-64 source program with cross-ABI function checks.
* ``game``: a small x86-64 game loop with persistent state, an RGBA frame per
  tick and PCM audio. Its candidate recovers state, input and audio code while
  rendering stays on original code.

Each target also carries incorrect alternatives that the checks must reject. These
are synthetic validation targets: creating or passing them is not evidence that a
model reconstructed anything.
"""

import json
import tempfile
from pathlib import Path

from hivemind_assembly.core.common import Blocked
from hivemind_assembly.domains.reverse_engineering import program

UTILITY = """__attribute__((noinline)) unsigned advance(unsigned state, unsigned char byte) {
    return (state * 33u) ^ ((unsigned)byte + 17u);
}
__attribute__((noinline)) unsigned char encode(unsigned state, unsigned char byte, unsigned index) {
    return (unsigned char)(byte ^ (state >> ((index & 3u) * 8u)));
}
__attribute__((noinline)) long run_length(const unsigned char *data, long count, long start) {
    long n = 1;
    while (start + n < count && data[start + n] == data[start] && n < 255) n++;
    return n;
}
__attribute__((noinline)) long pack(const unsigned char *data, long count, unsigned char *out) {
    long o = 0;
    for (long i = 0; i < count;) {
        long n = run_length(data, count, i);
        out[o++] = (unsigned char)n;
        out[o++] = data[i];
        i += n;
    }
    return o;
}
int ha_main(void) {
    unsigned state = 2166136261u, index = 0;
    unsigned char data[64], packed[128];
    long count;
    while ((count = ha_read(data, sizeof data)) > 0) {
        for (long i = 0; i < count; ++i) {
            state = advance(state, data[i]);
            data[i] = encode(state, data[i], index++);
        }
        long size = pack(data, count, packed);
        if (ha_write(packed, size) != size) return 3;
    }
    unsigned char footer[4];
    for (unsigned i = 0; i < 4; ++i) footer[i] = (unsigned char)(state >> (i * 8));
    return ha_write(footer, 4) == 4 ? 0 : 4;
}
"""

# Recovered as written by a reconstruction: separate units, no attributes.
UTILITY_CANDIDATE = {
    "state.c": """unsigned advance(unsigned state, unsigned char byte) {
    unsigned mixed = state * 33u;
    return mixed ^ (byte + 17u);
}
unsigned char encode(unsigned state, unsigned char byte, unsigned index) {
    unsigned shift = (index % 4u) * 8u;
    return (unsigned char)(byte ^ (unsigned char)(state >> shift));
}
""",
    "runs.c": """long run_length(const unsigned char *data, long count, long start) {
    long n = 1;
    while (n < 255 && start + n < count && data[start + n] == data[start]) ++n;
    return n;
}
""",
    "main.c": """long pack(const unsigned char *data, long count, unsigned char *out);
int ha_main(void) {
    unsigned state = 2166136261u, index = 0;
    unsigned char data[64], packed[128];
    long count;
    while ((count = ha_read(data, 64)) > 0) {
        for (long i = 0; i < count; ++i) {
            state = advance(state, data[i]);
            data[i] = encode(state, data[i], index);
            index += 1;
        }
        long size = pack(data, count, packed);
        if (ha_write(packed, size) != size) return 3;
    }
    unsigned char footer[4];
    for (unsigned i = 0; i < 4; ++i) footer[i] = (unsigned char)(state >> (8 * i));
    return ha_write(footer, 4) == 4 ? 0 : 4;
}
""",
}
UTILITY_DECLARATIONS = (
    "unsigned advance(unsigned state, unsigned char byte);\n"
    "unsigned char encode(unsigned state, unsigned char byte, unsigned index);\n"
    "long run_length(const unsigned char *data, long count, long start);\n"
)
# Complete source program for the cross-architecture target.
UTILITY_COMPLETE = dict(
    UTILITY_CANDIDATE,
    **{
        "pack.c": """long pack(const unsigned char *data, long count, unsigned char *out) {
    long o = 0, i = 0;
    while (i < count) {
        long n = run_length(data, count, i);
        out[o] = (unsigned char)n;
        out[o + 1] = data[i];
        o += 2;
        i += n;
    }
    return o;
}
"""
    },
)
UTILITY_MUTANTS = {
    # Caught by the function corpus.
    "encode_shift": ("state.c", "(index % 4u)", "(index % 2u)"),
    # Function cases never use 0xAB; whole-program composition must reject it.
    "advance_hidden": ("state.c", "return mixed ^ (byte + 17u);", "return mixed ^ (byte + 17u + (byte == 0xABu));"),
    # Function cases use buffers of at most 40 bytes; full 64-byte chunks expose it.
    "run_large_chunks": ("runs.c", "long n = 1;", "long n = 1;\n    if (count > 50) return 1;"),
    "footer_order": ("main.c", "(8 * i)", "(8 * (3 - i))"),
}
PACK_FALLBACK_MUTANT = ("pack.c", "long o = 0, i = 0;", "long o = 0, i = count > 60 ? 1 : 0;")


def _utility_function_checks():
    def buffer(data):
        return {"id": "data", "hex": bytes(data).hex(), "permissions": "r"}

    return {
        "advance": {
            "cases": [
                {"arguments": [s, b], "output_bits": 32}
                for s in (0, 1, 2166136261, 0xFFFFFFFF, 0x12345678)
                for b in (0, 1, 0x41, 0x7F, 0x80, 0xFF)
            ]
        },
        "encode": {
            "cases": [
                {"arguments": [s, b, i], "output_bits": 32}
                for s in (0, 0xA1B2C3D4, 0xFFFFFFFF)
                for b in (0, 0x5A, 0xFF)
                for i in range(6)
            ]
        },
        "run_length": {
            "cases": [
                {
                    "arguments": [{"buffer": "data"}, len(d), start],
                    "buffers": [buffer(d)],
                }
                for d, start in (
                    (b"a", 0),
                    (b"aab", 0),
                    (b"abbbc", 1),
                    (b"zzzzzzzz", 3),
                    (bytes(40), 0),
                )
            ]
        },
    }


def _utility_cases():
    inputs = (
        ("empty", b""),
        ("text", b"Hivemind Assembly\n"),
        ("runs", b"\x00" * 9 + b"\x01" * 3 + b"abc"),
        ("chunks", bytes(range(130))),
        ("long-run", b"\x07" * 300),
        ("marker", bytes(range(0xA0, 0xB0)) * 3),
        ("mixed", bytes((i * 73 + 19) % 256 for i in range(257))),
    )
    return [
        {"id": name, "input_hex": data.hex(), "effect_policy": "observable"}
        for name, data in inputs
    ]


def _callgraph(program_name, sha, edges):
    names = list(edges)
    return [
        {
            "program": program_name,
            "executable_sha256": sha,
            "revision": 1,
            "total_functions": len(names),
            "offset": 0,
            "next_offset": len(names),
            "has_more": False,
            "items": [
                {
                    "id": name,
                    "name": name,
                    "callees": edges[name],
                    "calls_truncated": False,
                }
                for name in names
            ],
        }
    ]


GAME = """struct game { int x, y, vx, vy, score, tick; unsigned seed; };
struct game world;

__attribute__((noinline)) void apply_input(struct game *g, unsigned char key) {
    if (key == 'L') g->vx -= 1;
    else if (key == 'R') g->vx += 1;
    else if (key == 'J' && g->y == 0) g->vy = 5;
    if (g->vx > 2) g->vx = 2;
    if (g->vx < -2) g->vx = -2;
}
__attribute__((noinline)) void step_physics(struct game *g) {
    g->x += g->vx;
    if (g->x < 0) { g->x = 0; g->vx = -g->vx; g->score += 1; }
    if (g->x > 7) { g->x = 7; g->vx = -g->vx; g->score += 1; }
    g->y += g->vy;
    if (g->y > 0) g->vy -= 1;
    if (g->y <= 0) { g->y = 0; g->vy = 0; }
    g->seed = g->seed * 1103515245u + 12345u;
    g->tick += 1;
}
__attribute__((noinline)) void render_frame(const struct game *g, unsigned char *pixels) {
    for (int row = 0; row < 6; ++row) {
        for (int col = 0; col < 8; ++col) {
            unsigned char *p = pixels + (row * 8 + col) * 4;
            int player = col == g->x && row == 5 - (g->y > 5 ? 5 : g->y);
            p[0] = player ? 250 : (unsigned char)(row * 20);
            p[1] = player ? (unsigned char)(g->score * 40) : (unsigned char)((g->seed >> (col * 3)) & 31);
            p[2] = row == 5 ? 90 : 30;
            p[3] = 255;
        }
    }
}
__attribute__((noinline)) void mix_audio(const struct game *g, short *samples) {
    int period = 2 + (g->vy < 0 ? -g->vy : g->vy) + (g->x & 1);
    int level = 1000 + g->score * 500;
    for (int i = 0; i < 16; ++i) {
        int phase = (g->tick * 16 + i) % (period * 2);
        samples[i] = (short)(phase < period ? level : -level);
    }
}
int ha_main(void) {
    unsigned char keys[12], pixels[192];
    short samples[16];
    for (int i = 0; i < 12; ++i) keys[i] = '.';
    long got = ha_read(keys, 12);
    if (got < 0) return 2;
    world.x = 3; world.y = 0; world.vx = 0; world.vy = 0;
    world.score = 0; world.tick = 0; world.seed = 7u;
    for (int t = 0; t < 12; ++t) {
        apply_input(&world, keys[t]);
        step_physics(&world);
        render_frame(&world, pixels);
        if (ha_write(pixels, sizeof pixels) != sizeof pixels) return 3;
        mix_audio(&world, samples);
        if (ha_file_write(2, samples, sizeof samples) != sizeof samples) return 4;
    }
    return world.score & 0x7f;
}
"""
GAME_CANDIDATE = {
    "logic.c": """void apply_input(struct game *g, unsigned char key) {
    switch (key) {
    case 'L': g->vx = g->vx - 1; break;
    case 'R': g->vx = g->vx + 1; break;
    case 'J': if (g->y == 0) g->vy = 5; break;
    default: break;
    }
    if (g->vx > 2) g->vx = 2;
    else if (g->vx < -2) g->vx = -2;
}
void step_physics(struct game *g) {
    g->x = g->x + g->vx;
    if (g->x < 0 || g->x > 7) {
        g->x = g->x < 0 ? 0 : 7;
        g->vx = -g->vx;
        g->score = g->score + 1;
    }
    g->y = g->y + g->vy;
    if (g->y > 0) g->vy = g->vy - 1;
    else { g->y = 0; g->vy = 0; }
    g->seed = g->seed * 1103515245u + 12345u;
    g->tick = g->tick + 1;
}
""",
    "audio.c": """void mix_audio(const struct game *g, short *samples) {
    int speed = g->vy;
    if (speed < 0) speed = -speed;
    int period = 2 + speed + (g->x & 1);
    int level = 1000 + 500 * g->score;
    for (int i = 0; i < 16; ++i)
        samples[i] = (short)(((g->tick * 16 + i) % (2 * period)) < period ? level : -level);
}
""",
    "loop.c": """void render_frame(const struct game *g, unsigned char *pixels);
int ha_main(void) {
    unsigned char keys[12], pixels[192];
    short samples[16];
    for (int i = 0; i < 12; ++i) keys[i] = '.';
    if (ha_read(keys, 12) < 0) return 2;
    world.x = 3; world.y = 0; world.vx = 0; world.vy = 0;
    world.score = 0; world.tick = 0; world.seed = 7u;
    for (int t = 0; t < 12; ++t) {
        apply_input(&world, keys[t]);
        step_physics(&world);
        render_frame(&world, pixels);
        if (ha_write(pixels, 192) != 192) return 3;
        mix_audio(&world, samples);
        if (ha_file_write(2, samples, 32) != 32) return 4;
    }
    return world.score & 0x7f;
}
""",
}
GAME_DECLARATIONS = (
    "struct game { int x, y, vx, vy, score, tick; unsigned seed; };\n"
    "extern struct game world;\n"
    "void apply_input(struct game *g, unsigned char key);\n"
    "void step_physics(struct game *g);\n"
    "void mix_audio(const struct game *g, short *samples);\n"
)
GAME_MUTANTS = {
    # Jump allowed in the air: function case with y>0 catches it.
    "double_jump": ("logic.c", "case 'J': if (g->y == 0) g->vy = 5; break;", "case 'J': g->vy = 5; break;"),
    # Function cases never bounce at the right wall; frames and exit code do.
    "right_wall": ("logic.c", "g->x = g->x < 0 ? 0 : 7;", "g->x = g->x < 0 ? 0 : 6;"),
    # Loudness by score: caught by function cases with a nonzero score.
    "audio_level": ("audio.c", "1000 + 500 * g->score", "1000 + 400 * g->score"),
    # Sample timing shifted by one sample: frame-exact audio comparison catches it.
    "audio_late": ("audio.c", "(g->tick * 16 + i)", "(g->tick * 16 + i + 1)"),
}


def _game_state(x=3, y=0, vx=0, vy=0, score=0, tick=0, seed=7):
    import struct

    return struct.pack("<iiiiiiI", x, y, vx, vy, score, tick, seed).hex()


def _game_function_checks():
    states = [
        _game_state(),
        _game_state(x=0, vx=-2, score=1),
        _game_state(y=3, vy=2, tick=4, seed=99),
        _game_state(x=5, vx=1, y=0, vy=0, score=2, tick=7),
        _game_state(x=6, vx=2, y=1, vy=-1, tick=9),
    ]
    return {
        "apply_input": {
            "cases": [
                {
                    "arguments": [{"buffer": "g"}, key],
                    "buffers": [{"id": "g", "hex": s}],
                }
                for s in states
                for key in b"LRJ.x"
            ]
        },
        "step_physics": {
            "cases": [
                # Left-wall and in-air cases only; the right wall is not covered.
                {"arguments": [{"buffer": "g"}], "buffers": [{"id": "g", "hex": s}]}
                for s in states[:4]
            ]
        },
        "mix_audio": {
            "cases": [
                {
                    "arguments": [{"buffer": "g"}, {"buffer": "out"}],
                    "buffers": [
                        {"id": "g", "hex": s, "permissions": "r"},
                        {"id": "out", "hex": "00" * 32},
                    ],
                }
                for s in states
            ]
        },
    }


FRAME_RULE = {
    "format": "rgba8_sequence",
    "width": 8,
    "height": 6,
    "frames": 12,
    "frame_rate_num": 30,
    "frame_rate_den": 1,
}
AUDIO_RULE = {"format": "pcm_s16le", "channels": 1, "sample_rate": 480, "frames": 192}


def _game_cases():
    inputs = (
        ("idle", b""),
        ("run-right", b"RRRRRRRRRRRR"),
        ("bounce-left", b"LLLLLL......"),
        ("jumps", b"J...J.RJ..LJ"),
        ("mixed", b"RJRRL.JLLRJ."),
    )
    return [
        {
            "id": name,
            "input_hex": data.hex(),
            "effect_policy": "observable",
            "captures": {"stdout": FRAME_RULE, "stderr": AUDIO_RULE},
        }
        for name, data in inputs
    ]


def _compile(source, architecture, optimization, jobs, compiler=""):
    with tempfile.TemporaryDirectory(prefix="ha-project-target-") as folder:
        root = Path(folder)
        (root / "original.c").write_text(source, encoding="utf-8")
        built = program.build(
            root,
            {
                "sources": ["original.c"],
                "optimization": optimization,
                "architecture": architecture,
            },
            jobs,
            compiler,
        )
    if not built["passed"]:
        raise Blocked("Project target requires Clang and LLD: " + str(built.get("build")))
    return bytes.fromhex(built["elf_hex"])


def target(kind, jobs, compiler=""):
    """Return {original, files, project, function_checks, cases, plan_pages, mutants}."""
    import hashlib

    if kind in ("utility", "arm64_to_x64"):
        arm = kind == "arm64_to_x64"
        original = _compile(UTILITY, "aarch64" if arm else "x86_64", "O2", jobs, compiler)
        sha = hashlib.sha256(original).hexdigest()
        units = UTILITY_COMPLETE if arm else UTILITY_CANDIDATE
        files = dict(units)
        names = list(units)
        functions = {
            "advance": {"sources": ["state.c"]},
            "encode": {"sources": ["state.c"]},
            "run_length": {"sources": ["runs.c"]},
            "ha_main": {"sources": names if arm else ["main.c", "state.c"]},
        }
        if arm:
            functions["pack"] = {"sources": ["pack.c", "runs.c"]}
            build = {
                "sources": names,
                "declarations": UTILITY_DECLARATIONS,
                "architecture": "x86_64",
                "optimization": "O2",
            }
            files["build.json"] = json.dumps(build, indent=2) + "\n"
            project = {"build": "build.json", "functions": functions}
        else:
            project = {
                "sources": names,
                "declarations": UTILITY_DECLARATIONS,
                "optimization": "O2",
                "functions": functions,
            }
        checks = _utility_function_checks()
        if arm:
            checks["pack"] = {
                "cases": [
                    {
                        "arguments": [{"buffer": "in"}, len(d), {"buffer": "out"}],
                        "buffers": [
                            {"id": "in", "hex": d.hex(), "permissions": "r"},
                            {"id": "out", "hex": "00" * (2 * len(d))},
                        ],
                    }
                    for d in (b"a", b"aaab", b"abcabc", b"\x07" * 20)
                ]
            }
        files["project.json"] = json.dumps(project, indent=2) + "\n"
        edges = {
            "advance": [],
            "encode": [],
            "run_length": [],
            "pack": ["run_length"],
            "ha_main": ["advance", "encode", "pack"],
        }
        mutants = dict(UTILITY_MUTANTS)
        if arm:
            mutants["pack_fallback"] = PACK_FALLBACK_MUTANT
        return {
            "original": original,
            "files": files,
            "manifest_path": "project.json",
            "function_checks": checks,
            "cases": _utility_cases(),
            "plan_pages": _callgraph("utility", sha, edges),
            "mutants": mutants,
        }
    if kind == "game":
        original = _compile(GAME, "x86_64", "O2", jobs, compiler)
        sha = hashlib.sha256(original).hexdigest()
        project = {
            "sources": list(GAME_CANDIDATE),
            "declarations": GAME_DECLARATIONS,
            "optimization": "O2",
            "functions": {
                "apply_input": {"sources": ["logic.c"]},
                "step_physics": {"sources": ["logic.c"]},
                "mix_audio": {"sources": ["audio.c"]},
                "ha_main": {"sources": ["loop.c"]},
            },
        }
        files = dict(GAME_CANDIDATE)
        files["project.json"] = json.dumps(project, indent=2) + "\n"
        edges = {
            "apply_input": [],
            "step_physics": [],
            "render_frame": [],
            "mix_audio": [],
            "ha_main": ["apply_input", "step_physics", "render_frame", "mix_audio"],
        }
        return {
            "original": original,
            "files": files,
            "manifest_path": "project.json",
            "function_checks": _game_function_checks(),
            "cases": _game_cases(),
            "plan_pages": _callgraph("game", sha, edges),
            "mutants": dict(GAME_MUTANTS),
        }
    raise ValueError("Unknown project target")
