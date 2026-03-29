"""Entry point for the StockMarketAI desktop application."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# PyInstaller sets sys._MEIPASS to the temp extraction dir for --onefile builds.
# When running from source, use the normal parent directory.
if getattr(sys, "frozen", False):
    BUNDLE_DIR = Path(sys._MEIPASS)
    PROJECT_ROOT = BUNDLE_DIR
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(PROJECT_ROOT))
if not getattr(sys, "frozen", False):
    os.chdir(PROJECT_ROOT)

def main() -> None:
    from PySide6.QtWidgets import QApplication
    from desktop.app import MainWindow
    from desktop.theme import BLOOMBERG_DARK_QSS

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(BLOOMBERG_DARK_QSS)

    window = MainWindow()
    window.showMaximized()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
