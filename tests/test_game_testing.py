"""Play-testing harness on the source-known Coin cavern example.

The original and the planted-defect reconstruction are real compiled programs run in
the deterministic engines. Fixed seeds make exploration results reproducible here;
a passing exploration is sampled evidence, not proof that no defect remains.
"""

import json
import os
import shutil

import pytest

from hivemind_assembly.application import game_example as ge
from hivemind_assembly.core import game_spec as gs
from hivemind_assembly.core import game_testing as gt
from hivemind_assembly.core.common import ContractError
from hivemind_assembly.core.jobs import Jobs
from hivemind_assembly.domains.reverse_engineering import program
from hivemind_assembly.domains.reverse_engineering.game_machine import open_engine

SPEC = gs.validate(json.loads(ge.files()["game.json"]))


def _compiler():
    value = os.environ.get("HA_TEST_CLANG") or shutil.which("clang") or shutil.which("gcc")
    if not value:
        pytest.skip("A C compiler is required")
    return value


@pytest.fixture(scope="module")
def images(tmp_path_factory):
    compiler = _compiler()
    result = {"original": ge.build_original(Jobs(), compiler)}
    for name, fixed in (("buggy", ()), ("edge", ("edge",)), ("fixed", ("edge", "knockback"))):
        root = tmp_path_factory.mktemp(name)
        files = ge.files(fixed)
        for file, text in files.items():
            (root / file).write_text(text)
        built = program.build(root, json.loads(files["build.json"]), Jobs(), compiler)
        assert built["passed"], built
        result[name] = bytes.fromhex(built["elf_hex"])
    return result


def session(image, side="candidate", live=True):
    return gt.Session(SPEC, open_engine(image, SPEC, live=live), side)


def pair(images, candidate="buggy", live=True):
    return lambda: gt.Pair(
        SPEC,
        session(images["original"], "original", live),
        session(images[candidate], "candidate", live),
    )


def route(name):
    return ge.records(ge.ROUTES[name])


def test_session_decodes_ticks_and_replays_exactly(images):
    first = session(images["original"])
    assert first.status == "awaiting_input" and first.ticks == 0
    first.feed(route("coin_route"))
    state = first.latest["values"]
    assert (state["x"], state["y"], state["coins"], state["score"]) == (13, 10, 2, 20)
    assert first.ticks == len(route("coin_route")) and not first.problems
    observation = first.observation()
    assert observation["frame"]["view"]["rows"][10][13] != observation["frame"]["view"]["rows"][10][12]
    assert observation["audio"]["samples"] == 8
    assert set(observation["coverage"]) >= {"step", "render"}
    again = session(images["original"])
    for record in gs.decode_token(observation["trajectory"], SPEC):
        again.feed(bytes([record]))
    assert again.observation() == observation
    image = first.images(1)[0]
    assert image["data"][:8] == b"\x89PNG\r\n\x1a\n" and len(image["rgba"]) == 16 * 12 * 4
    with pytest.raises(ContractError, match="whole input records|max_ticks"):
        first.feed(bytes(SPEC["limits"]["max_ticks"]))


def test_regression_routes_classify_the_original_quirk(images):
    clean = pair(images)()
    clean.feed(route("coin_route"))
    clean.end()
    assert clean.report()["outcome"] == "pass"
    assert clean.original.engine.exit_code == clean.candidate.engine.exit_code == 2
    quirk = pair(images)()
    quirk.feed(route("hole_quirk"))
    report = quirk.report()
    assert report["passed"] and report["outcome"] == "pass"
    shared = {tuple(p["signature"]) for p in report["original_behavior"]}
    assert ("invariant", "inside_world_y") in shared
    lone = session(images["buggy"])
    lone.feed(route("hole_quirk"))
    assert ("invariant", "inside_world_y") in {tuple(p["signature"]) for p in gt.session_findings(lone)}


def test_planted_defects_diverge_and_freeze_on_their_routes(images):
    edge = pair(images)()
    edge.feed(route("platform_edge"))
    report = edge.report()
    assert report["outcome"] == "divergence"
    assert report["divergence"]["signature"] == ["divergence", "state:y"]
    assert "y" in report["divergence"]["detail"]["state_differences"]
    spikes = pair(images)()
    spikes.feed(route("spike_landing"))
    report = spikes.report()
    assert report["outcome"] == "freeze"
    assert [f["signature"] for f in report["findings"]][:2] == [["freeze"], ["divergence", "status"]]
    assert report["candidate"]["status"] == "freeze"
    assert report["findings"][0]["detail"]["function"] in ("hurt", "tile", "step")
    fixed = pair(images, "fixed")()
    fixed.feed(route("spike_landing") + route("platform_edge"))
    assert fixed.report()["passed"]


