"""Desktop QSS — built from ``desktop.tokens`` so the app matches the website.

Design language (from ``website/assets/css/theme.css``):

* Pure black backgrounds, hairline white borders.
* Two fonts only: Outfit (sans, body/headings), JetBrains Mono (data,
  kickers, tickers, numbers).
* One accent colour: ``#00ff87`` — used for focus, buy, and primary CTA.
* Red ``#ff3b3b`` for sells / errors, amber ``#ffb020`` for cautions.
* Zero border-radius everywhere. Sharp corners only.
* Panels separated by 1-px hairlines; no thick borders, no double rules.

Paper and live modes are visually identical — the only mode affordance
is the translucent ``PAPER`` watermark painted behind the chart (see
``desktop.widgets.mode_watermark``).
"""
from __future__ import annotations

from desktop import tokens as T


DARK_TERMINAL_QSS = f"""
/* ═══════════════════════════════════════════════════════════════════
   Global
   ═══════════════════════════════════════════════════════════════════ */

* {{
    font-family: {T.FONT_SANS};
    font-size: {T.STEP_2};
    outline: 0;
}}

QMainWindow {{
    background-color: {T.BG_0};
    color: {T.FG_0};
}}

QWidget {{
    background-color: {T.BG_0};
    color: {T.FG_0};
}}

/* ═══════════════════════════════════════════════════════════════════
   Dock Widgets — movable panel containers
   ═══════════════════════════════════════════════════════════════════ */

QDockWidget {{
    color: {T.FG_1};
    font-family: {T.FONT_MONO};
    font-size: {T.STEP_1};
    border: 1px solid {T.BORDER_0};
}}

QDockWidget::title {{
    background-color: {T.BG_1};
    color: {T.FG_1};
    font-family: {T.FONT_MONO};
    font-size: {T.STEP_1};
    letter-spacing: 2px;
    text-transform: uppercase;
    padding: 8px 12px;
    border: none;
    border-bottom: 1px solid {T.BORDER_0};
    text-align: left;
}}

QDockWidget::close-button,
QDockWidget::float-button {{
    background: transparent;
    border: none;
    padding: 2px;
}}

QDockWidget::close-button:hover,
QDockWidget::float-button:hover {{
    background-color: {T.BG_3};
}}

/* Hide QGroupBox titles inside docks — dock title bar is the label */
QDockWidget QGroupBox {{
    margin-top: 2px;
    border-top: none;
}}

QDockWidget QGroupBox::title {{
    color: transparent;
    padding: 0;
    margin: 0;
    font-size: 1px;
    max-height: 0;
}}

/* ═══════════════════════════════════════════════════════════════════
   Panels (QGroupBox) — sharp containers
   ═══════════════════════════════════════════════════════════════════ */

QGroupBox {{
    border: 1px solid {T.BORDER_0};
    border-radius: 0;
    margin-top: 16px;
    padding: 6px 4px 4px 4px;
    background-color: {T.BG_1};
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 2px 8px;
    color: {T.FG_1};
    font-family: {T.FONT_MONO};
    font-size: {T.STEP_0};
    letter-spacing: 2px;
    background-color: {T.BG_0};
}}

/* ═══════════════════════════════════════════════════════════════════
   Data Tables — dense, sharp
   ═══════════════════════════════════════════════════════════════════ */

QTableWidget, QTableView {{
    background-color: {T.BG_0};
    color: {T.FG_0};
    gridline-color: transparent;
    border: none;
    border-radius: 0;
    selection-background-color: {T.ACCENT_DIM};
    selection-color: {T.FG_0};
    alternate-background-color: {T.BG_0};
    font-family: {T.FONT_MONO};
    font-size: {T.STEP_3};
}}

QHeaderView::section {{
    background-color: {T.BG_0};
    color: {T.FG_1};
    font-family: {T.FONT_MONO};
    font-size: {T.STEP_0};
    font-weight: 400;
    letter-spacing: 2px;
    border: none;
    border-bottom: 1px solid {T.BORDER_0};
    padding: 8px 10px;
    text-align: left;
}}

QTableWidget::item, QTableView::item {{
    padding: 6px 10px;
    border: none;
    border-bottom: 1px solid {T.BORDER_0};
}}

QTableWidget::item:selected, QTableView::item:selected {{
    background-color: {T.ACCENT_DIM};
    color: {T.FG_0};
}}

QTableWidget::item:hover, QTableView::item:hover {{
    background-color: {T.BG_2};
}}

/* ═══════════════════════════════════════════════════════════════════
   Labels
   ═══════════════════════════════════════════════════════════════════ */

QLabel {{
    color: {T.FG_0};
    background-color: transparent;
}}

/* ═══════════════════════════════════════════════════════════════════
   Inputs — sharp, dark
   ═══════════════════════════════════════════════════════════════════ */

QLineEdit {{
    background-color: {T.BG_1};
    color: {T.FG_0};
    border: 1px solid {T.BORDER_0};
    border-radius: 0;
    padding: 8px 12px;
    font-family: {T.FONT_MONO};
    font-size: {T.STEP_3};
    selection-background-color: {T.ACCENT_DIM};
    selection-color: {T.FG_0};
}}

QLineEdit:focus {{
    border-color: {T.ACCENT};
}}

QLineEdit:disabled {{
    color: {T.FG_1};
    border-color: {T.BORDER_0};
}}

/* ═══════════════════════════════════════════════════════════════════
   Buttons — default secondary (transparent, hairline, uppercase)

   Contrast rules (do not break):
   * Default / secondary: WHITE text on transparent/dark bg.
   * Primary (green bg): BLACK text, in every state (default/hover/pressed/focus).
   * Danger (red accent): red text default; BLACK text when filled red on hover/pressed.
   * Ghost: WHITE text (60% opacity default, full white on hover/pressed).
   * Disabled: dim white text that's still legible — never fades into the bg.
   ═══════════════════════════════════════════════════════════════════ */

QPushButton {{
    background-color: transparent;
    color: {T.FG_0};
    border: 1px solid {T.BORDER_1};
    border-radius: 0;
    padding: 9px 18px;
    min-height: 22px;
    font-family: {T.FONT_MONO};
    font-size: {T.STEP_1};
    font-weight: 500;
    letter-spacing: 2px;
    text-transform: uppercase;
}}

QPushButton:hover {{
    background-color: {T.BG_3};
    color: {T.FG_0};
    border-color: {T.FG_1};
}}

QPushButton:pressed {{
    background-color: {T.BG_3};
    color: {T.FG_0};
    border-color: {T.ACCENT};
}}

QPushButton:focus {{
    color: {T.FG_0};
    border-color: {T.ACCENT};
}}

QPushButton:disabled {{
    color: {T.FG_2};
    border-color: {T.BORDER_0};
    background-color: transparent;
}}

/* Primary — solid green fill, always BLACK text in every state */
QPushButton[variant="primary"] {{
    background-color: {T.ACCENT};
    color: {T.BG_0};
    border: 1px solid {T.ACCENT};
}}

QPushButton[variant="primary"]:hover {{
    background-color: {T.FG_0};
    color: {T.BG_0};
    border-color: {T.FG_0};
}}

QPushButton[variant="primary"]:pressed {{
    background-color: {T.ACCENT};
    color: {T.BG_0};
    border-color: {T.ACCENT};
}}

QPushButton[variant="primary"]:focus {{
    background-color: {T.ACCENT};
    color: {T.BG_0};
    border: 1px solid {T.BG_0};
}}

QPushButton[variant="primary"]:disabled {{
    background-color: {T.BG_2};
    color: {T.FG_2};
    border-color: {T.BORDER_0};
}}

/* Danger — red outline default, BLACK text when filled */
QPushButton[variant="danger"] {{
    background-color: transparent;
    color: {T.ALERT};
    border-color: rgba(255, 59, 59, 0.45);
}}

QPushButton[variant="danger"]:hover {{
    background-color: {T.ALERT};
    color: {T.BG_0};
    border-color: {T.ALERT};
}}

QPushButton[variant="danger"]:pressed {{
    background-color: {T.ALERT};
    color: {T.BG_0};
    border-color: {T.ALERT};
}}

QPushButton[variant="danger"]:disabled {{
    background-color: transparent;
    color: {T.FG_2};
    border-color: {T.BORDER_0};
}}

/* Ghost — borderless, always legible white text */
QPushButton[variant="ghost"] {{
    border-color: transparent;
    color: {T.FG_0};
    background-color: transparent;
}}

QPushButton[variant="ghost"]:hover {{
    color: {T.FG_0};
    background-color: {T.BG_2};
    border-color: transparent;
}}

QPushButton[variant="ghost"]:pressed {{
    color: {T.FG_0};
    background-color: {T.BG_3};
    border-color: transparent;
}}

QPushButton[variant="ghost"]:disabled {{
    color: {T.FG_2};
    background-color: transparent;
    border-color: transparent;
}}

/* Secondary is an explicit alias of the default look — needed because
   widgets/primitives/button.py::SecondaryButton sets variant="secondary"
   and without a matching selector it would fall through without the
   explicit white-text contract. */
QPushButton[variant="secondary"] {{
    background-color: transparent;
    color: {T.FG_0};
    border: 1px solid {T.BORDER_1};
}}

QPushButton[variant="secondary"]:hover {{
    background-color: {T.BG_3};
    color: {T.FG_0};
    border-color: {T.FG_1};
}}

QPushButton[variant="secondary"]:pressed {{
    background-color: {T.BG_3};
    color: {T.FG_0};
    border-color: {T.ACCENT};
}}

QPushButton[variant="secondary"]:disabled {{
    color: {T.FG_2};
    border-color: {T.BORDER_0};
}}

/* Tool buttons (toolbars, dock title-bar controls) — same contract */
QToolButton {{
    background-color: transparent;
    color: {T.FG_0};
    border: 1px solid transparent;
    padding: 6px 10px;
    font-family: {T.FONT_MONO};
    font-size: {T.STEP_1};
    letter-spacing: 2px;
    text-transform: uppercase;
}}

QToolButton:hover {{
    background-color: {T.BG_3};
    color: {T.FG_0};
    border-color: {T.BORDER_1};
}}

QToolButton:pressed {{
    background-color: {T.BG_3};
    color: {T.FG_0};
    border-color: {T.ACCENT};
}}

QToolButton:checked {{
    background-color: {T.BG_3};
    color: {T.ACCENT};
    border-color: {T.ACCENT};
}}

QToolButton:disabled {{
    color: {T.FG_2};
}}

/* ═══════════════════════════════════════════════════════════════════
   ComboBox
   ═══════════════════════════════════════════════════════════════════ */

QComboBox {{
    background-color: {T.BG_1};
    color: {T.FG_0};
    border: 1px solid {T.BORDER_0};
    border-radius: 0;
    padding: 8px 12px;
    font-family: {T.FONT_MONO};
    font-size: {T.STEP_3};
}}

QComboBox:hover {{
    border-color: {T.BORDER_1};
}}

QComboBox:focus {{
    border-color: {T.ACCENT};
}}

QComboBox::drop-down {{
    border: none;
    width: 16px;
}}

QComboBox QAbstractItemView {{
    background-color: {T.BG_2};
    color: {T.FG_0};
    selection-background-color: {T.ACCENT_DIM};
    selection-color: {T.FG_0};
    border: 1px solid {T.BORDER_0};
    outline: 0;
}}

/* ═══════════════════════════════════════════════════════════════════
   SpinBox
   ═══════════════════════════════════════════════════════════════════ */

QDoubleSpinBox, QSpinBox, QDateTimeEdit, QDateEdit, QTimeEdit {{
    background-color: {T.BG_1};
    color: {T.FG_0};
    border: 1px solid {T.BORDER_0};
    border-radius: 0;
    padding: 8px 12px;
    font-family: {T.FONT_MONO};
    font-size: {T.STEP_3};
}}

QDoubleSpinBox:focus, QSpinBox:focus,
QDateTimeEdit:focus, QDateEdit:focus, QTimeEdit:focus {{
    border-color: {T.ACCENT};
}}

/* ═══════════════════════════════════════════════════════════════════
   ScrollBars — thin, sharp
   ═══════════════════════════════════════════════════════════════════ */

QScrollBar:vertical {{
    background-color: transparent;
    width: 6px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background-color: {T.BORDER_1};
    min-height: 30px;
    border-radius: 0;
}}

QScrollBar::handle:vertical:hover {{
    background-color: {T.FG_2};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
    background: transparent;
}}

QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}

QScrollBar:horizontal {{
    background-color: transparent;
    height: 6px;
    margin: 0;
}}

QScrollBar::handle:horizontal {{
    background-color: {T.BORDER_1};
    min-width: 30px;
    border-radius: 0;
}}

QScrollBar::handle:horizontal:hover {{
    background-color: {T.FG_2};
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
    background: transparent;
}}

QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: transparent;
}}

/* ═══════════════════════════════════════════════════════════════════
   Progress Bars
   ═══════════════════════════════════════════════════════════════════ */

QProgressBar {{
    background-color: {T.BG_2};
    border: 1px solid {T.BORDER_0};
    border-radius: 0;
    text-align: center;
    color: {T.FG_1};
    font-family: {T.FONT_MONO};
    font-size: {T.STEP_0};
    min-height: 4px;
    max-height: 4px;
}}

QProgressBar::chunk {{
    background-color: {T.ACCENT};
}}

/* ═══════════════════════════════════════════════════════════════════
   Dialogs
   ═══════════════════════════════════════════════════════════════════ */

QDialog {{
    background-color: {T.BG_1};
    color: {T.FG_0};
    border: 1px solid {T.BORDER_1};
}}

/* ═══════════════════════════════════════════════════════════════════
   Tab Widget
   ═══════════════════════════════════════════════════════════════════ */

QTabWidget::pane {{
    border: 1px solid {T.BORDER_0};
    background-color: {T.BG_1};
    top: -1px;
}}

QTabBar::tab {{
    background-color: transparent;
    color: {T.FG_1};
    border: 1px solid transparent;
    border-bottom: 1px solid {T.BORDER_0};
    padding: 8px 16px;
    min-width: 80px;
    font-family: {T.FONT_MONO};
    font-size: {T.STEP_1};
    letter-spacing: 2px;
    text-transform: uppercase;
}}

QTabBar::tab:selected {{
    background-color: transparent;
    color: {T.ACCENT};
    border-bottom: 1px solid {T.ACCENT};
}}

QTabBar::tab:hover {{
    color: {T.FG_0};
    background-color: {T.BG_2};
}}

QTabBar::tab:disabled {{
    color: {T.FG_2};
}}

/* ═══════════════════════════════════════════════════════════════════
   Text Edit (chat, news, logs)
   ═══════════════════════════════════════════════════════════════════ */

QTextEdit, QPlainTextEdit {{
    background-color: {T.BG_0};
    color: {T.FG_0};
    border: 1px solid {T.BORDER_0};
    border-radius: 0;
    padding: 12px;
    selection-background-color: {T.ACCENT_DIM};
    selection-color: {T.FG_0};
    font-family: {T.FONT_SANS};
    font-size: {T.STEP_3};
}}

QTextEdit:focus, QPlainTextEdit:focus {{
    border-color: {T.BORDER_1};
}}

/* ═══════════════════════════════════════════════════════════════════
   Status Bar
   ═══════════════════════════════════════════════════════════════════ */

QStatusBar {{
    background-color: {T.BG_0};
    color: {T.FG_1};
    border-top: 1px solid {T.BORDER_0};
    font-family: {T.FONT_MONO};
    font-size: {T.STEP_1};
    letter-spacing: 1px;
}}

QStatusBar::item {{
    border: none;
}}

QStatusBar QLabel {{
    color: {T.FG_1};
}}

/* ═══════════════════════════════════════════════════════════════════
   Menu Bar
   ═══════════════════════════════════════════════════════════════════ */

QMenuBar {{
    background-color: {T.BG_0};
    color: {T.FG_1};
    border-bottom: 1px solid {T.BORDER_0};
    font-family: {T.FONT_MONO};
    font-size: {T.STEP_2};
    letter-spacing: 1px;
}}

QMenuBar::item {{
    padding: 6px 12px;
    background: transparent;
    color: {T.FG_1};
}}

QMenuBar::item:selected {{
    background-color: {T.BG_2};
    color: {T.FG_0};
}}

QMenu {{
    background-color: {T.BG_1};
    color: {T.FG_0};
    border: 1px solid {T.BORDER_1};
    padding: 4px 0;
    font-family: {T.FONT_MONO};
    font-size: {T.STEP_2};
}}

QMenu::item {{
    padding: 7px 22px;
    color: {T.FG_1};
}}

QMenu::item:selected {{
    background-color: {T.BG_3};
    color: {T.ACCENT};
}}

QMenu::item:disabled {{
    color: {T.FG_2};
}}

QMenu::separator {{
    height: 1px;
    background-color: {T.BORDER_0};
    margin: 4px 8px;
}}

/* ═══════════════════════════════════════════════════════════════════
   Tooltips
   ═══════════════════════════════════════════════════════════════════ */

QToolTip {{
    background-color: {T.BG_2};
    color: {T.FG_0};
    border: 1px solid {T.BORDER_1};
    padding: 6px 10px;
    font-family: {T.FONT_MONO};
    font-size: {T.STEP_1};
}}

/* ═══════════════════════════════════════════════════════════════════
   Splitter handle — invisible but draggable
   ═══════════════════════════════════════════════════════════════════ */

QSplitter::handle {{
    background-color: {T.BORDER_0};
}}

QSplitter::handle:horizontal {{
    width: 1px;
}}

QSplitter::handle:vertical {{
    height: 1px;
}}

/* ═══════════════════════════════════════════════════════════════════
   Checkbox / Radio
   ═══════════════════════════════════════════════════════════════════ */

QCheckBox, QRadioButton {{
    color: {T.FG_1};
    spacing: 8px;
    font-family: {T.FONT_SANS};
    font-size: {T.STEP_3};
}}

QCheckBox::indicator, QRadioButton::indicator {{
    width: 14px;
    height: 14px;
    border: 1px solid {T.BORDER_1};
    background-color: transparent;
}}

QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background-color: {T.ACCENT};
    border-color: {T.ACCENT};
}}

QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
    border-color: {T.FG_1};
}}
"""


