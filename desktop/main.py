"""Entry point for the StockMarketAI desktop application."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# PyInstaller sets sys._MEIPASS to the temp extraction dir for --onefile builds.
if getattr(sys, "frozen", False):
    BUNDLE_DIR = Path(sys._MEIPASS)
    sys.path.insert(0, str(BUNDLE_DIR))
    # CWD = next to the exe, where user's config.json lives
    EXE_DIR = Path(sys.executable).parent
    os.chdir(EXE_DIR)
    CONFIG_PATH = EXE_DIR / "config.json"
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(PROJECT_ROOT))
    os.chdir(PROJECT_ROOT)
    CONFIG_PATH = PROJECT_ROOT / "config.json"


def main() -> None:
    from PySide6.QtWidgets import QApplication
    from desktop.app import MainWindow
    from desktop.theme import BLOOMBERG_DARK_QSS

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(BLOOMBERG_DARK_QSS)

    window = MainWindow(config_path=CONFIG_PATH)
    window.showMaximized()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
