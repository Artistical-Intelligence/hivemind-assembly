"""Stepping game engine parity with batch replay; snapshots, policy and limits.

Real Clang/LLD (or GCC for x86-64) builds run under Unicorn. A stepped session must
produce exactly the streams, exit status and input consumption of program.replay
for the same input log, however the input is split into feeds.
"""

import os
import shutil
import threading

import pytest

from hivemind_assembly.application import project_targets
from hivemind_assembly.core.jobs import Jobs
from hivemind_assembly.domains.reverse_engineering import program
from hivemind_assembly.domains.reverse_engineering.game_machine import (
    GameMachine,
    ReplayEngine,
    elf_symbols,
    game_functions,
)

TICK = """int counter;
int ha_main(void) {
    unsigned char key;
    for (;;) {
        if (ha_read(&key, 1) != 1) break;
        if (key == 9) for (;;) counter += 1;
        if (key == 7) *(volatile int *)16 = 1;
        if (key == 5) {
            long seconds = 0, nanoseconds = 0;
            ha_clock(0, &seconds, &nanoseconds);
            counter += (int)seconds;
        }
        counter += key;
        unsigned char out[2] = {(unsigned char)counter, (unsigned char)ha_argc()};
        if (ha_write(out, 2) != 2) return 3;
        ha_file_write(2, &key, 1);
    }
    return counter & 0x7f;
}
"""
RDTSC = """int ha_main(void) {
    unsigned char key;
    if (ha_read(&key, 1) != 1) return 1;
    if (key) return (int)(__builtin_ia32_rdtsc() & 1);
    return 0;
}
"""
CHATTY = """int ha_main(void) {
    unsigned char key = 1;
    for (int i = 0; i < 5000; ++i) ha_write(&key, 1);
    return 0;
}
"""


def compiler(architecture="x86_64"):
    clang = os.environ.get("HA_TEST_CLANG") or shutil.which("clang")
    if architecture == "aarch64" and (not clang or not shutil.which("ld.lld")):
        pytest.skip("AArch64 builds require Clang and LLD")
    if not clang and not shutil.which("gcc"):
        pytest.skip("A C compiler is required")
    return clang or ""


def build(tmp_path, source, architecture="x86_64"):
    root = tmp_path / ("build-" + architecture)
    root.mkdir(exist_ok=True)
    (root / "main.c").write_text(source)
    built = program.build(
        root,
        {"sources": ["main.c"], "optimization": "O2", "architecture": architecture},
        Jobs(),
        compiler(architecture),
    )
    assert built["passed"], built
    return bytes.fromhex(built["elf_hex"])


def stepped(image, inputs, chunk=1, **options):
    machine = GameMachine(image, **options)
    for offset in range(0, len(inputs), chunk):
        machine.feed(inputs[offset : offset + chunk])
    machine.end()
    return machine


def observed(machine):
    return (
        machine.status,
        machine.exit_code,
        machine.output_tail("stdout", 0).hex(),
        machine.output_tail("stderr", 0).hex(),
        machine.input_consumed,
    )


def batch(image, inputs, **options):
    result = program.replay(image, inputs, **options)
    return (
        result["status"],
        result["exit_code"],
        result["stdout_hex"],
        result["stderr_hex"],
        result["input_consumed"],
    ), result


@pytest.mark.parametrize("architecture", ["x86_64", "aarch64"])
@pytest.mark.parametrize("chunk", [1, 2, 64])
def test_stepped_play_matches_batch_replay(tmp_path, architecture, chunk):
    image = build(tmp_path, TICK, architecture)
    for inputs in (b"", b"\x01", b"\x01\x02\x03\x04\x05", bytes(range(10, 40))):
        expected, raw = batch(image, inputs, argv=["game", "x"], clock_ns=3_000_000_000)
        machine = stepped(image, inputs, chunk, argv=["game", "x"], clock_ns=3_000_000_000)
        assert observed(machine) == expected
        # Whole blocks are counted, so deterministic costs agree exactly.
        assert machine.instructions == raw["instructions"]


def test_existing_game_target_and_coverage_agree_with_batch_replay():
    image = project_targets.target("game", Jobs(), compiler())["original"]
    entries, _ = game_functions(elf_symbols(image))
    for inputs in (b"RJRRL.JLLRJ.", b"RRR", b""):
        expected, raw = batch(image, inputs, coverage=entries)
        machine = stepped(image, inputs)
        assert observed(machine) == expected
        assert machine.coverage() == raw["coverage"]
        # The game reads twelve keys at once, so it waits until twelve arrive.
        live = GameMachine(image)
        live.feed(inputs[:3])
        assert live.output_size("stdout") == 0 and live.status == "awaiting_input"


