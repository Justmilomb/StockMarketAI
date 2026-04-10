"""Mode selector dialog -- choose Stocks, Polymarket, or Crypto on startup."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from desktop.design import (
    APP_NAME_UPPER,
    BASE_QSS,
    BORDER,
    GLOW,
    GLOW_BORDER,
    SECONDARY_BTN_QSS,
    SURFACE,
    TEXT,
    TEXT_DIM,
    TEXT_MID,
    FONT_FAMILY,
)


class ModeSelector(QDialog):
    """Minimal mode selector matching the blank website design."""

    def __init__(self, parent: object = None, show_simple: bool = True) -> None:
        super().__init__(parent)
        self.setWindowTitle("blank")
        self.setFixedSize(400, 440 if show_simple else 380)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setStyleSheet(BASE_QSS + f"""
            QDialog {{ border: 1px solid {BORDER}; }}
        """)

        self._selected: Optional[str] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 20)
        layout.setSpacing(8)

        # Title
        title = QLabel(APP_NAME_UPPER)
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(f"""
            color: {TEXT}; font-size: 36px; font-weight: 700;
            font-family: {FONT_FAMILY}; letter-spacing: -1px;
        """)
        layout.addWidget(title)

        subtitle = QLabel("SELECT TRADING MODE")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet(f"""
            color: {TEXT_MID}; font-size: 11px; font-weight: 300;
            font-family: {FONT_FAMILY}; letter-spacing: 3px;
        """)
        layout.addWidget(subtitle)

        layout.addSpacing(20)

        # Mode buttons -- all use the same green accent from BASE_QSS
        stocks_btn = QPushButton("STOCKS")
        stocks_btn.setCursor(Qt.PointingHandCursor)
        stocks_btn.clicked.connect(lambda: self._select("stocks"))
        layout.addWidget(stocks_btn)

        poly_btn = QPushButton("POLYMARKET")
        poly_btn.setCursor(Qt.PointingHandCursor)
        poly_btn.clicked.connect(lambda: self._select("polymarket"))
        layout.addWidget(poly_btn)

        if show_simple:
            simple_btn = QPushButton("SIMPLE")
            simple_btn.setCursor(Qt.PointingHandCursor)
            simple_btn.clicked.connect(lambda: self._select("simple"))
            layout.addWidget(simple_btn)

        crypto_btn = QPushButton("CRYPTO  --  COMING SOON")
        crypto_btn.setEnabled(False)
        crypto_btn.setToolTip("Crypto trading is not yet available")
        layout.addWidget(crypto_btn)

        layout.addSpacing(12)

        # Quit
        quit_btn = QPushButton("QUIT")
        quit_btn.setCursor(Qt.PointingHandCursor)
        quit_btn.setStyleSheet(SECONDARY_BTN_QSS)
        quit_btn.clicked.connect(self.reject)
        layout.addWidget(quit_btn)

    def _select(self, mode: str) -> None:
        self._selected = mode
        self.accept()

    def run(self) -> Optional[str]:
        """Show the dialog and return the selected mode, or None if cancelled."""
        _show_modal = getattr(self, "exec")
        result = _show_modal()
        if result == QDialog.Accepted:
            return self._selected
        return None
