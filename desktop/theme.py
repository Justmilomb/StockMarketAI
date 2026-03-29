"""Bloomberg-dark QSS theme for the PySide6 desktop app.

Translates the Textual terminal.css aesthetic into Qt Style Sheets.
Colours: black background, gold/amber text, green/red for signals.
"""

BLOOMBERG_DARK_QSS = """
/* ═══════════════════════════════════════════════════════════════════
   Global
   ═══════════════════════════════════════════════════════════════════ */

QMainWindow {
    background-color: #000000;
    color: #ffd700;
}

QWidget {
    background-color: #000000;
    color: #ffd700;
    font-family: "Consolas", "Cascadia Mono", "Courier New", monospace;
    font-size: 12px;
}

/* ═══════════════════════════════════════════════════════════════════
   Panels — bordered containers
   ═══════════════════════════════════════════════════════════════════ */

QGroupBox {
    border: 1px solid #444444;
    border-radius: 0px;
    margin-top: 14px;
    padding: 8px 4px 4px 4px;
    background-color: #000000;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top center;
    padding: 0 6px;
    color: #ffb000;
    font-weight: bold;
    background-color: #000000;
}

/* ═══════════════════════════════════════════════════════════════════
   Data Tables
   ═══════════════════════════════════════════════════════════════════ */

QTableWidget {
    background-color: #000000;
    color: #ffd700;
    gridline-color: #1a1a1a;
    border: none;
    selection-background-color: #333333;
    selection-color: #ffffff;
    alternate-background-color: #0a0a0a;
}

QHeaderView::section {
    background-color: #1a1a1a;
    color: #ffb000;
    font-weight: bold;
    border: none;
    border-bottom: 1px solid #444444;
    padding: 4px 6px;
}

QTableWidget::item {
    padding: 2px 6px;
    border: none;
}

QTableWidget::item:selected {
    background-color: #333333;
    color: #ffffff;
}

QTableWidget::item:hover {
    background-color: #111111;
}

/* ═══════════════════════════════════════════════════════════════════
   Labels
   ═══════════════════════════════════════════════════════════════════ */

QLabel {
    color: #ffd700;
    background-color: transparent;
}

QLabel[panelTitle="true"] {
    color: #ffb000;
    font-weight: bold;
    border-bottom: 1px solid #444444;
    padding-bottom: 4px;
    margin-bottom: 4px;
}

/* ═══════════════════════════════════════════════════════════════════
   Inputs
   ═══════════════════════════════════════════════════════════════════ */

QLineEdit {
    background-color: #111111;
    color: #ffffff;
    border: 1px solid #444444;
    border-radius: 0px;
    padding: 4px 8px;
}

QLineEdit:focus {
    border-color: #ffb000;
}

/* ═══════════════════════════════════════════════════════════════════
   Buttons
   ═══════════════════════════════════════════════════════════════════ */

QPushButton {
    background-color: #1a1a1a;
    color: #ffb000;
    border: 1px solid #444444;
    border-radius: 0px;
    padding: 4px 12px;
    min-height: 22px;
}

QPushButton:hover {
    background-color: #333333;
    border-color: #ffb000;
}

QPushButton:pressed {
    background-color: #444444;
}

QPushButton:disabled {
    color: #666666;
    border-color: #333333;
}

/* ═══════════════════════════════════════════════════════════════════
   ComboBox / Select
   ═══════════════════════════════════════════════════════════════════ */

QComboBox {
    background-color: #111111;
    color: #ffffff;
    border: 1px solid #444444;
    padding: 4px 8px;
}

QComboBox:hover {
    border-color: #ffb000;
}

QComboBox::drop-down {
    border: none;
    width: 20px;
}

QComboBox QAbstractItemView {
    background-color: #111111;
    color: #ffffff;
    selection-background-color: #333333;
    selection-color: #ffffff;
    border: 1px solid #444444;
}

/* ═══════════════════════════════════════════════════════════════════
   SpinBox
   ═══════════════════════════════════════════════════════════════════ */

QDoubleSpinBox, QSpinBox {
    background-color: #111111;
    color: #ffffff;
    border: 1px solid #444444;
    padding: 4px 8px;
}

/* ═══════════════════════════════════════════════════════════════════
   ScrollBars (thin, dark)
   ═══════════════════════════════════════════════════════════════════ */

QScrollBar:vertical {
    background-color: #0a0a0a;
    width: 8px;
    margin: 0;
}

QScrollBar::handle:vertical {
    background-color: #333333;
    min-height: 20px;
    border-radius: 4px;
}

QScrollBar::handle:vertical:hover {
    background-color: #555555;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar:horizontal {
    background-color: #0a0a0a;
    height: 8px;
    margin: 0;
}

QScrollBar::handle:horizontal {
    background-color: #333333;
    min-width: 20px;
    border-radius: 4px;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}

/* ═══════════════════════════════════════════════════════════════════
   Progress Bars (pipeline)
   ═══════════════════════════════════════════════════════════════════ */

QProgressBar {
    background-color: #1a1a1a;
    border: 1px solid #333333;
    border-radius: 0px;
    text-align: center;
    color: #ffd700;
    min-height: 14px;
    max-height: 14px;
}

QProgressBar::chunk {
    background-color: #00bfff;
}

/* ═══════════════════════════════════════════════════════════════════
   Dialogs
   ═══════════════════════════════════════════════════════════════════ */

QDialog {
    background-color: #111111;
    color: #ffd700;
    border: 1px solid #ffb000;
}

/* ═══════════════════════════════════════════════════════════════════
   Tab Widget
   ═══════════════════════════════════════════════════════════════════ */

QTabWidget::pane {
    border: 1px solid #444444;
    background-color: #000000;
}

QTabBar::tab {
    background-color: #111111;
    color: #888888;
    border: 1px solid #444444;
    border-bottom: none;
    padding: 6px 16px;
    min-width: 80px;
}

QTabBar::tab:selected {
    background-color: #000000;
    color: #ffb000;
    border-bottom: 2px solid #ffb000;
}

QTabBar::tab:hover {
    background-color: #1a1a1a;
    color: #ffd700;
}

/* ═══════════════════════════════════════════════════════════════════
   Text Edit (chat, news)
   ═══════════════════════════════════════════════════════════════════ */

QTextEdit {
    background-color: #000000;
    color: #ffd700;
    border: none;
    selection-background-color: #333333;
    selection-color: #ffffff;
}

/* ═══════════════════════════════════════════════════════════════════
   Status Bar
   ═══════════════════════════════════════════════════════════════════ */

QStatusBar {
    background-color: #0a0a0a;
    color: #ffb000;
    border-top: 1px solid #333333;
    font-size: 11px;
}

QStatusBar::item {
    border: none;
}

/* ═══════════════════════════════════════════════════════════════════
   Menu Bar (if used later)
   ═══════════════════════════════════════════════════════════════════ */

QMenuBar {
    background-color: #0a0a0a;
    color: #ffb000;
    border-bottom: 1px solid #333333;
}

QMenuBar::item:selected {
    background-color: #333333;
}

QMenu {
    background-color: #111111;
    color: #ffd700;
    border: 1px solid #444444;
}

QMenu::item:selected {
    background-color: #333333;
}

/* ═══════════════════════════════════════════════════════════════════
   Tooltips
   ═══════════════════════════════════════════════════════════════════ */

QToolTip {
    background-color: #1a1a1a;
    color: #ffd700;
    border: 1px solid #444444;
    padding: 4px;
}
"""

# Colour constants reused by panel code for per-cell colouring
COLORS = {
    "gold": "#ffd700",
    "amber": "#ffb000",
    "green": "#00ff00",
    "red": "#ff0000",
    "cyan": "#00bfff",
    "white": "#ffffff",
    "gray": "#888888",
    "dark_gray": "#666666",
    "bg_dark": "#000000",
    "bg_panel": "#0a0a0a",
    "bg_input": "#111111",
    "bg_header": "#1a1a1a",
    "bg_selected": "#333333",
    "border": "#444444",
}

# Strategy profile colours (matching terminal/views.py)
STRATEGY_COLORS = {
    "conservative": "#888888",
    "day_trader": "#00cccc",
    "swing": "#cccc00",
    "crisis_alpha": "#ff4444",
    "trend_follower": "#00cc00",
}

# Signal/verdict colours
SIGNAL_COLORS = {
    "BUY": "#00ff00",
    "SELL": "#ff0000",
    "HOLD": "#ffb000",
}

VERDICT_COLORS = {
    "GREEN": "#00ff00",
    "RED": "#ff0000",
    "ORANGE": "#ff8c00",
    "AMBER": "#ffb000",
}
