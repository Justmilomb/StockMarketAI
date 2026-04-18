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
    EXE_DIR = Path(sys.executable).parent
    # For frozen builds we no longer chdir to EXE_DIR — user state lives
    # in %LOCALAPPDATA%\blank\ (owned by desktop.paths), the exe parent
    # is now effectively read-only under %LOCALAPPDATA%\Programs\blank.
    # We chdir to the user data dir so any legacy relative-path writes
    # land in the durable location instead of the install directory.
    from desktop.paths import (
        migrate_user_state_if_needed,
        user_data_dir,
        config_path as _user_config_path,
    )
    _MIGRATION_RESULT = migrate_user_state_if_needed()
    os.chdir(str(user_data_dir()))
    CONFIG_PATH = _user_config_path()
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(PROJECT_ROOT))
    sys.path.insert(0, str(PROJECT_ROOT / "core"))
    os.chdir(PROJECT_ROOT)
    CONFIG_PATH = PROJECT_ROOT / "config.json"
    _MIGRATION_RESULT = None


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

    # paper_mode → broker.practice (and agent.paper_mode — redundant but explicit)
    if "paper_mode" in remote_cfg:
        practice = remote_cfg["paper_mode"] == "true"
        local.setdefault("broker", {})["practice"] = practice
        local.setdefault("agent", {})["paper_mode"] = practice
        changed = True

    # auto_trading → agent.enabled (start/stop the AI agent loop)
    if "auto_trading" in remote_cfg:
        local.setdefault("agent", {})["enabled"] = remote_cfg["auto_trading"] == "true"
        changed = True

    # max_position_pct → agent.max_position_pct (percent of equity per ticker)
    if "max_position_pct" in remote_cfg:
        try:
            local.setdefault("agent", {})["max_position_pct"] = float(remote_cfg["max_position_pct"])
            changed = True
        except ValueError:
            pass

    # refresh_interval_s → agent.cadence_seconds (min seconds between iterations)
    if "refresh_interval_s" in remote_cfg:
        try:
            val = int(float(remote_cfg["refresh_interval_s"]))
            local.setdefault("agent", {})["cadence_seconds"] = max(30, val)
            changed = True
        except ValueError:
            pass

    if changed:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(local, f, indent=2)
        logger.info("Remote config applied to local config.json")


def _start_telemetry(*, server_url: str) -> None:
    """Initialise the telemetry collector + uploader.

    Reads the live ``telemetry`` block from ``config.json`` and the
    stored licence key from disk. A disabled telemetry config or a
    missing licence key short-circuits without starting anything.
    """
    import json

    from core import telemetry
    from core.telemetry.hooks import TelemetryLogHandler
    from core.telemetry.machine_id import get_machine_id
    from core.telemetry.uploader import TelemetryUploader
    from desktop.license import _read_stored_key
    from desktop.paths import user_data_dir

    config_path = Path("config.json")
    try:
        with config_path.open("r", encoding="utf-8") as f:
            raw_cfg = json.load(f)
    except Exception:
        raw_cfg = {}

    t_cfg = raw_cfg.get("telemetry") or {}
    enabled = bool(t_cfg.get("enabled", True))
    if not enabled:
        logger.info("telemetry disabled in config — skipping bootstrap")
        return

    licence_key = (_read_stored_key() or "").strip()
    if not licence_key:
        logger.info("no licence key on disk — telemetry will not upload")
        return

    # Default to the licence/admin server host if the telemetry endpoint
    # isn't explicitly configured. The server exposes /api/telemetry on
    # the same origin, so we just append the path.
    endpoint = str(
        t_cfg.get("endpoint")
        or (server_url.rstrip("/") + "/api/telemetry"),
    )

    data_dir = user_data_dir()
    db_path = data_dir / "data" / "telemetry.db"
    machine_id = get_machine_id(data_dir)

    collector = telemetry.init(
        db_path=db_path,
        machine_id=machine_id,
        licence_key=licence_key,
        endpoint=endpoint,
        enabled=True,
        max_queue_size=int(t_cfg.get("max_queue_size", 100_000)),
    )

    uploader = TelemetryUploader(
        collector,
        upload_hour=int(t_cfg.get("upload_hour", 3)),
        batch_size=int(t_cfg.get("batch_size", 500)),
    )
    uploader.start()
    collector.attach_uploader(uploader)

    # Route WARNING+ records into the error_log event stream so crashes
    # can be correlated with the preceding agent actions. The handler
    # is installed once globally.
    handler = TelemetryLogHandler()
    root = logging.getLogger()
    root.addHandler(handler)

    logger.info(
        "telemetry started (endpoint=%s machine_id=%s)",
        endpoint, machine_id,
    )


