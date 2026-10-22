"""Domain-independent play-testing over deterministic game engines.

A domain supplies engines that run one program and expose `feed(bytes)`, `end()`,
`status`, `exit_code`, `input_consumed`, `instructions`, `costs`,
`output_size(stream)`, `output_tail(stream, start)`, `coverage()`, `symbol(name)`,
`read_memory(address, size)`, `diagnostics()`, `snapshot()`, `restore(snapshot)` and
a `capabilities` dict, plus optional `rebind(cancel)` and `snapshot_bytes(snapshot)`.
A Session drives one engine through a validated game spec, decodes ticks and detects
problems. A Pair runs the original and the candidate in lockstep and records the
first divergent tick. Exploration, shrinking, confirmation, bug packages and saved
regressions are built from these.

Every finding names its trajectory (the input log), so it replays exactly. Problems
on the candidate that reproduce on the original with the same trajectory are
original behavior, not reconstruction defects. Harness bounds and cancellation are
inconclusive outcomes (`limit`, `cancelled`), never a pass. Instruction counts are
deterministic costs, not hardware timing.
"""

import math
import random
import re
import time
from collections import deque

from . import game_spec as gs
from .common import ContractError
from .observations import compare_capture

CRASH = (
    "fault",
    "unsupported_syscall",
    "unsupported_cpu_state",
    "unsupported_instruction_or_fault",
    "crash",
)
LIMITS = ("instruction_limit", "wall_clock_limit", "output_limit", "event_limit")
DEFECTS = ("crash", "freeze", "invariant", "slowdown", "bad_exit", "protocol", "divergence")
INCONCLUSIVE = ("limit", "cancelled")
REGRESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")


