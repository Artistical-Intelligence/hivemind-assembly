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


@pytest.mark.parametrize(
    "version,expected",
    [
        ("v22.19.0", False),
        ("v24.0.0", False),
        ("v24.10.9", False),
        ("v24.11.0", True),
        ("v24.15.0", True),
        ("v25.9.0", False),
        ("v26.0.0", True),
        ("unexpected output", False),
    ],
)
def test_node_version_matches_pinned_rea_requirements(monkeypatch, version, expected):
    monkeypatch.setattr(prerequisites.shutil, "which", lambda name: "/fixture/node")
    monkeypatch.setattr(
        prerequisites.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout=version, stderr=""),
    )
    assert prerequisites.available("node") is expected


def test_windows_refresh_prefers_new_registry_path_and_jdk(monkeypatch):
    import os
    import sys

    class Key:
        def __init__(self, hive): self.hive = hive
        def __enter__(self): return self
        def __exit__(self, *args): pass

    values = {
        'machine': {'Path': r'C:\new-node;%JAVA_HOME%\bin', 'JAVA_HOME': r'C:\jdk-21'},
        'user': {'Path': r'C:\user-tools;C:\NEW-NODE', 'JAVA_HOME': r'C:\jdk-25'},
    }
    registry = SimpleNamespace(
        HKEY_LOCAL_MACHINE='machine', HKEY_CURRENT_USER='user',
        OpenKey=lambda hive, key: Key(hive),
        QueryValueEx=lambda handle, name: (values[handle.hive][name], 1),
    )
    monkeypatch.setitem(sys.modules, 'winreg', registry)
    monkeypatch.setattr(prerequisites, 'os', SimpleNamespace(name='nt', environ=os.environ))
    # Registry precedence only; a real LLVM installation on the host (as on
    # GitHub's Windows runners) must not add its folder to this fixture.
    monkeypatch.setattr(prerequisites, 'STANDARD_FOLDERS', {})
    monkeypatch.setenv('JAVA_HOME', r'C:\old-jre')
    monkeypatch.setenv('PATH', r'C:\old-node;C:\user-tools;C:\Windows')
    prerequisites.refresh_windows_path()
    assert os.environ['JAVA_HOME'] == r'C:\jdk-25'
    assert os.environ['PATH'].split(';') == [r'C:\new-node', r'C:\jdk-25\bin', r'C:\user-tools', r'C:\old-node', r'C:\Windows']
    once = os.environ['PATH']
    prerequisites.refresh_windows_path()
    assert os.environ['PATH'] == once


@pytest.mark.parametrize('compiler_version,expected', [('21.0.4', True), ('17.0.9', False), ('25.0.1', False)])
def test_java_home_selects_one_matching_full_jdk(monkeypatch, tmp_path, compiler_version, expected):
    import os

    home = tmp_path / 'selected jdk'
    (home / 'bin').mkdir(parents=True)
    java = home / 'bin' / ('java.exe' if os.name == 'nt' else 'java')
    javac = home / 'bin' / ('javac.exe' if os.name == 'nt' else 'javac')
    java.touch(); javac.touch()
    monkeypatch.setenv('JAVA_HOME', str(home))
    monkeypatch.setattr(prerequisites.shutil, 'which', lambda name: '/unrelated-old-java')
    observed = []
    def version(argv, **kwargs):
        observed.append(argv[0])
        text = 'javac ' + compiler_version if argv[0] == str(javac) else 'openjdk version "21.0.4"'
        return SimpleNamespace(returncode=0, stdout=text, stderr='')
    monkeypatch.setattr(prerequisites.subprocess, 'run', version)
    assert prerequisites.available('java') is expected
    assert observed == [str(java), str(javac)]
    javac.unlink()
    assert not prerequisites.available('java')


@pytest.mark.parametrize("returncode,lands,ok", [(0, True, True), (1, True, True), (0, False, False)])
def test_install_is_judged_by_whether_the_tool_is_found(monkeypatch, returncode, lands, ok):
    # winget reports an error for an already-installed package; a zero exit
    # without a usable tool is still a failure.
    installed = {"git", "node", "java", "winget"}
    monkeypatch.setattr(prerequisites, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(prerequisites.shutil, "which", lambda name: name if name in installed else None)
    monkeypatch.setattr(prerequisites, "available", lambda name: name in installed)
    monkeypatch.setattr(prerequisites, "refresh_windows_path", lambda: None)

    def install(argv, **kwargs):
        if lands:
            installed.add("clang")
        return SimpleNamespace(returncode=returncode)

    monkeypatch.setattr(prerequisites.subprocess, "run", install)
    if ok:
        assert prerequisites.install_missing() == {"installed": ["LLVM.LLVM"]}
    else:
        with pytest.raises(prerequisites.Blocked, match="choose Yes"):
            prerequisites.install_missing()


def test_path_refresh_finds_llvm_in_its_standard_folder(monkeypatch, tmp_path):
    import os
    import sys

    llvm = tmp_path / "Program Files" / "LLVM" / "bin"
    llvm.mkdir(parents=True)
    (llvm / "clang.exe").write_bytes(b"")

    class Key:
        def __enter__(self): return self
        def __exit__(self, *args): pass

    registry = SimpleNamespace(
        HKEY_LOCAL_MACHINE="machine", HKEY_CURRENT_USER="user",
        OpenKey=lambda hive, key: Key(),
        QueryValueEx=lambda handle, name: (_ for _ in ()).throw(OSError()),
    )
    monkeypatch.setitem(sys.modules, "winreg", registry)
    monkeypatch.setattr(prerequisites, "os", SimpleNamespace(name="nt", environ=os.environ))
    monkeypatch.setattr(prerequisites, "available", lambda name: False)
    monkeypatch.setattr(prerequisites.shutil, "which", lambda name: None)
    monkeypatch.setattr(prerequisites.ntpath, "expandvars", lambda value: str(llvm) if value.startswith("%ProgramFiles%") else value)
    monkeypatch.setenv("PATH", r"C:\Windows")
    prerequisites.refresh_windows_path()
    assert os.environ["PATH"].split(";") == [r"C:\Windows", str(llvm)]
