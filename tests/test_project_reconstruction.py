"""Project-level reconstruction: composition, fallback, rollback and the Stop 3 suite.

Source-known synthetic targets with actual Clang/LLD builds and emulated replay.
These are not evidence that a model reconstructed anything.
"""

import os
import platform
import shutil
import subprocess

import pytest
import test_app

from hivemind_assembly.application import project_targets
from hivemind_assembly.application.project_checks import run_checks, starter
from hivemind_assembly.core.common import file_hash
from hivemind_assembly.core.jobs import Jobs
from hivemind_assembly.domains.reverse_engineering import (
    planning,
    program,
    project_hybrid,
    project_reconstruction,
)

app = test_app.app


def _toolchain():
    clang = os.environ.get("HA_TEST_CLANG") or shutil.which("clang")
    if not clang or not (shutil.which("ld.lld") or shutil.which("lld")):
        pytest.skip("Clang and LLD are required")
    return clang


@pytest.fixture(scope="module")
def jobs():
    return Jobs()


@pytest.fixture(scope="module")
def targets(jobs):
    clang = _toolchain()
    return {
        kind: project_targets.target(kind, jobs, clang)
        for kind in ("utility", "arm64_to_x64", "game")
    }


def _check(tmp_path, target, files=None, verified=None, plan=True, checks=None):
    for name, text in (files or target["files"]).items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    return project_reconstruction.check(
        tmp_path,
        target["manifest_path"],
        target["original"],
        target["function_checks"] if checks is None else checks,
        target["cases"],
        Jobs(),
        os.environ.get("HA_TEST_CLANG", ""),
        None,
        planning.plan(target["plan_pages"]) if plan else None,
        verified=verified,
    )


def _mutant(target, name):
    unit, before, after = target["mutants"][name]
    files = dict(target["files"])
    assert before in files[unit]
    files[unit] = files[unit].replace(before, after)
    return files


def test_utility_combines_recovered_and_fallback_regions(tmp_path, targets):
    target = targets["utility"]
    result = _check(tmp_path, target)
    composition = result["composition"]
    assert result["passed"] is True
    assert composition["applicable"] and composition["passed"]
    assert sorted(composition["recovered"]) == ["advance", "encode", "ha_main", "run_length"]
    # pack and the trusted runtime stay on original machine code.
    assert "pack" in composition["fallback"] and "ha_read" in composition["fallback"]
    assert composition["fallback_planned"] == ["pack"]
    assert not composition["unexercised"] and not composition["rejected"]
    assert all(composition["executions"][n] > 0 for n in composition["recovered"])
    # Dependency order from the callgraph plan: leaves before ha_main.
    order = [f["function"] for f in result["functions"]]
    assert order.index("run_length") < order.index("ha_main")
    assert result["verified_prefix"] == order
    assert result["image"] != target["original"]
    regions = {r["function"]: r for r in composition["regions"]}
    assert regions["advance"]["recovered_address"] > max(
        s["address"] + s["size"] for s in program.load_image(target["original"])[1]
    )


def test_utility_rejects_incorrect_alternatives(tmp_path, targets):
    target = targets["utility"]
    (tmp_path / "shift").mkdir()
    shifted = _check(tmp_path / "shift", target, _mutant(target, "encode_shift"))
    assert shifted["passed"] is False
    assert {f["function"]: f["passed"] for f in shifted["functions"]}["encode"] is False
    # The failing region is not composed; it keeps running the original code.
    assert "encode" not in shifted["composition"]["recovered"]
    assert "encode" in shifted["composition"]["fallback"]
    assert shifted["composition"]["passed"] is True

    for name, region in (
        ("advance_hidden", "advance"),
        ("run_large_chunks", "run_length"),
        ("footer_order", "ha_main"),
    ):
        folder = tmp_path / name
        folder.mkdir()
        result = _check(folder, target, _mutant(target, name))
        composition = result["composition"]
        assert result["passed"] is False, name
        # Function checks alone do not see these; whole-program composition does.
        assert all(f["passed"] is not False for f in result["functions"]), name
        assert [r["function"] for r in composition["rejected"]] == [region]
        assert composition["rejected"][0]["cases"], name
        assert composition["passed"] is True
        assert region in composition["fallback"]
        assert len(composition["recovered"]) == 3


