"""Source-known software scene: apply tick-indexed moves, then capture RGBA."""
import sys
from pathlib import Path

events = [tuple(map(int, line.split())) for line in sys.stdin]
if len(events) > 64 or any(
    len(event) != 3 or not 0 <= event[0] < 16
    or any(not -16 <= delta <= 16 for delta in event[1:])
    for event in events
):
    raise ValueError("Invalid replay event")
x = y = 1
frames = bytearray()
for tick in range(16):
    for when, dx, dy in events:
        if when == tick:
            x, y = max(0, min(14, x + dx)), max(0, min(14, y + dy))
    # The reference describes pixels by their coordinates, independently of C's
    # background fill plus sprite overlay. Rows are stored top to bottom.
    for row in range(16):
        for column in range(16):
            pixel = (240, 80, 20, 255) if x <= column < x + 2 and y <= row < y + 2 else (column * 8, row * 8, 32, 255)
            frames.extend(pixel)
Path("frames.rgba").write_bytes(frames)
Path("final.bin").write_bytes(bytes((x, y)))
