"""Owner-declared game test contracts: tick inputs, observations, rules and cells.

A game spec tells HA how to drive and observe a deterministic program one tick at a
time. Inputs are fixed-size records fed through the program's own input stream, so
a play session is reproduced exactly by its input log (its trajectory). Each tick's
outputs are fixed-size records on standard output/error, decoded into named state
fields, raw RGBA frames and signed 16-bit PCM audio. Rules are declarative checks on
decoded state; nothing in a spec is evaluated as code. Cells group similar
situations for exploration. Everything is bounded and invalid contracts are rejected
rather than guessed.
"""

import base64
import hashlib
import json
import math
import re
import struct
import zlib
from pathlib import PurePosixPath

from .common import ContractError, canonical, digest

NAME = re.compile(r"[a-z][a-z0-9_]{0,31}")
FIELD_TYPES = {
    "u8": ("B", 1),
    "i8": ("b", 1),
    "u16": ("H", 2),
    "i16": ("h", 2),
    "u32": ("I", 4),
    "i32": ("i", 4),
    "u64": ("Q", 8),
    "i64": ("q", 8),
}
OPERATORS = ("==", "!=", "<", "<=", ">", ">=")
MAX_TICKS = 4096
MAX_RECORD = 64
MAX_TICK_OUTPUT = 262144
MAX_INSTRUCTIONS = 10_000_000
TOKEN_PREFIX = "g1."
SYMBOLS = ".#@o*+x=%&$~^:;-"
FIELDS = {
    "version",
    "name",
    "platform",
    "original_path",
    "candidate_manifest",
    "candidate_path",
    "process",
    "input",
    "actions",
    "output",
    "state",
    "memory_state",
    "rules",
    "cells",
    "limits",
    "compare",
    "functions",
    "starts",
    "allowed_exit_codes",
    "regressions_path",
}


def _integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ContractError(f"{name} must be an integer from {low} to {high}")
    return value


def _name(value, what):
    if not isinstance(value, str) or not NAME.fullmatch(value):
        raise ContractError(
            f"{what} names use 1–32 lowercase letters, digits or underscores, starting with a letter"
        )
    return value


def _hex(value, what, size=None, limit=MAX_TICKS * MAX_RECORD):
    if not isinstance(value, str) or len(value) > 2 * limit:
        raise ContractError(f"{what} must be bounded hexadecimal text")
    try:
        data = bytes.fromhex(value)
    except ValueError as error:
        raise ContractError(f"{what} must be hexadecimal") from error
    if size is not None and len(data) != size:
        raise ContractError(f"{what} must be exactly {size} bytes")
    return data