def test_pause_points_expose_memory_and_snapshots_restore_exactly(tmp_path):
    image = build(tmp_path, TICK)
    machine = GameMachine(image)
    assert machine.status == "awaiting_input" and machine.costs
    address = machine.symbol("counter")
    machine.feed(b"\x03")
    assert machine.read_memory(address, 4) == (3).to_bytes(4, "little")
    snapshot = machine.snapshot()
    machine.feed(b"\x04")
    first = machine.output_tail("stdout", 0)
    machine.restore(snapshot)
    machine.feed(b"\x0a")
    assert machine.output_tail("stdout", 0)[:2] == first[:2] != machine.output_tail("stdout", 0)[2:]
    assert machine.read_memory(address, 4) == (13).to_bytes(4, "little")
    machine.restore(snapshot)
    machine.feed(b"\x04")
    assert machine.output_tail("stdout", 0) == first
    with pytest.raises(Exception):
        machine.read_memory(0x10, 4)


def test_freeze_fault_and_policy_stops_match_batch_replay(tmp_path):
    image = build(tmp_path, TICK)
    frozen = stepped(image, b"\x01\x09", freeze_tick_instructions=50_000)
    assert frozen.status == "freeze"
    assert frozen.stop_context["stop_reason"] == "tick_instruction_limit"
    assert frozen.stop_context["function"] == "ha_main"
    expected, _ = batch(image, b"\x01\x09", max_instructions=50_000)
    assert expected[0] == "budget_exhausted"
    total = stepped(image, b"\x01\x09", max_instructions=60_000, freeze_tick_instructions=60_000)
    assert total.status == "instruction_limit"
    faulted = stepped(image, b"\x01\x07")
    expected, _ = batch(image, b"\x01\x07")
    assert faulted.status == expected[0] == "fault"
    assert faulted.stop_context["memory_access"]["access"] == "write"
    clocked = stepped(image, b"\x05", clock_ns=7_000_000_000)
    assert observed(clocked) == batch(image, b"\x05", clock_ns=7_000_000_000)[0]
    if "clang" in os.path.basename(compiler()).lower():
        rdtsc = build(tmp_path, RDTSC)
        assert stepped(rdtsc, b"\x00").status == "completed"
        assert stepped(rdtsc, b"\x01").status == batch(rdtsc, b"\x01")[0][0] == "unsupported_cpu_state"
    chatty = build(tmp_path, CHATTY)
    assert GameMachine(chatty).status == batch(chatty, b"")[0][0] == "event_limit"


def test_cancellation_and_ended_input(tmp_path):
    image = build(tmp_path, TICK)
    cancel = threading.Event()
    machine = GameMachine(image, cancel=cancel)
    cancel.set()
    machine.feed(b"\x01")
    assert machine.status == "cancelled"
    finished = stepped(image, b"\x02")
    assert finished.status == "completed" and finished.exit_code == 2
    with pytest.raises(Exception, match="already ended"):
        finished.feed(b"\x01")


def test_replay_engine_reports_end_of_input_observations(tmp_path):
    image = build(tmp_path, TICK)
    engine = ReplayEngine(image, program.replay, "unicorn_linux", {"max_instructions": 1_000_000})
    assert engine.capabilities["stepping"] == "replay" and engine.status == "completed"
    engine.feed(b"\x01\x02")
    expected, _ = batch(image, b"\x01\x02", max_instructions=1_000_000)
    assert (engine.status, engine.exit_code, engine.output_tail("stdout", 0).hex()) == expected[:3]
    snapshot = engine.snapshot()
    engine.feed(b"\x03")
    engine.restore(snapshot)
    assert engine.output_tail("stdout", 0).hex() == expected[2]
    with pytest.raises(Exception, match="live memory"):
        engine.read_memory(0, 1)


def test_snapshots_restore_in_any_order(tmp_path):
    image = build(tmp_path, TICK)
    machine = GameMachine(image)
    machine.feed(b"\x01")
    early = machine.snapshot()
    machine.feed(b"\x02\x03")
    late = machine.snapshot()
    expected = (list(machine.costs), machine.output_tail("stdout", 0), machine.instructions)
    machine.restore(early)
    machine.feed(b"\x04")
    machine.restore(late)
    assert (list(machine.costs), machine.output_tail("stdout", 0), machine.instructions) == expected
    machine.feed(b"\x05")
    reference = stepped(image, b"\x01\x02\x03\x05")
    assert machine.costs == reference.costs[: len(machine.costs)]
