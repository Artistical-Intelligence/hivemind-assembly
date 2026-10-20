import os
import shutil
import pytest
from hivemind_assembly.application.runtime_verification import verify_runtime_lanes

CLANG = os.environ.get("HA_TEST_CLANG") or shutil.which("clang")


@pytest.mark.skipif(not CLANG, reason="Clang required; set HA_TEST_CLANG")
def test_actual_installation_runtime_probes(tmp_path):
    checks = verify_runtime_lanes(tmp_path, {"c_compiler": CLANG})
    assert checks["qiling_runtime"]["passed"], checks
    assert checks["linked_functions"]["passed"], checks
    assert checks["linked_functions"]["abis"] == [
        "sysv",
        "win64",
        "aapcs64",
        "winarm64",
    ]
    assert checks["linked_functions"]["native_oracle"]["passed"]


def test_probe_failures_are_reported_independently(tmp_path):
    checks = verify_runtime_lanes(
        tmp_path, {"c_compiler": "missing-compiler-fixture-xyz"}
    )
    assert set(checks) == {"qiling_runtime", "linked_functions"}
    assert all(not v["passed"] and v["reason"] for v in checks.values())


@pytest.mark.skipif(not CLANG, reason="Clang required; set HA_TEST_CLANG")
@pytest.mark.parametrize(
    "host,abi,format", [("nt", "win64", "PE"), ("posix", "sysv", "ELF")]
)
def test_foundation_fixture_matches_admitted_native_format(tmp_path, host, abi, format):
    from hivemind_assembly.application.verification import build_analysis_fixture
    from hivemind_assembly.core.jobs import Jobs
    from hivemind_assembly.domains.reverse_engineering.call_images import load

    path, evidence = build_analysis_fixture(
        tmp_path, {"c_compiler": CLANG}, Jobs(), host
    )
    assert evidence["passed"] and evidence["analysis_format"] == format
    assert load(path.read_bytes(), symbol="transform")["abi"] == abi
