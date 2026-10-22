"""Owner-declared game test contracts: tick inputs, observations, rules and cells.

A game spec tells HA how to drive and observe a deterministic program one tick at a
time. Inputs are fixed-size records fed through the program's own input stream, so
a play session is reproduced exactly by its input log (its trajectory). Each tick's
outputs are fixed-size records on standard output/error, decoded into named state
fields, raw RGBA frames and signed 16-bit PCM audio. Rules are declarative checks on
decoded state; nothing in a spec is evaluated as code. Cells group similar
situations for exploration. Everything is bounded and invalid contracts are rejected
rather than guessed.

A `native` section describes a real game run natively through an adapter (a Godot
project or an SDL2 program): which keys or input actions the input bits press,
which state values the adapter reports (Godot node properties, or memory by symbol
and pointer path), the frame size and the frame rate. Its input records, output
layout and state fields are derived from it, so the rest of the harness is unchanged.
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
    "f32": ("f", 4),
    "f64": ("d", 8),
}
OPERATORS = ("==", "!=", "<", "<=", ">", ">=")
MAX_TICKS = 4096
MAX_RECORD = 64
MAX_TICK_OUTPUT = 262144
# A whole session's declared output, so engines can hold and bound it.
MAX_SESSION_OUTPUT = 64 * 2**20
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
    "native",
}
NATIVE_ADAPTERS = ("godot", "sdl2")
ENV_NAME = re.compile(r"[A-Z_][A-Z0-9_]{0,63}")


def _integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ContractError(f"{name} must be an integer from {low} to {high}")
    return value


def _number(value, name):
    """Rule and condition constants: integers, or finite numbers for float fields."""
    if type(value) is float:
        if not math.isfinite(value):
            raise ContractError(f"{name} must be finite")
        return value
    return _integer(value, name, -(2**63), 2**64 - 1)


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
        _number(item["value"], what + " value")
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


def _arguments(value, what):
    if not isinstance(value, list) or len(value) > 32 or any(
        not isinstance(item, str) or len(item) > 512 or "\0" in item for item in value
    ):
        raise ContractError(what + " are at most 32 strings")
    return value


def _launch(adapter, item, side):
    """One side's native launch: a Godot project folder or an SDL2 executable."""
    if not isinstance(item, dict):
        raise ContractError(f"native.{side} must be an object")
    if adapter == "godot":
        if set(item) - {"project", "engine", "args"}:
            raise ContractError(f"native.{side} takes project, engine and args")
        relative(item.get("project"), f"native.{side}.project")
        engine = item.setdefault("engine", "godot")
        if engine != "godot":
            relative(engine, f"native.{side}.engine")
    else:
        if set(item) - {"executable", "folder", "args", "env"}:
            raise ContractError(f"native.{side} takes executable, folder, args and env")
        relative(item.get("executable"), f"native.{side}.executable")
        if "folder" in item:
            relative(item["folder"], f"native.{side}.folder")
            if not (item["executable"] + "/").startswith(item["folder"].rstrip("/") + "/"):
                raise ContractError(f"native.{side}.executable must be inside its folder")
        env = item.setdefault("env", {})
        if not isinstance(env, dict) or len(env) > 16:
            raise ContractError(f"native.{side}.env maps at most 16 names")
        for name, text in env.items():
            if (
                not isinstance(name, str)
                or not ENV_NAME.fullmatch(name)
                or name.startswith(("LD_", "HA_TICK_"))
                or not isinstance(text, str)
                or len(text) > 512
                or "\0" in text
            ):
                raise ContractError("Native environment entries need plain names and values (no LD_ or HA_TICK_)")
    _arguments(item.setdefault("args", []), f"native.{side}.args")
    return item


def _control_name(text, taken):
    name = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:28] or "input"
    if not name[0].isalpha():
        name = "k_" + name
    base, index = name[:28], 2
    while name in taken:
        name = f"{base}_{index}"
        index += 1
    taken.add(name)
    return name


