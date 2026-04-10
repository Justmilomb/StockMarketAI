"""Simple app theme -- imports from the shared design system."""
from __future__ import annotations

from desktop.design import (
    BG,
    SURFACE,
    TEXT,
    TEXT_MID,
    TEXT_DIM,
    GLOW,
    GLOW_DIM,
    GLOW_MID,
    GLOW_BORDER,
    BORDER,
    BORDER_HOVER,
    RED,
    AMBER,
    FONT_FAMILY,
)

# Backward-compatible COLORS dict for widgets that reference it
COLORS = {
    "bg": BG,
    "surface": SURFACE,
    "border": BORDER,
    "border_hover": BORDER_HOVER,
    "text": TEXT,
    "text_mid": TEXT_MID,
    "text_dim": TEXT_DIM,
    "glow": GLOW,
    "glow_dim": GLOW_DIM,
    "red": RED,
    "amber": AMBER,
}

SIMPLE_QSS = f"""
* {{
    font-family: {FONT_FAMILY};
}}

QMainWindow {{
    background-color: {BG};
}}

QWidget {{
    background-color: {BG};
    color: {TEXT};
}}

QLabel {{
    background: transparent;
    color: {TEXT};
}}

QScrollArea {{
    border: none;
    background: transparent;
}}

QScrollBar:vertical {{
    background: {BG};
    width: 6px;
    border: none;
}}

QScrollBar::handle:vertical {{
    background: {GLOW_DIM};
    border-radius: 3px;
    min-height: 30px;
}}

QScrollBar::handle:vertical:hover {{
    background: {GLOW_MID};
}}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {{
    background: none;
    border: none;
    height: 0px;
}}

QPushButton {{
    background: transparent;
    color: {GLOW};
    border: 1px solid {GLOW_BORDER};
    border-radius: 2px;
    padding: 8px 20px;
    font-size: 13px;
    font-weight: 400;
    letter-spacing: 1px;
}}

QPushButton:hover {{
    background: {GLOW};
    color: {BG};
}}

QPushButton:pressed {{
    background: {GLOW};
    color: {BG};
}}

QLineEdit {{
    background: {SURFACE};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 8px 12px;
    font-size: 14px;
}}

QLineEdit:focus {{
    border-color: {GLOW_BORDER};
}}

QStatusBar {{
    background: {BG};
    color: {TEXT_DIM};
    border-top: 1px solid {BORDER};
    font-size: 12px;
    font-weight: 300;
    padding: 4px 12px;
}}
"""


def signal_color(signal: str) -> str:
    """Return the accent colour for a signal string."""
    s = signal.upper()
    if "BUY" in s:
        return GLOW
    if "SELL" in s:
        return RED
    return AMBER


def change_color(pct: float) -> str:
    """Return green/red/dim for a percentage change."""
    if pct > 0.01:
        return GLOW
    if pct < -0.01:
        return RED
    return TEXT_DIM
