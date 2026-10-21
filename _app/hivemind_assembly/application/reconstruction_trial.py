"""First autonomous reconstruction target, without a supplied solution in the workspace.

This is a synthetic, source-known validation target. Creating it is not evidence
that a model reconstructed it; a real team must still run the objective.
"""

import json
import tempfile
from pathlib import Path

from hivemind_assembly.core.common import Blocked
from hivemind_assembly.domains.reverse_engineering.program import build

OBJECTIVE = (
    "Recover the behavior of original.elf into candidate.c. Use Ghidra inventory "
    "and decompilation and REA analysis of the binary, with a separate adviser "
    "briefing before substantive steps. The original C source is not in this "
    "workspace. Build with build.json and use compare_program for development "
    "checks. Preserve the input binary. Continue through edits, failed checks "
    "and checkpoints until independent complete-program acceptance passes. "
    "Report the supported input/output scope and any remaining uncertainties."
)

# Three ordinary functions, chunk boundaries and persistent state; no host APIs
# beyond the existing freestanding read/write runtime are needed.
SOURCE = """unsigned advance(unsigned state, unsigned char byte) {
    return (state * 33u) ^ ((unsigned)byte + 17u);
}
unsigned char encode(unsigned state, unsigned char byte, unsigned index) {
    return (unsigned char)(byte ^ (state >> ((index & 3u) * 8u)));
}
int ha_main(void) {
    unsigned state = 2166136261u, index = 0;
    unsigned char data[31];
    long count;
    while ((count = ha_read(data, sizeof data)) > 0) {
        for (long i = 0; i < count; ++i) {
            unsigned char byte = data[i];
            state = advance(state, byte);
            data[i] = encode(state, byte, index++);
        }
        if (ha_write(data, count) != count) return 3;
    }
    unsigned char footer[4];
    for (unsigned i = 0; i < 4; ++i) footer[i] = (unsigned char)(state >> (i * 8));
    return ha_write(footer, sizeof footer) == sizeof footer ? 0 : 4;
}
"""


def example(app):
    compiler = app.config.get("foundations", {}).get("c_compiler", "")
    with tempfile.TemporaryDirectory(prefix="ha-reconstruction-trial-") as folder:
        root = Path(folder)
        (root / "original.c").write_text(SOURCE, encoding="utf-8")
        built = build(
            root,
            {"sources": ["original.c"], "optimization": "O0"},
            app.broker.jobs,
            compiler,
        )
        if not built["passed"]:
            raise Blocked(
                "Reconstruction trial requires a working C compiler: "
                + str(built.get("build"))
            )
        image = bytes.fromhex(built["elf_hex"])

    development = [
        {"id": "empty", "input_hex": "", "effect_policy": "observable"},
        {
            "id": "text",
            "input_hex": b"Hivemind Assembly\n".hex(),
            "effect_policy": "observable",
        },
    ]
    # Cases are sealed by Acceptance before the task can start. Only development
    # inputs are copied to the project. Neither expected output nor C source is.
    cases = development + [
        {
            "id": "protected-" + str(i),
            "input_hex": data.hex(),
            "effect_policy": "observable",
        }
        for i, data in enumerate(
            (
                bytes(range(30)),
                bytes(range(31)),
                bytes(range(32)),
                bytes(range(62)),
                bytes(range(256)),
                b"\xff" * 129,
                bytes((i * 73 + 19) % 256 for i in range(513)),
            )
        )
    ]
    contract = {
        "scope": "linux_program",
        "original_path": "original.elf",
        "manifest_path": "build.json",
        "cases": cases,
    }
    files = {
        "candidate.c": "/* Recover the supplied binary's behavior here. */\nint ha_main(void) { return 0; }\n",
        "build.json": json.dumps(
            {
                "sources": ["candidate.c"],
                "architecture": "x86_64",
                "optimization": "O2",
            },
            indent=2,
        )
        + "\n",
        "development.json": json.dumps(development, indent=2) + "\n",
        "README.txt": (
            OBJECTIVE + "\n\n"
            "This synthetic multi-function x64 ELF reads binary stdin and writes binary stdout. "
            "The candidate is intentionally unfinished. Original source and protected cases "
            "are absent from the project. The empty and text development inputs are provided "
            "in development.json; compare_program accepts them as its cases argument. "
            "The supplied runtime provides ha_read, ha_write and ha_main without headers. "
            "All target replay is emulated. Independent acceptance checks streams, exit and "
            "input consumption over a finite corpus, including read-boundary cases; it does "
            "not prove all possible inputs. Native model sessions and Ghidra/REA/Hermes "
            "must be configured to run the autonomous objective. Start it in Projects & tasks.\n"
        ),
    }
    return files, contract, image