# ── Colour constants reused by panel code for per-cell colouring ─────

COLORS = {
    # Canonical tokens
    "bg":            T.BG_0,
    "bg_panel":      T.BG_1,
    "bg_raised":     T.BG_2,
    "bg_active":     T.BG_3,
    "text":          T.FG_0,
    "text_mid":      T.FG_1,
    "text_dim":      T.FG_2,
    "text_faint":    T.FG_3,
    "accent":        T.ACCENT,
    "accent_soft":   T.ACCENT_SOFT,
    "accent_dim":    T.ACCENT_DIM,
    "warn":          T.WARN,
    "alert":         T.ALERT,
    "border":        T.BORDER_0,
    "border_strong": T.BORDER_1,

    # Legacy colour keys still referenced by some panels — mapped onto
    # the new palette so the loud terminal look (gold/amber/cyan) is
    # gone and everything reads as one coherent black/white/green UI.
    "gold":        T.FG_0,
    "amber":       T.FG_1_HEX,
    "green":       T.ACCENT,
    "red":         T.ALERT,
    "cyan":        T.FG_1_HEX,
    "white":       T.FG_0,
    "gray":        T.FG_2_HEX,
    "dark_gray":   T.FG_3_HEX,
    "bg_dark":     T.BG_0,
    "bg_input":    T.BG_1,
    "bg_header":   T.BG_1,
    "bg_selected": T.ACCENT_DIM,
}

# Strategy profile colours — collapsed onto the new palette.
STRATEGY_COLORS = {
    "conservative":   T.FG_2_HEX,
    "day_trader":     T.ACCENT,
    "swing":          T.FG_0,
    "crisis_alpha":   T.ALERT,
    "trend_follower": T.FG_1_HEX,
}

# Signal/verdict colours — green for buy, red for sell, white for hold.
SIGNAL_COLORS = {
    "BUY":  T.ACCENT,
    "SELL": T.ALERT,
    "HOLD": T.FG_1_HEX,
}

VERDICT_COLORS = {
    "GREEN":  T.ACCENT,
    "RED":    T.ALERT,
    "ORANGE": T.WARN,
    "AMBER":  T.WARN,
}


# ── Mode overlays ────────────────────────────────────────────────────
# Paper and live are visually identical. The only mode affordance is
# the translucent ``PAPER`` watermark painted behind the chart. Keeping
# these constants around as empty strings so any imports still resolve.

MODE_OVERLAY_STOCKS = ""
MODE_OVERLAY_POLYMARKET = ""

MODE_COLORS = {
    "stocks":     {"accent": T.ACCENT, "header": T.FG_0},
    "polymarket": {"accent": T.ACCENT, "header": T.FG_0},
}