def relative(value, what):
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 240
        or any(c in value for c in ("\\", ":", "\0"))
    ):
        raise ContractError(f"{what} must be a relative project path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(p in ("", ".", "..") for p in value.split("/")):
        raise ContractError(f"{what} must stay inside the project")
    return value


def _condition(item, fields, what):
    if not isinstance(item, dict) or set(item) - {"field", "op", "value", "other"}:
        raise ContractError(f"{what} conditions use field, op and value or other")
    if item.get("field") not in fields:
        raise ContractError(f"{what} condition names an unknown field")
    if item.get("op") not in OPERATORS:
        raise ContractError(f"{what} condition operator must be one of " + ", ".join(OPERATORS))
    if ("value" in item) == ("other" in item):
        raise ContractError(f"{what} condition needs exactly one of value or other")
    if "value" in item:
        _integer(item["value"], what + " value", -(2**63), 2**64 - 1)
    elif item["other"] not in fields:
        raise ContractError(f"{what} condition compares with an unknown field")
    return item


def conditions(value, fields, what):
    if not isinstance(value, list) or len(value) > 16:
        raise ContractError(f"{what} takes at most 16 conditions")
    return [_condition(item, fields, what) for item in value]


def _segment(item, names):
    if not isinstance(item, dict):
        raise ContractError("Output segments must be objects")
    if "size" in item:
        # Normalized specs carry the derived size; it must still agree.
        item = dict(item)
        declared = item.pop("size")
        result = _segment(item, names)
        if declared != result["size"]:
            raise ContractError("Segment size does not match its declared format")
        return result
    name = _name(item.get("name"), "Output segment")
    if name in names:
        raise ContractError("Output segment names must be unique")
    names.add(name)
    kind = item.get("format", "raw")
    if kind == "raw":
        if set(item) - {"name", "format", "bytes"}:
            raise ContractError("Raw segments take name and bytes")
        size = _integer(item.get("bytes"), "Segment bytes", 1, 65536)
        return {"name": name, "format": "raw", "bytes": size, "size": size}
    if kind == "rgba8":
        if set(item) - {"name", "format", "width", "height"}:
            raise ContractError("RGBA segments take name, width and height")
        width = _integer(item.get("width"), "Frame width", 1, 512)
        height = _integer(item.get("height"), "Frame height", 1, 512)
        return {
            "name": name,
            "format": "rgba8",
            "width": width,
            "height": height,
            "size": width * height * 4,
        }
    if kind == "pcm_s16le":
        if set(item) - {"name", "format", "channels", "samples", "sample_rate"}:
            raise ContractError("PCM segments take name, channels, samples and sample_rate")
        channels = _integer(item.get("channels"), "Audio channels", 1, 8)
        samples = _integer(item.get("samples"), "Audio samples per tick", 1, 65536)
        rate = _integer(item.get("sample_rate"), "Audio sample rate", 1, 384000)
        return {
            "name": name,
            "format": "pcm_s16le",
            "channels": channels,
            "samples": samples,
            "sample_rate": rate,
            "size": channels * samples * 2,
        }
    raise ContractError("Segment format must be raw, rgba8 or pcm_s16le")


def _tolerance(segment, rule):
    if not isinstance(rule, dict):
        raise ContractError("Comparison tolerances must be objects")
    if segment["format"] == "rgba8":
        if set(rule) - {"max_channel_error", "max_bad_pixels"}:
            raise ContractError("Frame tolerances are max_channel_error and max_bad_pixels")
        return {
            "max_channel_error": _integer(rule.get("max_channel_error", 0), "max_channel_error", 0, 255),
            "max_bad_pixels": _integer(
                rule.get("max_bad_pixels", 0),
                "max_bad_pixels",
                0,
                segment["width"] * segment["height"],
            ),
        }
    if segment["format"] == "pcm_s16le":
        if set(rule) - {"max_sample_error", "max_rms_error"}:
            raise ContractError("Audio tolerances are max_sample_error and max_rms_error")
        rms = rule.get("max_rms_error", 0)
        if type(rms) not in (int, float) or not math.isfinite(rms) or not 0 <= rms <= 65535:
            raise ContractError("max_rms_error must be finite and between 0 and 65535")
        return {
            "max_sample_error": _integer(rule.get("max_sample_error", 0), "max_sample_error", 0, 65535),
            "max_rms_error": rms,
        }
    raise ContractError("Only frame and audio segments accept tolerances; raw bytes stay exact")


def validate(spec):
    """Return a normalized copy of a game spec or raise ContractError."""
    if not isinstance(spec, dict):
        raise ContractError("A game spec must be a JSON object")
    unknown = set(spec) - FIELDS
    if unknown:
        raise ContractError("Unknown game spec fields: " + ", ".join(sorted(unknown)))
    if len(canonical(spec)) > 262144:
        raise ContractError("Game spec exceeds 256 KiB")
    value = json.loads(canonical(spec))
    if value.get("version") != 1:
        raise ContractError("Expected game spec version 1")
    name = value.setdefault("name", "Game")
    if not isinstance(name, str) or not 1 <= len(name) <= 80:
        raise ContractError("Game name must have 1–80 characters")
    if value.setdefault("platform", "linux") not in ("linux", "windows"):
        raise ContractError("Game platform must be linux or windows")
    for key in ("original_path", "candidate_manifest", "candidate_path"):
        if key in value:
            relative(value[key], key)
    if "candidate_manifest" in value and "candidate_path" in value:
        raise ContractError("Use candidate_manifest or candidate_path, not both")
    regressions = value.setdefault("regressions_path", "game-regressions.json")
    relative(regressions, "regressions_path")
    process = value.setdefault("process", {})
    allowed_process = (
        {"argv", "env", "clock_ns"}
        if value["platform"] == "linux"
        else {"command_line", "env", "clock_ms"}
    )
    if not isinstance(process, dict) or set(process) - allowed_process:
        raise ContractError("Process inputs allow " + ", ".join(sorted(allowed_process)))

    inputs = value.get("input")
    if not isinstance(inputs, dict) or set(inputs) - {"record_bytes", "neutral", "controls"}:
        raise ContractError("input requires record_bytes and controls, with optional neutral")
    size = _integer(inputs.get("record_bytes"), "record_bytes", 1, MAX_RECORD)
    neutral = inputs.setdefault("neutral", "00" * size)
    _hex(neutral, "Neutral input", size)
    controls = inputs.get("controls")
    if not isinstance(controls, dict) or not 1 <= len(controls) <= 64:
        raise ContractError("Declare 1–64 named controls")
    for control, record in controls.items():
        _name(control, "Control")
        _hex(record, "Control " + control, size)

    actions = value.setdefault("actions", {c: [[c, 1]] for c in controls})
    if not isinstance(actions, dict) or not 1 <= len(actions) <= 64:
        raise ContractError("Declare 1–64 named actions")
    for action, steps in actions.items():
        _name(action, "Action")
        if not isinstance(steps, list) or not 1 <= len(steps) <= 16:
            raise ContractError("Each action has 1–16 [control, ticks] steps")
        total = 0
        for step in steps:
            if (
                not isinstance(step, list)
                or len(step) != 2
                or step[0] not in controls
            ):
                raise ContractError("Action steps are [declared control, ticks]")
            total += _integer(step[1], "Action ticks", 1, 240)
        if total > 600:
            raise ContractError("An action may span at most 600 ticks")

    output = value.get("output")
    if not isinstance(output, dict) or set(output) - {"stdout", "stderr"}:
        raise ContractError("output declares per-tick stdout and/or stderr segments")
    names = set()
    for stream in ("stdout", "stderr"):
        segments = output.setdefault(stream, [])
        if not isinstance(segments, list) or len(segments) > 16:
            raise ContractError("Each stream declares at most 16 segments")
        output[stream] = [_segment(item, names) for item in segments]
        if sum(s["size"] for s in output[stream]) > MAX_TICK_OUTPUT:
            raise ContractError("Per-tick output exceeds 256 KiB on " + stream)
    if not names:
        raise ContractError("Declare at least one per-tick output segment")
    segments = {s["name"]: s for stream in ("stdout", "stderr") for s in output[stream]}

    fields = {}
    state = value.get("state")
    if state is not None:
        if not isinstance(state, dict) or set(state) - {"segment", "fields"}:
            raise ContractError("state names a raw segment and its fields")
        segment = segments.get(state.get("segment"))
        if not segment or segment["format"] != "raw":
            raise ContractError("state must name a raw output segment")
        items = state.get("fields")
        if not isinstance(items, list) or not 1 <= len(items) <= 64:
            raise ContractError("Declare 1–64 state fields")
        for item in items:
            if not isinstance(item, dict) or set(item) - {"name", "offset", "type", "endian"}:
                raise ContractError("State fields take name, offset, type and endian")
            field = _name(item.get("name"), "State field")
            if field in fields:
                raise ContractError("State field names must be unique")
            if item.get("type") not in FIELD_TYPES:
                raise ContractError("State field type must be one of " + ", ".join(FIELD_TYPES))
            if item.setdefault("endian", "little") not in ("little", "big"):
                raise ContractError("State field endian must be little or big")
            width = FIELD_TYPES[item["type"]][1]
            _integer(item.get("offset"), "State field offset", 0, segment["size"] - width)
            fields[field] = "state"
    memory = value.setdefault("memory_state", [])
    if not isinstance(memory, list) or len(memory) > 32:
        raise ContractError("Declare at most 32 memory state fields")
    for item in memory:
        if not isinstance(item, dict) or set(item) - {"name", "symbol", "address", "offset", "type"}:
            raise ContractError("Memory fields take name, symbol or address, offset and type")
        field = _name(item.get("name"), "Memory field")
        if field in fields:
            raise ContractError("Memory field names must be unique and differ from state fields")
        if ("symbol" in item) == ("address" in item):
            raise ContractError("Memory fields need exactly one of symbol or address")
        if "symbol" in item and (
            not isinstance(item["symbol"], str)
            or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.$]{0,127}", item["symbol"])
        ):
            raise ContractError("Invalid memory symbol name")
        if "address" in item:
            _integer(item["address"], "Memory address", 0, 2**64 - 1)
        _integer(item.setdefault("offset", 0), "Memory offset", 0, 1 << 20)
        if item.get("type") not in FIELD_TYPES:
            raise ContractError("Memory field type must be one of " + ", ".join(FIELD_TYPES))
        fields[field] = "memory"

    rules = value.setdefault("rules", [])
    if not isinstance(rules, list) or len(rules) > 64:
        raise ContractError("Declare at most 64 rules")
    ids = set()
    checks = {"min", "max", "min_field", "max_field", "equals", "not_equals", "monotonic", "max_step"}
    for rule in rules:
        if not isinstance(rule, dict) or set(rule) - checks - {"id", "field", "when"}:
            raise ContractError("Unknown rule fields")
        rule_id = _name(rule.get("id"), "Rule")
        if rule_id in ids:
            raise ContractError("Rule IDs must be unique")
        ids.add(rule_id)
        if rule.get("field") not in fields:
            raise ContractError("Rule " + rule_id + " names an unknown field")
        if not checks & set(rule):
            raise ContractError("Rule " + rule_id + " declares no check")
        for key in ("min", "max", "equals", "not_equals"):
            if key in rule:
                _integer(rule[key], "Rule " + key, -(2**63), 2**64 - 1)
        for key in ("min_field", "max_field"):
            if key in rule and rule[key] not in fields:
                raise ContractError("Rule " + rule_id + " compares with an unknown field")
        if rule.get("monotonic", "nondecreasing") not in ("nondecreasing", "nonincreasing"):
            raise ContractError("monotonic is nondecreasing or nonincreasing")
        if "max_step" in rule:
            _integer(rule["max_step"], "max_step", 0, 2**63 - 1)
        if "when" in rule:
            rule["when"] = conditions(rule["when"], fields, "Rule when")

    cells = value.get("cells")
    if cells is not None:
        if not isinstance(cells, dict) or set(cells) - {"fields", "quantize"}:
            raise ContractError("cells take fields and optional quantize")
        chosen = cells.get("fields")
        if (
            not isinstance(chosen, list)
            or not 1 <= len(chosen) <= 8
            or len(set(chosen)) != len(chosen)
            or any(f not in fields for f in chosen)
        ):
            raise ContractError("cells.fields lists 1–8 distinct declared fields")
        quantize = cells.setdefault("quantize", {})
        if not isinstance(quantize, dict) or set(quantize) - set(chosen):
            raise ContractError("cells.quantize applies only to cell fields")
        for field, step in quantize.items():
            _integer(step, "Cell quantization", 1, 1 << 30)

    limits = value.setdefault("limits", {})
    if not isinstance(limits, dict) or set(limits) - {
        "max_ticks",
        "max_instructions",
        "freeze_tick_instructions",
        "slow_tick_instructions",
    }:
        raise ContractError("Unknown limits")
    _integer(limits.setdefault("max_ticks", 1000), "max_ticks", 1, MAX_TICKS)
    total = _integer(
        limits.setdefault("max_instructions", MAX_INSTRUCTIONS), "max_instructions", 1000, MAX_INSTRUCTIONS
    )
    freeze = _integer(
        limits.setdefault("freeze_tick_instructions", min(2_000_000, total)),
        "freeze_tick_instructions",
        1000,
        total,
    )
    if "slow_tick_instructions" in limits:
        _integer(limits["slow_tick_instructions"], "slow_tick_instructions", 1, freeze - 1)

    compare = value.setdefault("compare", {})
    if not isinstance(compare, dict) or set(compare) - {"ignore_fields", "segments", "exit_code"}:
        raise ContractError("compare takes ignore_fields, segments and exit_code")
    ignored = compare.setdefault("ignore_fields", [])
    if not isinstance(ignored, list) or any(f not in fields or fields[f] != "state" for f in ignored):
        raise ContractError("ignore_fields lists declared state fields")
    tolerances = compare.setdefault("segments", {})
    if not isinstance(tolerances, dict) or set(tolerances) - set(segments):
        raise ContractError("Comparison tolerances name declared segments")
    for segment_name, rule in list(tolerances.items()):
        tolerances[segment_name] = _tolerance(segments[segment_name], rule)
    if type(compare.setdefault("exit_code", True)) is not bool:
        raise ContractError("compare.exit_code must be boolean")

    functions = value.setdefault("functions", {})
    if not isinstance(functions, dict) or len(functions) > 256:
        raise ContractError("functions maps at most 256 names to addresses")
    for function, address in functions.items():
        if not isinstance(function, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.$]{0,127}", function):
            raise ContractError("Invalid function name")
        _integer(address, "Function address", 0, 2**64 - 1)

    starts = value.setdefault("starts", {})
    if not isinstance(starts, dict) or len(starts) > 32:
        raise ContractError("Declare at most 32 named starts")
    for start, item in starts.items():
        _name(start, "Start")
        if not isinstance(item, dict) or set(item) - {"inputs_hex", "expect"}:
            raise ContractError("Starts take inputs_hex and optional expect")
        data = _hex(item.get("inputs_hex"), "Start inputs")
        if len(data) % size or len(data) // size > limits["max_ticks"]:
            raise ContractError("Start inputs must be whole records within max_ticks")
        item["expect"] = conditions(item.get("expect", []), fields, "Start")

    exits = value.get("allowed_exit_codes")
    if exits is not None and (
        not isinstance(exits, list)
        or not 1 <= len(exits) <= 64
        or any(type(c) is not int or not 0 <= c <= 0xFFFFFFFF for c in exits)
    ):
        raise ContractError("allowed_exit_codes lists 1–64 exit codes")
    return value


