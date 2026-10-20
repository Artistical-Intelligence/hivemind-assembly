"""Source-known stereo pulse reference driven by sample-indexed level changes."""
import struct
import sys
from pathlib import Path

levels = [0] * 32
for line in sys.stdin:
    tick, level = map(int, line.split())
    if not 0 <= tick < 32 or not -30000 <= level <= 30000:
        raise ValueError("Invalid replay event")
    levels[tick:] = [level] * (32 - tick)
samples = []
for frame, level in enumerate(levels):
    pulse = level if frame % 8 < 4 else -level
    samples.extend((pulse, -pulse))
Path("audio.pcm").write_bytes(struct.pack("<64h", *samples))
