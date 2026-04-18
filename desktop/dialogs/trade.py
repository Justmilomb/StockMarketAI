"""Trade dialog — submit market / limit / stop orders."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
)

from desktop import tokens as T
from desktop.dialogs._base import BaseDialog


_INPUT_STYLE = (
    "QDoubleSpinBox, QComboBox {{ background: transparent; border: none;"
    " border-bottom: 1px solid {border}; color: {fg};"
    " font-family: {mono}; font-size: 14px; padding: 4px 0;"
    " letter-spacing: 1px; }}"
    "QDoubleSpinBox:focus, QComboBox:focus {{ border-bottom: 1px solid {accent}; }}"
    "QComboBox::drop-down {{ border: none; padding-right: 4px; }}"
    "QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; }}"
)


def _input_qss() -> str:
    return _INPUT_STYLE.format(
        border=T.BORDER_1,
        fg=T.FG_0,
        mono=T.FONT_MONO,
        accent=T.ACCENT_HEX,
    )


class TradeDialog(BaseDialog):
    def __init__(self, ticker: str, parent=None) -> None:
        super().__init__(
            kicker=f"ORDER \u2014 {ticker}",
            title="Submit trade",
            parent=parent,
        )
        self.setFixedSize(460, 420)
        self.result_data: dict | None = None
        self._ticker = ticker

        body = self.body_layout()

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(14)
        form.setLabelAlignment(Qt.AlignLeft)

        input_css = _input_qss()
        label_css = (
            f"color: {T.FG_2_HEX}; font-family: {T.FONT_MONO};"
            f" font-size: 10px; letter-spacing: 2px;"
        )

        def _label(text: str) -> QLabel:
            lbl = QLabel(text.upper())
            lbl.setStyleSheet(label_css)
            return lbl

        self._side = QComboBox()
        self._side.addItems(["BUY", "SELL"])
        self._side.setStyleSheet(input_css)
        form.addRow(_label("Side"), self._side)

        self._qty = QDoubleSpinBox()
        self._qty.setRange(0.000001, 999_999)
        self._qty.setDecimals(6)
        self._qty.setValue(1.0)
        self._qty.setStyleSheet(input_css)
        form.addRow(_label("Quantity"), self._qty)

        self._order_type = QComboBox()
        self._order_type.addItems(["Market", "Limit", "Stop"])
        self._order_type.currentTextChanged.connect(self._on_type_changed)
        self._order_type.setStyleSheet(input_css)
        form.addRow(_label("Order type"), self._order_type)

        self._price = QDoubleSpinBox()
        self._price.setRange(0.01, 999_999)
        self._price.setDecimals(2)
        self._price.setValue(0.0)
        self._price.setEnabled(False)
        self._price.setStyleSheet(input_css)
        form.addRow(_label("Price"), self._price)

        body.addLayout(form)
        body.addStretch(1)

        self.add_footer_button("CANCEL", variant="ghost", slot=self.reject)
        self.add_footer_button("SUBMIT", variant="primary", slot=self._submit)

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
