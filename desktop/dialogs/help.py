"""Help dialog — keybinding reference."""
from __future__ import annotations
from PySide6.QtWidgets import QDialog, QPushButton, QTextEdit, QVBoxLayout

HELP_TEXT = """
<h3 style="color:#ffb000;">StockMarketAI Terminal — Keyboard Shortcuts</h3>
<table style="color:#ffd700; width:100%;">
<tr><td style="color:#00ff00; width:60px;">?</td><td>Show this help</td></tr>
<tr><td style="color:#00ff00;">Q</td><td>Quit</td></tr>
<tr><td style="color:#00ff00;">R</td><td>Refresh data</td></tr>
<tr><td style="color:#00ff00;">A</td><td>Toggle mode (Advisor / Auto)</td></tr>
<tr><td style="color:#00ff00;">W</td><td>Cycle watchlist</td></tr>
<tr><td style="color:#00ff00;">S</td><td>AI suggest ticker</td></tr>
<tr><td style="color:#00ff00;">I</td><td>Generate AI insights</td></tr>
<tr><td style="color:#00ff00;">N</td><td>Refresh news</td></tr>
<tr><td style="color:#00ff00;">C</td><td>Focus chat input</td></tr>
<tr><td style="color:#00ff00;">G</td><td>Show chart for selected ticker</td></tr>
<tr><td style="color:#00ff00;">T</td><td>Open trade dialog</td></tr>
<tr><td style="color:#00ff00;">=</td><td>Add ticker to watchlist</td></tr>
<tr><td style="color:#00ff00;">-</td><td>Remove ticker from watchlist</td></tr>
<tr><td style="color:#00ff00;">/</td><td>Search tickers</td></tr>
<tr><td style="color:#00ff00;">D</td><td>AI recommendations</td></tr>
<tr><td style="color:#00ff00;">O</td><td>AI optimise config</td></tr>
<tr><td style="color:#00ff00;">H</td><td>Show account history</td></tr>
<tr><td style="color:#00ff00;">P</td><td>Show investment pies</td></tr>
<tr><td style="color:#00ff00;">E</td><td>Browse instruments</td></tr>
<tr><td style="color:#00ff00;">L</td><td>Lock/unlock ticker (protect from auto-trade)</td></tr>
</table>
"""

class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Help")
        self.setMinimumSize(500, 400)
        layout = QVBoxLayout(self)
        text = QTextEdit()
        text.setReadOnly(True)
        text.setHtml(HELP_TEXT)
        layout.addWidget(text)
        btn = QPushButton("Close")
        btn.clicked.connect(self.accept)
        layout.addWidget(btn)
