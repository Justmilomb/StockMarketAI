"""Deterministic avatar generator for blank.

Produces 100 unique 256x256 SVG avatars under this directory, named
``avatar_001.svg`` .. ``avatar_100.svg``. Each avatar is a black
background with a single green accent (#00ff87) design drawn from one of
ten style families (10 variations each).

Run manually whenever the catalogue changes:

    python desktop/assets/avatars/_generate.py

The server bundles these at request time; the desktop app ships them as
data files via PyInstaller.
"""
from __future__ import annotations

import math
import random
from pathlib import Path

W = H = 256
BG = "#000000"
FG = "#00ff87"
OUT = Path(__file__).parent


def _rng(seed: int) -> random.Random:
    return random.Random(seed)


def _wrap(body: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
        f'width="{W}" height="{H}">'
        f'<rect width="{W}" height="{H}" fill="{BG}"/>'
        f"{body}"
        "</svg>\n"
    )


# ── Style 1: concentric rings ─────────────────────────────────────
def _rings(seed: int) -> str:
    r = _rng(seed)
    count = r.randint(3, 7)
    parts = []
    for i in range(count):
        radius = 20 + i * (90 // count)
        stroke = 1 + (i % 3)
        opacity = 0.3 + (i / count) * 0.7
        parts.append(
            f'<circle cx="128" cy="128" r="{radius}" fill="none" '
            f'stroke="{FG}" stroke-width="{stroke}" opacity="{opacity:.2f}"/>'
        )
    return "".join(parts)


# ── Style 2: rotated triangle stack ──────────────────────────────
def _triangles(seed: int) -> str:
    r = _rng(seed)
    count = r.randint(2, 5)
    parts = []
    for i in range(count):
        rot = r.randint(0, 360)
        scale = 0.5 + i * 0.2
        opacity = 0.25 + (i / count) * 0.75
        size = 60 * scale
        parts.append(
            f'<polygon points="128,{128 - size} {128 - size},{128 + size * 0.5} '
            f'{128 + size},{128 + size * 0.5}" fill="none" stroke="{FG}" '
            f'stroke-width="2" opacity="{opacity:.2f}" '
            f'transform="rotate({rot} 128 128)"/>'
        )
    return "".join(parts)


# ── Style 3: dot grid ────────────────────────────────────────────
def _dotgrid(seed: int) -> str:
    r = _rng(seed)
    step = r.choice([24, 32, 40])
    radius = r.choice([2, 3, 4])
    parts = []
    start = (W - ((W // step) - 1) * step) // 2
    for row in range(W // step):
        for col in range(W // step):
            cx = start + col * step
            cy = start + row * step
            # Random opacity pattern for "unique" feel.
            opacity = 0.2 + r.random() * 0.8
            parts.append(
                f'<circle cx="{cx}" cy="{cy}" r="{radius}" fill="{FG}" '
                f'opacity="{opacity:.2f}"/>'
            )
    return "".join(parts)


# ── Style 4: monogram ────────────────────────────────────────────
def _monogram(seed: int) -> str:
    r = _rng(seed)
    letter = chr(ord("A") + (seed % 26))
    size = r.choice([110, 130, 150])
    weight = r.choice([300, 500, 700])
    # Box around letter for definition.
    box = ""
    if r.random() < 0.4:
        box = (
            f'<rect x="40" y="40" width="176" height="176" fill="none" '
            f'stroke="{FG}" stroke-width="1.5" opacity="0.5"/>'
        )
    return (
        box
        + f'<text x="128" y="128" text-anchor="middle" dominant-baseline="central" '
        f'font-family="Helvetica, Arial, sans-serif" font-size="{size}" '
        f'font-weight="{weight}" fill="{FG}">{letter}</text>'
    )


# ── Style 5: line bars (like a tiny chart) ───────────────────────
def _bars(seed: int) -> str:
    r = _rng(seed)
    count = r.choice([8, 12, 16, 20])
    gap = 2
    total_w = 176
    bar_w = (total_w - gap * (count - 1)) / count
    parts = []
    for i in range(count):
        h = 20 + r.random() * 140
        x = 40 + i * (bar_w + gap)
        y = 128 - h / 2
        opacity = 0.4 + r.random() * 0.6
        parts.append(
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_w:.2f}" '
            f'height="{h:.2f}" fill="{FG}" opacity="{opacity:.2f}"/>'
        )
    return "".join(parts)


# ── Style 6: crosshatch / lines ──────────────────────────────────
def _crosshatch(seed: int) -> str:
    r = _rng(seed)
    angle = r.choice([30, 45, 60, 90, 120, 135])
    step = r.choice([10, 14, 18])
    parts = []
    for i in range(-W, W * 2, step):
        opacity = 0.25 + (r.random() * 0.6)
        parts.append(
            f'<line x1="{i}" y1="0" x2="{i}" y2="{H}" stroke="{FG}" '
            f'stroke-width="1.5" opacity="{opacity:.2f}"/>'
        )
    body = f'<g transform="rotate({angle} 128 128)">{"".join(parts)}</g>'
    return body


# ── Style 7: sine wave layers ────────────────────────────────────
def _waves(seed: int) -> str:
    r = _rng(seed)
    count = r.choice([2, 3, 4])
    parts = []
    for i in range(count):
        freq = 0.02 + r.random() * 0.04
        amp = 20 + r.random() * 30
        offset = 60 + i * (140 / count)
        pts = []
        for x in range(0, W + 4, 4):
            y = offset + amp * math.sin(freq * x + i * 0.8)
            pts.append(f"{x},{y:.2f}")
        opacity = 0.4 + (i / count) * 0.6
        parts.append(
            f'<polyline points="{" ".join(pts)}" fill="none" stroke="{FG}" '
            f'stroke-width="2" opacity="{opacity:.2f}"/>'
        )
    return "".join(parts)


# ── Style 8: hexagon / polygon ring ──────────────────────────────
def _polygon(seed: int) -> str:
    r = _rng(seed)
    sides = r.choice([5, 6, 7, 8])
    count = r.randint(2, 4)
    parts = []
    for i in range(count):
        radius = 40 + i * 30
        rot = r.randint(0, 360)
        pts = []
        for k in range(sides):
            theta = math.radians(rot + k * 360 / sides)
            x = 128 + radius * math.cos(theta)
            y = 128 + radius * math.sin(theta)
            pts.append(f"{x:.2f},{y:.2f}")
        opacity = 0.35 + (i / count) * 0.6
        parts.append(
            f'<polygon points="{" ".join(pts)}" fill="none" stroke="{FG}" '
            f'stroke-width="2" opacity="{opacity:.2f}"/>'
        )
    return "".join(parts)


# ── Style 9: plus / cross glyphs ─────────────────────────────────
def _crosses(seed: int) -> str:
    r = _rng(seed)
    count_x = r.choice([3, 4, 5])
    size = 180 // count_x
    arm = size // 3
    parts = []
    pad = (W - count_x * size) // 2
    for row in range(count_x):
        for col in range(count_x):
            cx = pad + col * size + size / 2
            cy = pad + row * size + size / 2
            opacity = 0.3 + r.random() * 0.7
            parts.append(
                f'<line x1="{cx - arm}" y1="{cy}" x2="{cx + arm}" y2="{cy}" '
                f'stroke="{FG}" stroke-width="2" opacity="{opacity:.2f}"/>'
                f'<line x1="{cx}" y1="{cy - arm}" x2="{cx}" y2="{cy + arm}" '
                f'stroke="{FG}" stroke-width="2" opacity="{opacity:.2f}"/>'
            )
    return "".join(parts)


# ── Style 10: abstract face ──────────────────────────────────────
def _face(seed: int) -> str:
    r = _rng(seed)
    head_r = 70 + r.randint(-10, 10)
    eye_y = 110 + r.randint(-10, 10)
    eye_gap = 24 + r.randint(-6, 8)
    mouth_style = r.choice(["line", "arc", "dot"])
    eye_shape = r.choice(["dot", "line", "square"])
    # Head
    parts = [
        f'<circle cx="128" cy="128" r="{head_r}" fill="none" stroke="{FG}" '
        f'stroke-width="2" opacity="0.85"/>'
    ]
    # Eyes
    for sign in (-1, 1):
        ex = 128 + sign * eye_gap
        if eye_shape == "dot":
            parts.append(f'<circle cx="{ex}" cy="{eye_y}" r="4" fill="{FG}"/>')
        elif eye_shape == "line":
            parts.append(
                f'<line x1="{ex - 6}" y1="{eye_y}" x2="{ex + 6}" y2="{eye_y}" '
                f'stroke="{FG}" stroke-width="3"/>'
            )
        else:  # square
            parts.append(
                f'<rect x="{ex - 4}" y="{eye_y - 4}" width="8" height="8" fill="{FG}"/>'
            )
    # Mouth
    my = 152 + r.randint(-6, 12)
    if mouth_style == "line":
        parts.append(
            f'<line x1="108" y1="{my}" x2="148" y2="{my}" stroke="{FG}" '
            f'stroke-width="2"/>'
        )
    elif mouth_style == "arc":
        parts.append(
            f'<path d="M108 {my} Q128 {my + 14} 148 {my}" fill="none" '
            f'stroke="{FG}" stroke-width="2"/>'
        )
    else:  # dot
        parts.append(f'<circle cx="128" cy="{my}" r="3" fill="{FG}"/>')
    return "".join(parts)


STYLES = [
    _rings, _triangles, _dotgrid, _monogram, _bars,
    _crosshatch, _waves, _polygon, _crosses, _face,
]


def main() -> None:
    for i in range(1, 101):
        style = STYLES[(i - 1) // 10]  # 10 per style
        # Seed varies within each style for uniqueness.
        body = style(seed=i * 101 + 7)
        path = OUT / f"avatar_{i:03d}.svg"
        path.write_text(_wrap(body), encoding="utf-8")
    print(f"Wrote 100 avatars to {OUT}")


if __name__ == "__main__":
    main()
