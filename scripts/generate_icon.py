"""Generate desktop/assets/icon.ico — gold 'B' on black, Bloomberg terminal style.

Uses PySide6 for rendering (already a project dependency). No Pillow needed.

Usage:
    python scripts/generate_icon.py
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter


SIZES = [16, 32, 48, 64, 128, 256]
GOLD = QColor("#ffd700")
BLACK = QColor("#000000")
OUTPUT = Path(__file__).resolve().parent.parent / "desktop" / "assets" / "icon.ico"


def render_b(size: int) -> bytes:
    """Render a gold 'B' centred on a black square, return PNG bytes."""
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(BLACK)

    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    font = QFont("Consolas", 1)
    font.setPixelSize(int(size * 0.72))
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(GOLD)
    painter.drawText(img.rect(), Qt.AlignmentFlag.AlignCenter, "B")
    painter.end()

    buf = QByteArray()
    qbuf = QBuffer(buf)
    qbuf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(qbuf, "PNG")
    qbuf.close()
    return bytes(buf.data())


def build_ico(images: list[tuple[int, bytes]]) -> bytes:
    """Compose a multi-size ICO file from (size, png_bytes) pairs."""
    count = len(images)
    header_size = 6
    entry_size = 16
    data_offset = header_size + entry_size * count

    # ICO header: reserved=0, type=1 (icon), count
    header = struct.pack("<HHH", 0, 1, count)

    entries = bytearray()
    payloads = bytearray()
    offset = data_offset

    for size, png in images:
        w = 0 if size >= 256 else size  # 0 means 256 in ICO format
        h = w
        entries += struct.pack(
            "<BBBBHHII",
            w,          # width
            h,          # height
            0,          # colour count (0 = no palette)
            0,          # reserved
            1,          # colour planes
            32,         # bits per pixel
            len(png),   # data size
            offset,     # offset from start of file
        )
        payloads += png
        offset += len(png)

    return bytes(header) + bytes(entries) + bytes(payloads)


def main() -> None:
    app = QGuiApplication(sys.argv)  # noqa: F841 — needed for font rendering

    images = [(size, render_b(size)) for size in SIZES]
    ico_data = build_ico(images)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(ico_data)
    print(f"Written {OUTPUT} ({len(ico_data):,} bytes, {len(SIZES)} sizes)")


if __name__ == "__main__":
    main()
