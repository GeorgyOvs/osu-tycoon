"""Avatars for the career's world.

Everyone gets a generated identicon (a symmetric pattern from the name, a colour of their own, a gold frame for
legends). A real picture can replace it: put `<name>.png` or `<name>.jpg` into data/avatars/ (case-insensitive),
for your own career or anyone in the world. No image library needed: the PNG is written by hand.
"""
import colorsys
import hashlib
import struct
import zlib
from functools import lru_cache
from pathlib import Path

from app.config import DATA_DIR

AVATAR_DIR = DATA_DIR / "avatars"
SIZE = 128
GRID = 5
GOLD = (232, 186, 66)


def custom_file(name: str) -> Path | None:
    if not AVATAR_DIR.is_dir():
        return None
    wanted = {f"{name.lower()}.png", f"{name.lower()}.jpg", f"{name.lower()}.jpeg"}
    return next((p for p in AVATAR_DIR.iterdir() if p.name.lower() in wanted), None)


def _png(pixels: list[bytes], size: int) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + row for row in pixels)  # filter type 0 per row
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


@lru_cache(maxsize=4096)
def identicon(name: str, legend: bool = False) -> bytes:
    digest = hashlib.sha256(name.lower().encode()).digest()
    hue = digest[0] / 255
    fg = tuple(round(c * 255) for c in colorsys.hls_to_rgb(hue, 0.58, 0.62))
    bg = tuple(round(c * 255) for c in colorsys.hls_to_rgb((hue + 0.5) % 1, 0.16, 0.25))
    # A 5x5 pattern mirrored around the middle column, like GitHub's identicons.
    cells = [[False] * GRID for _ in range(GRID)]
    bit = 0
    for x in range((GRID + 1) // 2):
        for y in range(GRID):
            on = (digest[1 + bit // 8] >> (bit % 8)) & 1 == 1
            cells[y][x] = cells[y][GRID - 1 - x] = on
            bit += 1
    border = 8 if legend else 0
    margin = 14
    cell = (SIZE - 2 * margin) // GRID
    rows = []
    for py in range(SIZE):
        row = bytearray()
        for px in range(SIZE):
            if border and (px < border or py < border or px >= SIZE - border or py >= SIZE - border):
                colour = GOLD
            else:
                gx, gy = (px - margin) // cell, (py - margin) // cell
                inside = 0 <= gx < GRID and 0 <= gy < GRID and px >= margin and py >= margin
                colour = fg if inside and cells[gy][gx] else bg
            row += bytes(colour)
        rows.append(bytes(row))
    return _png(rows, SIZE)


def avatar(name: str, legend: bool = False) -> tuple[bytes, str]:
    """(image bytes, media type) for this player."""
    path = custom_file(name)
    if path is not None:
        return path.read_bytes(), "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return identicon(name, legend), "image/png"