def test_regressed_region_rolls_back_to_original_code(tmp_path, targets):
    target = targets["utility"]
    verified = {"recovered": ["advance", "encode", "ha_main", "run_length"]}
    result = _check(tmp_path, target, _mutant(target, "advance_hidden"), verified=verified)
    composition = result["composition"]
    assert composition["regressed"] == ["advance"]
    assert composition["rolled_back"] == ["advance"]
    assert composition["passed"] is True and "advance" in composition["fallback"]
    # Without history the same failure is a rejection, not a regression.
    plain = _check(tmp_path, target, _mutant(target, "advance_hidden"))
    assert plain["composition"]["regressed"] == []


def test_arm64_original_reconstructed_as_x64_program(tmp_path, targets):
    target = targets["arm64_to_x64"]
    assert program.image_machine(target["original"]) == 183
    result = _check(tmp_path, target)
    assert result["passed"] is True
    assert result["composition"]["applicable"] is False
    assert all(f["abi"] == "sysv" for f in result["functions"])
    assert {f["function"] for f in result["functions"] if f["passed"]} == {
        "advance",
        "encode",
        "run_length",
        "pack",
    }
    assert result["program"]["passed"] is True
    assert program.image_machine(result["image"]) == 62
    for name in target["mutants"]:
        folder = tmp_path / name
        folder.mkdir()
        assert _check(folder, target, _mutant(target, name))["passed"] is False, name


def test_game_target_frames_audio_and_fallback_rendering(tmp_path, targets):
    target = targets["game"]
    result = _check(tmp_path, target)
    composition = result["composition"]
    assert result["passed"] is True
    assert sorted(composition["recovered"]) == [
        "apply_input",
        "ha_main",
        "mix_audio",
        "step_physics",
    ]
    assert composition["fallback_planned"] == ["render_frame"]
    assert composition["executions"]["mix_audio"] == 5 * 12
    expected = {
        "double_jump": ("apply_input", "function"),
        "right_wall": ("step_physics", "program"),
        "audio_level": ("mix_audio", "function"),
        "audio_late": ("mix_audio", "function"),
    }
    for name, (region, layer) in expected.items():
        folder = tmp_path / name
        folder.mkdir()
        outcome = _check(folder, target, _mutant(target, name))
        assert outcome["passed"] is False, name
        assert region not in outcome["composition"]["recovered"], name
        assert region in outcome["composition"]["fallback"], name
        if layer == "program":
            rejected = outcome["composition"]["rejected"]
            assert [r["function"] for r in rejected] == [region]
            assert any(
                "captures" in c["differences"] or "exit_code" in c["differences"]
                for c in rejected[0]["cases"]
            )
        else:
            assert {f["function"]: f["passed"] for f in outcome["functions"]}[region] is False
    # Delayed audio is also visible to the whole-program audio comparator alone.
    folder = tmp_path / "audio-program-only"
    folder.mkdir()
    checks = {k: v for k, v in target["function_checks"].items() if k != "mix_audio"}
    late = _check(folder, target, _mutant(target, "audio_late"), checks=checks)
    assert [r["function"] for r in late["composition"]["rejected"]] == ["mix_audio"]
    case = late["composition"]["rejected"][0]["cases"][0]
    assert "captures" in case["differences"]


def test_inlined_region_is_reported_unexercised(tmp_path, jobs):
    from hivemind_assembly.application.reconstruction_trial import SOURCE

    _toolchain()
    (tmp_path / "o.c").write_text(SOURCE)
    built = program.build(tmp_path, {"sources": ["o.c"], "optimization": "O2"}, jobs)
    original = bytes.fromhex(built["elf_hex"])
    (tmp_path / "advance.c").write_text(
        "unsigned advance(unsigned s, unsigned char b) { return (s * 33u) ^ (b + 18u); }\n"
    )
    (tmp_path / "project.json").write_text(
        '{"sources": ["advance.c"], "functions": {"advance": {"sources": ["advance.c"]}}}'
    )
    result = project_reconstruction.check(
        tmp_path,
        "project.json",
        original,
        {},
        [{"id": "t", "input_hex": b"abc".hex(), "effect_policy": "observable"}],
        jobs,
    )
    composition = result["composition"]
    # ha_main inlined the original advance, so the incorrect region never runs.
    assert composition["passed"] is True
    assert composition["unexercised"] == ["advance"]
    assert composition["unvalidated"] == ["advance"]
    assert result["passed"] is False