def spec_hash(spec):
    return digest(spec)


def segments(spec):
    return {s["name"]: s for stream in ("stdout", "stderr") for s in spec["output"][stream]}


def frame_segment(spec):
    return next((s for s in spec["output"]["stdout"] + spec["output"]["stderr"] if s["format"] == "rgba8"), None)


def audio_segment(spec):
    return next((s for s in spec["output"]["stdout"] + spec["output"]["stderr"] if s["format"] == "pcm_s16le"), None)


def field_names(spec):
    names = [f["name"] for f in (spec.get("state") or {}).get("fields", [])]
    return names + [f["name"] for f in spec["memory_state"]]


def record_sizes(spec):
    return {stream: sum(s["size"] for s in spec["output"][stream]) for stream in ("stdout", "stderr")}


def complete_ticks(spec, stdout_size, stderr_size):
    """Ticks with a complete record on every stream that declares one."""
    counts = [
        size // record
        for size, record in zip((stdout_size, stderr_size), record_sizes(spec).values())
        if record
    ]
    return min(counts)


def tick_segments(spec, stdout, stderr, index):
    """Raw bytes of every declared segment for one tick."""
    result = {}
    for stream, data in (("stdout", stdout), ("stderr", stderr)):
        record = sum(s["size"] for s in spec["output"][stream])
        offset = index * record
        for segment in spec["output"][stream]:
            result[segment["name"]] = bytes(data[offset : offset + segment["size"]])
            offset += segment["size"]
    return result


