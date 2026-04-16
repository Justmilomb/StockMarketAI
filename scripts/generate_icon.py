"""Generate desktop/assets/icon.ico — terminal-style candlestick trio.

Three sharp candlesticks on a black background: a red bearish one,
an amber bullish one (the app's brand colour — same `#ff8c00` used
in the header label), and a green bullish one. Instantly recognisable
as trading, sharp terminal aesthetic, zero rounded edges, no
typographic logo.

Uses PySide6 for rendering (already a project dependency). No Pillow needed.

Usage:
    python scripts/generate_icon.py
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter


SIZES = [16, 32, 48, 64, 128, 256]

BG = QColor("#000000")
RED = QColor("#e53935")      # bearish
AMBER = QColor("#ff8c00")    # brand accent (matches header label)
GREEN = QColor("#43a047")    # bullish
WICK = QColor("#b0b0b0")     # wick grey

OUTPUT = Path(__file__).resolve().parent.parent / "desktop" / "assets" / "icon.ico"


# Per-candle spec: (body_top_pct, body_bot_pct, wick_top_pct, wick_bot_pct, colour)
# Pcts are fractions of canvas height measured from the top.
# Left candle is the shortest bearish bar; middle amber is tall;
# right green is tallest — suggests an upward trend.
CANDLES = [
    (0.42, 0.70, 0.32, 0.78, RED),     # left — red, medium short
    (0.22, 0.74, 0.12, 0.82, AMBER),   # middle — amber, tall (brand)
    (0.14, 0.58, 0.06, 0.88, GREEN),   # right — green, tallest
]


def render_candles(size: int) -> bytes:
    """Render the candlestick trio at ``size`` × ``size`` and return PNG bytes."""
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(BG)

    painter = QPainter(img)
    # Sharp, no anti-alias — pure pixels, terminal style.
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

    margin_x = max(1, int(round(size * 0.12)))
    inner_w = size - 2 * margin_x

    # At very small sizes a 0.14 body would round to 2px and the gap to
    # 4px, which works. At 16px we drop the wicks so the candles stay
    # legible as three clean bars.
    body_w = max(2, int(round(size * 0.14)))
    gap = max(1, (inner_w - 3 * body_w) // 2)
    # Re-derive body width if gap math pushed us past the canvas.
    while 3 * body_w + 2 * gap > inner_w and body_w > 2:
        body_w -= 1
    show_wicks = size >= 32
    wick_w = max(1, size // 48)

    for idx, (body_top, body_bot, wick_top, wick_bot, colour) in enumerate(CANDLES):
        x = margin_x + idx * (body_w + gap)
        cx = x + body_w // 2 - wick_w // 2

        if show_wicks:
            wy = int(round(size * wick_top))
            wh = max(1, int(round(size * (wick_bot - wick_top))))
            painter.fillRect(cx, wy, wick_w, wh, WICK)

        by = int(round(size * body_top))
        bh = max(1, int(round(size * (body_bot - body_top))))
        painter.fillRect(x, by, body_w, bh, colour)

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
    app = QGuiApplication(sys.argv)  # noqa: F841 — needed for QPainter

    images = [(size, render_candles(size)) for size in SIZES]
    ico_data = build_ico(images)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(ico_data)
    print(f"Written {OUTPUT} ({len(ico_data):,} bytes, {len(SIZES)} sizes)")


if __name__ == "__main__":
    main()
