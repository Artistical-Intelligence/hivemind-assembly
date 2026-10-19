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