def launch(mode: str | None = None) -> None:
    """Launch the blank desktop app.

    Args:
        mode: 'desktop' for default desktop edition (shows stocks/polymarket
              selector), None for full mode selector.
    """
    _load_dotenv(Path(os.getcwd()))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    _setup_error_handlers()

    # Log migration result on frozen builds so the very first installer
    # run leaves a breadcrumb in the user's log file showing whether v1
    # state was carried over.
    if _MIGRATION_RESULT is not None:
        logger.info(
            "User state migration: %s", _MIGRATION_RESULT.as_dict(),
        )
        logger.info("User data dir: %s", CONFIG_PATH.parent)

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
    from PySide6.QtWidgets import QApplication, QSplashScreen
    from desktop.theme import DARK_TERMINAL_QSS

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    from desktop.fonts import register_app_fonts
    register_app_fonts()

    app.setStyleSheet(DARK_TERMINAL_QSS)

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

    # ── Risk disclosure (skipped if snoozed for 7 days) ─────────────
    from desktop.dialogs.risk_disclosure import (
        RiskDisclosureDialog,
        should_show as _risk_should_show,
    )
    if _risk_should_show():
        RiskDisclosureDialog().exec()

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

    # ── Telemetry bootstrap ──────────────────────────────────────────
    # Start the collector + uploader now so scraper / agent / chat hooks
    # can emit from the moment MainWindow comes up. Failures here must
    # never block the app — telemetry is optional.
    try:
        _start_telemetry(server_url=server_url)
    except Exception as exc:
        logger.warning("telemetry bootstrap failed: %s", exc)

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

    from desktop import tokens as _T
    painter.setFont(QFont("Outfit", 11, QFont.Light))
    painter.setPen(QColor(_T.FG_1_HEX))
    subtitle_rect = pixmap.rect().adjusted(0, 80, 0, 80)
    painter.drawText(subtitle_rect, Qt.AlignCenter, "CERTIFIED RANDOM")

    painter.setFont(QFont("Outfit", 10, QFont.Thin))
    painter.setPen(QColor(_T.FG_2_HEX))
    painter.drawText(
        pixmap.rect().adjusted(0, 0, 0, -20),
        Qt.AlignBottom | Qt.AlignHCenter,
        "Loading...",
    )
    painter.end()

    splash = QSplashScreen(pixmap)
    splash.show()
    app.processEvents()

    from desktop.app import MainWindow
    from desktop.dialogs.mode_selector import ModeSelector

    app.setStyleSheet(DARK_TERMINAL_QSS)

    splash.hide()
    picker = ModeSelector()
    selected = picker.run()
    if selected is None:
        sys.exit(0)

    splash.show()
    splash.showMessage(
        "Initialising services...",
        Qt.AlignBottom | Qt.AlignHCenter,
        QColor(_T.FG_1_HEX),
    )
    app.processEvents()

    window = MainWindow(config_path=CONFIG_PATH, forced_paper_mode=selected)
    window.showMaximized()
    splash.finish(window)

    try:
        from desktop.onboarding import maybe_start_tour
        maybe_start_tour(window)
    except Exception as exc:
        logger.warning("Onboarding tour failed to start: %s", exc)

    # Flush telemetry on graceful exit so the last session's events are
    # shipped before the uploader thread is joined.
    def _on_about_to_quit() -> None:
        try:
            from core import telemetry
            telemetry.flush()
            telemetry.close()
        except Exception:
            pass

    app.aboutToQuit.connect(_on_about_to_quit)

    _run_loop = getattr(app, "exec")
    sys.exit(_run_loop())


def main() -> None:
    """Default entry point."""
    launch()


if __name__ == "__main__":
    main()
