"""HumanEval-Decompile import and re-executability scoring (native execution)."""

import os
import shutil

import pytest

from hivemind_assembly.core.common import Blocked
from hivemind_assembly.core.jobs import Jobs
from hivemind_assembly.domains.reverse_engineering import external_benchmarks as bench

ROW = {
    "index": "0",
    "language": "c",
    "opt": "O2",
    "func_dep": "#include <stdio.h>\n#include <stdlib.h>\n#include <math.h>\n",
    "func": "int func0(float numbers[], int size, float threshold) {\n    for (int i = 0; i < size; i++)\n        for (int j = i + 1; j < size; j++)\n            if (fabs(numbers[i] - numbers[j]) < threshold) return 1;\n    return 0;\n}\n",
    "test": "#include <assert.h>\nint main(){\n    float a[] = {1.0, 2.0, 3.9, 4.0, 5.0, 2.2};\n    assert(func0(a, 6, 0.3) == 1);\n    assert(func0(a, 6, 0.05) == 0);\n    return 0;\n}\n",
}


def compiler():
    found = shutil.which("gcc") or shutil.which("clang")
    if not found or os.name == "nt":
        pytest.skip("A native POSIX C toolchain is required")
    return found


def test_reexecutability_scoring_requires_permission_and_rejects_wrong_code():
    compiler()
    jobs = Jobs()
    expected = {"kind": bench.KIND, "func_dep": ROW["func_dep"], "test": ROW["test"]}
    assert bench.compile_object(ROW, jobs)[:4] == b"\x7fELF"
    with pytest.raises(Blocked, match="owner permission"):
        bench.evaluate({"source": ROW["func"]}, expected, jobs)
    assert bench.evaluate({"source": ROW["func"]}, expected, jobs, allow_native=True)
    wrong = ROW["func"].replace("< threshold", "<= threshold * 0")
    assert not bench.evaluate({"source": wrong}, expected, jobs, allow_native=True)
    assert not bench.evaluate({"source": ROW["func"] + "int main(void){return 0;}"}, expected, jobs, allow_native=True)
    assert not bench.evaluate({"code": ROW["func"]}, expected, jobs, allow_native=True)


@pytest.mark.skipif(not os.environ.get("HA_BENCHMARK_FETCH"), reason="Set HA_BENCHMARK_FETCH=1 to fetch the pinned public benchmark")
def test_pinned_benchmark_import_has_disjoint_holdouts(tmp_path):
    compiler()
    jobs = Jobs()
    path = bench.fetch(tmp_path, jobs)
    rows = bench.load(path)
    assert len(rows) == 656
    cases = bench.cases(path, jobs, limit=8)
    holdout = {c["family"] for c in cases if c["split"] == "holdout"}
    regression = {c["family"] for c in cases if c["split"] == "regression"}
    assert holdout and regression and not holdout & regression
    # Every optimization level of a problem stays in one split.
    for family in holdout | regression:
        assert len({c["split"] for c in cases if c["family"] == family}) == 1
        assert len([c for c in cases if c["family"] == family]) == 2
    assert not {c["project"] for c in cases if c["split"] == "holdout"} & {
        c["project"] for c in cases if c["split"] == "regression"
    }
    assert all("test" not in c["inputs"] and "func_dep" not in c["inputs"] for c in cases)
    first = next(r for r in rows if r["opt"] == "O0")
    expected = next(c for c in cases if c["id"] == "humaneval-0-O0")["expected"]
    assert bench.evaluate({"source": first["func"]}, expected, jobs, allow_native=True)
