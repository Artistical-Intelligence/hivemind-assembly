import json
import os
import shutil
import sys

import pytest

from hivemind_assembly.core.jobs import Jobs


def test_windows_environment_names_and_no_model_credentials(tmp_path, monkeypatch):
    # Windows normalizes os.environ keys to uppercase. Child processes still
    # need these ordinary OS paths; filtering them by mixed case breaks Node.
    root = os.environ.get("SystemRoot", "/fixture/windows")
    monkeypatch.setenv("SYSTEMROOT", root)
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-never-forward")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-never-forward")
    monkeypatch.setenv("GITHUB_TOKEN", "fixture-never-forward")
    result = Jobs().run(
        "environment",
        [sys.executable, "-c", "import json,os; print(json.dumps(dict(os.environ)))"],
        tmp_path,
    )
    assert result["status"] == "completed" and result["exit_code"] == 0
    environment = {k.upper(): v for k, v in json.loads(result["output"]).items()}
    assert environment["SYSTEMROOT"] == root
    assert environment["APPDATA"] == str(tmp_path / "roaming")
    assert (
        not {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GITHUB_TOKEN"} & environment.keys()
    )


@pytest.mark.skipif(not shutil.which("node"), reason="Node required")
def test_real_node_crypto_starts_with_managed_environment(tmp_path):
    result = Jobs().run(
        "node-crypto",
        [
            shutil.which("node"),
            "-e",
            "console.log(require('node:crypto').randomBytes(32).length)",
        ],
        tmp_path,
    )
    assert result["status"] == "completed" and result["exit_code"] == 0, result
    assert result["output"].strip() == "32"
