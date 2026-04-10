"""Shared design system for the blank desktop app.

All colours, fonts, and base styles match the blank website (website/index.html).
Every dialog and screen imports from here -- single source of truth.
"""
from __future__ import annotations

# ── Brand ─────────────────────────────────────────────────────────────

APP_NAME = "blank"
APP_NAME_UPPER = "BLANK"
COMPANY = "certified random"
COMPANY_UPPER = "CERTIFIED RANDOM"

# ── Colours ───────────────────────────────────────────────────────────

BG = "#000000"
SURFACE = "#0a0a0a"
TEXT = "#ffffff"
TEXT_MID = "rgba(255,255,255,0.5)"
TEXT_DIM = "rgba(255,255,255,0.2)"
GLOW = "#00ff87"
GLOW_DIM = "rgba(0,255,135,0.06)"
GLOW_MID = "rgba(0,255,135,0.15)"
GLOW_BORDER = "rgba(0,255,135,0.25)"
BORDER = "rgba(255,255,255,0.06)"
BORDER_HOVER = "rgba(255,255,255,0.12)"
RED = "#ff4d4d"
AMBER = "#ffaa00"

# Hex versions for QPainter / QColor (no rgba)
GLOW_HEX = "#00ff87"
TEXT_MID_HEX = "#808080"
TEXT_DIM_HEX = "#333333"
BORDER_HEX = "#0f0f0f"

# ── Font ──────────────────────────────────────────────────────────────

FONT_FAMILY = "'Outfit', 'Segoe UI', sans-serif"

# ── Base QSS ──────────────────────────────────────────────────────────

BASE_QSS = f"""
QWidget {{
    background: {BG};
    color: {TEXT};
    font-family: {FONT_FAMILY};
    font-size: 13px;
}}

QLabel {{
    background: transparent;
    border: none;
    padding: 0;
}}

QPushButton {{
    background: transparent;
    color: {GLOW};
    border: 1px solid {GLOW_BORDER};
    border-radius: 2px;
    padding: 10px 24px;
    font-family: {FONT_FAMILY};
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
QPushButton:disabled {{
    color: {TEXT_DIM};
    border-color: {BORDER};
}}

QLineEdit {{
    background: {SURFACE};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 2px;
    padding: 10px 14px;
    font-family: {FONT_FAMILY};
    font-size: 14px;
    font-weight: 400;
    selection-background-color: {GLOW_MID};
}}
QLineEdit:focus {{
    border-color: {GLOW_BORDER};
}}

QScrollBar:vertical {{
    background: transparent;
    width: 4px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {BORDER_HOVER};
    border-radius: 2px;
    min-height: 20px;
}}
QScrollBar::handle:vertical:hover {{
    background: {TEXT_DIM};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}
"""

# Secondary button style (dim, for "quit" / "skip" buttons)
SECONDARY_BTN_QSS = f"""
QPushButton {{
    color: {TEXT_DIM};
    border-color: {BORDER};
}}
QPushButton:hover {{
    color: {TEXT};
    background: transparent;
    border-color: {BORDER_HOVER};
}}
"""

# Danger button style
DANGER_BTN_QSS = f"""
QPushButton {{
    color: {RED};
    border-color: rgba(255,77,77,0.25);
}}
QPushButton:hover {{
    background: {RED};
    color: {BG};
}}
"""
