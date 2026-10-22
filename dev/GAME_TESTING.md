# Game play-testing design (proposal v0.2)

This is the design record for letting AI and local bots play the games Hivemind
Assembly (HA) rebuilds, so they can test, troubleshoot and improve them. It revises
the owner's *Visual Game Testing Proposal v0.1* (22 October 2026) and its notes. The
implementation status section at the end is updated as files land; claims there are
limited to what was actually run.

## Evaluation of v0.1

Kept from v0.1, because they are right:

- Targeted, reproducible experiments come first; broad autonomous play supports them.
- Navigation may adapt, but a controlled comparison never steers around a defect.
- The original is the fidelity reference, quirks included. A problem that reproduces
  on the original is original behavior, not a reconstruction defect.
- An independent verifier decides; agent narration or agreement is not evidence.
- Crashes, timeouts, unsupported operations and unreached preconditions are
  first-class outcomes, never silent skips or passes.
- State numbers before pictures; meaningful actions before raw buttons; a slow
  vision model is used sparingly, while fast local code handles precision.
- Training (reinforcement learning, imitation) is a later optimization. Test hooks,
  exact replay, automatic detection, exploration and shrinking find bugs first.

Gaps that v0.2 closes:

1. **It did not use HA's biggest advantage.** HA already runs originals and rebuilt
   programs under deterministic, bounded emulation with explicit input/output
   boundaries (`ha_read`, `ha_write`, fixed clock, no host effects). For those lanes
   the emulator *is* the test hook: frame-exact input through the program's own input
   stream, no window focus or OS-level input, deterministic by construction,
   save/load without game cooperation, memory state by symbol, and function coverage
   from symbols. v0.1 treated hooks as something each game must add first.
2. **No durable session identity.** HA retries operations after crashes and lost
   responses. v0.2 makes every play session an input log (a *trajectory*). Every
   observation is a pure function of (program image, game spec, trajectory), so
   interrupted operations are recomputed rather than reconciled, and a trajectory is
   always a ready regression case.
3. **Two documents, two goals.** The main text covered original/candidate fidelity;
   the notes covered single-build bug finding. One harness now does both: lockstep
   differential play against the original, plus crash/freeze/invariant/slowdown
   detection on any build, with original-behavior classification.
4. **Underspecified minimization and deduplication.** Problems carry a signature
   (kind plus rule, channel or stop location). Shrinking first truncates after the
   failing tick, then removes chunks (delta debugging), then replaces remaining
   inputs with the neutral input, keeping only reductions that reproduce the same
   signature. Confirmation replays on fresh engines.
5. **Desktop automation is the wrong hook.** OS-level keyboard/mouse adapters,
   desktop focus management and virtual controllers are unnecessary for HA's emulated
   lanes, and real games get the same tick contract from a small adapter inside the
   game process instead: a Godot autoload, or an SDL2 preload library on Linux.
   Nothing in v0.2 types into other windows or needs a visible desktop, and native
   execution needs the owner's permission.
6. **Images for chat-based assistants.** HA's native workers are browser chat
   sessions. Frames are rendered as upscaled PNG artifacts attached to the worker's
   next turn when the route supports uploads, and small frames also get a character
   map with a color legend, so text-only transports still see the screen.

## Architecture

| Part | Location | Responsibility |
| --- | --- | --- |
| Game spec | `core/game_spec.py` | Validated contract: input records, controls and macro actions, per-tick output segments (raw state, RGBA frame, PCM audio), state fields, memory fields, declarative rules, cells, limits, comparison tolerances, named starts, native launches; trajectory tokens; PNG and character views |
| Harness | `core/game_testing.py` | Domain-independent sessions over an engine protocol: tick decoding, problem detection, lockstep differential pairs, scripted replay, Go-Explore exploration, shrinking, confirmation, bug packages, saved regressions, metrics |
| Engines | `domains/reverse_engineering/game_machine.py` | Live stepping engine for static x86-64/AArch64 ELF (Unicorn; pauses when the game waits for input; snapshots; memory reads; symbol coverage) and a replay engine over the existing Linux and Windows PE batch replays |
| Native lane | `domains/reverse_engineering/native_game.py` | Launch plans for Godot 4 projects and Linux SDL2 programs (runtime copies, adapter builds, credential-free environment), `NativeEngine` over the tick protocol, memory state by symbol and pointer path, replayed snapshots, determinism probe |
| Adapters | `domains/reverse_engineering/native_adapters/` | `ha_tick.gd` (Godot autoload), `ha_sdl_tick.c` (SDL2 frames, keys, virtual clocks, event delivery), `ha_entropy.c` (seeded operating-system randomness) |
| Operations | `domains/reverse_engineering/game_play.py` | Worker and owner operations `describe_game`, `play_game`, `test_game`; candidate build cache; session cache |
| Acceptance | `domains/reverse_engineering/game_acceptance.py` | `game_play` scope: sealed original, spec and trajectories; independent rebuild; per-tick comparison with pinned tolerances; candidate rules |
| Images to workers | `core/broker.py`, `automation/team.py` | Domain results may emit PNG images; the next native turn attaches them when the route supports uploads |
| Dashboard | `application/static/game_testing.js` | Owner play controls, frame/state view, explore, compare, shrink, saved regressions |
| Example | `application/game_example.py` | Source-known platformer with an original quirk and planted candidate defects |

