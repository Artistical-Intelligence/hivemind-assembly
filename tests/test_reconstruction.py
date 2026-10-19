import shutil
import pytest
from hivemind_assembly.core.acceptance import Acceptance
from hivemind_assembly.core.broker import Broker
from hivemind_assembly.core.controller import Controller
from hivemind_assembly.core.common import Blocked, ContractError
from hivemind_assembly.core.jobs import Jobs
from hivemind_assembly.domains.reverse_engineering.domain import (
    ReverseEngineeringDomain,
)
from hivemind_assembly.domains.reverse_engineering.reconstruction import (
    compile_function,
    extract_function,
    compare_functions,
    vectors,
)

pytestmark = pytest.mark.skipif(
    not (shutil.which("clang") or shutil.which("gcc")), reason="C compiler unavailable"
)


@pytest.mark.parametrize(
    "source,original,widths",
    [
        (
            "unsigned recovered(unsigned a,unsigned b){return a+b;}",
            "89f801f0c3",
            [32, 32],
        ),
        (
            "unsigned recovered(unsigned a,unsigned b){return a<b?a:b;}",
            "89f839f70f47c6c3",
            [32, 32],
        ),
        (
            "unsigned long long recovered(unsigned long long a,unsigned long long b){return a^b;}",
            "4889f84831f0c3",
            [64, 64],
        ),
    ],
)
def test_compiled_reconstruction_matches_original(source, original, widths):
    built = compile_function(source, "recovered", Jobs())
    assert built["passed"], built
    result = compare_functions(
        bytes.fromhex(original),
        bytes.fromhex(built["machine_hex"]),
        vectors(widths, 41),
        widths[0],
    )
    assert result["passed"], result
    assert result["tested"] >= 64


def test_loops_and_stack_are_emulated_without_native_execution():
    source = "unsigned recovered(unsigned a){unsigned r=0; for(unsigned i=0;i<(a&31);i++) r+=i; return r;}"
    built = compile_function(source, "recovered", Jobs())
    from hivemind_assembly.domains.reverse_engineering.reconstruction import (
        execute_function,
    )

    for n in range(32):
        result = execute_function(bytes.fromhex(built["machine_hex"]), [n], 32)
        assert result["value"] == sum(range(n))
        assert result["abi_ok"] and result["status"] == "completed"


def test_wrong_candidate_and_nonterminating_candidate_are_rejected():
    good = compile_function(
        "unsigned recovered(unsigned a,unsigned b){return a-b;}", "recovered", Jobs()
    )
    assert not compare_functions(
        bytes.fromhex("89f801f0c3"),
        bytes.fromhex(good["machine_hex"]),
        vectors([32, 32], 1),
        32,
    )["passed"]
    result = compare_functions(
        bytes.fromhex("89f8c3"), bytes.fromhex("ebfe"), [[4]], 32
    )
    assert not result["passed"]
    assert result["failures"][0]["candidate"]["status"] == "budget_exhausted"


@pytest.mark.parametrize(
    "source",
    [
        '#include "/etc/passwd"\nunsigned recovered(void){return 0;}',
        'unsigned recovered(void){__asm__("ret");return 0;}',
        "extern unsigned helper(unsigned); unsigned recovered(unsigned x){return helper(x);}",
        "unsigned global=4; unsigned recovered(unsigned x){return global+x;}",
    ],
)
def test_unsupported_dependencies_are_rejected(source):
    with pytest.raises(Blocked):
        compile_function(source, "recovered", Jobs())


def test_compiler_errors_and_missing_symbol_are_not_passes():
    assert not compile_function("this is not C", "recovered", Jobs())["passed"]
    with pytest.raises(ContractError):
        compile_function("unsigned another(void){return 2;}", "recovered", Jobs())
    with pytest.raises(ContractError):
        extract_function(b"not an object", "recovered")


def test_protected_compiled_acceptance_does_not_trust_worker_checks(store):
    c = Controller(store)
    b = Broker(c, {}, ReverseEngineeringDomain())
    task = store.create_project("C recovery", "Recover sum", paused=True)
    root = b.workspace(task["id"])
    (root / "original.hex").write_text("89f801f0c3")
    a = Acceptance(c, b)
    described = a.configure(
        task["id"],
        {
            "scope": "x86_64_c_functions",
            "checks": [
                {
                    "original_path": "original.hex",
                    "original_format": "hex",
                    "candidate_path": "sum.c",
                    "function": "sum",
                    "argument_bits": [32, 32],
                    "output_bits": 32,
                }
            ],
        },
    )
    assert "cases_artifact" not in described["checks"][0]
    store.state(task["id"], "queued")
    epoch = c.acquire(task["id"], "worker.opus")
    c.brief(
        task["id"],
        {"revision": 0},
        {"procedure": "Recover sum", "acceptance": "Compiled check"},
        {"critical_gaps": []},
        [],
    )
    b.execute(
        {
            "id": "inspect",
            "task_id": task["id"],
            "owner": "worker.opus",
            "epoch": epoch,
            "revision": 0,
            "tool": "list_files",
            "args": {},
        }
    )
    task = store.task(task["id"])
    (root / "sum.c").write_text("unsigned sum(unsigned a,unsigned b){return a-b;}")
    assert not a.evaluate(
        task, {"result_operations": ["inspect"], "request_id": "bad"}
    )["passed"]
    # Editing the workspace original cannot substitute for pinned truth.
    (root / "original.hex").write_text("89f829f0c3")
    (root / "sum.c").write_text("unsigned sum(unsigned a,unsigned b){return a+b;}")
    result = a.evaluate(task, {"result_operations": ["inspect"], "request_id": "good"})
    assert result["passed"], result
    assert store.task(task["id"])["status"] == "accepted"


def test_bad_original_cannot_be_used_as_an_acceptance_oracle(store):
    c = Controller(store)
    b = Broker(c, {}, ReverseEngineeringDomain())
    t = store.create_project("Bad original", "Reject loop", paused=True)
    (b.workspace(t["id"]) / "original.hex").write_text("ebfe")
    with pytest.raises(Blocked, match="Original function"):
        Acceptance(c, b).configure(
            t["id"],
            {
                "scope": "x86_64_c_functions",
                "checks": [
                    {
                        "original_path": "original.hex",
                        "original_format": "hex",
                        "candidate_path": "f.c",
                        "function": "f",
                    }
                ],
            },
        )


@pytest.mark.parametrize("code", ["0f05c3", "cd80c3", "0f34c3", "e900010000"])
def test_platform_effects_and_escape_are_not_silent_noops(code):
    from hivemind_assembly.domains.reverse_engineering.reconstruction import (
        execute_function,
    )

    result = execute_function(bytes.fromhex(code), [], 32)
    assert result["status"] == "unsupported", result