class Session:
    """One engine under a game spec: inputs, decoded ticks, rules and problems."""

    def __init__(self, spec, engine, side="candidate", history=64):
        self.spec, self.engine, self.side = spec, engine, side
        self.record = spec["input"]["record_bytes"]
        self.sizes = gs.record_sizes(spec)
        self.live = engine.capabilities["stepping"] == "live"
        self.inputs = bytearray()
        self.ticks = 0
        self.recent = deque(maxlen=history)
        self.previous = {}
        self.problems = []
        self.signatures = {}
        self.cost_index = 0
        self.ended = False
        self.ignored_ticks = 0
        self.memory, self.unresolved = [], []
        for item in spec["memory_state"]:
            address = item["address"] if "address" in item else engine.symbol(item["symbol"])
            if address is None or not engine.capabilities.get("memory"):
                self.unresolved.append(item["name"])
            else:
                self.memory.append((item, address + item["offset"]))
        self._observe()

    # Driving.
    @property
    def status(self):
        return self.engine.status

    @property
    def stopped(self):
        """True when further input cannot change what this program does."""
        terminal = self.engine.status not in ("awaiting_input", "ready", "running")
        if self.live:
            return terminal
        # A replay always ends its input; only a stop before consuming it is final.
        return terminal and self.engine.input_consumed < len(self.inputs)

    def rebind(self, cancel):
        """Observe this request's cancellation when a cached session is reused."""
        rebind = getattr(self.engine, "rebind", None)
        if rebind is not None:
            rebind(cancel)

    def feed(self, records):
        if len(records) % self.record:
            raise ContractError("Inputs must be whole input records")
        if (len(self.inputs) + len(records)) // self.record > self.spec["limits"]["max_ticks"]:
            raise ContractError("Trajectory would exceed this game's max_ticks")
        if self.ended:
            raise ContractError("Input has already ended for this session")
        step = self.record if self.live else len(records)
        for offset in range(0, len(records), max(step, 1)):
            if self.stopped:
                self.ignored_ticks += (len(records) - offset) // self.record
                break
            chunk = bytes(records[offset : offset + step])
            self.inputs += chunk
            self.engine.feed(chunk)
            self._observe()

    def end(self):
        if not self.ended:
            self.ended = True
            self.engine.end()
            self._observe()

    # Observation and detection.
    def _problem(self, kind, key, tick, detail):
        signature = (kind, *key)
        if signature in self.signatures:
            return
        self.signatures[signature] = len(self.problems)
        self.problems.append(
            {
                "kind": kind,
                "signature": list(signature),
                "tick": tick,
                "input_ticks": len(self.inputs) // self.record,
                "side": self.side,
                # Problems detected after end of input reproduce only with it.
                "after_end": self.ended,
                "detail": detail,
            }
        )

    def _memory_values(self):
        values = {}
        for item, address in self.memory:
            width = gs.FIELD_TYPES[item["type"]][1]
            try:
                raw = self.engine.read_memory(address, width)
            except ContractError:
                continue
            values[item["name"]] = gs.decode_field(raw, 0, item["type"])
        return values

    def tick_parts(self, start, stop):
        """Raw segments for ticks [start, stop) straight from the engine streams."""
        stdout = self.engine.output_tail("stdout", start * self.sizes["stdout"])
        stderr = self.engine.output_tail("stderr", start * self.sizes["stderr"])
        return [gs.tick_segments(self.spec, stdout, stderr, i) for i in range(stop - start)]

    def _observe(self):
        engine, spec = self.engine, self.spec
        if not self.live:
            # A replay engine re-runs the whole input log with end of input, so
            # every observation is a fresh analysis rather than an increment.
            self.ticks, self.previous, self.cost_index = 0, {}, 0
            self.problems, self.signatures = [], {}
            self.recent.clear()
        sizes = (engine.output_size("stdout"), engine.output_size("stderr"))
        total = gs.complete_ticks(spec, *sizes)
        if total > self.ticks:
            parts = self.tick_parts(self.ticks, total)
            memory = (
                self._memory_values()
                if self.memory and self.live and engine.status == "awaiting_input"
                else {}
            )
            for offset, segments in enumerate(parts):
                index = self.ticks + offset
                values = gs.decode_state(spec, segments)
                if index == total - 1:
                    values.update(memory)
                for violation in gs.check_rules(spec, values, self.previous):
                    self._problem("invariant", (violation["rule"],), index, violation)
                self.previous.update(values)
                self.recent.append({"tick": index, "values": values, "parts": segments})
            self.ticks = total
        slow = spec["limits"].get("slow_tick_instructions")
        costs = engine.costs
        for index in range(self.cost_index, len(costs)):
            if slow and costs[index] > slow:
                self._problem(
                    "slowdown",
                    (),
                    max(self.ticks - 1, 0),
                    {"instructions": costs[index], "budget": slow, "interval": index},
                )
        self.cost_index = len(costs)
        status = engine.status
        diagnostics = engine.diagnostics()
        where = (diagnostics.get("stop_context") or {}).get("function")
        if status in CRASH:
            self._problem("crash", (status, where or "?"), self.ticks, diagnostics)
        elif status == "freeze":
            # Where a budget runs out inside a loop varies with the trajectory, so
            # the location is evidence, not part of the signature.
            self._problem("freeze", (), self.ticks, diagnostics | {"function": where})
        elif status in LIMITS:
            self._problem("limit", (status,), self.ticks, diagnostics)
        elif status == "cancelled":
            self._problem("cancelled", (), self.ticks, {})
        elif status == "completed":
            allowed = spec.get("allowed_exit_codes")
            if allowed is not None and engine.exit_code not in allowed:
                self._problem("bad_exit", (engine.exit_code,), self.ticks, {"exit_code": engine.exit_code})
            records = gs.record_sizes(spec)
            if any(size % record for size, record in zip(sizes, records.values()) if record):
                self._problem("protocol", ("partial_record",), self.ticks, {"bytes": dict(zip(records, sizes))})
        if status in ("awaiting_input", "completed"):
            counts = [size // record for size, record in zip(sizes, gs.record_sizes(spec).values()) if record]
            if len(set(counts)) > 1:
                self._problem("protocol", ("unequal_streams",), self.ticks, {"ticks": counts})

    @property
    def latest(self):
        return self.recent[-1] if self.recent else None

    def snapshot(self, light=False):
        recent = list(self.recent)[-1:] if light else list(self.recent)
        return {
            "engine": self.engine.snapshot(),
            "inputs": bytes(self.inputs),
            "ticks": self.ticks,
            "recent": recent,
            "previous": dict(self.previous),
            "problems": list(self.problems),
            "signatures": dict(self.signatures),
            "cost_index": self.cost_index,
            "ended": self.ended,
            "ignored_ticks": self.ignored_ticks,
        }

    def restore(self, snapshot):
        self.engine.restore(snapshot["engine"])
        self.inputs = bytearray(snapshot["inputs"])
        self.ticks = snapshot["ticks"]
        self.recent = deque(snapshot["recent"], maxlen=self.recent.maxlen)
        self.previous = dict(snapshot["previous"])
        self.problems = list(snapshot["problems"])
        self.signatures = dict(snapshot["signatures"])
        self.cost_index = snapshot["cost_index"]
        self.ended = snapshot["ended"]
        self.ignored_ticks = snapshot["ignored_ticks"]

    def snapshot_bytes(self, snapshot):
        """Approximate memory held by a snapshot (engine state, inputs, frames)."""
        measure = getattr(self.engine, "snapshot_bytes", None)
        held = measure(snapshot["engine"]) if measure else 0
        recent = sum(len(v) for item in snapshot["recent"] for v in item["parts"].values())
        return held + len(snapshot["inputs"]) + recent + 64 * len(snapshot["problems"])

    def cell(self):
        latest = self.latest
        if latest is None:
            return "start"
        return gs.cell(self.spec, latest["values"], latest["parts"])

    def covered(self):
        return sorted(name for name, hits in self.engine.coverage().items() if hits)

    def summary(self):
        return {
            "side": self.side,
            "status": self.engine.status,
            "exit_code": self.engine.exit_code,
            "ticks": self.ticks,
            "input_ticks": len(self.inputs) // self.record,
            "input_consumed": self.engine.input_consumed,
            "ignored_ticks": self.ignored_ticks,
            "ended": self.ended,
            "instructions": self.engine.instructions,
            "problems": self.problems,
        }

    def observation(self, recent=8, view=True):
        latest = self.latest
        result = self.summary() | {
            "trajectory": gs.encode_token(self.inputs),
            "state": latest["values"] if latest else {},
            "recent": [
                {"tick": item["tick"], "state": item["values"]}
                for item in list(self.recent)[-recent:]
            ],
            "cell": self.cell(),
            "coverage": self.covered(),
            "last_tick_instructions": self.engine.costs[-1] if self.engine.costs else None,
            "capabilities": self.engine.capabilities,
            "unresolved_memory_fields": self.unresolved,
        }
        frame, audio = gs.frame_segment(self.spec), gs.audio_segment(self.spec)
        if frame and latest:
            result["frame"] = {
                "tick": latest["tick"],
                "segment": frame["name"],
                "width": frame["width"],
                "height": frame["height"],
            }
            if view:
                result["frame"]["view"] = gs.ascii_view(
                    latest["parts"][frame["name"]], frame["width"], frame["height"]
                )
        if audio and latest:
            result["audio"] = {"tick": latest["tick"]} | gs.audio_summary(
                latest["parts"][audio["name"]], audio
            )
        return result

    def images(self, count=1, label=None):
        """PNG views (and raw RGBA) of the main frame for the most recent ticks."""
        frame = gs.frame_segment(self.spec)
        if frame is None or count < 1:
            return []
        return [
            frame_image(frame, item["parts"][frame["name"]], label or self.side, item["tick"])
            for item in list(self.recent)[-count:]
        ]


def frame_image(frame, raw, side, tick):
    """One frame as an upscaled PNG for agents plus raw RGBA for local viewers."""
    width, height = frame["width"], frame["height"]
    return {
        "name": f"{side}-tick-{tick}.png",
        "data": gs.png(raw, width, height, gs.view_scale(width, height)),
        "rgba": bytes(raw),
        "width": width,
        "height": height,
        "side": side,
        "tick": tick,
    }


def recent_images(sessions, count):
    """Newest ticks first, alternating sides, so a few attachments show both builds."""
    per_side = [list(reversed(session.images(count))) for session in sessions]
    ordered = []
    for index in range(max((len(images) for images in per_side), default=0)):
        for images in per_side:
            if index < len(images):
                ordered.append(images[index])
    return ordered


def _tolerance_rule(segment, tolerances):
    if segment["format"] == "rgba8":
        return {
            "format": "rgba8",
            "width": segment["width"],
            "height": segment["height"],
            **({"max_channel_error": 0, "max_bad_pixels": 0} | tolerances.get(segment["name"], {})),
        }
    return {
        "format": "pcm_s16le",
        "channels": segment["channels"],
        "frames": segment["samples"],
        "sample_rate": segment["sample_rate"],
        **({"max_sample_error": 0, "max_rms_error": 0} | tolerances.get(segment["name"], {})),
    }


def compare_tick(spec, original, candidate):
    """Compare one tick's segments; frames/audio use the pinned tolerances."""
    channels, differences = {}, {}
    state = spec.get("state") or {}
    ignored = set(spec["compare"]["ignore_fields"])
    for name, segment in gs.segments(spec).items():
        a, b = original[name], candidate[name]
        if segment["format"] == "raw":
            if name == state.get("segment"):
                fields = state["fields"]
                masked_a, masked_b = bytearray(a), bytearray(b)
                for field in fields:
                    if field["name"] in ignored:
                        width = gs.FIELD_TYPES[field["type"]][1]
                        masked_a[field["offset"] : field["offset"] + width] = bytes(width)
                        masked_b[field["offset"] : field["offset"] + width] = bytes(width)
                for field in fields:
                    left = gs.decode_field(a, field["offset"], field["type"], field["endian"])
                    right = gs.decode_field(b, field["offset"], field["type"], field["endian"])
                    if left != right and field["name"] not in ignored:
                        differences[field["name"]] = [left, right]
                passed = masked_a == masked_b
                channels[name] = {
                    "format": "state",
                    "passed": passed,
                    "exact": a == b,
                    "fields": dict(differences),
                    "undeclared_bytes_differ": not passed and not differences,
                }
            else:
                channels[name] = {"format": "raw", "passed": a == b, "exact": a == b}
        elif a == b:
            # Identical captures pass under every tolerance; skip per-sample metrics.
            channels[name] = {"format": segment["format"], "passed": True, "exact": True, "reason": "compared"}
        else:
            metric = compare_capture(b, a, _tolerance_rule(segment, spec["compare"]["segments"]))
            metric.pop("frames", None)
            channels[name] = metric
    return all(item["passed"] for item in channels.values()), channels, differences


def _primary(channels, differences, spec):
    state = (spec.get("state") or {}).get("segment")
    if state and not channels[state]["passed"]:
        return "state:" + (next(iter(differences)) if differences else "bytes")
    for name, item in channels.items():
        if not item["passed"]:
            return name
    return "unknown"


class Pair:
    """Original and candidate fed identical inputs in lockstep."""

    def __init__(self, spec, original, candidate, detail_limit=8):
        self.spec, self.original, self.candidate = spec, original, candidate
        self.fed = bytearray()
        self.live = original.live and candidate.live
        self.compared = 0
        self.divergence = None
        self.divergent_ticks = 0
        self.examples = []
        self.detail_limit = detail_limit
        self._compare()

    @property
    def stopped(self):
        return self.divergence is not None or self.original.stopped or self.candidate.stopped

    @property
    def inputs(self):
        return self.fed

    @property
    def ended(self):
        return self.original.ended and self.candidate.ended

    @property
    def problems(self):
        return self.candidate_problems() + ([self.divergence] if self.divergence else [])

    def rebind(self, cancel):
        self.original.rebind(cancel)
        self.candidate.rebind(cancel)

    def feed(self, records):
        record = self.spec["input"]["record_bytes"]
        if len(records) % record:
            raise ContractError("Inputs must be whole input records")
        if (len(self.fed) + len(records)) // record > self.spec["limits"]["max_ticks"]:
            raise ContractError("Trajectory would exceed this game's max_ticks")
        step = record if self.live else len(records)
        for offset in range(0, len(records), max(step, 1)):
            if self.original.stopped and self.candidate.stopped:
                remaining = (len(records) - offset) // record
                self.original.ignored_ticks += remaining
                self.candidate.ignored_ticks += remaining
                break
            chunk = bytes(records[offset : offset + step])
            self.fed += chunk
            for session in (self.original, self.candidate):
                if not session.stopped:
                    session.feed(chunk)
                else:
                    session.ignored_ticks += len(chunk) // record
            self._compare()

    def end(self):
        self.original.end()
        self.candidate.end()
        self._compare(final=True)

    def _diverge(self, tick, channels, differences, primary, extra=None):
        self.divergent_ticks += 1
        item = {
            "kind": "divergence",
            "signature": ["divergence", primary],
            "tick": tick,
            "input_ticks": len(self.fed) // self.spec["input"]["record_bytes"],
            "side": "pair",
            "after_end": self.ended,
            "detail": {"channels": channels, "state_differences": differences, **(extra or {})},
        }
        if len(self.examples) < self.detail_limit:
            self.examples.append({"tick": tick, "primary": primary, "state_differences": differences})
        if self.divergence is None:
            self.divergence = item

    def _compare(self, final=False):
        a, b = self.original, self.candidate
        if not self.live:
            self.compared, self.divergence, self.divergent_ticks, self.examples = 0, None, 0, []
        common = min(a.ticks, b.ticks)
        if common > self.compared:
            left, right = a.tick_parts(self.compared, common), b.tick_parts(self.compared, common)
            for offset, (x, y) in enumerate(zip(left, right)):
                passed, channels, differences = compare_tick(self.spec, x, y)
                if not passed:
                    self._diverge(self.compared + offset, channels, differences, _primary(channels, differences, self.spec))
            self.compared = common
        status = (a.status, b.status)
        if self.divergence is not None or any(s in ("running", "ready") for s in status):
            return
        if any(s in LIMITS or s == "cancelled" for s in status):
            # A harness bound or cancellation says nothing about either program;
            # the ticks compared so far still count, the rest is inconclusive.
            return
        if a.status != b.status:
            self._diverge(common, {}, {}, "status", {"original_status": a.status, "candidate_status": b.status})
        elif (
            a.status == "completed"
            and self.spec["compare"]["exit_code"]
            and a.engine.exit_code != b.engine.exit_code
        ):
            self._diverge(
                common,
                {},
                {},
                "exit_code",
                {"original_exit_code": a.engine.exit_code, "candidate_exit_code": b.engine.exit_code},
            )
        elif a.ticks != b.ticks:
            # Both programs consumed the same input and are waiting or finished.
            self._diverge(common, {}, {}, "ticks", {"original_ticks": a.ticks, "candidate_ticks": b.ticks})

    def candidate_problems(self):
        """Candidate problems, marked when the original shows the same signature."""
        original = {tuple(p["signature"]) for p in self.original.problems}
        return [
            p | {"original_behavior": tuple(p["signature"]) in original}
            for p in self.candidate.problems
            if p["kind"] not in INCONCLUSIVE
        ]

    def inconclusive(self):
        """Harness bounds and cancellation on either side."""
        return inconclusive(self.original.problems) + inconclusive(self.candidate.problems)

    def findings(self):
        """Reconstruction defects, most specific first.

        A candidate-only crash or freeze explains the status divergence it causes;
        otherwise the first divergence comes before candidate-only rule violations,
        which are usually its consequences.
        """
        defects = [p for p in self.candidate_problems() if not p["original_behavior"]]
        severe = [p for p in defects if p["kind"] in ("crash", "freeze")]
        rest = [p for p in defects if p["kind"] not in ("crash", "freeze")]
        return severe + ([self.divergence] if self.divergence else []) + rest

    def snapshot(self, light=False):
        return {
            "original": self.original.snapshot(light),
            "candidate": self.candidate.snapshot(light),
            "fed": bytes(self.fed),
            "compared": self.compared,
            "divergence": self.divergence,
            "divergent_ticks": self.divergent_ticks,
            "examples": list(self.examples),
        }

    def restore(self, snapshot):
        self.original.restore(snapshot["original"])
        self.candidate.restore(snapshot["candidate"])
        self.fed = bytearray(snapshot["fed"])
        self.compared = snapshot["compared"]
        self.divergence = snapshot["divergence"]
        self.divergent_ticks = snapshot["divergent_ticks"]
        self.examples = list(snapshot["examples"])

    def snapshot_bytes(self, snapshot):
        return self.original.snapshot_bytes(snapshot["original"]) + self.candidate.snapshot_bytes(snapshot["candidate"])

    def cell(self):
        return self.original.cell()

    def report(self):
        findings = self.findings()
        stopped = self.inconclusive()
        return {
            "passed": not findings and not stopped,
            "outcome": outcome(findings, stopped),
            "compared_ticks": self.compared,
            "divergence": self.divergence,
            "divergent_ticks": self.divergent_ticks,
            "divergence_examples": self.examples,
            "findings": findings,
            "inconclusive": stopped,
            "original_behavior": [p for p in self.candidate_problems() if p["original_behavior"]],
            "original": self.original.summary(),
            "candidate": self.candidate.summary(),
            "trajectory": gs.encode_token(self.fed),
            "ended": self.ended,
        }


def outcome(findings, stopped=()):
    """Outcome vocabulary for a finished experiment.

    Findings decide first. Without findings, cancellation and harness bounds are
    inconclusive outcomes; only an experiment that ran to its end can pass.
    """
    if findings:
        kinds = {f["kind"] for f in findings}
        for kind in ("crash", "freeze", "divergence", "invariant", "bad_exit", "protocol", "slowdown"):
            if kind in kinds:
                return kind
        return "inconclusive"
    kinds = {p["kind"] for p in stopped}
    if "cancelled" in kinds:
        return "cancelled"
    if "limit" in kinds:
        return "limit"
    return "pass"


def session_findings(session):
    return [p for p in session.problems if p["kind"] not in INCONCLUSIVE]


def inconclusive(problems):
    return [p for p in problems if p["kind"] in INCONCLUSIVE]


def session_report(session):
    found = session_findings(session)
    stopped = inconclusive(session.problems)
    return {
        "passed": not found and not stopped,
        "outcome": outcome(found, stopped),
        "findings": found,
        "inconclusive": stopped,
    }


def check_expectations(spec, values, expect):
    results = []
    for item in expect:
        met = gs.holds(item, values)
        results.append({"condition": item, "met": met, "actual": values.get(item["field"])})
    return results


def start_inputs(spec, start):
    """Inputs and expectations for a named start or a trajectory token."""
    if not start:
        return b"", []
    if start in spec["starts"]:
        item = spec["starts"][start]
        return bytes.fromhex(item["inputs_hex"]), item["expect"]
    return gs.decode_token(start, spec), []


def explore(
    spec,
    make_runner,
    *,
    steps=200,
    seed=0,
    start=b"",
    deadline=None,
    cancel=None,
    max_branch=12,
    sticky=0.7,
    findings_limit=32,
    reference=None,
    max_cells=1024,
    max_archive_bytes=256 * 2**20,
    occurrences=4,
):
    """Go-Explore without training: return to archived cells and try new actions.

    `make_runner()` returns a fresh Session or Pair. Cells come from the declared
    cell fields (the original's state in a Pair) or a coarse frame grid. Newly
    executed functions make a cell more attractive. A branch stops at its first
    finding, which is recorded once per signature with its exact trajectory. When a
    single build is explored, `reference()` (a fresh original Session) classifies
    findings: a signature is original behavior only if the original reproduces
    every recorded occurrence; otherwise an occurrence it does not reproduce is the
    finding. The archive keeps at most `max_cells` cells and `max_archive_bytes` of
    snapshots, evicting the least promising cells. A time limit, cancellation or a
    harness bound on a branch makes the outcome inconclusive rather than a pass.
    """
    if type(steps) is not int or not 1 <= steps <= 20000:
        raise ContractError("Exploration steps must be 1–20000")
    rng = random.Random(seed)
    started = time.monotonic()
    record = spec["input"]["record_bytes"]
    actions = sorted(spec["actions"])
    records = {name: gs.expand(spec, [name]) for name in actions}
    runner = make_runner()
    differential = isinstance(runner, Pair)
    sides = (runner.original, runner.candidate) if differential else (runner,)
    if start:
        runner.feed(start)
    findings, quirks, seen = {}, {}, {}
    stops = []

    def collect(step):
        problems = runner.findings() if differential else session_findings(runner)
        bounded = runner.inconclusive() if differential else inconclusive(runner.problems)
        if problems:
            # One finding per detection: later entries are usually its consequences.
            primary = problems[0]
            key = tuple(primary["signature"])
            occurrence = primary | {
                "trajectory": gs.encode_token(runner.inputs),
                "trajectory_ticks": len(runner.inputs) // record,
                "step": step,
                "consequences": [p["signature"] for p in problems[1:]],
            }
            if key not in findings and len(findings) < findings_limit:
                findings[key] = occurrence
            if key in findings and not differential and reference is not None:
                found = seen.setdefault(key, [])
                if len(found) < occurrences and all(o["trajectory"] != occurrence["trajectory"] for o in found):
                    found.append(occurrence)
        elif bounded:
            stops.append(bounded[0] | {"trajectory": gs.encode_token(runner.inputs), "step": step})
        if differential:
            for problem in runner.candidate_problems():
                if problem["original_behavior"]:
                    quirks.setdefault(
                        tuple(problem["signature"]),
                        problem | {"trajectory": gs.encode_token(runner.inputs)},
                    )
        return bool(problems) or bool(bounded)

    union = {session.side: set() for session in sides}

    def coverage():
        names = set()
        for session in sides:
            now = set(session.covered())
            union[session.side] |= now
            names |= now
        return names

    covered = coverage()
    root = runner.cell()
    archive, held, evicted = {}, 0, 0

    def weight(cell, step):
        entry = archive[cell]
        return (
            (2.0 if entry["new_code"] else 1.0)
            * (1.5 if step - entry["found"] <= 25 else 1.0)
            / math.sqrt(entry["chosen"] + 1)
        )

    def admit(cell, entry, step):
        nonlocal held, evicted
        old = archive.get(cell)
        if old is not None:
            held -= old["bytes"]
        archive[cell] = entry
        held += entry["bytes"]
        while len(archive) > 1 and (len(archive) > max_cells or held > max_archive_bytes):
            victims = [c for c in archive if c not in (root, cell)]
            if not victims:
                break
            victim = min(victims, key=lambda c: (weight(c, step), -archive[c]["ticks"], c))
            held -= archive.pop(victim)["bytes"]
            evicted += 1

    def entry_for(step, ticks, chosen, new_code):
        snapshot = runner.snapshot(light=True)
        return {
            "snapshot": snapshot,
            "bytes": runner.snapshot_bytes(snapshot),
            "ticks": ticks,
            "chosen": chosen,
            "new_code": new_code,
            "found": step,
        }

    if not collect(0):
        admit(root, entry_for(0, len(runner.inputs) // record, 0, True), 0)
    ticks_executed, stopped, completed = 0, "budget", 0
    for step in range(1, steps + 1):
        if not archive:
            stopped = "no_live_cells"
            break
        if cancel is not None and cancel.is_set():
            stopped = "cancelled"
            break
        if deadline is not None and time.monotonic() >= deadline:
            stopped = "deadline"
            break
        cells = sorted(archive)
        chosen = rng.choices(cells, [weight(c, step) for c in cells])[0]
        entry = archive[chosen]
        entry["chosen"] += 1
        runner.restore(entry["snapshot"])
        previous = None
        for _ in range(rng.randint(1, max_branch)):
            action = previous if previous and rng.random() < sticky else rng.choice(actions)
            previous = action
            if (len(runner.inputs) + len(records[action])) // record > spec["limits"]["max_ticks"]:
                break
            runner.feed(records[action])
            ticks_executed += len(records[action]) // record
            if collect(step) or runner.stopped:
                break
            cell = runner.cell()
            now = coverage()
            new_code = bool(now - covered)
            covered |= now
            ticks = len(runner.inputs) // record
            if cell not in archive or ticks < archive[cell]["ticks"]:
                old = archive.get(cell)
                admit(
                    cell,
                    entry_for(
                        step,
                        ticks,
                        old["chosen"] if old else 0,
                        new_code or (old["new_code"] if old else False),
                    ),
                    step,
                )
        completed = step
    classified = True
    if reference is not None and not differential:
        for key in list(findings):
            if cancel is not None and cancel.is_set():
                classified, stopped = False, "cancelled"
                break
            defect = None
            for occurrence in seen.get(key) or [findings[key]]:
                if reproduces(reference, gs.decode_token(occurrence["trajectory"], spec), key) is None:
                    defect = occurrence
                    break
            if defect is None:
                quirks[key] = findings.pop(key) | {
                    "original_behavior": True,
                    "occurrences_checked": len(seen.get(key) or [1]),
                }
            else:
                findings[key] = defect
    found = list(findings.values())
    bounded = list(stops)
    if stopped == "cancelled":
        bounded.append({"kind": "cancelled", "signature": ["cancelled"]})
    elif stopped == "deadline":
        bounded.append({"kind": "limit", "signature": ["limit", "time"]})
    result_outcome = outcome(found, bounded)
    return {
        "mode": "differential" if differential else "single",
        "seed": seed,
        "steps_run": completed,
        "ticks_executed": ticks_executed,
        "cells": len(archive),
        "cells_evicted": evicted,
        "deepest_cell_ticks": max((e["ticks"] for e in archive.values()), default=0),
        "coverage": {side: sorted(names) for side, names in union.items()},
        "findings": found,
        "original_behavior": list(quirks.values()),
        "classified_against_original": classified if reference is not None and not differential else None,
        "limit_hits": len(stops),
        "inconclusive": bounded[:8],
        "passed": result_outcome == "pass",
        "outcome": result_outcome,
        "stopped": stopped,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "claim": "Seeded exploration over the declared actions; a finding is reproducible from its trajectory. A time limit can end it early, so how far it got depends on host speed. Unfound defects are not excluded.",
    }


def reproduces(make_runner, inputs, signature, end=False):
    runner = make_runner()
    runner.feed(inputs)
    if end and not runner.stopped:
        runner.end()
    hits = [f for f in (runner.findings() if isinstance(runner, Pair) else session_findings(runner)) if tuple(f["signature"]) == tuple(signature)]
    return hits[0] if hits else None


def shrink(spec, make_runner, inputs, signature, *, end=False, deadline=None, cancel=None, max_tests=300):
    """Minimize a trajectory while the same problem signature still reproduces.

    `end` replays every trial with end of input, for problems that only appear then.
    """
    record = spec["input"]["record_bytes"]
    neutral = bytes.fromhex(spec["input"]["neutral"])
    started = time.monotonic()
    tests = 0
    stopped = "complete"

    def test(chunks):
        nonlocal tests, stopped
        if tests >= max_tests:
            stopped = "test_budget"
            return None
        if cancel is not None and cancel.is_set():
            stopped = "cancelled"
            return None
        if deadline is not None and time.monotonic() >= deadline:
            stopped = "deadline"
            return None
        tests += 1
        return reproduces(make_runner, b"".join(chunks), signature, end)

    chunks = [inputs[i : i + record] for i in range(0, len(inputs), record)]
    first = test(chunks)
    if first is None:
        return {"reproduced": False, "signature": list(signature), "end": end, "tests": tests, "stopped": stopped}
    original_ticks = len(chunks)
    # Later inputs cannot influence a problem detected earlier.
    chunks = chunks[: max(1, first["input_ticks"])]
    granularity = 2
    while len(chunks) >= 2 and stopped == "complete":
        size = math.ceil(len(chunks) / granularity)
        removed = False
        for index in range(granularity):
            trial = chunks[: index * size] + chunks[(index + 1) * size :]
            if not trial:
                continue
            hit = test(trial)
            if hit is not None:
                chunks = trial[: max(1, hit["input_ticks"])]
                granularity = max(granularity - 1, 2)
                removed = True
                break
            if stopped != "complete":
                break
        if not removed:
            if granularity >= len(chunks):
                break
            granularity = min(granularity * 2, len(chunks))
    for index in range(len(chunks)):
        if stopped != "complete":
            break
        if chunks[index] == neutral:
            continue
        trial = chunks[:index] + [neutral] + chunks[index + 1 :]
        if test(trial) is not None:
            chunks = trial
    minimized = b"".join(chunks)
    confirmations = [reproduces(make_runner, minimized, signature, end) for _ in range(2)]
    confirmed = all(confirmations) and len({c["tick"] for c in confirmations}) == 1
    return {
        "reproduced": True,
        "signature": list(signature),
        "end": end,
        "original_ticks": original_ticks,
        "minimized_ticks": len(chunks),
        "trajectory": gs.encode_token(minimized),
        "controls": gs.control_names(spec, minimized),
        "problem": confirmations[0] if confirmations[0] else first,
        "confirmed": confirmed,
        "tests": tests,
        "stopped": stopped,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }


def package(spec, make_runner, inputs, signature=None, window=8, images=2, end=False):
    """Bug package: inputs, state window, frames around the failing tick, coverage."""
    runner = make_runner()
    differential = isinstance(runner, Pair)
    sessions = (runner.original, runner.candidate) if differential else (runner,)
    for session in sessions:
        session.recent = deque(maxlen=max(window, images) + 1)
    runner.feed(inputs)
    if end and not runner.stopped:
        runner.end()
    problems = runner.findings() if differential else session_findings(runner)
    chosen = next(
        (p for p in problems if signature is None or tuple(p["signature"]) == tuple(signature)),
        None,
    )
    if chosen is None:
        stopped = runner.inconclusive() if differential else inconclusive(runner.problems)
        return {"reproduced": False, "signature": signature, "end": end, "outcome": outcome(problems, stopped)}
    tick = chosen["tick"]
    first, last = max(0, tick - window), tick + 1
    states, pictures = {}, []
    frame = gs.frame_segment(spec)
    for session in sessions:
        stop = min(last, session.ticks)
        start = min(first, stop)
        parts = session.tick_parts(start, stop)
        states[session.side] = [
            {"tick": start + i, "state": gs.decode_state(spec, p)} for i, p in enumerate(parts)
        ]
        if frame and images:
            for i, p in list(enumerate(parts))[-images:]:
                pictures.append(frame_image(frame, p[frame["name"]], session.side, start + i))
    controls = gs.control_names(spec, inputs)
    return {
        "reproduced": True,
        "problem": chosen,
        "outcome": outcome([chosen]),
        "trajectory": gs.encode_token(inputs),
        "end": end,
        "input_controls": controls[-(window * 4) :],
        "input_ticks": len(controls),
        "state_window": states,
        "coverage": {s.side: s.covered() for s in sessions},
        "diagnostics": {s.side: s.engine.diagnostics() for s in sessions},
        "_images": pictures,
    }


def validate_regressions(spec, value):
    if not isinstance(value, dict) or set(value) - {"version", "regressions"} or value.get("version") != 1:
        raise ContractError("Regressions file needs version 1 and a regressions list")
    items = value.get("regressions")
    if not isinstance(items, list) or len(items) > 256:
        raise ContractError("Keep at most 256 regressions")
    ids = set()
    record = spec["input"]["record_bytes"]
    for item in items:
        if not isinstance(item, dict) or set(item) - {"id", "inputs_hex", "expect", "end", "signature", "note"}:
            raise ContractError("Regressions take id, inputs_hex, expect, end, signature and note")
        if not isinstance(item.get("id"), str) or not REGRESSION_ID.fullmatch(item["id"]) or item["id"] in ids:
            raise ContractError("Regression IDs must be unique short names")
        ids.add(item["id"])
        data = gs._hex(item.get("inputs_hex"), "Regression inputs")
        if len(data) % record or len(data) // record > spec["limits"]["max_ticks"]:
            raise ContractError("Regression inputs must be whole records within max_ticks")
        if item.setdefault("expect", "match_original") not in ("match_original", "no_problems"):
            raise ContractError("Regression expect is match_original or no_problems")
        if type(item.setdefault("end", True)) is not bool:
            raise ContractError("Regression end must be boolean")
        if "note" in item and (not isinstance(item["note"], str) or len(item["note"]) > 500):
            raise ContractError("Regression notes are at most 500 characters")
    return items


def run_regressions(spec, make_pair, make_session, items, *, deadline=None, cancel=None):
    results = []
    for item in items:
        if cancel is not None and cancel.is_set():
            results.append({"id": item["id"], "passed": False, "outcome": "cancelled"})
            continue
        if deadline is not None and time.monotonic() >= deadline:
            results.append({"id": item["id"], "passed": False, "outcome": "limit", "reason": "time limit"})
            continue
        inputs = bytes.fromhex(item["inputs_hex"])
        if item["expect"] == "match_original":
            runner = make_pair()
            runner.feed(inputs)
            if item["end"]:
                runner.end()
            report = runner.report()
            results.append(
                {
                    "id": item["id"],
                    "expect": item["expect"],
                    "end": item["end"],
                    "passed": report["passed"],
                    "outcome": report["outcome"],
                    "divergence": report["divergence"],
                    "findings": report["findings"],
                    "inconclusive": report["inconclusive"],
                    "trajectory": report["trajectory"],
                }
            )
        else:
            session = make_session()
            session.feed(inputs)
            if item["end"]:
                session.end()
            report = session_report(session)
            results.append(
                {
                    "id": item["id"],
                    "expect": item["expect"],
                    "end": item["end"],
                    **report,
                    "trajectory": gs.encode_token(session.inputs),
                }
            )
    return {
        "passed": all(r["passed"] for r in results),
        "total": len(results),
        "failed": [r["id"] for r in results if not r["passed"]],
        "results": results,
    }