### Game spec (`game.json`)

```json
{
  "version": 1,
  "name": "Coin cavern",
  "original_path": "original.elf",
  "candidate_manifest": "build.json",
  "input": {"record_bytes": 1, "neutral": "00",
            "controls": {"none": "00", "left": "01", "right": "02", "jump": "04"}},
  "actions": {"run_right": [["right", 4]], "jump": [["jump", 1], ["none", 3]]},
  "output": {
    "stdout": [{"name": "state", "bytes": 16},
               {"name": "frame", "format": "rgba8", "width": 16, "height": 12}],
    "stderr": [{"name": "audio", "format": "pcm_s16le", "channels": 1,
                "samples": 8, "sample_rate": 480}]
  },
  "state": {"segment": "state", "fields": [{"name": "x", "offset": 2, "type": "i8"}]},
  "rules": [{"id": "inside_world", "field": "x", "min": 0, "max": 15}],
  "cells": {"fields": ["x"]},
  "limits": {"max_ticks": 600, "freeze_tick_instructions": 200000}
}
```

A tick is one fixed output record per declared stream. Inputs are fixed records. The
stepping engine feeds one record at a time and runs until the program blocks on its
next read, so each step is frame-exact and state can also be read from memory at that
point. Reads block until the requested byte count is available or input ends, which
makes a stepped session byte-for-byte identical to the batch replay of the same input
log (tests check this). Rules support bounds (constants or other fields), equality,
monotonicity, finiteness and maximum per-tick change, optionally guarded by `when`
conditions.

### Real games (native lane)

A `native` section replaces the emulated fields. It names the adapter (`godot` or
`sdl2`), each side's launch (a project folder, or an executable with an optional
folder, arguments and environment), inputs (keys, or Godot input actions), state
(Godot node properties or group counts; SDL2 memory by symbol, address and pointer
path), an optional frame size, the frame rate, a seed, the display (virtual X or
headless) and time limits. The contract derives controls, actions (each input held
for `action_ticks`; declared actions override, for example press-and-release moves
for turn-based games), the output layout and the state fields, so every player,
oracle and package works unchanged.

