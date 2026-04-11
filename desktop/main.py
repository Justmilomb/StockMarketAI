"""Entry point for the blank desktop application."""
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
    sys.path.insert(0, str(BUNDLE_DIR / "core"))
    # CWD = next to the exe, where user's config.json lives
    EXE_DIR = Path(sys.executable).parent
    os.chdir(EXE_DIR)
    CONFIG_PATH = EXE_DIR / "config.json"
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(PROJECT_ROOT))
    sys.path.insert(0, str(PROJECT_ROOT / "core"))
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


def _apply_remote_config(remote_cfg: dict[str, str]) -> None:
    """Override local config.json values with remote admin settings."""
    import json

    config_path = Path("config.json")
    if not config_path.exists():
        return

    try:
        with open(config_path, encoding="utf-8") as f:
            local = json.load(f)
    except Exception:
        return

    changed = False

    # paper_mode → broker.practice
    if "paper_mode" in remote_cfg:
        practice = remote_cfg["paper_mode"] == "true"
        local.setdefault("broker", {})["practice"] = practice
        changed = True

    # auto_trading → stored for AutoEngine to read
    if "auto_trading" in remote_cfg:
        local["auto_trading_enabled"] = remote_cfg["auto_trading"] == "true"
        changed = True

    # strategy params
    if "max_position_pct" in remote_cfg:
        try:
            val = float(remote_cfg["max_position_pct"]) / 100
            local.setdefault("strategy", {})["position_size_fraction"] = val
            changed = True
        except ValueError:
            pass

    if "confidence_threshold" in remote_cfg:
        try:
            val = float(remote_cfg["confidence_threshold"])
            local.setdefault("strategy", {})["threshold_buy"] = val
            changed = True
        except ValueError:
            pass

    if "trailing_stop_pct" in remote_cfg:
        try:
            val = float(remote_cfg["trailing_stop_pct"]) / 100
            local.setdefault("strategy", {})["trailing_stop"] = val
            changed = True
        except ValueError:
            pass

    if "refresh_interval_s" in remote_cfg:
        try:
            val = int(float(remote_cfg["refresh_interval_s"]))
            local["refresh_interval_seconds"] = val
            changed = True
        except ValueError:
            pass

    if changed:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(local, f, indent=2)
        logger.info("Remote config applied to local config.json")