def _native(value):
    """Validate a native section and derive input, actions, output and state."""
    native = value["native"]
    if not isinstance(native, dict) or set(native) - {
        "adapter",
        "original",
        "candidate",
        "inputs",
        "state",
        "frame",
        "fps",
        "seed",
        "display",
        "tick_seconds",
        "startup_seconds",
        "action_ticks",
        "frame_ns",
    }:
        raise ContractError("Unknown native game fields")
    for key in ("original_path", "candidate_manifest", "candidate_path", "process", "functions"):
        if key in value and value[key]:
            raise ContractError(f"Native games name their launch in native; remove {key}")
    # Output and state are derived; a normalized spec may carry them unchanged.
    declared = {key: value.pop(key) for key in ("output", "state") if key in value}
    adapter = native.get("adapter")
    if adapter not in NATIVE_ADAPTERS:
        raise ContractError("native.adapter is godot or sdl2")
    if adapter == "sdl2" and value["platform"] != "linux":
        raise ContractError("The SDL2 adapter runs on Linux")
    sides = [side for side in ("original", "candidate") if side in native]
    if not sides:
        raise ContractError("Name a native original and/or candidate")
    for side in sides:
        _launch(adapter, native[side], side)
    inputs = native.get("inputs")
    if not isinstance(inputs, list) or not 1 <= len(inputs) <= 64:
        raise ContractError("native.inputs lists 1–64 keys or actions")
    for item in inputs:
        if not isinstance(item, dict) or len(item) != 1 or not set(item) <= {"key", "action"}:
            raise ContractError("Each native input is {key: name} or {action: name}")
        text = next(iter(item.values()))
        if not isinstance(text, str) or not 1 <= len(text) <= 64:
            raise ContractError("Native key and action names have 1–64 characters")
        if "action" in item and adapter != "godot":
            raise ContractError("Input actions need the Godot adapter; SDL2 games press keys")
    fps = _integer(native.setdefault("fps", 60), "native.fps", 1, 240)
    _integer(native.setdefault("seed", 0), "native.seed", 0, 2**31 - 1)
    _integer(native.setdefault("tick_seconds", 10), "native.tick_seconds", 1, 120)
    _integer(native.setdefault("startup_seconds", 60), "native.startup_seconds", 1, 600)
    hold = _integer(native.setdefault("action_ticks", 6), "native.action_ticks", 1, 120)
    display = native.setdefault("display", "virtual")
    if display not in ("virtual", "headless") or (display == "headless" and adapter != "godot"):
        raise ContractError("native.display is virtual, or headless for Godot state-only play")
    frame = native.get("frame")
    if frame is not None:
        if not isinstance(frame, dict) or set(frame) != {"width", "height"}:
            raise ContractError("native.frame takes width and height")
        _integer(frame["width"], "Frame width", 1, 512)
        _integer(frame["height"], "Frame height", 1, 512)
        if display == "headless":
            raise ContractError("Headless Godot play renders no frames; remove native.frame or use virtual")
    fields, offset = [], 0
    names = set()
    state = native.setdefault("state", [])
    if not isinstance(state, list) or len(state) > 64:
        raise ContractError("native.state lists at most 64 values")
    for item in state:
        if not isinstance(item, dict):
            raise ContractError("native.state entries are objects")
        name = _name(item.get("name"), "Native state")
        if name in names:
            raise ContractError("Native state names must be unique")
        names.add(name)
        if item.get("type") not in FIELD_TYPES:
            raise ContractError("Native state type must be one of " + ", ".join(FIELD_TYPES))
        if adapter == "godot":
            if set(item) - {"name", "type", "node", "property", "group", "missing"} or ("node" in item) == ("group" in item):
                raise ContractError("Godot state reads a node (optionally a property) or counts a group")
            for key in ("node", "property", "group"):
                if key in item and (not isinstance(item[key], str) or not 1 <= len(item[key]) <= 200):
                    raise ContractError("Godot node paths, properties and groups have 1–200 characters")
            if "property" in item and "node" not in item:
                raise ContractError("A Godot property needs its node")
            if "missing" in item and (type(item["missing"]) not in (int, float) or not math.isfinite(item["missing"])):
                raise ContractError("missing is a number")
        else:
            if set(item) - {"name", "type", "symbol", "address", "offset", "pointers"} or ("symbol" in item) == ("address" in item):
                raise ContractError("SDL2 state reads memory by symbol or address, with optional offset and pointers")
            _memory_location(item)
        fields.append({"name": name, "offset": offset, "type": item["type"], "endian": "little"})
        offset += FIELD_TYPES[item["type"]][1]
    output = []
    if fields:
        output.append({"name": "state", "bytes": offset})
    if frame is not None:
        output.append({"name": "frame", "format": "rgba8", "width": frame["width"], "height": frame["height"]})
    if not output:
        raise ContractError("A native game reports state values and/or a frame")
    value["output"] = {"stdout": output, "stderr": []}
    if fields:
        value["state"] = {"segment": "state", "fields": fields}
    if "output" in declared:
        names = set()
        derived = [_segment(dict(item), names) for item in output]
        if declared["output"] != {"stdout": derived, "stderr": []}:
            raise ContractError("Native games derive their output layout; remove output")
    if "state" in declared and declared["state"] != value.get("state"):
        raise ContractError("Native games derive their state fields; remove state")
    record = (len(inputs) + 7) // 8
    taken = {"none", "wait"}
    controls = {"none": "00" * record}
    for index, item in enumerate(inputs):
        bits = bytearray(record)
        bits[index >> 3] |= 1 << (index & 7)
        controls[_control_name(next(iter(item.values())), taken)] = bits.hex()
    if "input" not in value:
        value["input"] = {"record_bytes": record, "neutral": "00" * record, "controls": controls}
        value.setdefault(
            "actions",
            {name: [[name, hold]] for name in controls if name != "none"} | {"wait": [["none", hold]]},
        )
    elif not isinstance(value["input"], dict) or value["input"].get("record_bytes") != record:
        raise ContractError(f"Native input records have {record} byte(s): one bit per native input")
    native["frame_ns"] = 1_000_000_000 // fps


