"""Build minimal runtime/source archives, excluding all user and development state."""

from pathlib import Path
import hashlib, json, sys, urllib.request, zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = json.loads((ROOT / "_app/release_status.json").read_text())["version"]
LOCAL_WHEELS = {
    "unicodecsv-0.14.1-py3-none-any.whl": "03f6c823c054ed114fe017b60c792ea05b1bddc4c3dc8b2222f6c3b4f19230fe",
}
BOOTSTRAP = {
    "python-3.12.10-embed-amd64.zip": (
        "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip",
        "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3",
    ),
    "pip-25.0.1-py3-none-any.whl": (
        None,
        "c46efd13b6aa8279f33f2864459c8ce587ea6a1a59ee20de055868d8f7688f7f",
    ),
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bootstrap():
    folder = ROOT / "_app/bootstrap"
    folder.mkdir(exist_ok=True)
    for name, expected in LOCAL_WHEELS.items():
        path = folder / "wheels" / name
        if not path.is_file() or sha(path) != expected:
            raise RuntimeError("Bundled pure-Python wheel integrity failure: " + name)
    for name, (url, expected) in BOOTSTRAP.items():
        path = folder / name
        if path.exists() and sha(path) == expected:
            continue
        if url is None:
            with urllib.request.urlopen("https://pypi.org/pypi/pip/25.0.1/json") as r:
                metadata = json.load(r)
            url = next(
                x["url"]
                for x in metadata["urls"]
                if x["filename"] == name and x["digests"]["sha256"] == expected
            )
        stage = folder / (name + ".download")
        urllib.request.urlretrieve(url, stage)
        if sha(stage) != expected:
            raise RuntimeError("Bootstrap integrity failure: " + name)
        stage.replace(path)


def files():
    for p in ROOT.rglob("*"):
        if not p.is_file():
            continue
        r = p.relative_to(ROOT)
        if r.as_posix() == "_app/package_manifest.json":
            continue
        if any(
            x
            in {
                ".git",
                ".pytest_cache",
                ".ruff_cache",
                "__pycache__",
                "node_modules",
                ".venv",
                "release",
                "state",
            }
            for x in r.parts
        ):
            continue
        if p.suffix in {".pyc", ".pyo", ".sqlite3"} or p.name.endswith(".download"):
            continue
        yield p, r


def build(destination):
    bootstrap()
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    inventory = list(files())
    outputs = []
    for kind in ("Windows", "Source"):
        out = destination / f"Hivemind_Assembly_{VERSION}_{kind}.zip"
        manifest = {}
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for p, r in inventory:
                if kind == "Windows" and not (
                    r.parts[0] == "_app"
                    or str(r) in ("README.md", "Start_Hivemind_Assembly.cmd")
                ):
                    continue
                if (
                    kind == "Source"
                    and r.parts[:2] == ("_app", "bootstrap")
                    and r.parts[2] != "wheels"
                ):
                    continue
                manifest[str(r).replace("\\", "/")] = sha(p)
                z.write(p, "Hivemind_Assembly/" + r.as_posix())
            z.writestr(
                "Hivemind_Assembly/_app/package_manifest.json",
                json.dumps(
                    {"version": VERSION, "kind": kind, "files": manifest}, indent=2
                ),
            )
        with zipfile.ZipFile(out) as z:
            assert z.testzip() is None
            for name, h in manifest.items():
                assert (
                    hashlib.sha256(z.read("Hivemind_Assembly/" + name)).hexdigest() == h
                )
        outputs.append(
            {
                "file": str(out.resolve()),
                "bytes": out.stat().st_size,
                "sha256": sha(out),
                "files": len(manifest),
            }
        )
    return outputs


if __name__ == "__main__":
    print(
        json.dumps(
            build(sys.argv[1] if len(sys.argv) > 1 else ROOT.parent / "deliverables"),
            indent=2,
        )
    )
