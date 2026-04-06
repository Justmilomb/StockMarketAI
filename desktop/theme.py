"""Bloomberg terminal dark theme — sharp, dense, monospace.

Pure black backgrounds, bright terminal colours, 0px border-radius,
Consolas monospace everywhere. Designed for information density.
"""

BLOOMBERG_DARK_QSS = """
/* ═══════════════════════════════════════════════════════════════════
   Global
   ═══════════════════════════════════════════════════════════════════ */

* {
    font-family: "Consolas", "Cascadia Mono", "Courier New", monospace;
    font-size: 12px;
}

QMainWindow {
    background-color: #000000;
    color: #ff8c00;
}

QWidget {
    background-color: #000000;
    color: #ffd700;
}

/* ═══════════════════════════════════════════════════════════════════
   Dock Widgets — movable panel containers
   ═══════════════════════════════════════════════════════════════════ */

QDockWidget {
    color: #ff8c00;
    font-weight: bold;
    font-size: 11px;
    border: 1px solid #333333;
}

QDockWidget::title {
    background-color: #1a1a1a;
    color: #ff8c00;
    padding: 3px 6px;
    border-bottom: 1px solid #333333;
    text-align: left;
}

QDockWidget::close-button, QDockWidget::float-button {
    background: transparent;
    border: none;
    padding: 2px;
}

QDockWidget::close-button:hover, QDockWidget::float-button:hover {
    background-color: #333333;
}

/* Hide QGroupBox titles inside docks — dock title bar is the label */
QDockWidget QGroupBox {
    margin-top: 2px;
    border-top: none;
}

QDockWidget QGroupBox::title {
    color: transparent;
    padding: 0px;
    margin: 0px;
    font-size: 1px;
    max-height: 0px;
}

/* ═══════════════════════════════════════════════════════════════════
   Panels (QGroupBox) — sharp containers
   ═══════════════════════════════════════════════════════════════════ */

QGroupBox {
    border: 1px solid #333333;
    border-radius: 0px;
    margin-top: 14px;
    padding: 4px 2px 2px 2px;
    background-color: #0a0a0a;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 1px 6px;
    color: #ff8c00;
    font-weight: bold;
    font-size: 10px;
    background-color: #0a0a0a;
}

/* ═══════════════════════════════════════════════════════════════════
   Data Tables — dense, sharp
   ═══════════════════════════════════════════════════════════════════ */

QTableWidget {
    background-color: #000000;
    color: #ffd700;
    gridline-color: #222222;
    border: 1px solid #333333;
    border-radius: 0px;
    selection-background-color: #1a2a3a;
    selection-color: #ffffff;
    alternate-background-color: #0a0a0a;
}

QHeaderView::section {
    background-color: #1a1a1a;
    color: #ff8c00;
    font-weight: bold;
    font-size: 10px;
    border: none;
    border-right: 1px solid #333333;
    border-bottom: 1px solid #333333;
    padding: 3px 4px;
}

QTableWidget::item {
    padding: 1px 4px;
    border: none;
}

QTableWidget::item:selected {
    background-color: #1a2a3a;
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

/* ═══════════════════════════════════════════════════════════════════
   Inputs — sharp, dark
   ═══════════════════════════════════════════════════════════════════ */

QLineEdit {
    background-color: #111111;
    color: #ffffff;
    border: 1px solid #444444;
    border-radius: 0px;
    padding: 3px 6px;
}

QLineEdit:focus {
    border-color: #ff8c00;
}

/* ═══════════════════════════════════════════════════════════════════
   Buttons — sharp, dense
   ═══════════════════════════════════════════════════════════════════ */

QPushButton {
    background-color: #1a1a1a;
    color: #ff8c00;
    border: 1px solid #444444;
    border-radius: 0px;
    padding: 4px 10px;
    min-height: 20px;
    font-weight: bold;
}

QPushButton:hover {
    background-color: #2a2a2a;
    border-color: #ff8c00;
}

QPushButton:pressed {
    background-color: #333333;
}

QPushButton:disabled {
    color: #444444;
    border-color: #222222;
    background-color: #0a0a0a;
}

/* ═══════════════════════════════════════════════════════════════════
   ComboBox
   ═══════════════════════════════════════════════════════════════════ */

QComboBox {
    background-color: #111111;
    color: #ffffff;
    border: 1px solid #444444;
    border-radius: 0px;
    padding: 3px 6px;
}

QComboBox:hover {
    border-color: #ff8c00;
}

QComboBox::drop-down {
    border: none;
    width: 16px;
}

QComboBox QAbstractItemView {
    background-color: #111111;
    color: #ffffff;
    selection-background-color: #1a2a3a;
    selection-color: #ffffff;
    border: 1px solid #333333;
}

/* ═══════════════════════════════════════════════════════════════════
   SpinBox
   ═══════════════════════════════════════════════════════════════════ */

QDoubleSpinBox, QSpinBox {
    background-color: #111111;
    color: #ffffff;
    border: 1px solid #444444;
    border-radius: 0px;
    padding: 3px 6px;
}

/* ═══════════════════════════════════════════════════════════════════
   ScrollBars — thin, sharp
   ═══════════════════════════════════════════════════════════════════ */

QScrollBar:vertical {
    background-color: #0a0a0a;
    width: 10px;
    margin: 0;
}

QScrollBar::handle:vertical {
    background-color: #333333;
    min-height: 20px;
}

QScrollBar::handle:vertical:hover {
    background-color: #444444;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar:horizontal {
    background-color: #0a0a0a;
    height: 10px;
    margin: 0;
}

QScrollBar::handle:horizontal {
    background-color: #333333;
    min-width: 20px;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}

/* ═══════════════════════════════════════════════════════════════════
   Progress Bars
   ═══════════════════════════════════════════════════════════════════ */

QProgressBar {
    background-color: #1a1a1a;
    border: 1px solid #333333;
    border-radius: 0px;
    text-align: center;
    color: #ffd700;
    min-height: 12px;
    max-height: 12px;
}

QProgressBar::chunk {
    background-color: #00bfff;
}

/* ═══════════════════════════════════════════════════════════════════
   Dialogs
   ═══════════════════════════════════════════════════════════════════ */

QDialog {
    background-color: #0a0a0a;
    color: #ffd700;
    border: 1px solid #444444;
}

/* ═══════════════════════════════════════════════════════════════════
   Tab Widget
   ═══════════════════════════════════════════════════════════════════ */

QTabWidget::pane {
    border: 1px solid #333333;
    background-color: #0a0a0a;
}

QTabBar::tab {
    background-color: #111111;
    color: #888888;
    border: 1px solid #333333;
    border-bottom: none;
    padding: 4px 12px;
    min-width: 60px;
}

QTabBar::tab:selected {
    background-color: #0a0a0a;
    color: #ff8c00;
    border-bottom: 2px solid #ff8c00;
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
    border: 1px solid #333333;
    selection-background-color: #1a2a3a;
    selection-color: #ffffff;
}

/* ═══════════════════════════════════════════════════════════════════
   Status Bar
   ═══════════════════════════════════════════════════════════════════ */

QStatusBar {
    background-color: #0a0a0a;
    color: #ff8c00;
    border-top: 1px solid #333333;
    font-size: 11px;
}

QStatusBar::item {
    border: none;
}

/* ═══════════════════════════════════════════════════════════════════
   Menu Bar
   ═══════════════════════════════════════════════════════════════════ */

QMenuBar {
    background-color: #0a0a0a;
    color: #ff8c00;
    border-bottom: 1px solid #333333;
}

QMenuBar::item {
    padding: 4px 8px;
}

QMenuBar::item:selected {
    background-color: #1a1a1a;
}

QMenu {
    background-color: #111111;
    color: #ffd700;
    border: 1px solid #333333;
    padding: 2px;
}

QMenu::item {
    padding: 4px 16px;
}

QMenu::item:selected {
    background-color: #1a2a3a;
}

QMenu::separator {
    height: 1px;
    background-color: #333333;
    margin: 2px 4px;
}

/* ═══════════════════════════════════════════════════════════════════
   Tooltips
   ═══════════════════════════════════════════════════════════════════ */

QToolTip {
    background-color: #1a1a1a;
    color: #ffd700;
    border: 1px solid #333333;
    padding: 4px;
}
"""

# Colour constants reused by panel code for per-cell colouring
COLORS = {
    "gold": "#ffd700",
    "amber": "#ff8c00",
    "green": "#00ff00",
    "red": "#ff0000",
    "cyan": "#00bfff",
    "white": "#ffffff",
    "gray": "#888888",
    "dark_gray": "#555555",
    "bg_dark": "#000000",
    "bg_panel": "#0a0a0a",
    "bg_input": "#111111",
    "bg_header": "#1a1a1a",
    "bg_selected": "#1a2a3a",
    "border": "#333333",
}

# Strategy profile colours
STRATEGY_COLORS = {
    "conservative": "#888888",
    "day_trader": "#00ff00",
    "swing": "#ffd700",
    "crisis_alpha": "#ff0000",
    "trend_follower": "#00bfff",
}

# Signal/verdict colours
SIGNAL_COLORS = {
    "BUY": "#00ff00",
    "SELL": "#ff0000",
    "HOLD": "#ffd700",
}

VERDICT_COLORS = {
    "GREEN": "#00ff00",
    "RED": "#ff0000",
    "ORANGE": "#ff8c00",
    "AMBER": "#ffd700",
}
