"""Help dialog — keybinding reference (non-modal, stays on top)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFrame, QLabel, QPushButton, QVBoxLayout

from desktop import tokens as T


_SHORTCUTS: list[tuple[str, str]] = [
    ("?", "Show this help"),
    ("Q", "Quit"),
    ("R", "Refresh data"),
    ("A", "Toggle mode (Advisor / Auto)"),
    ("W", "Cycle watchlist"),
    ("S", "advisor suggest ticker"),
    ("I", "generate advisor insights"),
    ("N", "Refresh news"),
    ("C", "Focus chat input"),
    ("G", "Show chart for selected ticker"),
    ("T", "Open trade dialog"),
    ("=", "Add ticker to watchlist"),
    ("-", "Remove ticker from watchlist"),
    ("/", "Search tickers"),
    ("D", "advisor recommendations"),
    ("O", "advisor optimise config"),
    ("H", "Show account history"),
    ("P", "Show investment pies"),
    ("E", "Browse instruments"),
    ("L", "Lock/unlock ticker"),
    ("B", "About blank"),
]


def _build_html() -> str:
    rows = "".join(
        f'<tr>'
        f'<td style="color:{T.ACCENT_HEX};font-family:{T.FONT_MONO};'
        f'font-size:12px;padding:6px 16px 6px 0;'
        f'letter-spacing:1px;width:60px;">{escape(key)}</td>'
        f'<td style="color:{T.FG_1_HEX};font-family:{T.FONT_SANS};'
        f'font-size:12px;padding:6px 0;">{escape(label)}</td>'
        f'</tr>'
        for key, label in _SHORTCUTS
    )
    return (
        f'<table cellspacing="0" cellpadding="0" style="width:100%;">'
        f'{rows}</table>'
    )


def escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Help")
        self.setMinimumSize(520, 520)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setModal(False)
        self.setStyleSheet(
            f"QDialog {{ background: {T.BG_0};"
            f" border: 1px solid {T.BORDER_1}; }}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 22)
        root.setSpacing(0)

        kicker = QLabel("REFERENCE")
        kicker.setStyleSheet(
            f"color: {T.FG_2_HEX}; font-family: {T.FONT_MONO};"
            f" font-size: 10px; letter-spacing: 3px;"
        )
        root.addWidget(kicker)

        title = QLabel("Keyboard shortcuts")
        title.setStyleSheet(
            f"color: {T.FG_0}; font-family: {T.FONT_SANS};"
            f" font-size: 22px; font-weight: 500;"
            f" letter-spacing: -0.01em; padding: 4px 0 14px 0;"
        )
        root.addWidget(title)

        rule = QFrame()
        rule.setFixedHeight(1)
        rule.setStyleSheet(f"background: {T.BORDER_0};")
        root.addWidget(rule)

        from PySide6.QtWidgets import QTextBrowser
        text = QTextBrowser()
        text.setHtml(_build_html())
        text.setStyleSheet(
            f"QTextBrowser {{ background: transparent; border: none;"
            f" padding: 10px 0 0 0; color: {T.FG_1_HEX}; }}"
        )
        root.addWidget(text, 1)

        btn = QPushButton("CLOSE")
        btn.setProperty("variant", "ghost")
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(self.close)
        root.addWidget(btn, 0, Qt.AlignRight)
