# Blank — AI Trading Terminal

AI-powered stock trading terminal by Certified Random. Bloomberg-style panel layout with charts, chat, orders, and multi-asset support (stocks, crypto, polymarket).

Combines a 12-model ML ensemble, ARIMA/ETS statistical baselines, 5 Claude analyst personas, and a consensus engine to generate buy/sell/hold signals with probability scores.

## Quick Start

### Download (Windows)
1. Download `BlankSetup.exe` from the latest release
2. Run the installer
3. Enter your license key on first launch
4. Follow the setup wizard (Claude CLI + Trading 212)

### Build from Source
```
setup.bat                              # Create venv + install deps
build.bat                              # Build blank.exe + installer
```

Output: `dist/BlankSetup.exe`

## Project Structure

```
core/           29 ML/AI/broker modules (on sys.path)
desktop/        PySide6 app (Bloomberg-dark UI)
terminal/       Textual TUI (dev-only)
server/         FastAPI license server
website/        Landing page + admin panel
backtesting/    Walk-forward validation engine
installer/      PyInstaller specs + Inno Setup scripts
```

See `docs/DIRECTORY_STRUCTURE.md` for the full annotated tree.

## Configuration

All runtime config lives in `config.json`:
- `watchlists` — ticker lists per asset class
- `strategy` — buy/sell thresholds, position sizing
- `broker` — Trading 212 API config, paper mode toggle
- `claude` — model selections for AI analysis

API keys go in `.env` (see `.env.example`).

## Requirements

- Python 3.12+
- Claude CLI (`npm install -g @anthropic-ai/claude-code`)
- Trading 212 account (optional, for live trading)
- Windows 10+ (for desktop app)

## License

See `LICENSE`.
