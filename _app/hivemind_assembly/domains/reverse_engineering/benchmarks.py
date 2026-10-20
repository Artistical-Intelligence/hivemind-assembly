"""Generate the design's 24-function, 12-family, two-compiler/O0/O2 corpus.

All variants of a family share a split. Generated source is protected evaluator
truth; do not import this directory into an agent's project workspace.
"""

import argparse, hashlib, json, shutil, subprocess
from pathlib import Path

FAMILIES = {
    "add": ["return a+b;", "return (a+17u)+b;"],
    "subtract": ["return a-b;", "return b-a-9u;"],
    "multiply": ["return a*b;", "return a*3u+b*5u;"],
    "boolean": ["return a&b;", "return (a^b)|0x1234u;"],
    "shift": ["return a<<(b&31u);", "return a>>(b&31u);"],
    "compare": ["return a<b;", "return a==b;"],
    "select": ["return a<b?a:b;", "return a>b?a+1u:b+2u;"],
    "sign": ["return (unsigned)((int)a<(int)b);", "return (unsigned)((int)a>>3);"],
    "rotate": [
        "unsigned n=b&31u; return (a<<n)|(a>>((32u-n)&31u));",
        "return (a<<8)|(a>>24);",
    ],
    "loop": [
        "unsigned r=0;for(unsigned i=0;i<(b&7u);i++)r+=a+i;return r;",
        "unsigned r=a;for(unsigned i=0;i<4;i++)r=r*3u+b;return r;",
    ],
    "byte": [
        "return ((a&255u)<<8)|((a>>8)&255u);",
        "return (unsigned)(unsigned char)a+(unsigned)(unsigned short)b;",
    ],
    "guard": ["return b?a/b:0;", "return b?a%b:a;"],
}
HOLDOUT = {"rotate", "loop", "byte", "guard"}


def generate(out, compilers=("gcc", "clang")):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    manifest = []
    missing = []
    for family, variants in FAMILIES.items():
        for i, body in enumerate(variants):
            name = f"{family}_{i}"
            source = f"__attribute__((noinline)) unsigned target(unsigned a,unsigned b){{{body}}}\n"
            src = out / (name + ".c")
            src.write_text(source)
            for compiler in compilers:
                command = shutil.which(compiler)
                for level in ("O0", "O2"):
                    entry = {
                        "id": f"{name}_{compiler}_{level}",
                        "family": family,
                        "split": "holdout" if family in HOLDOUT else "development",
                        "compiler": compiler,
                        "optimization": level,
                        "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
                    }
                    if not command:
                        entry.update(status="blocked", reason="Compiler unavailable")
                        missing.append(entry["id"])
                    else:
                        obj = out / (entry["id"] + ".o")
                        p = subprocess.run(
                            [
                                command,
                                "-" + level,
                                "-fno-stack-protector",
                                "-fno-asynchronous-unwind-tables",
                                "-c",
                                str(src),
                                "-o",
                                str(obj),
                            ],
                            capture_output=True,
                            text=True,
                        )
                        if p.returncode:
                            entry.update(status="failed", reason=p.stderr)
                        else:
                            entry.update(
                                status="compiled",
                                object=obj.name,
                                sha256=hashlib.sha256(obj.read_bytes()).hexdigest(),
                                compiler_version=subprocess.check_output(
                                    [command, "--version"], text=True
                                ).splitlines()[0],
                            )
                    manifest.append(entry)
    (out / "manifest.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "source_truth": "protected",
                "cases": manifest,
                "expected_cases": 48 * len(compilers),
                "missing_compiler_cases": missing,
            },
            indent=2,
        )
    )
    return {
        "expected": 48 * len(compilers),
        "compiled": sum(x["status"] == "compiled" for x in manifest),
        "blocked": len(missing),
        "families": 12,
        "holdout_families": sorted(HOLDOUT),
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("output")
    print(json.dumps(generate(p.parse_args().output), indent=2))