@pytest.mark.skipif(
    platform.system() != "Linux" or platform.machine() not in ("x86_64", "AMD64"),
    reason="Native execution of the composed ELF needs an x86-64 Linux host",
)
def test_composed_image_runs_natively_like_the_original(tmp_path, targets, jobs):
    target = targets["utility"]
    units = {n: target["files"][n] for n in ("state.c", "runs.c", "main.c")}
    composed = project_hybrid.compose(
        tmp_path,
        units,
        project_targets.UTILITY_DECLARATIONS,
        "O2",
        target["original"],
        ["run_length", "ha_main"],
        jobs,
    )
    assert composed["passed"] and composed["recovered"] == ["run_length", "ha_main"]
    paths = []
    for name, data in (("original", target["original"]), ("composed", composed["image"])):
        path = tmp_path / name
        path.write_bytes(data)
        path.chmod(0o755)
        paths.append(path)
    for data in (b"", b"Hivemind\n" * 20, bytes(range(256)) * 3):
        runs = [subprocess.run([str(p)], input=data, capture_output=True, timeout=10) for p in paths]
        assert runs[0].returncode == runs[1].returncode == 0
        assert runs[0].stdout == runs[1].stdout


def test_composition_contract_failures_are_explicit(tmp_path, targets, jobs):
    target = targets["utility"]
    units = {"state.c": target["files"]["state.c"]}
    with pytest.raises(Exception, match="defined once"):
        project_hybrid.compose(
            tmp_path, units, "", "O2", target["original"], ["run_length"], jobs
        )
    with pytest.raises(Exception, match="No unique original function"):
        project_hybrid.compose(
            tmp_path, {"x.c": "int invented(void){return 1;}\n"}, "", "O2", target["original"], ["invented"], jobs
        )
    missing = project_hybrid.compose(
        tmp_path,
        {"x.c": "int helper_nowhere(int);\nunsigned advance(unsigned s, unsigned char b){return helper_nowhere(s)+b;}\n"},
        "",
        "O2",
        target["original"],
        ["advance"],
        jobs,
    )
    assert missing["passed"] is False and missing["stage"] == "link"
    assert "helper_nowhere" in str(missing["build"])


def test_game_starter_pins_project_acceptance_and_accepts_repair(app):
    clang = _toolchain()
    app.config["foundations"]["c_compiler"] = clang
    task = starter(app, "project_game", "project_game_starter_01")
    root = app.broker.workspace(task["id"])
    assert (root / "original.elf").exists() and not (root / "original.c").exists()
    first = run_checks(app, task["id"])["result"]
    assert first["passed"] is False
    assert [r["function"] for r in first["composition"]["rejected"]] == ["step_physics"]
    assert "cases" not in first["composition"]["rejected"][0]
    assert "render_frame" in first["composition"]["fallback"]
    logic = (root / "logic.c").read_text()
    app.workspace.write(
        task["id"],
        "logic.c",
        logic.replace("g->x < 0 ? 0 : 6", "g->x < 0 ? 0 : 7"),
        file_hash(root / "logic.c"),
    )
    second = run_checks(app, task["id"])["result"]
    assert second["passed"] is True
    assert second["accepted_regions"] == ["apply_input", "ha_main", "mix_audio", "step_physics"]
    assert "render_frame" in second["composition"]["fallback"]
    assert second["executable_artifact"]


