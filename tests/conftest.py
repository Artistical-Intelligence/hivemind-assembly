import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "_app"))
import pytest
from workbench.store import Store
from workbench.controller import Controller


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "state")
    yield s
    s.close()


@pytest.fixture
def ready(store):
    c = Controller(store)
    t = store.create_project("Fixture", "Verify a bounded region")
    epoch = c.acquire(t["id"], "worker.opus")
    c.brief(
        t["id"],
        {"revision": 0},
        {"procedure": "run fixtures", "acceptance": "known result"},
        {"critical_gaps": []},
        [],
    )
    return c, t, epoch


# Emulation- and compiler-heavy modules (each over ~8 s on a 2-core host).
# `pytest -m "not slow"` is the quick development tier; CI runs everything.
SLOW_MODULES = {
    "test_windows_memory",
    "test_windows_files",
    "test_project_reconstruction",
    "test_windows_program",
    "test_program_libc",
    "test_windows_process",
    "test_arm64_dependencies",
    "test_program_captures",
    "test_hybrid_recovery",
    "test_unicorn_diagnostics",
    "test_workflow_learning",
    "test_semantics",
    "test_windows_diagnostics",
    "test_call_images",
    "test_call_memory",
    "test_platform_runtime",
    "test_tool_testing",
    "test_linux_dependencies",
    "test_game_testing",
    "test_game_play",
}


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: emulation/compiler-heavy test module")


def pytest_collection_modifyitems(config, items):
    for item in items:
        if item.module.__name__.rsplit(".", 1)[-1] in SLOW_MODULES:
            item.add_marker(pytest.mark.slow)
