"""Browse buttons: the operating system's own picker fills a path field."""

import base64
import subprocess
import sys

import pytest

from hivemind_assembly.application import pickers
from hivemind_assembly.core.common import Blocked, ContractError
import test_app

app = test_app.app  # the application fixture


def test_pasted_paths_lose_quotes_and_spaces():
    assert pickers.user_path('  "C:\\Targets\\game.exe"  ') == "C:\\Targets\\game.exe"
    assert pickers.user_path("'/home/me/notes.md'") == "/home/me/notes.md"
    assert pickers.user_path('C:\\a "quoted" name.txt') == 'C:\\a "quoted" name.txt'
    assert pickers.user_path(None) == ""


def test_windows_uses_a_topmost_powershell_dialog():
    argv, env = pickers.commands(
        "file", "Choose", "All files (*.*)|*.*", "win32", lambda name: "C:\\ps\\" + name
    )
    assert argv[0].endswith("powershell.exe") and "-STA" in argv
    script = base64.b64decode(argv[argv.index("-EncodedCommand") + 1]).decode("utf-16-le")
    assert "OpenFileDialog" in script and "TopMost = $true" in script
    assert env == {"HA_PICK_KIND": "file", "HA_PICK_TITLE": "Choose", "HA_PICK_FILTER": "All files (*.*)|*.*"}


def test_other_systems_use_their_own_pickers():
    argv, _ = pickers.commands("folder", 'Say "hi"', "", "darwin", lambda name: None)
    assert argv[:2] == ["osascript", "-e"] and 'choose folder with prompt "Say \\"hi\\""' in argv[2]
    argv, _ = pickers.commands("folder", "T", "", "linux", lambda name: "/usr/bin/" + name)
    assert argv[0] == "zenity" and "--directory" in argv
    argv, _ = pickers.commands("file", "T", "", "linux", lambda name: "/usr/bin/kdialog" if name == "kdialog" else None)
    assert argv[0] == "kdialog" and "--getopenfilename" in argv
    argv, _ = pickers.commands("file", "T", "", "linux", lambda name: None)
    assert argv[:2] == [sys.executable, "-c"]


def fake(returncode=0, stdout=b"", stderr=b""):
    calls = []

    def run(argv, **kw):
        calls.append((argv, kw))
        return subprocess.CompletedProcess(argv, returncode, stdout, stderr)

    return run, calls


def test_choose_returns_the_path_or_cancelled():
    run, calls = fake(stdout="C:\\Targets\\game.exe".encode())
    assert pickers.choose("program", run, "win32", lambda n: "powershell.exe") == {
        "path": "C:\\Targets\\game.exe"
    }
    assert calls[0][1]["env"]["HA_PICK_KIND"] == "file"
    assert calls[0][1]["timeout"] == pickers.WAIT
    run, _ = fake()
    assert pickers.choose("program", run, "win32", lambda n: "powershell.exe") == {"cancelled": True}
    run, _ = fake(returncode=1, stderr=b"execution error: User canceled. (-128)")
    assert pickers.choose("practice", run, "darwin") == {"cancelled": True}
    run, _ = fake(stdout=b"/Users/me/problems/\n")
    assert pickers.choose("practice", run, "darwin") == {"path": "/Users/me/problems"}


def test_choose_explains_when_no_picker_can_open():
    with pytest.raises(ContractError):
        pickers.choose("anything")

    def missing(argv, **kw):
        raise FileNotFoundError(argv[0])

    with pytest.raises(Blocked, match="type or paste"):
        pickers.choose("document", missing, "linux", lambda n: "/usr/bin/zenity")
    run, _ = fake(returncode=1, stderr=b"_tkinter.TclError: no display name")
    with pytest.raises(Blocked, match="type or paste"):
        pickers.choose("document", run, "linux", lambda n: None)
    with pytest.raises(Blocked, match="type or paste"):
        pickers.choose("document", fake()[0], "win32", lambda n: None)


def test_browse_endpoint_and_quoted_paths(app, tmp_path, monkeypatch):
    monkeypatch.setattr(pickers, "choose", lambda purpose: {"path": "/picked/" + purpose})
    assert app.action("/api/choose-path", {"purpose": "program"}) == {"path": "/picked/program"}
    task = app.action(
        "/api/project", {"name": "Quoted", "objective": "Import", "start_paused": True}
    )
    source = tmp_path / "game data.bin"
    source.write_bytes(b"\x01\x02")
    imported = app.action("/api/import-target", {"task": task["id"], "path": f'"{source}"'})
    assert imported["name"] == "game data.bin"
    with pytest.raises(ContractError, match="Browse"):
        app.action("/api/import-target", {"task": task["id"], "path": str(tmp_path / "missing.exe")})
    with pytest.raises(ContractError, match="Browse"):
        app.action("/api/source", {"path": f'"{tmp_path / "missing.md"}"'})
    notes = tmp_path / "notes.md"
    notes.write_text("Integer arithmetic")
    assert app.action("/api/source", {"path": f'  "{notes}" '})["id"]


def test_byte_order_mark_is_not_part_of_the_path():
    run, _ = fake(stdout="\ufeffC:\\Users\\me\\Café\\game.exe".encode("utf-8"))
    assert pickers.choose("program", run, "win32", lambda n: "powershell.exe") == {
        "path": "C:\\Users\\me\\Café\\game.exe"
    }
