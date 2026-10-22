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
5. **Scope that does not apply yet.** OS-level keyboard/mouse adapters, desktop focus
   management and virtual controllers are unnecessary for HA's emulated lanes and are
   deferred until a native graphical lane exists. Nothing in v0.2 types into other
   windows or needs a visible desktop.
6. **Images for chat-based assistants.** HA's native workers are browser chat
   sessions. Frames are rendered as upscaled PNG artifacts attached to the worker's
   next turn when the route supports uploads, and small frames also get a character
   map with a color legend, so text-only transports still see the screen.

## Architecture

| Part | Location | Responsibility |
| --- | --- | --- |
| Game spec | `core/game_spec.py` | Validated contract: input records, controls and macro actions, per-tick output segments (raw state, RGBA frame, PCM audio), state fields, memory fields, declarative rules, cells, limits, comparison tolerances, named starts; trajectory tokens; PNG and character views |
| Harness | `core/game_testing.py` | Domain-independent sessions over an engine protocol: tick decoding, problem detection, lockstep differential pairs, scripted replay, Go-Explore exploration, shrinking, confirmation, bug packages, saved regressions, metrics |
| Engines | `domains/reverse_engineering/game_machine.py` | Live stepping engine for static x86-64/AArch64 ELF (Unicorn; pauses when the game waits for input; snapshots; memory reads; symbol coverage) and a replay engine over the existing Linux and Windows PE batch replays |
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
monotonicity and maximum per-tick change, optionally guarded by `when` conditions.

### Players

- **Scripted**: trajectories and named starts replay exactly.
- **Exploration** (no training): a Go-Explore archive keyed by cells, restoring engine
  snapshots, sticky random macro actions, novelty bonus for newly executed functions.
  In differential mode the original and candidate run in lockstep and the first
  divergent tick is recorded immediately.
- **AI**: a native worker calls `play_game` with a few named actions per turn and
  receives state, recent history, problems, the action menu, a character view and
  attached frame images. Every call is replay-safe and can be batched.
- **Owner**: the dashboard plays the same trajectories with buttons.

### Oracles and outcome vocabulary

`pass`, `divergence` (original and candidate differ beyond pinned tolerances: state,
frame, audio, status, exit code or tick count), `crash` (fault or unsupported effect),
`freeze` (per-tick instruction budget exhausted), `invariant` (rule violated),
`slowdown` (tick over its instruction budget), `bad_exit`, `protocol` (output does not
match the declared layout), `unreached` (start preconditions unmet), `limit`
(inconclusive harness bound) and `cancelled`. Candidate problems that reproduce on the
original with the same trajectory are reported as `original_behavior`.

### Reproduce, minimize, retain

Every report carries trajectory tokens. `test_game` can confirm, shrink and package a
problem (inputs as control names, state window, frames from both sides around the
failing tick, coverage, stop context). Saved regressions (`game-regressions.json`)
rerun with `test_game` mode `regressions` on every new build. Owners can pin
trajectories into a `game_play` acceptance contract; detailed sealed observations stay
protected and workers see only pass/fail and first-divergence ticks.

### Safety and limits

Emulated lanes need no native execution permission and touch no host files,
network or windows. Every engine call is bounded by per-tick and total instruction
budgets, output and event limits, wall-clock limits and cancellation. Deterministic
instruction counts stand in for frame time; they are not hardware timing.

## Deferred, with reasons

- **Native graphical builds and OS-level input.** Needs a native lane with a game-side
  hook protocol (the same tick contract over a pipe) and a disposable machine. Not
  needed for current emulated targets.
- **Learned policies (BTR, MariQ-style controllers).** Only for a single navigation
  skill that scripts and exploration cannot handle; measure against the scripted
  baseline first. Named starts and retained trajectories are the first reusable skills.
- **Pointer-driven games and numbered on-screen markers.** Inputs are controller
  records today.
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
  the fixes, those checks report divergence and freeze on the sealed routes.
- Single-build exploration finds the freeze and moves the shared quirk to original
  behavior. Replay engines agree with live sessions on the first divergent tick. A
  Windows x64 console game runs through the replay engine.
- Worker path: the three operations run through `Broker.execute`, are replay-safe,
  store frames as PNG task artifacts, and the next native turn attaches them only
  when the route has upload bindings (fixture browser bindings; no live provider).
- Dashboard: a real Chromium run loads the example, plays and undoes actions,
  compares both builds, explores, shrinks, opens a bug package and runs regressions.

Not established: play by a signed-in native model, native graphical builds, OS-level
input, trained policies, pointer-driven games, or hardware timing. Exploration that
finds nothing is sampled evidence only.
