"""Fetch a hash-pinned guest loader/libc for development tests; never install it."""

import argparse
import hashlib
import io
from pathlib import Path
import tarfile
import urllib.request
import zstandard

URL = "https://archive.ubuntu.com/ubuntu/pool/main/c/cross-toolchain-base/libc6-arm64-cross_2.39-0ubuntu8cross1_all.deb"
SHA256 = "76547cb8a4d7f057e23dcade45a17fc0f3d5c2fa0d3ff125bca56f7c4ecd7a07"
NAMES = ("ld-linux-aarch64.so.1", "libc.so.6")


def prepare(destination, package=None):
    if package is None:
        with urllib.request.urlopen(URL, timeout=60) as response:
            package = response.read(2_000_001)
    if hashlib.sha256(package).hexdigest() != SHA256:
        raise ValueError("ARM64 fixture package hash mismatch")
    # Debian ar container. Read only the pinned data archive and two regular
    # files; no package scripts, links, permissions or arbitrary paths extracted.
    if package[:8] != b"!<arch>\n":
        raise ValueError("Invalid fixture container")
    offset, payload = 8, None
    while offset + 60 <= len(package):
        header = package[offset : offset + 60]
        size = int(header[48:58])
        if header[:16].strip() == b"data.tar.zst":
            payload = package[offset + 60 : offset + 60 + size]
            break
        offset += 60 + size + size % 2
    if payload is None:
        raise ValueError("Missing fixture data archive")
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    payload = zstandard.ZstdDecompressor().decompress(
        payload, max_output_size=32_000_000
    )
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
        for name in NAMES:
            member = archive.getmember("./usr/aarch64-linux-gnu/lib/" + name)
            if not member.isfile() or member.size > 8_000_000:
                raise ValueError("Invalid fixture library")
            (destination / name).write_bytes(archive.extractfile(member).read())
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination")
    parser.add_argument("--package", type=Path)
    args = parser.parse_args()
    prepare(args.destination, args.package.read_bytes() if args.package else None)
    print("Pinned ARM64 guest fixture ready")