Tick protocol 1: HA listens on a localhost port; when the game reaches its first
frame (so loading counts against the startup limit, not a frame's) the adapter
connects and proves a per-launch token; HA then sends one input record (`I`) or end of
input (`E`), the game runs exactly one frame with it, and the adapter answers with
that frame's record (`T`, tick, length, payload). Godot steps one physics frame per record at a fixed
frame rate and reports node properties and a scaled viewport frame. The SDL2 preload
treats each presented frame (renderer, OpenGL swap or window surface) as a tick
boundary, and each wait without events as one tick for event-driven games; HA reads
declared state from the paused process's memory.

Determinism is the adapters' job and is checked, not assumed:

- Godot runs with `--fixed-fps`; the adapter seeds the global generator at start and
  at the first input. SDL2 games' own code sees virtual clocks that advance one frame
  per tick.
- On Linux, `getrandom`, `getentropy`, `syscall(SYS_getrandom)` and `arc4random` return
  seeded bytes, one stream per calling library and thread class, so a driver's or
  worker thread's draws do not shift the game's. For Godot the library is preloaded
  alone and reopens `RTLD_DEEPBIND` libraries (GDExtensions in Rust or C++) without
  that flag so their requests reach it.
- SDL2 games receive only HA's key presses, quit, render resets and their own
  events; window-system and device events arrive at run-dependent times and are not
  delivered.
- `describe_game` launches each side twice, plays the start named `probe` (else the
  first start) and then seeded random actions, and reports the first differing tick.
  Native snapshots are input logs replayed from a fresh launch; replays that differ
  are counted (`replay_mismatches`) because findings may then not reproduce.

Not controlled: Godot's clock-seeded `RandomNumberGenerator` objects and
`randomize()` after the first input, hardware random instructions (RDRAND, which
C++ `std::random_device` may use), `/dev/urandom` reads, races between game threads
and real-time audio.

### Players

- **Scripted**: trajectories and named starts replay exactly.
- **Exploration** (no training): a Go-Explore archive keyed by cells, restoring engine
  snapshots, sticky random macro actions, novelty bonus for newly executed functions.
  In differential mode the original and candidate run in lockstep and the first
  divergent tick is recorded immediately. The archive is bounded in cells and
  snapshot bytes; native snapshots replay from a fresh launch, so native exploration
  is slower.
- **AI**: a native worker calls `play_game` with a few named actions per turn and
  receives state, recent history, problems, the action menu, a character view and
  attached frame images. Every call is replay-safe and can be batched.
- **Owner**: the dashboard plays the same trajectories with buttons.

### Oracles and outcome vocabulary

`pass`, `divergence` (original and candidate differ beyond pinned tolerances: state,
frame, audio, status, exit code or tick count), `crash` (fault, unsupported effect or,
for native games, a signal), `freeze` (per-tick instruction budget exhausted, or a
native frame not finished within its wall-clock limit), `invariant` (rule violated),
`slowdown` (tick over its instruction budget), `bad_exit`, `protocol` (output does not
match the declared layout), `unreached` (start preconditions unmet), `limit`
(inconclusive harness bound, including a native adapter failure) and `cancelled`.
`limit` and `cancelled` are inconclusive and never pass. Candidate problems that
reproduce on the original with the same trajectory are reported as
`original_behavior`; in single-build exploration each occurrence is checked.

### Reproduce, minimize, retain

Every report carries trajectory tokens. `test_game` can confirm, shrink and package a
problem (inputs as control names, state window, frames from both sides around the
failing tick, coverage, stop context). Saved regressions (`game-regressions.json`)
rerun with `test_game` mode `regressions` on every new build. Owners can pin
trajectories into a `game_play` acceptance contract; detailed sealed observations stay
protected and workers see only pass/fail and first-divergence ticks. Acceptance seals
emulated games only; native games keep saved regressions.

### Safety and limits

Emulated lanes need no native execution permission and touch no host files,
network or windows. Every engine call is bounded by per-tick and total instruction
budgets, output and event limits, wall-clock limits and cancellation. Deterministic
instruction counts stand in for frame time; they are not hardware timing.

The native lane runs the game's own code on this computer. It needs the project's
trusted native execution permission, uses a credential-free environment and a fresh
home folder per launch, bounds startup and every frame by wall-clock limits, and
stops the process group on cancellation. It is not a sandbox; use a disposable
machine for games you do not trust.

## Deferred, with reasons

- **More native adapters.** Windows and macOS SDL2 programs (needs DLL or dylib
  injection), exported Godot binaries (packed projects), other engines (Unity,
  Unreal, custom) and native audio capture. The tick protocol is engine-neutral, so
  each is an adapter, not a harness change.
- **Learned policies (BTR, MariQ-style controllers).** Only for a single navigation
  skill that scripts and exploration cannot handle; measure against the scripted
  baseline first. Named starts and retained trajectories are the first reusable skills.
- **Pointer-driven games and numbered on-screen markers.** Inputs are controller and
  key records today; the SDL2 adapter does not deliver mouse, touch or controller
  events.
- **Cross-platform semantic state mapping** beyond declared state fields.

## Implementation status

All parts in the architecture table landed in version 0.26.0. What was run:

- Engine parity: stepped play (one byte, two bytes and 64 bytes per feed) equals
  `program.replay` streams, exit status, input consumption and instruction counts on
  x86-64 and AArch64 builds and on the existing game project target, including
  function-entry coverage. Faults, clock reads, `rdtsc`, event limits, per-tick
  freezes, total budgets, cancellation and snapshot restoration are covered.
- Coin cavern example (`application/game_example.py`): the scripted route and the
  floor-gap quirk pass as regressions, and the quirk is classified as original
  behavior. Differential exploration (seed 0, 150 steps) finds the platform-edge
  divergence; shrinking reduces it to at most ten inputs and confirms it on fresh
  engines. After that fix, exploration finds the spike freeze; after both fixes, a
  200-step exploration finds nothing and the pinned `game_play` checks pass. Before
  the fixes, those checks report divergence and freeze on the sealed routes, which
  follow different paths from the workspace routes.
- Single-build exploration finds the freeze and moves the shared quirk to original
  behavior. Replay engines agree with live sessions on the first divergent tick. A
  Windows x64 console game runs through the replay engine.
- Review fixes, each with a test: cancelled and bounded runs are inconclusive, never
  a pass; engine output and event bounds come from the contract; single-build
  findings are checked per occurrence; the exploration archive is bounded with exact
  progress counts; cached sessions observe each request's cancellation; owner play
  continues while the task is paused; replay engines name each bound; shrinking and
  packages handle findings after end of input.
- Worker path: the three operations run through `Broker.execute`, are replay-safe,
  store frames as PNG task artifacts, and the next native turn attaches them only
  when the route has upload bindings (fixture browser bindings; no live provider).
- Dashboard: a real Chromium run loads the example, plays and undoes actions,
  compares both builds, explores, shrinks, opens a bug package and runs regressions.
- Native lane tests (`tests/test_native_game.py`): an SDL2 program (virtual time,
  pointer-path state, a planted speed change found at tick 4, a SIGSEGV crash, a
  frame-timeout freeze, exploration, shrinking to one control); an event-driven SDL2
  program (each press on its own tick, no window-system events; the previous adapter
  fails this test); a game that loads for longer than a frame may (the previous
  adapter reported a freeze); seeded randomness through `getrandom`, `syscall`,
  `getentropy` and an `RTLD_DEEPBIND` library, with core dumps disabled; and a
  headless Godot project (exact fixed-step movement, seeded generator, repeatable
  `Crypto` bytes with the preload). Hosted Linux CI first ran these tests in this
  version and exposed the slow-loading case.

Real free games, played by `dev/check_real_games.py` at `4b1efb3` on Linux x86-64
(Xvfb with Mesa llvmpipe, Godot 4.7.1) from pinned commits and checksums; the planted
defects are one-line changes the script makes:

| Game (built with) | Compared | Result |
| --- | --- | --- |
| Dodge the Creeps, Godot demo (GDScript) | the demo with itself | Probe: both sides replay identically. 30 exploration steps (1920 ticks, 51 cells, 127 s): pass. |
| Dodge the Creeps, godot-rust port (Rust GDExtension) | GDScript original vs Rust port | Probe: both sides replay identically, with operating-system randomness seeded (an earlier run without the preload found the port differing from tick 161). 30 exploration steps (1370 ticks, 25 cells, 235 s): `divergence state:mobs` at tick 295; shrinking reduced it from 300 to 286 ticks (71 tests) and confirmed it on fresh launches. The port draws mob paths from Rust's generator, not Godot's, so mob counts are expected to differ. |
| Chromium B.S.U. 0.9.16.1-3 (C++, SDL2, OpenGL) | Ubuntu's binary vs a rebuild, by frames | Probe: both sides replay identically. 30 exploration steps (1296 ticks, 81 cells, 92 s): pass. |
| Chromium B.S.U., planted defect | rebuild vs a copy whose upper bound uses the horizontal limit, by memory state | 30 exploration steps (1376 ticks, 41 cells, 88 s): `divergence state:y` at tick 156; shrinking reduced it from 160 to 22 ticks (176 tests) and confirmed it on fresh launches. Defect alone: 30 exploration steps (1376 ticks, 41 cells, 43 s): `invariant hero_inside_y` at tick 156. |
| sokoban-rs 1.2.2 (Rust, SDL2, event-driven) | upstream vs a copy that lets a box be pushed into another box, by frames | Scripted `up, right, right`: `divergence frame` at tick 4. 30 exploration steps (292 ticks, 12 cells, 34 s): `divergence frame` at tick 32; shrinking reduced it from 34 to 17 ticks (52 tests) and confirmed it on fresh launches. Upstream alone: 30 exploration steps (336 ticks, 14 cells, 18 s): pass. |

The port's divergence shrinks to pressing start and waiting, so it does not depend on
the player's input; the Chromium B.S.U. defect shrinks to leaving the menu and holding
`up`; the sokoban-rs defect shrinks to a walk that pushes one box into the other.
`describe_game` reported every side above as replaying identically.

Not established: play by a signed-in native model, trained policies, pointer-driven
games, Windows or macOS native adapters, exported Godot binaries, native audio or
hardware timing. Exploration that finds nothing is sampled evidence only, and the
real-game checks are scripted, seeded play by HA's harness.
