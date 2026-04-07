"""Entry point for the Blank desktop application."""
from __future__ import annotations

import logging
import multiprocessing
import os
import sys
import threading
from pathlib import Path

# CRITICAL: Must be called before anything else in a frozen exe.
# Without this, every subprocess spawned by ProcessPoolExecutor
# re-launches the full app, creating infinite window copies.
multiprocessing.freeze_support()

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


def _load_dotenv(directory: Path) -> None:
    """Load .env file from directory into os.environ (no external deps)."""
    env_file = directory / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


logger = logging.getLogger("blank")


def _setup_error_handlers() -> None:
    """Install global exception handlers so crashes are logged, not silent."""

    def _on_unhandled(exc_type: type, exc_value: BaseException, exc_tb: object) -> None:
        logger.critical("Unhandled exception", exc_info=(exc_type, exc_value, exc_tb))

    def _on_thread_error(args: threading.ExceptHookArgs) -> None:
        logger.critical(
            "Unhandled thread exception: %s",
            args.exc_value,
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = _on_unhandled
    threading.excepthook = _on_thread_error


def main() -> None:
    _load_dotenv(Path(os.getcwd()))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    _setup_error_handlers()

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
    from PySide6.QtWidgets import QApplication, QSplashScreen
    from desktop.app import MainWindow
    from desktop.theme import BLOOMBERG_DARK_QSS

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(BLOOMBERG_DARK_QSS)

    # App icon — embedded in the EXE for frozen builds, loaded from file for dev
    if getattr(sys, "frozen", False):
        icon_path = Path(sys._MEIPASS) / "desktop" / "assets" / "icon.ico"
    else:
        icon_path = Path(__file__).parent / "assets" / "icon.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    # ── License gate ─────────────────────────────────────────────────
    from desktop.license import validate, _read_stored_key, _read_server_url
    from desktop.dialogs.license import LicenseDialog

    server_url = _read_server_url()
    stored_key = _read_stored_key()

    if stored_key:
        # try silent validation of stored key
        result = validate(server_url=server_url, key=stored_key)
        if not result.get("valid"):
            # stored key is bad — prompt for a new one
            dialog = LicenseDialog(server_url=server_url)
            if not dialog.run():
                sys.exit(0)
    else:
        # no stored key — must enter one
        dialog = LicenseDialog(server_url=server_url)
        if not dialog.run():
            sys.exit(0)

    logger.info("License validated — launching app")

    # ── Splash screen ────────────────────────────────────────────────
    pixmap = QPixmap(600, 340)
    pixmap.fill(QColor("#000000"))
    painter = QPainter(pixmap)

    # App name
    painter.setFont(QFont("Consolas", 48, QFont.Bold))
    painter.setPen(QColor("#ffd700"))
    painter.drawText(pixmap.rect(), Qt.AlignCenter, "BLANK")

    # Gold accent line under title
    painter.setPen(QColor("#ff8c00"))
    cx = pixmap.width() // 2
    cy = pixmap.height() // 2 + 32
    painter.drawLine(cx - 80, cy, cx + 80, cy)

    # Subtitle
    painter.setFont(QFont("Consolas", 12))
    painter.setPen(QColor("#ff8c00"))
    subtitle_rect = pixmap.rect().adjusted(0, 80, 0, 80)
    painter.drawText(subtitle_rect, Qt.AlignCenter, "CERTIFIED RANDOM")

    # Loading text
    painter.setFont(QFont("Consolas", 10))
    painter.setPen(QColor("#555555"))
    painter.drawText(
        pixmap.rect().adjusted(0, 0, 0, -20),
        Qt.AlignBottom | Qt.AlignHCenter,
        "Loading...",
    )
    painter.end()

    splash = QSplashScreen(pixmap)
    splash.show()
    app.processEvents()

    # ── Mode selector ────────────────────────────────────────────────
    from desktop.dialogs.mode_selector import ModeSelector

    # Hide splash so it doesn't overlap the mode selector
    splash.close()
    app.processEvents()

    selector = ModeSelector()
    selector_result = selector.run()
    if selector_result is None:
        sys.exit(0)

    # ── Re-show splash while loading ─────────────────────────────────
    splash.show()
    splash.showMessage(
        "Initialising services...", Qt.AlignBottom | Qt.AlignHCenter, QColor("#888888"),
    )
    app.processEvents()

    window = MainWindow(config_path=CONFIG_PATH, initial_asset=selector_result)
    window.showMaximized()
    splash.finish(window)
    exit_code = app.exec()
    sys.exit(exit_code)

if __name__ == "__main__":
    main()
