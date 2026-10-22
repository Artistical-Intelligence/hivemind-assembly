"""Status claims in README/ROADMAP come from release_status.json, not hand edits."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location("status_docs", ROOT / "dev" / "status_docs.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_documents_match_release_status():
    assert _module().check(write=False) == []


def test_version_is_consistent():
    import hivemind_assembly

    status = json.loads((ROOT / "_app" / "release_status.json").read_text())
    assert hivemind_assembly.__version__ == status["version"]
    assert f"Current version: {status['version']}." in (ROOT / "README.md").read_text()


def test_evidence_requires_exact_commits_and_inference_flag():
    docs = _module()
    status = json.loads((ROOT / "_app" / "release_status.json").read_text())
    broken = json.loads(json.dumps(status))
    broken["evidence"][0]["commit"] = "4f057ab"
    with pytest.raises(ValueError, match="full commit"):
        docs.render(broken)
    broken = json.loads(json.dumps(status))
    del broken["evidence"][0]["live_model_inference"]
    with pytest.raises(ValueError, match="exactly"):
        docs.render(broken)
    broken = json.loads(json.dumps(status))
    broken["native_live_acceptance"]["validated_routes"] = 6
    with pytest.raises(ValueError, match="routes"):
        docs.render(broken)


def test_runs_from_before_the_recreated_repository_are_not_linked():
    docs = _module()
    status = json.loads((ROOT / "_app" / "release_status.json").read_text())
    status["evidence"][0]["runs"] = [100, 300]
    status["run_logs_removed_before"] = {"run": 200, "date": "2026-10-22", "reason": "Logs are gone."}
    block = docs.render(status)
    assert "100 (log removed)" in block and docs.RUN + "100" not in block
    assert f"[300]({docs.RUN}300)" in block
    assert "Runs marked “log removed” ran before 2026-10-22. Logs are gone." in block
    status["run_logs_removed_before"] = {"run": 200, "date": "22 Oct"}
    with pytest.raises(ValueError, match="run_logs_removed_before"):
        docs.render(status)