def decode_field(raw, offset, kind, endian="little"):
    code, width = FIELD_TYPES[kind]
    return struct.unpack_from(("<" if endian == "little" else ">") + code, raw, offset)[0]


def decode_state(spec, parts):
    state = spec.get("state")
    if not state:
        return {}
    raw = parts[state["segment"]]
    return {
        f["name"]: decode_field(raw, f["offset"], f["type"], f["endian"])
        for f in state["fields"]
    }


def holds(item, values):
    """Evaluate one declarative condition; None when a value is unavailable."""
    left = values.get(item["field"])
    right = item["value"] if "value" in item else values.get(item["other"])
    if left is None or right is None:
        return None
    return {
        "==": left == right,
        "!=": left != right,
        "<": left < right,
        "<=": left <= right,
        ">": left > right,
        ">=": left >= right,
    }[item["op"]]


def check_rules(spec, values, previous):
    """Return violations for one tick. `previous` holds the prior tick's values."""
    violations = []
    for rule in spec["rules"]:
        if "when" in rule and not all(holds(c, values) for c in rule["when"]):
            continue
        value = values.get(rule["field"])
        if value is None:
            continue
        failed = []
        for key, bound in (("min", rule.get("min")), ("max", rule.get("max"))):
            if bound is not None and (value < bound if key == "min" else value > bound):
                failed.append(key)
        for key in ("min_field", "max_field"):
            if key in rule:
                other = values.get(rule[key])
                if other is not None and (value < other if key == "min_field" else value > other):
                    failed.append(key)
        if "equals" in rule and value != rule["equals"]:
            failed.append("equals")
        if "not_equals" in rule and value == rule["not_equals"]:
            failed.append("not_equals")
        before = previous.get(rule["field"])
        if before is not None:
            if "monotonic" in rule and (
                value < before if rule["monotonic"] == "nondecreasing" else value > before
            ):
                failed.append("monotonic")
            if "max_step" in rule and abs(value - before) > rule["max_step"]:
                failed.append("max_step")
        if failed:
            violations.append(
                {
                    "rule": rule["id"],
                    "field": rule["field"],
                    "value": value,
                    "previous": before,
                    "failed": failed,
                }
            )
    return violations


