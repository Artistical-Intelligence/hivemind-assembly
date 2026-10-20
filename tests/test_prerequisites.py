from types import SimpleNamespace

import pytest
from hivemind_assembly.application import prerequisites


@pytest.mark.parametrize(
    "host,clang,expected",
    [("nt", False, ["LLVM.LLVM"]), ("nt", True, []), ("posix", False, [])],
)
def test_setup_cross_compiler_with_existing_gcc(monkeypatch, host, clang, expected):
    installed = {"git", "node", "java", "gcc", "winget"}
    if clang:
        installed.add("clang")
    calls = []
    monkeypatch.setattr(prerequisites, "os", SimpleNamespace(name=host))
    monkeypatch.setattr(
        prerequisites.shutil, "which", lambda name: name if name in installed else None
    )
    monkeypatch.setattr(prerequisites, "available", lambda name: name in installed)
    monkeypatch.setattr(prerequisites, "refresh_windows_path", lambda: None)

    def install(argv, **kwargs):
        calls.append(argv)
        installed.add("clang")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(prerequisites.subprocess, "run", install)
    assert prerequisites.install_missing() == {"installed": expected}
    assert [argv[argv.index("--id") + 1] for argv in calls] == expected
