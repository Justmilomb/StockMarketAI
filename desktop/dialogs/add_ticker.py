"""Add ticker dialog — simple input for a ticker symbol."""
from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
)

class AddTickerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Ticker")
        self.setMinimumWidth(300)
        self.ticker: str = ""

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Enter ticker symbol:"))

        self._input = QLineEdit()
        self._input.setPlaceholderText("e.g. AAPL, TSLA, RR.L")
        self._input.returnPressed.connect(self._add)
        layout.addWidget(self._input)

        buttons = QHBoxLayout()
        add_btn = QPushButton("Add")
        add_btn.clicked.connect(self._add)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(add_btn)
        buttons.addWidget(cancel_btn)
        layout.addLayout(buttons)

    def _add(self) -> None:
        self.ticker = self._input.text().strip().upper()
        if self.ticker:
            self.accept()
