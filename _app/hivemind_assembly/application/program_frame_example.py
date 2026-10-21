"""Small source-known emulated renderer with temporal protected checks."""

import json
import tempfile
from pathlib import Path

from hivemind_assembly.core.common import Blocked
from hivemind_assembly.domains.reverse_engineering.windows_program import build

SOURCE = """int ha_main(void) {
    unsigned char input[8], pixels[8][8][4];
    if (ha_read(input, 8) != 8) return 2;
    int x = 0;
    for (int frame = 0; frame < 8; ++frame) {
        if (input[frame]) x = (x + 1) % 8;
        for (int row = 0; row < 8; ++row) {
            for (int col = 0; col < 8; ++col) {
                pixels[row][col][0] = col == x ? 240 : 16;
                pixels[row][col][1] = row * 16;
                pixels[row][col][2] = 32;
                pixels[row][col][3] = 255;
            }
        }
        ha_write(pixels, sizeof pixels);
    }
    ha_error(&x, sizeof x);
    return 0;
}
"""


def example(app):
    manifest = {"sources": ["candidate.c"], "optimization": "O2"}
    with tempfile.TemporaryDirectory(prefix="ha-program-frames-") as folder:
        root = Path(folder)
        (root / "candidate.c").write_text(SOURCE)
        built = build(
            root,
            manifest | {"optimization": "O0"},
            app.broker.jobs,
            app.config.get("foundations", {}).get("c_compiler", ""),
        )
    if not built["passed"]:
        raise Blocked("Frame program example requires working Clang and LLD")
    rule = {
        "format": "rgba8_sequence",
        "width": 8,
        "height": 8,
        "frames": 8,
        "frame_rate_num": 60,
        "frame_rate_den": 1,
    }
    contract = {
        "scope": "windows_program",
        "original_path": "original.exe",
        "manifest_path": "build.json",
        "cases": [
            {"id": name, "input_hex": bytes(events).hex(), "captures": {"stdout": rule}}
            for name, events in (
                ("still", [0] * 8),
                ("move", [0, 1, 0, 1, 0, 0, 0, 0]),
                ("early", [1, 1, 1, 0, 0, 0, 0, 0]),
            )
        ],
    }
    files = {
        "original.c": SOURCE,
        "candidate.c": SOURCE,
        "build.json": json.dumps(manifest, indent=2) + "\n",
        "acceptance.json": json.dumps(contract, indent=2) + "\n",
        "README.txt": (
            "This source-known Windows PE renderer executes only in the bounded emulator. "
            "It emits eight 8x8 RGBA frames to stdout and final position to stderr. "
            "Clang and LLD are required; native target execution is not. Run checks, then "
            "Inspect captures to scrub the reference and candidate together. Change "
            "if (input[frame]) to if (frame > 0 && input[frame - 1]) and rerun: "
            "the movement is one frame late although the final position is unchanged. "
            "The protected frame corpus catches this. Editing acceptance.json or original.c "
            "does not change the sealed evaluator. Frame rate is declared playback metadata, "
            "not measured timing. This does not provide a GPU, window system or game engine.\n"
        ),
    }
    return files, contract, bytes.fromhex(built["pe_hex"])
