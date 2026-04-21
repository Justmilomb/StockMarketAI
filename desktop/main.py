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
    # If no config.json is about to be seeded (fresh install, or
    # reinstall after user wiped their data), clear any stale
    # first-run UI markers so the onboarding tour and risk
    # disclosure re-show. These files live in %LOCALAPPDATA%\blank\
    # and can outlive an uninstall/reinstall cycle.
    if not CONFIG_PATH.exists():
        for _marker in (".onboarding_complete", "risk_disclosure_snoozed_until.txt"):
            try:
                (user_data_dir() / _marker).unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass
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

    # Request native OpenGL for hardware-accelerated rendering. Must be
    # set before QApplication is created. Falls back to software renderer
    # automatically if the GPU/driver doesn't support it.
    QApplication.setAttribute(Qt.AA_UseDesktopOpenGL, True)
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
    from desktop.license import _read_server_url

    server_url = _read_server_url()

    def _wake_server() -> None:
        try:
            import requests
            requests.get(f"{server_url.rstrip('/')}/api/health", timeout=60)
        except Exception:
            pass

    wake_thread = threading.Thread(target=_wake_server, daemon=True)
    wake_thread.start()

    # ── Account auth (fully skippable — app is free to install) ─────
    # Anyone can open the app. Gated actions (trade / agent / chat)
    # nudge the user to sign in at the point of use; we never block
    # the UI behind sign-in.
    from desktop.auth import fetch_me
    from desktop.auth_state import auth_state

    result: dict = {}
    me = fetch_me(server_url=server_url)
    if me.get("ok"):
        auth_state().set_signed_in(
            email=me.get("email", ""),
            name=me.get("name", ""),
        )
        result = me
        logger.info("Resumed session for %s", me.get("email", "<unknown>"))
    else:
        # No valid stored session — offer the sign-in dialog once, but
        # let the user skip and browse the UI signed-out.
        from desktop.dialogs.signin import SignInDialog
        dialog = SignInDialog()
        dialog.run()
        if auth_state().is_signed_in:
            # Fetch remote config (kill-switch / force-update) now that
            # we have a token. If it fails, launch signed-in anyway —
            # the enforcement branches below will short-circuit safely.
            result = fetch_me(server_url=server_url)
            if not result.get("ok"):
                result = {}

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

    _run_loop = getattr(app, "exec")
    sys.exit(_run_loop())


def main() -> None:
    """Default entry point."""
    launch()


if __name__ == "__main__":
    main()
