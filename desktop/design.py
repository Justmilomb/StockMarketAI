"""Design constants + base QSS for dialogs.

Thin shim over :mod:`desktop.tokens` — the tokens module is the single
source of truth for the palette (it mirrors ``website/assets/css/theme.css``).
This module re-exports the legacy names so every dialog that imports
from ``desktop.design`` keeps working, and provides the small QSS
snippets (``BASE_QSS``, ``SECONDARY_BTN_QSS``, ``DANGER_BTN_QSS``) used
by the dialog pass.
"""
from __future__ import annotations

from desktop import tokens as T


# ── Brand ─────────────────────────────────────────────────────────────

APP_NAME = "blank"
APP_NAME_UPPER = "blank"
COMPANY = "certified random"
COMPANY_UPPER = "CERTIFIED RANDOM"


# ── Colours (re-exported from tokens) ────────────────────────────────

BG = T.BG_0
SURFACE = T.BG_1
SURFACE_RAISED = T.BG_2
TEXT = T.FG_0
TEXT_MID = T.FG_1
TEXT_DIM = T.FG_2
TEXT_FAINT = T.FG_3
GLOW = T.ACCENT
GLOW_DIM = T.ACCENT_DIM
GLOW_MID = T.ACCENT_SOFT
GLOW_BORDER = T.ACCENT_BORDER
BORDER = T.BORDER_0
BORDER_HOVER = T.BORDER_1
RED = T.ALERT
AMBER = T.WARN

# Hex variants for QPainter / QColor where rgba() strings are not allowed
GLOW_HEX = T.ACCENT_HEX
TEXT_MID_HEX = T.FG_1_HEX
TEXT_DIM_HEX = T.FG_2_HEX
BORDER_HEX = T.BORDER_0_HEX


# ── Fonts ────────────────────────────────────────────────────────────

FONT_FAMILY = T.FONT_SANS
FONT_MONO = T.FONT_MONO


# ── Base QSS — used by dialogs that style themselves in isolation ───

BASE_QSS = f"""
QWidget {{
    background: {T.BG_0};
    color: {T.FG_0};
    font-family: {T.FONT_SANS};
    font-size: {T.STEP_3};
}}

QLabel {{
    background: transparent;
    border: none;
    padding: 0;
}}

QPushButton {{
    background: transparent;
    color: {T.FG_0};
    border: 1px solid {T.BORDER_1};
    border-radius: 0;
    padding: 10px 22px;
    font-family: {T.FONT_MONO};
    font-size: {T.STEP_1};
    letter-spacing: 2px;
    text-transform: uppercase;
}}
QPushButton:hover {{
    background: {T.BG_3};
    color: {T.FG_0};
    border-color: {T.FG_1};
}}
QPushButton:pressed {{
    background: {T.ACCENT};
    color: {T.BG_0};
    border-color: {T.ACCENT};
}}
QPushButton:disabled {{
    color: {T.FG_3};
    border-color: {T.BORDER_0};
}}

QPushButton[variant="primary"] {{
    background: {T.ACCENT};
    color: {T.BG_0};
    border-color: {T.ACCENT};
}}
QPushButton[variant="primary"]:hover {{
    background: {T.FG_0};
    color: {T.BG_0};
    border-color: {T.FG_0};
}}

QLineEdit {{
    background: {T.BG_1};
    color: {T.FG_0};
    border: 1px solid {T.BORDER_0};
    border-radius: 0;
    padding: 10px 14px;
    font-family: {T.FONT_MONO};
    font-size: {T.STEP_3};
    selection-background-color: {T.ACCENT_DIM};
}}
QLineEdit:focus {{
    border-color: {T.ACCENT};
}}

QScrollBar:vertical {{
    background: transparent;
    width: 4px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {T.BORDER_1};
    min-height: 20px;
}}
QScrollBar::handle:vertical:hover {{
    background: {T.FG_2};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}
"""


# Secondary button style (dim, for "quit" / "skip" buttons).
SECONDARY_BTN_QSS = f"""
QPushButton {{
    color: {T.FG_2};
    border-color: {T.BORDER_0};
    background: transparent;
}}
QPushButton:hover {{
    color: {T.FG_0};
    background: transparent;
    border-color: {T.BORDER_1};
}}
"""


# Danger button style.
DANGER_BTN_QSS = f"""
QPushButton {{
    color: {T.ALERT};
    border-color: rgba(255, 59, 59, 0.32);
    background: transparent;
}}
QPushButton:hover {{
    background: {T.ALERT};
    color: {T.BG_0};
    border-color: {T.ALERT};
}}
"""


# Primary CTA style (solid green, black text — matches website .btn-primary).
PRIMARY_BTN_QSS = f"""
QPushButton {{
    background: {T.ACCENT};
    color: {T.BG_0};
    border: 1px solid {T.ACCENT};
}}
QPushButton:hover {{
    background: {T.FG_0};
    color: {T.BG_0};
    border-color: {T.FG_0};
}}
QPushButton:disabled {{
    background: {T.BG_2};
    color: {T.FG_3};
    border-color: {T.BORDER_0};
}}
"""
