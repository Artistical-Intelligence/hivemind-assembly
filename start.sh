#!/usr/bin/env bash
set -euo pipefail
APP_ROOT="$(cd -- "$(dirname -- "$0")" && pwd)/_app"
DATA_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/unified-workbench"
mkdir -p "$DATA_ROOT"
if [ ! -x "$DATA_ROOT/runtime/bin/python" ]; then python3 -m venv "$DATA_ROOT/runtime"; fi
"$DATA_ROOT/runtime/bin/python" -m pip install -r "$APP_ROOT/requirements.txt"
"$DATA_ROOT/runtime/bin/python" -m playwright install chromium
PYTHONPATH="$APP_ROOT" "$DATA_ROOT/runtime/bin/python" -m hivemind_assembly serve
