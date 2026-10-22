"""Game play-testing contracts: validation, decoding, rules, cells, tokens and views."""

import copy
import struct
import zlib

import pytest

from hivemind_assembly.application import game_example
from hivemind_assembly.core import game_spec as gs
from hivemind_assembly.core.common import ContractError

MINIMAL = {
    "version": 1,
    "input": {"record_bytes": 1, "controls": {"none": "00", "left": "01"}},
    "output": {
        "stdout": [
            {"name": "state", "bytes": 4},
            {"name": "frame", "format": "rgba8", "width": 2, "height": 2},
        ],
        "stderr": [{"name": "audio", "format": "pcm_s16le", "channels": 1, "samples": 2, "sample_rate": 60}],
    },
    "state": {
        "segment": "state",
        "fields": [
            {"name": "x", "offset": 0, "type": "i16"},
            {"name": "hp", "offset": 2, "type": "u8"},
            {"name": "max_hp", "offset": 3, "type": "u8"},
        ],
    },
}


def spec(**changes):
    value = copy.deepcopy(MINIMAL)
    value.update(changes)
    return gs.validate(value)


def test_defaults_are_explicit_and_validation_is_idempotent():
    value = spec()
    assert value["name"] == "Game" and value["platform"] == "linux"
    assert value["input"]["neutral"] == "00"
    assert value["actions"] == {"none": [["none", 1]], "left": [["left", 1]]}
    assert value["limits"] == {
        "max_ticks": 1000,
        "max_instructions": 10_000_000,
        "freeze_tick_instructions": 2_000_000,
    }
    assert value["regressions_path"] == "game-regressions.json"
    assert gs.validate(value) == value
    example = gs.validate(game_example.SPEC)
    assert gs.validate(example) == example
    assert gs.record_sizes(example) == {"stdout": 16 + 16 * 12 * 4, "stderr": 16}


@pytest.mark.parametrize(
    "change, message",
    [
        ({"version": 2}, "version 1"),
        ({"script": "print(1)"}, "Unknown game spec fields"),
        ({"input": {"record_bytes": 1, "controls": {"Left": "01"}}}, "lowercase"),
        ({"input": {"record_bytes": 2, "controls": {"none": "00"}}}, "exactly 2 bytes"),
        ({"input": {"record_bytes": 1, "controls": {}}}, "1–64 named controls"),
        ({"actions": {"go": [["jump", 1]]}}, "declared control"),
        ({"actions": {"go": [["none", 241]]}}, "Action ticks"),
        ({"output": {"stdout": []}}, "at least one"),
        ({"output": {"stdout": [{"name": "frame", "format": "rgba8", "width": 0, "height": 1}]}}, "Frame width"),
        ({"output": {"stdout": [{"name": "a", "bytes": 1}, {"name": "a", "bytes": 1}]}}, "unique"),
        ({"output": {"stdout": [{"name": "a", "format": "jpeg"}]}}, "raw, rgba8 or pcm_s16le"),
        ({"state": {"segment": "frame", "fields": []}}, "raw output segment"),
        ({"state": {"segment": "state", "fields": [{"name": "x", "offset": 3, "type": "u16"}]}}, "offset"),
        ({"rules": [{"id": "r", "field": "missing", "min": 0}]}, "unknown field"),
        ({"rules": [{"id": "r", "field": "x"}]}, "declares no check"),
        ({"rules": [{"id": "r", "field": "x", "monotonic": "up"}]}, "nondecreasing"),
        ({"cells": {"fields": ["x", "x"]}}, "distinct"),
        ({"limits": {"freeze_tick_instructions": 20_000_000}}, "freeze_tick_instructions"),
        ({"compare": {"segments": {"state": {"max_channel_error": 1}}}}, "raw bytes stay exact"),
        ({"original_path": "../original.elf"}, "inside the project"),
        ({"candidate_manifest": "a.json", "candidate_path": "b.elf"}, "not both"),
        ({"starts": {"s": {"inputs_hex": "0000", "expect": [{"field": "x", "op": "~", "value": 1}]}}}, "operator"),
    ],
)
def test_invalid_contracts_are_rejected(change, message):
    value = copy.deepcopy(MINIMAL)
    value.update(change)
    with pytest.raises(ContractError, match=message):
        gs.validate(value)


