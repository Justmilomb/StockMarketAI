"""Trade dialog — submit orders."""
from __future__ import annotations
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDoubleSpinBox, QFormLayout,
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

class TradeDialog(QDialog):
    def __init__(self, ticker: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Trade - {ticker}")
        self.setMinimumWidth(350)
        self.result_data: dict | None = None

        layout = QVBoxLayout(self)

        title = QLabel(f"TRADE - {ticker}")
        title.setStyleSheet("color: #ffb000; font-weight: bold; font-size: 14px;")
        layout.addWidget(title)

        form = QFormLayout()

        self._side = QComboBox()
        self._side.addItems(["BUY", "SELL"])
        form.addRow("Side:", self._side)

        self._qty = QDoubleSpinBox()
        self._qty.setRange(0.000001, 999999)
        self._qty.setDecimals(6)
        self._qty.setValue(1.0)
        form.addRow("Quantity:", self._qty)

        self._order_type = QComboBox()
        self._order_type.addItems(["Market", "Limit", "Stop"])
        self._order_type.currentTextChanged.connect(self._on_type_changed)
        form.addRow("Order Type:", self._order_type)

        self._price = QDoubleSpinBox()
        self._price.setRange(0.01, 999999)
        self._price.setDecimals(2)
        self._price.setValue(0.0)
        self._price.setEnabled(False)
        form.addRow("Price:", self._price)

        layout.addLayout(form)

        buttons = QHBoxLayout()
        submit = QPushButton("Submit Order")
        submit.setStyleSheet("color: #00ff00; font-weight: bold;")
        submit.clicked.connect(self._submit)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(submit)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

        self._ticker = ticker

    def _on_type_changed(self, text: str) -> None:
        self._price.setEnabled(text != "Market")

    def _submit(self) -> None:
        self.result_data = {
            "ticker": self._ticker,
            "side": self._side.currentText(),
            "quantity": self._qty.value(),
            "order_type": self._order_type.currentText().lower(),
            "price": self._price.value() if self._price.isEnabled() else None,
        }
        self.accept()