def test_worker_project_check_retains_snapshot_and_rolls_back(store, targets):
    import json

    from hivemind_assembly.core.acceptance import Acceptance
    from hivemind_assembly.core.broker import Broker
    from hivemind_assembly.core.controller import Controller
    from hivemind_assembly.domains.reverse_engineering.domain import (
        ReverseEngineeringDomain,
    )

    clang = _toolchain()
    target = targets["utility"]
    task = store.create_project("utility project", "Recover the packer", paused=True)
    root = store.root / "projects" / task["project_id"] / "workspace"
    root.mkdir(parents=True, exist_ok=True)
    for name, text in target["files"].items():
        (root / name).write_text(text)
    (root / "original.elf").write_bytes(target["original"])
    (root / "plan.json").write_text(json.dumps(planning.plan(target["plan_pages"])))
    controller = Controller(store)
    broker = Broker(controller, {"foundations": {"c_compiler": clang}}, ReverseEngineeringDomain())
    service = Acceptance(controller, broker)
    contract = service.configure(
        task["id"],
        {
            "scope": "linux_project",
            "original_path": "original.elf",
            "manifest_path": "project.json",
            "cases": target["cases"],
            "function_checks": target["function_checks"],
            "required_functions": ["advance", "encode", "run_length"],
        },
    )
    assert contract["scope"] == "linux_project"
    assert store.get("acceptance_contract", task["id"])["minimum_recovered"] == 3
    store.state(task["id"], "queued")
    epoch = controller.acquire(task["id"], "worker.opus")
    controller.brief(
        task["id"],
        {"revision": 0},
        {"procedure": "compose regions", "acceptance": "protected corpus"},
        {"critical_gaps": []},
        [],
    )
    revision = [0]

    def call(op, tool, args):
        result = broker.execute(
            {
                "id": op,
                "task_id": task["id"],
                "owner": "worker.opus",
                "epoch": epoch,
                "revision": revision[0],
                "tool": tool,
                "args": args,
            }
        )
        if tool == "write_file":
            # A saved edit changes the revision; the adviser must brief again.
            revision[0] += 1
            controller.brief(
                task["id"],
                {"revision": revision[0]},
                {"procedure": "recheck after edit", "acceptance": "protected corpus"},
                {"critical_gaps": []},
                [],
            )
        return result

    check_args = {
        "original_path": "original.elf",
        "manifest_path": "project.json",
        "function_checks": target["function_checks"],
        "cases": target["cases"][:4],
        "plan_path": "plan.json",
    }
    good = call("project-check-1", "compare_project", check_args)
    assert good["passed"] and good["executable_artifact"]
    assert "pack" in good["composition"]["fallback"]
    listing = call("snapshots-1", "verified_sources", {"limit": 3})
    snapshot = listing["snapshots"][0]
    assert snapshot["current"] and sorted(snapshot["composition"]["recovered"]) == [
        "advance",
        "encode",
        "ha_main",
        "run_length",
    ]
    assert set(snapshot["files"]) == {"state.c", "runs.c", "main.c", "project.json"}
    # A later edit breaks advance on inputs only the program corpus reaches.
    unit, before, after = target["mutants"]["advance_hidden"]
    call(
        "edit-1",
        "write_file",
        {
            "path": unit,
            "text": target["files"][unit].replace(before, after),
            "expected_hash": file_hash(root / unit),
        },
    )
    regressed = call("project-check-2", "compare_project", dict(check_args, cases=target["cases"]))
    assert regressed["passed"] is False
    assert regressed["composition"]["regressed"] == ["advance"]
    assert regressed["composition"]["rolled_back"] == ["advance"]
    listing = call("snapshots-2", "verified_sources", {"limit": 3})
    assert len(listing["snapshots"]) == 1 and not listing["snapshots"][0]["current"]
    restore = listing["snapshots"][0]["files"][unit]
    call(
        "restore-1",
        "write_file",
        {"path": unit, "artifact": restore["artifact"], "expected_hash": restore["current_sha256"]},
    )
    assert (root / unit).read_text() == target["files"][unit]
    restored = call("project-check-3", "compare_project", dict(check_args, cases=target["cases"]))
    assert restored["passed"] and restored["composition"]["regressed"] == []
    accepted = service.evaluate(
        store.task(task["id"]),
        {"result_operations": ["project-check-3"], "summary": "Recovered regions"},
    )
    assert accepted["passed"]
