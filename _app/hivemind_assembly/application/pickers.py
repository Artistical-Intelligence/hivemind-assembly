"""Browse buttons: show this computer's own file or folder picker and return the path.

The dashboard only runs on 127.0.0.1, so the picker opens on the same computer as
the browser. Browsers never reveal full file paths, which is why HA asks the
operating system instead. Nothing is read or copied here; the chosen path only
fills a form field that the owner still submits.
"""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys

from hivemind_assembly.core.common import Blocked, ContractError

# What each Browse button is for: picker title and, for files, the file types offered.
PURPOSES = {
    "program": ("file", "Choose the program to rebuild", "All files (*.*)|*.*"),
    "document": (
        "file",
        "Choose a reference document",
        "Documents (*.pdf;*.docx;*.xlsx;*.xlsm;*.md;*.txt;*.html;*.json;*.csv;*.c;*.h;*.py;*.ps1)|"
        "*.pdf;*.docx;*.xlsx;*.xlsm;*.md;*.txt;*.html;*.json;*.csv;*.c;*.h;*.py;*.ps1|All files (*.*)|*.*",
    ),
    "knowledge-folder": ("folder", "Choose the folder of reference material", ""),
    "app-settings": (
        "file",
        "Choose the app's MCP settings file",
        "Settings files (*.json)|*.json|All files (*.*)|*.*",
    ),
    "practice": ("folder", "Choose the practice problems folder", ""),
    "backup-folder": ("folder", "Choose the folder to back up to GitHub", ""),
    "mcp-program": (
        "file",
        "Choose the program that offers the tools",
        "Programs (*.exe;*.cmd;*.bat)|*.exe;*.cmd;*.bat|All files (*.*)|*.*",
    ),
}

# Windows PowerShell 5.1 ships with every supported Windows and runs STA, which the
# WinForms dialogs need. A topmost owner keeps the dialog in front of Chrome.
WINDOWS_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Application]::EnableVisualStyles()
$owner = New-Object System.Windows.Forms.Form -Property @{TopMost = $true; ShowInTaskbar = $false}
if ($env:HA_PICK_KIND -eq 'folder') {
  $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
  $dialog.Description = $env:HA_PICK_TITLE
  $dialog.ShowNewFolderButton = $false
  $answer = $dialog.ShowDialog($owner)
  $chosen = $dialog.SelectedPath
} else {
  $dialog = New-Object System.Windows.Forms.OpenFileDialog
  $dialog.Title = $env:HA_PICK_TITLE
  $dialog.Filter = $env:HA_PICK_FILTER
  $dialog.Multiselect = $false
  $dialog.CheckFileExists = $true
  $answer = $dialog.ShowDialog($owner)
  $chosen = $dialog.FileName
}
$owner.Dispose()
if ($answer -eq [System.Windows.Forms.DialogResult]::OK -and $chosen) { [Console]::Out.Write($chosen) }
"""

# Last resort on Linux without zenity or kdialog; a separate process keeps Tk off
# the server's threads.
TK_SCRIPT = r"""
import os, sys, tkinter
from tkinter import filedialog
root = tkinter.Tk()
root.withdraw()
root.attributes("-topmost", True)
title = os.environ["HA_PICK_TITLE"]
chosen = (filedialog.askdirectory(title=title, mustexist=True)
          if os.environ["HA_PICK_KIND"] == "folder" else filedialog.askopenfilename(title=title))
root.destroy()
sys.stdout.write(chosen or "")
"""

WAIT = 15 * 60  # the owner may take a while to find the file


def user_path(value):
    """A typed or pasted path without stray spaces or the quotes Windows adds to
    "Copy as path"."""
    text = str(value or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1].strip()
    return text


def commands(kind, title, filters, platform=None, which=shutil.which):
    """The picker command for this computer, as (argv, extra environment)."""
    platform = platform or sys.platform
    env = {"HA_PICK_KIND": kind, "HA_PICK_TITLE": title, "HA_PICK_FILTER": filters}
    if platform == "win32":
        shell = which("powershell.exe") or which("powershell")
        builtin = os.path.join(
            os.environ.get("SystemRoot", r"C:\Windows"),
            "System32", "WindowsPowerShell", "v1.0", "powershell.exe",
        )
        if not shell and platform == sys.platform and os.path.exists(builtin):
            shell = builtin
        if not shell:
            raise Blocked("Windows PowerShell isn't available, so type or paste the path.")
        encoded = base64.b64encode(WINDOWS_SCRIPT.encode("utf-16-le")).decode()
        return [shell, "-NoProfile", "-NonInteractive", "-STA", "-EncodedCommand", encoded], env
    if platform == "darwin":
        what = "folder" if kind == "folder" else "file"
        prompt = title.replace("\\", "\\\\").replace('"', '\\"')
        return ["osascript", "-e", f'POSIX path of (choose {what} with prompt "{prompt}")'], env
    if which("zenity"):
        return ["zenity", "--file-selection", "--title=" + title] + (
            ["--directory"] if kind == "folder" else []
        ), env
    if which("kdialog"):
        return ["kdialog", "--title", title] + (
            ["--getexistingdirectory", "."] if kind == "folder" else ["--getopenfilename", "."]
        ), env
    return [sys.executable, "-c", TK_SCRIPT], env


def choose(purpose, run=subprocess.run, platform=None, which=shutil.which):
    """Show the picker and return {"path": ...}, or {"cancelled": True}."""
    if purpose not in PURPOSES:
        raise ContractError("Unknown Browse button")
    kind, title, filters = PURPOSES[purpose]
    argv, extra = commands(kind, title, filters, platform, which)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if (platform or sys.platform) == "win32" else 0
    try:
        done = run(
            argv,
            env={**os.environ, **extra},
            capture_output=True,
            timeout=WAIT,
            creationflags=flags,
        )
    except FileNotFoundError:
        raise Blocked("This computer has no file picker HA can open, so type or paste the path.")
    except subprocess.TimeoutExpired:
        return {"cancelled": True}
    out = done.stdout.decode("utf-8", errors="replace") if isinstance(done.stdout, bytes) else done.stdout or ""
    out = out.lstrip("\ufeff")  # some consoles start redirected UTF-8 with a byte-order mark
    chosen = out.strip().splitlines()[-1].strip() if out.strip() else ""
    if done.returncode != 0 and not chosen:
        # zenity, kdialog and osascript exit 1 on Cancel; anything else is a failure.
        err = done.stderr.decode("utf-8", errors="replace") if isinstance(done.stderr, bytes) else done.stderr or ""
        if done.returncode == 1 and ("cancel" in err.lower() or not err.strip()):
            return {"cancelled": True}
        if "tkinter" in err or "TclError" in err or "display" in err.lower():
            raise Blocked("This computer has no file picker HA can open, so type or paste the path.")
        raise Blocked("The file picker didn't open: " + (err.strip().splitlines() or ["unknown error"])[-1][:200])
    if not chosen:
        return {"cancelled": True}
    return {"path": chosen.rstrip("/") if kind == "folder" and chosen not in ("/",) else chosen}