def test_decoding_rules_and_cells():
    value = spec(
        rules=[
            {"id": "bounds", "field": "x", "min": 0, "max": 10},
            {"id": "hp_cap", "field": "hp", "max_field": "max_hp"},
            {"id": "teleport", "field": "x", "max_step": 2},
            {"id": "healing_only_when_alive", "field": "hp", "monotonic": "nonincreasing", "when": [{"field": "hp", "op": ">", "value": 0}]},
        ],
        cells={"fields": ["x"], "quantize": {"x": 4}},
    )
    stdout = struct.pack("<hBB", 12, 5, 4) + bytes(range(16))
    stderr = struct.pack("<hh", 1000, -1000)
    assert gs.complete_ticks(value, len(stdout), len(stderr)) == 1
    assert gs.complete_ticks(value, len(stdout) * 2, len(stderr)) == 1
    parts = gs.tick_segments(value, stdout, stderr, 0)
    assert parts["frame"] == bytes(range(16)) and parts["audio"] == stderr
    state = gs.decode_state(value, parts)
    assert state == {"x": 12, "hp": 5, "max_hp": 4}
    violations = {v["rule"]: v for v in gs.check_rules(value, state, {"x": 5, "hp": 3})}
    assert violations["bounds"]["failed"] == ["max"]
    assert violations["hp_cap"]["failed"] == ["max_field"]
    assert violations["teleport"]["failed"] == ["max_step"]
    assert violations["healing_only_when_alive"]["failed"] == ["monotonic"]
    assert gs.check_rules(value, {"x": 5, "hp": 0, "max_hp": 4}, {"x": 5, "hp": 3}) == []
    assert gs.cell(value, state, parts) == "x=3"
    framed = spec()
    assert gs.cell(framed, state, parts).startswith("frame:")


def test_trajectory_tokens_and_action_expansion():
    value = gs.validate(game_example.SPEC)
    records = gs.expand(value, ["jump", {"control": "right", "ticks": 2}, {"record": "05", "ticks": 1}])
    assert records == bytes.fromhex("04000000" + "0202" + "05")
    token = gs.encode_token(records)
    assert gs.decode_token(token, value) == records
    assert gs.decode_token("", value) == b""
    assert gs.control_names(value, records)[:2] == ["jump", "none"]
    assert gs.control_names(value, b"\x07") == ["07"]
    tampered = token[:-1] + ("0" if token[-1] != "0" else "1")
    for bad in (tampered, "g2." + token[3:], "g1.!!!.0", 7):
        with pytest.raises(ContractError):
            gs.decode_token(bad, value)
    too_long = gs.encode_token(bytes(value["limits"]["max_ticks"] + 1))
    with pytest.raises(ContractError, match="max_ticks"):
        gs.decode_token(too_long, value)
    with pytest.raises(ContractError, match="Unknown action"):
        gs.expand(value, ["teleport"])
    with pytest.raises(ContractError, match="2000 ticks"):
        gs.expand(value, [{"control": "none", "ticks": 600}] * 4)


def test_png_and_character_views_are_exact():
    pixels = bytes([255, 0, 0, 255, 0, 255, 0, 255, 0, 0, 255, 255, 255, 255, 255, 255])
    data = gs.png(pixels, 2, 2, 3)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", data[16:24])
    assert (width, height) == (6, 6)
    start = data.index(b"IDAT") + 4
    length = struct.unpack(">I", data[start - 8 : start - 4])[0]
    raw = zlib.decompress(data[start : start + length])
    rows = [raw[i * 25 : (i + 1) * 25] for i in range(6)]
    assert all(row[0] == 0 for row in rows)
    assert rows[0][1:5] == bytes([255, 0, 0, 255]) and rows[0][13:17] == bytes([0, 255, 0, 255])
    assert rows[5][1:5] == bytes([0, 0, 255, 255])
    view = gs.ascii_view(pixels, 2, 2)
    assert view["rows"] == [".#", "@o"]
    assert view["legend"]["."] == [255, 0, 0, 255]
    assert gs.ascii_view(bytes(65 * 4), 65, 1) is None
    with pytest.raises(ContractError):
        gs.png(pixels[:-1], 2, 2)
    assert gs.audio_summary(struct.pack("<hh", 3, -4), {"samples": 2})["peak"] == 4