def cell(spec, values, parts):
    """A coarse situation key for exploration archives."""
    cells = spec.get("cells")
    if cells:
        quantize = cells.get("quantize", {})
        items = []
        for field in cells["fields"]:
            value = values.get(field)
            if value is not None:
                value //= quantize.get(field, 1)
            items.append(f"{field}={value}")
        return ",".join(items)
    frame = frame_segment(spec)
    if frame is None:
        return "state:" + hashlib.sha256(
            b"".join(parts[s["name"]] for s in spec["output"]["stdout"] if s["format"] == "raw")
        ).hexdigest()[:16]
    # Go-Explore style: an 8x8 grid of 8-level luminance averages.
    raw, width, height = parts[frame["name"]], frame["width"], frame["height"]
    grid = []
    for gy in range(8):
        for gx in range(8):
            x0, x1 = gx * width // 8, max(gx * width // 8 + 1, (gx + 1) * width // 8)
            y0, y1 = gy * height // 8, max(gy * height // 8 + 1, (gy + 1) * height // 8)
            total = count = 0
            for y in range(y0, min(y1, height)):
                for x in range(x0, min(x1, width)):
                    o = (y * width + x) * 4
                    total += raw[o] * 3 + raw[o + 1] * 6 + raw[o + 2]
                    count += 1
            grid.append(str(min(7, total // max(count, 1) // 320)))
    return "frame:" + "".join(grid)


def encode_token(inputs):
    """A self-contained, integrity-checked trajectory handle (the input log)."""
    packed = base64.urlsafe_b64encode(zlib.compress(bytes(inputs), 9)).decode().rstrip("=")
    return TOKEN_PREFIX + packed + "." + hashlib.sha256(bytes(inputs)).hexdigest()[:16]


def decode_token(token, spec):
    if token in (None, ""):
        return b""
    if not isinstance(token, str) or len(token) > 400000 or not token.startswith(TOKEN_PREFIX):
        raise ContractError("Unknown trajectory token")
    try:
        packed, check = token[len(TOKEN_PREFIX):].rsplit(".", 1)
        compressed = base64.urlsafe_b64decode(packed + "=" * (-len(packed) % 4))
        decoder = zlib.decompressobj()
        inputs = decoder.decompress(compressed, MAX_TICKS * MAX_RECORD + 1)
    except (ValueError, zlib.error) as error:
        raise ContractError("Corrupt trajectory token") from error
    if decoder.unconsumed_tail or hashlib.sha256(inputs).hexdigest()[:16] != check:
        raise ContractError("Corrupt trajectory token")
    size = spec["input"]["record_bytes"]
    if len(inputs) % size or len(inputs) // size > spec["limits"]["max_ticks"]:
        raise ContractError("Trajectory does not fit this game's input records and max_ticks")
    return inputs


def expand(spec, steps):
    """Turn action names and explicit control/record steps into input records."""
    if not isinstance(steps, list) or len(steps) > 64:
        raise ContractError("Supply at most 64 steps per request")
    size = spec["input"]["record_bytes"]
    controls = spec["input"]["controls"]
    records = bytearray()
    for step in steps:
        if isinstance(step, str):
            if step not in spec["actions"]:
                raise ContractError("Unknown action: " + step[:40])
            for control, ticks in spec["actions"][step]:
                records += bytes.fromhex(controls[control]) * ticks
            continue
        if not isinstance(step, dict) or set(step) - {"control", "record", "ticks"}:
            raise ContractError("Steps are action names, {control, ticks} or {record, ticks}")
        ticks = _integer(step.get("ticks", 1), "Step ticks", 1, 600)
        if ("control" in step) == ("record" in step):
            raise ContractError("A step names exactly one control or raw record")
        if "control" in step:
            if step["control"] not in controls:
                raise ContractError("Unknown control")
            record = bytes.fromhex(controls[step["control"]])
        else:
            record = _hex(step["record"], "Raw input record", size)
        records += record * ticks
        if len(records) // size > MAX_TICKS:
            break
    if len(records) // size > 2000:
        raise ContractError("A request may add at most 2000 ticks")
    return bytes(records)


def control_names(spec, inputs):
    """Readable per-tick control names (raw hex when no control matches)."""
    size = spec["input"]["record_bytes"]
    by_record = {}
    for name, record in spec["input"]["controls"].items():
        by_record.setdefault(record, name)
    return [
        by_record.get(inputs[i : i + size].hex(), inputs[i : i + size].hex())
        for i in range(0, len(inputs), size)
    ]


def describe(spec):
    """Compact contract summary for agents and the dashboard."""
    frame, audio = frame_segment(spec), audio_segment(spec)
    return {
        "name": spec["name"],
        "platform": spec["platform"],
        "record_bytes": spec["input"]["record_bytes"],
        "controls": sorted(spec["input"]["controls"]),
        "actions": {
            name: {"steps": steps, "ticks": sum(t for _, t in steps)}
            for name, steps in spec["actions"].items()
        },
        "segments": [
            {k: v for k, v in s.items() if k != "size"} | {"stream": stream}
            for stream in ("stdout", "stderr")
            for s in spec["output"][stream]
        ],
        "frame": frame and {"segment": frame["name"], "width": frame["width"], "height": frame["height"]},
        "audio": audio and {"segment": audio["name"], "samples": audio["samples"], "channels": audio["channels"]},
        "fields": field_names(spec),
        "rules": [r["id"] for r in spec["rules"]],
        "cells": spec.get("cells") or "frame luminance grid",
        "limits": spec["limits"],
        "starts": sorted(spec["starts"]),
        "comparison": spec["compare"],
    }


def png(rgba, width, height, scale=1):
    """Encode tightly packed RGBA8 pixels as PNG with integer nearest-neighbor scaling."""
    if len(rgba) != width * height * 4 or not 1 <= scale <= 64:
        raise ContractError("Frame bytes do not match the declared size")
    stride = width * 4
    lines = []
    for y in range(height):
        row = bytes(rgba[y * stride : (y + 1) * stride])
        if scale > 1:
            row = b"".join(row[i : i + 4] * scale for i in range(0, stride, 4))
        lines.append((b"\x00" + row) * scale)

    def chunk(kind, data):
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width * scale, height * scale, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(b"".join(lines), 6))
        + chunk(b"IEND", b"")
    )


def view_scale(width, height):
    return max(1, min(16, 512 // max(width, height)))


def ascii_view(rgba, width, height):
    """A character map of small frames for text-only readers; None for large frames."""
    if width > 64 or height > 48:
        return None
    legend, rows, truncated = {}, [], False
    for y in range(height):
        row = []
        for x in range(width):
            o = (y * width + x) * 4
            color = tuple(rgba[o : o + 4])
            if color not in legend:
                if len(legend) < len(SYMBOLS):
                    legend[color] = SYMBOLS[len(legend)]
                else:
                    truncated = True
            row.append(legend.get(color, "?"))
        rows.append("".join(row))
    return {
        "rows": rows,
        "legend": {symbol: list(color) for color, symbol in legend.items()},
        "truncated_colors": truncated,
    }


def audio_summary(raw, segment):
    samples = [s[0] for s in struct.iter_unpack("<h", raw)] if raw else []
    peak = max((abs(s) for s in samples), default=0)
    rms = math.sqrt(sum(s * s for s in samples) / len(samples)) if samples else 0.0
    return {"peak": peak, "rms": round(rms, 3), "silent": peak == 0, "samples": segment["samples"]}
