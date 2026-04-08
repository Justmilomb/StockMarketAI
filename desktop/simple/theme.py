"""Simple app theme — matches the website's clean, minimal aesthetic."""
from __future__ import annotations

# Colour palette (mirrors website/index.html CSS variables)
COLORS = {
    "bg": "#000000",
    "surface": "#0a0a0a",
    "border": "rgba(255, 255, 255, 0.06)",
    "border_hover": "rgba(255, 255, 255, 0.12)",
    "text": "#ffffff",
    "text_mid": "rgba(255, 255, 255, 0.5)",
    "text_dim": "rgba(255, 255, 255, 0.2)",
    "glow": "#00ff87",
    "glow_dim": "rgba(0, 255, 135, 0.08)",
    "red": "#ff4d4d",
    "amber": "#ffaa00",
}

SIMPLE_QSS = """
* {
    font-family: "Outfit", "Segoe UI", sans-serif;
}

QMainWindow {
    background-color: #000000;
}

QWidget {
    background-color: #000000;
    color: #ffffff;
}

QLabel {
    background: transparent;
    color: #ffffff;
}

QScrollArea {
    border: none;
    background: transparent;
}

QScrollBar:vertical {
    background: #000000;
    width: 6px;
    border: none;
}

QScrollBar::handle:vertical {
    background: rgba(255, 255, 255, 0.08);
    border-radius: 3px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background: rgba(255, 255, 255, 0.15);
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: none;
    border: none;
    height: 0px;
}

QPushButton {
    background: transparent;
    color: #00ff87;
    border: 1px solid rgba(0, 255, 135, 0.25);
    border-radius: 2px;
    padding: 8px 20px;
    font-size: 13px;
    font-weight: 400;
    letter-spacing: 1px;
}

QPushButton:hover {
    background: #00ff87;
    color: #000000;
}

QPushButton:pressed {
    background: rgba(0, 255, 135, 0.8);
    color: #000000;
}

QLineEdit {
    background: #0a0a0a;
    color: #ffffff;
    border: 1px solid rgba(255, 255, 255, 0.06);
    padding: 8px 12px;
    font-size: 14px;
}

QLineEdit:focus {
    border-color: rgba(0, 255, 135, 0.25);
}

QStatusBar {
    background: #000000;
    color: rgba(255, 255, 255, 0.2);
    border-top: 1px solid rgba(255, 255, 255, 0.06);
    font-size: 12px;
    font-weight: 300;
    padding: 4px 12px;
}
"""
"""

Signal colour helpers.
"""


def signal_color(signal: str) -> str:
    """Return the accent colour for a signal string."""
    s = signal.upper()
    if "BUY" in s:
        return COLORS["glow"]
    if "SELL" in s:
        return COLORS["red"]
    return COLORS["amber"]


def change_color(pct: float) -> str:
    """Return green/red/dim for a percentage change."""
    if pct > 0.01:
        return COLORS["glow"]
    if pct < -0.01:
        return COLORS["red"]
    return COLORS["text_dim"]