def _memory_location(item):
    if "symbol" in item and (
        not isinstance(item["symbol"], str)
        or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.$]{0,127}", item["symbol"])
    ):
        raise ContractError("Invalid memory symbol name")
    if "address" in item:
        _integer(item["address"], "Memory address", 0, 2**64 - 1)
    _integer(item.setdefault("offset", 0), "Memory offset", 0, 1 << 20)
    pointers = item.setdefault("pointers", [])
    if not isinstance(pointers, list) or len(pointers) > 8:
        raise ContractError("A memory pointer path follows at most 8 pointers")
    for step in pointers:
        _integer(step, "Pointer offset", 0, 1 << 20)


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
    if "native" in value:
        value.pop("process")
        value.pop("functions", None)
        _native(value)
        value["process"] = {}

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
        if not isinstance(item, dict) or set(item) - {"name", "symbol", "address", "offset", "pointers", "type"}:
            raise ContractError("Memory fields take name, symbol or address, offset, pointers and type")
        field = _name(item.get("name"), "Memory field")
        if field in fields:
            raise ContractError("Memory field names must be unique and differ from state fields")
        if ("symbol" in item) == ("address" in item):
            raise ContractError("Memory fields need exactly one of symbol or address")
        _memory_location(item)
        if item.get("type") not in FIELD_TYPES:
            raise ContractError("Memory field type must be one of " + ", ".join(FIELD_TYPES))
        fields[field] = "memory"

    rules = value.setdefault("rules", [])
    if not isinstance(rules, list) or len(rules) > 64:
        raise ContractError("Declare at most 64 rules")
    ids = set()
    checks = {"min", "max", "min_field", "max_field", "equals", "not_equals", "monotonic", "max_step", "finite"}
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
                _number(rule[key], "Rule " + key)
        for key in ("min_field", "max_field"):
            if key in rule and rule[key] not in fields:
                raise ContractError("Rule " + rule_id + " compares with an unknown field")
        if rule.get("monotonic", "nondecreasing") not in ("nondecreasing", "nonincreasing"):
            raise ContractError("monotonic is nondecreasing or nonincreasing")
        if "max_step" in rule:
            _integer(rule["max_step"], "max_step", 0, 2**63 - 1)
        if "finite" in rule and rule["finite"] is not True:
            raise ContractError("finite is true when present")
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
    if sum(s["size"] for s in segments.values()) * limits["max_ticks"] > MAX_SESSION_OUTPUT:
        raise ContractError("max_ticks × per-tick output must stay within 64 MiB")

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


def output_bound(spec):
    """Bytes an engine may hold for one session: every declared tick plus slack."""
    return sum(record_sizes(spec).values()) * (spec["limits"]["max_ticks"] + 2) + 65536


def event_bound(spec):
    """Input/output calls an engine allows for one session."""
    return min(2_000_000, max(4096, (spec["limits"]["max_ticks"] + 2) * 256))


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
    """One field value; a non-finite float decodes as None (no value)."""
    code, width = FIELD_TYPES[kind]
    value = struct.unpack_from(("<" if endian == "little" else ">") + code, raw, offset)[0]
    if code in "fd" and not math.isfinite(value):
        return None
    return value


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
            # A declared field without a value decoded a NaN or an infinity.
            if rule.get("finite") and rule["field"] in values:
                violations.append(
                    {"rule": rule["id"], "field": rule["field"], "value": None, "previous": previous.get(rule["field"]), "failed": ["finite"]}
                )
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
        "native": spec.get("native")
        and {
            "adapter": spec["native"]["adapter"],
            "inputs": spec["native"]["inputs"],
            "fps": spec["native"]["fps"],
            "display": spec["native"]["display"],
            "sides": [s for s in ("original", "candidate") if s in spec["native"]],
        },
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