def test_exploration_shrinking_and_packages_drive_the_fix_loop(images):
    first = gt.explore(SPEC, pair(images), steps=150, seed=0)
    assert first["mode"] == "differential" and first["outcome"] == "divergence"
    finding = first["findings"][0]
    assert finding["signature"] == ["divergence", "state:y"]
    inputs = gs.decode_token(finding["trajectory"], SPEC)
    shrunk = gt.shrink(SPEC, pair(images), inputs, finding["signature"])
    assert shrunk["reproduced"] and shrunk["confirmed"]
    assert shrunk["minimized_ticks"] <= min(10, len(inputs))
    minimized = gs.decode_token(shrunk["trajectory"], SPEC)
    package = gt.package(SPEC, pair(images), minimized, finding["signature"])
    assert package["reproduced"] and package["outcome"] == "divergence"
    assert {i["side"] for i in package["_images"]} == {"original", "candidate"}
    windows = package["state_window"]
    assert windows["original"][-1]["state"]["y"] != windows["candidate"][-1]["state"]["y"]
    second = gt.explore(SPEC, pair(images, "edge"), steps=200, seed=0)
    assert [f["signature"] for f in second["findings"]] == [["freeze"]]
    freeze = second["findings"][0]
    shrunk = gt.shrink(SPEC, pair(images, "edge"), gs.decode_token(freeze["trajectory"], SPEC), ["freeze"])
    assert shrunk["confirmed"] and shrunk["minimized_ticks"] <= 20
    final = gt.explore(SPEC, pair(images, "fixed"), steps=200, seed=0)
    assert final["outcome"] == "pass" and not final["findings"]
    assert {tuple(q["signature"]) for q in final["original_behavior"]} <= {
        ("invariant", "inside_world_y"),
        ("invariant", "no_teleport_x"),
    }


def test_single_build_exploration_uses_the_original_as_reference(images):
    report = gt.explore(
        SPEC,
        lambda: session(images["edge"]),
        steps=300,
        seed=0,
        reference=lambda: session(images["original"], "original"),
    )
    assert report["mode"] == "single"
    assert ["freeze"] in [f["signature"] for f in report["findings"]]
    assert all(not f.get("original_behavior") for f in report["findings"])
    assert ("invariant", "inside_world_y") in {tuple(q["signature"]) for q in report["original_behavior"]}


def test_replay_engines_match_live_sessions(images):
    live = pair(images)()
    live.feed(route("platform_edge"))
    replayed = pair(images, live=False)()
    replayed.feed(route("platform_edge"))
    assert replayed.original.engine.capabilities["observations"] == "after_end_of_input"
    left, right = live.report(), replayed.report()
    assert left["divergence"]["tick"] == right["divergence"]["tick"]
    assert left["divergence"]["signature"] == right["divergence"]["signature"]
    for runner in (live, replayed):
        assert not runner.original.problems


def test_saved_regressions_and_start_preconditions(images):
    items = gt.validate_regressions(SPEC, json.loads(ge.files()["game-regressions.json"]))
    result = gt.run_regressions(SPEC, pair(images), lambda: session(images["buggy"]), items)
    assert result["passed"] and result["total"] == 2
    bad = items + [{"id": "edge", "inputs_hex": route("platform_edge").hex(), "expect": "match_original", "end": True}]
    result = gt.run_regressions(SPEC, pair(images), lambda: session(images["buggy"]), bad)
    assert result["failed"] == ["edge"]
    lone = [{"id": "spikes", "inputs_hex": route("spike_landing").hex(), "expect": "no_problems", "end": False}]
    result = gt.run_regressions(SPEC, pair(images), lambda: session(images["edge"]), lone)
    assert result["results"][0]["outcome"] == "freeze"
    inputs, expect = gt.start_inputs(SPEC, "upper_platform")
    start = session(images["original"])
    start.feed(inputs)
    assert all(item["met"] for item in gt.check_expectations(SPEC, start.latest["values"], expect))
    for value in ({"version": 2, "regressions": []}, {"version": 1, "regressions": [{"id": "a", "inputs_hex": "zz"}]}):
        with pytest.raises(ContractError):
            gt.validate_regressions(SPEC, value)


def test_windows_pe_game_uses_the_replay_engine(tmp_path):
    from hivemind_assembly.domains.reverse_engineering.windows_program import build

    clang = os.environ.get("HA_TEST_CLANG") or shutil.which("clang")
    if not clang or not shutil.which("lld-link"):
        pytest.skip("Clang and lld-link are required")
    source = """int ha_main(void) {
    unsigned char key; int x = 0;
    while (ha_read(&key, 1) == 1) {
        x += key == 'R' ? 1 : key == 'L' ? -1 : 0;
        unsigned char out[2] = {(unsigned char)x, key};
        ha_write(out, 2);
    }
    return x & 0x7f;
}
"""
    (tmp_path / "main.c").write_text(source)
    built = build(tmp_path, {"sources": ["main.c"], "optimization": "O2"}, Jobs(), clang)
    assert built["passed"], built
    image = bytes.fromhex(built["pe_hex"])
    spec = gs.validate(
        {
            "version": 1,
            "platform": "windows",
            "input": {"record_bytes": 1, "controls": {"left": "4c", "right": "52", "none": "2e"}},
            "output": {"stdout": [{"name": "state", "bytes": 2}]},
            "state": {"segment": "state", "fields": [{"name": "x", "offset": 0, "type": "i8"}]},
            "rules": [{"id": "x_small", "field": "x", "max": 2}],
        }
    )
    runner = gt.Session(spec, open_engine(image, spec), "candidate")
    assert runner.engine.capabilities["runtime"] == "speakeasy_windows"
    runner.feed(gs.expand(spec, ["right", "right", "right", "left"]))
    assert runner.latest["values"]["x"] == 2
    assert [p["signature"] for p in runner.problems] == [["invariant", "x_small"]]
    assert runner.engine.exit_code == 2
