import shutil
import os
import subprocess
from pathlib import Path
import pytest
from hivemind_assembly.core.common import Blocked, ContractError
from hivemind_assembly.domains.reverse_engineering import pe_dependencies
from hivemind_assembly.domains.reverse_engineering.call_images import execute

CLANG = os.environ.get("HA_TEST_CLANG") or shutil.which("clang")
LLD = os.environ.get("HA_TEST_LLD") or shutil.which("lld-link")
if not LLD and CLANG:
    sibling = Path(CLANG).with_name("lld-link.exe" if os.name == "nt" else "lld-link")
    if sibling.is_file():
        LLD = str(sibling)
pytestmark = pytest.mark.skipif(
    not CLANG or not LLD, reason="Clang and LLD required; set HA_TEST_CLANG/HA_TEST_LLD"
)


def object_file(root, name, source):
    (root / (name + ".c")).write_text(source)
    subprocess.run(
        [
            CLANG,
            "--target=x86_64-pc-windows-msvc",
            "-O2",
            "-ffreestanding",
            "-fno-builtin",
            "-fno-stack-protector",
            "-c",
            str(root / (name + ".c")),
            "-o",
            str(root / (name + ".obj")),
        ],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def dlls(tmp_path):
    object_file(
        tmp_path,
        "helper",
        "unsigned data=19;unsigned *ptr=&data;unsigned mix(unsigned x){return x+*ptr;}",
    )
    object_file(
        tmp_path,
        "main",
        "__declspec(dllimport) unsigned mix(unsigned);unsigned recovered(unsigned x){return mix(x)*3;}",
    )
    subprocess.run(
        [
            LLD,
            "/dll",
            "/noentry",
            "/nodefaultlib",
            "/fixed:no",
            "/export:mix",
            "/out:helper.dll",
            "/implib:helper.lib",
            "helper.obj",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            LLD,
            "/dll",
            "/noentry",
            "/nodefaultlib",
            "/fixed:no",
            "/export:recovered",
            "/out:main.dll",
            "main.obj",
            "helper.lib",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    return (tmp_path / "main.dll").read_bytes(), {
        "helper.dll": (tmp_path / "helper.dll").read_bytes()
    }


def test_declared_dll_link_and_relocation(dlls):
    root, deps = dlls
    image = pe_dependencies.load(root, symbol="recovered", dependencies=deps)
    assert len(image["imports"]) == 1 and image["dependencies"].keys() == deps.keys()
    for value in (0, 1, 128, 0xFFFFFFFF):
        result = execute(image, {"arguments": [value], "output_bits": 32})
        assert result["status"] == "completed" and result["abi_ok"], result
        assert result["value"] == ((value + 19) * 3) & 0xFFFFFFFF


def test_missing_import_never_fetches_or_substitutes(dlls):
    root, deps = dlls
    with pytest.raises(Blocked):
        pe_dependencies.load(root, symbol="recovered")
    with pytest.raises(Blocked, match="not supplied"):
        pe_dependencies.load(
            root, symbol="recovered", dependencies={"different.dll": deps["helper.dll"]}
        )
    with pytest.raises(ContractError):
        pe_dependencies.load(
            root, symbol="recovered", dependencies={"../helper.dll": deps["helper.dll"]}
        )


def test_loader_initialization_is_not_silently_skipped(dlls):
    import pefile

    root, deps = dlls
    pe = pefile.PE(data=deps["helper.dll"])
    pe.OPTIONAL_HEADER.AddressOfEntryPoint = 0x1000
    with pytest.raises(Blocked, match="initialization"):
        pe_dependencies.load(
            root, symbol="recovered", dependencies={"helper.dll": bytes(pe.write())}
        )


def test_forwarded_export(dlls, tmp_path):
    root, deps = dlls
    # A real LLD forwarder imports no code itself; it points to the supplied helper.
    subprocess.run(
        [
            LLD,
            "/dll",
            "/noentry",
            "/nodefaultlib",
            "/fixed:no",
            "/export:forwarded=helper.mix",
            "/out:forward.dll",
            "helper.obj",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    image = pe_dependencies.load(
        (tmp_path / "forward.dll").read_bytes(), symbol="forwarded", dependencies=deps
    )
    assert execute(image, {"arguments": [9], "output_bits": 32})["value"] == 28


def test_protected_dependency_is_not_replaced_by_workspace_edit(dlls, store, tmp_path):
    import json, threading
    from types import SimpleNamespace
    from hivemind_assembly.core.jobs import Jobs
    from hivemind_assembly.core.artifacts import Artifacts
    from hivemind_assembly.domains.reverse_engineering.call_acceptance import (
        CallAcceptance,
    )

    root, deps = dlls
    (tmp_path / "recovered.c").write_text(
        "unsigned recovered(unsigned x){return (x+19u)*3u;}"
    )
    (tmp_path / "manifest.json").write_text(json.dumps({"sources": ["recovered.c"]}))
    t = store.create_project("DLL recovery", "retain dependencies")
    artifacts = Artifacts(store)
    project = t["project_id"]
    context = SimpleNamespace(
        jobs=Jobs(),
        config={"foundations": {"c_compiler": CLANG}},
        cancel=threading.Event(),
    )
    verifier = CallAcceptance()
    contract = verifier.prepare(
        tmp_path,
        {
            "scope": "x86_64_linked_calls",
            "original_path": "main.dll",
            "original_symbol": "recovered",
            "original_dependencies": {"helper.dll": "helper.dll"},
            "manifest_path": "manifest.json",
            "function": "recovered",
            "candidate_abi": "sysv",
            "cases": [
                {"arguments": [0], "output_bits": 32},
                {"arguments": [0xFFFFFFFF], "output_bits": 32},
            ],
        },
        artifacts,
        project,
        context,
    )
    (tmp_path / "helper.dll").write_bytes(b"changed original dependency")
    assert verifier.verify(tmp_path, contract, artifacts, project, context)["passed"]
