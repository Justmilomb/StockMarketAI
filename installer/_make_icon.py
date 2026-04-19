"""Generate desktop/assets/icon.ico from the v3 blank-app-icon SVG."""
from __future__ import annotations

import io
from pathlib import Path

import resvg_py
from PIL import Image

SRC = Path(__file__).parent.parent / "website" / "assets" / "images" / "blank" / "blank-app-icon.svg"
DST = Path(__file__).parent.parent / "desktop" / "assets" / "icon.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def render_png(svg_path: Path, size: int) -> Image.Image:
    png_bytes = bytes(resvg_py.svg_to_bytes(svg_path=str(svg_path), width=size, height=size))
    return Image.open(io.BytesIO(png_bytes)).convert("RGBA")


def main() -> None:
    if not SRC.exists():
        raise SystemExit(f"Source SVG not found: {SRC}")
    images = [render_png(SRC, s) for s in SIZES]
    base = images[-1]
    base.save(DST, format="ICO", sizes=[(s, s) for s in SIZES], append_images=images[:-1])
    print(f"Wrote {DST} ({DST.stat().st_size} bytes) with sizes {SIZES}")


if __name__ == "__main__":
    main()
