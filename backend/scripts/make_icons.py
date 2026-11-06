"""Draw the PWA icons. Run from anywhere: python backend/scripts/make_icons.py"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "web" / "assets" / "icons"


def _chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def write_png(path: Path, size: int, pixels: bytes) -> None:
    raw = b"".join(b"\x00" + pixels[y * size * 4 : (y + 1) * size * 4] for y in range(size))
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(raw, 9)) + _chunk(b"IEND", b"")
    path.write_bytes(png)


def paint(size: int) -> bytes:
    buf = bytearray(size * size * 4)
    deep = (6, 49, 74)
    sun = (255, 209, 102)
    cx = (size - 1) / 2
    cy = (size - 1) / 2
    radius = size * 0.42

    def inside_ellipse(x, y, ex, ey, rx, ry) -> bool:
        if rx <= 0 or ry <= 0:
            return False
        dx = (x - ex) / rx
        dy = (y - ey) / ry
        return dx * dx + dy * dy <= 1

    def set_px(x, y, color) -> None:
        if x < 0 or y < 0 or x >= size or y >= size:
            return
        i = (y * size + x) * 4
        buf[i : i + 4] = bytes((*color, 255))

    body_x = cx - size * 0.02
    body_y = cy + size * 0.01
    body_rx = size * 0.16
    body_ry = size * 0.09
    tail = (
        (body_x - body_rx * 0.72, body_y),
        (body_x - body_rx * 1.55, body_y - body_ry * 1.15),
        (body_x - body_rx * 1.55, body_y + body_ry * 1.15),
    )
    eye_x = body_x + body_rx * 0.42
    eye_y = body_y - body_ry * 0.18

    for y in range(size):
        for x in range(size):
            if (x - cx) ** 2 + (y - cy) ** 2 > radius ** 2:
                continue
            set_px(x, y, deep)
            # Tail triangle.
            x1, y1 = tail[0]
            x2, y2 = tail[1]
            x3, y3 = tail[2]
            denom = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
            if denom:
                a = ((y2 - y3) * (x - x3) + (x3 - x2) * (y - y3)) / denom
                b = ((y3 - y1) * (x - x3) + (x1 - x3) * (y - y3)) / denom
                c = 1 - a - b
                if a >= 0 and b >= 0 and c >= 0:
                    set_px(x, y, sun)
            if inside_ellipse(x, y, body_x, body_y, body_rx, body_ry):
                set_px(x, y, sun)
            if inside_ellipse(x, y, eye_x, eye_y, size * 0.028, size * 0.028):
                set_px(x, y, (255, 255, 255))
            if inside_ellipse(x, y, eye_x + size * 0.006, eye_y, size * 0.014, size * 0.014):
                set_px(x, y, deep)
    return bytes(buf)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for size in (192, 512):
        write_png(OUT / f"icon-{size}.png", size, paint(size))
        print(OUT / f"icon-{size}.png")


if __name__ == "__main__":
    main()