def launch(mode: str | None = None) -> None:
    """Launch the Blank desktop app.

    Args:
        mode: 'bloomberg' for Bloomberg edition (shows stocks/polymarket
              selector), None for full mode selector.
    """
    _load_dotenv(Path(os.getcwd()))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    _setup_error_handlers()

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
    from PySide6.QtWidgets import QApplication, QSplashScreen
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

    # ── Wake up Render server (fire-and-forget while user sees UI) ──
    from desktop.license import validate, _read_stored_key, _read_server_url

    server_url = _read_server_url()

    def _wake_server() -> None:
        try:
            import requests
            requests.get(f"{server_url.rstrip('/')}/api/health", timeout=60)
        except Exception:
            pass

    wake_thread = threading.Thread(target=_wake_server, daemon=True)
    wake_thread.start()

    # ── License gate ─────────────────────────────────────────────────
    from desktop.dialogs.license import LicenseDialog

    stored_key = _read_stored_key()

    if stored_key:
        result = validate(server_url=server_url, key=stored_key)
        if not result.get("valid"):
            dialog = LicenseDialog(server_url=server_url)
            if not dialog.run():
                sys.exit(0)
            result = validate(server_url=server_url)
    else:
        dialog = LicenseDialog(server_url=server_url)
        if not dialog.run():
            sys.exit(0)
        result = validate(server_url=server_url)

    logger.info("License validated — launching app")

    # ── First-run setup wizard ───────────────────────────────────────
    from desktop.dialogs.setup_wizard import SetupWizard

    if SetupWizard.should_show():
        wizard = SetupWizard()
        wizard.run()

    # ── Remote config enforcement ────────────────────────────────────
    from PySide6.QtWidgets import QMessageBox

    remote_cfg = result.get("config", {})

    if remote_cfg.get("kill_switch") == "true":
        QMessageBox.critical(
            None, "blank",
            "trading has been disabled by the administrator.\n\n"
            "Contact support if you believe this is an error.",
        )
        sys.exit(1)

    if remote_cfg.get("maintenance_mode") == "true":
        QMessageBox.information(
            None, "blank",
            "blank is currently under maintenance.\n\n"
            "The service will be back shortly. Please try again later.",
        )
        sys.exit(0)

    if remote_cfg.get("force_update") == "true":
        update_url = remote_cfg.get("update_url", "")
        msg = QMessageBox(
            QMessageBox.Warning, "blank — update required",
            "a new version of blank is available.\n\n"
            "You must update before continuing.",
        )
        if update_url:
            msg.setInformativeText("Download: " + update_url)
        msg.addButton("Download", QMessageBox.AcceptRole)
        msg.addButton("Quit", QMessageBox.RejectRole)
        _show_msg = getattr(msg, "exec")
        choice = _show_msg()
        if choice == 0 and update_url:
            import webbrowser
            webbrowser.open(update_url)
        sys.exit(0)

    _apply_remote_config(remote_cfg)

    # ── Splash screen ────────────────────────────────────────────────
    from desktop.design import BG, TEXT, TEXT_DIM, TEXT_MID, GLOW, FONT_FAMILY

    pixmap = QPixmap(600, 340)
    pixmap.fill(QColor(BG))
    painter = QPainter(pixmap)

    painter.setFont(QFont("Outfit", 48, QFont.Bold))
    painter.setPen(QColor(TEXT))
    painter.drawText(pixmap.rect(), Qt.AlignCenter, "blank")

    painter.setPen(QColor(GLOW))
    cx = pixmap.width() // 2
    cy = pixmap.height() // 2 + 32
    painter.drawLine(cx - 60, cy, cx + 60, cy)

    painter.setFont(QFont("Outfit", 11, QFont.Light))
    painter.setPen(QColor("#808080"))
    subtitle_rect = pixmap.rect().adjusted(0, 80, 0, 80)
    painter.drawText(subtitle_rect, Qt.AlignCenter, "CERTIFIED RANDOM")

    painter.setFont(QFont("Outfit", 10, QFont.Thin))
    painter.setPen(QColor("#333333"))
    painter.drawText(
        pixmap.rect().adjusted(0, 0, 0, -20),
        Qt.AlignBottom | Qt.AlignHCenter,
        "Loading...",
    )
    painter.end()

    splash = QSplashScreen(pixmap)
    splash.show()
    app.processEvents()

    # ── Asset selector (stocks / polymarket) ────────────────────────────
    from desktop.dialogs.mode_selector import ModeSelector
    from desktop.app import MainWindow

    splash.close()
    app.processEvents()

    selector = ModeSelector()
    selector_result = selector.run()
    if selector_result is None:
        sys.exit(0)

    # ── Apply mode-specific colour overlay ────────────────────────────
    if selector_result == "polymarket":
        from desktop.theme import MODE_OVERLAY_POLYMARKET
        app.setStyleSheet(BLOOMBERG_DARK_QSS + MODE_OVERLAY_POLYMARKET)
    else:
        from desktop.theme import MODE_OVERLAY_STOCKS
        app.setStyleSheet(BLOOMBERG_DARK_QSS + MODE_OVERLAY_STOCKS)

    splash.show()
    splash.showMessage(
        "Initialising services...", Qt.AlignBottom | Qt.AlignHCenter, QColor("#888888"),
    )
    app.processEvents()

    window = MainWindow(config_path=CONFIG_PATH, initial_asset=selector_result)
    window.showMaximized()
    splash.finish(window)
    sys.exit(app.exec())


def main() -> None:
    """Default entry point."""
    launch()


if __name__ == "__main__":
    main()
