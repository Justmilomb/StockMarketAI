# Desktop App

PySide6 Bloomberg-dark desktop GUI providing a 3×4 grid layout with live trading data, AI chat, news, pipeline visualisation, and settings. Alternative front-end to the Textual TUI.

## Purpose

Provides a native desktop application entry point. Uses the same backend services as the TUI (AiService, BrokerService, NewsAgent, etc.) wired via Qt timers and background worker threads, exposed through a Bloomberg-style panel grid.

## Entry Point

```bash
python desktop/main.py
```

`desktop/main.py` handles PyInstaller `freeze_support()`, `.env` loading, applies the Bloomberg-dark QSS stylesheet, and launches `MainWindow`.

## Layout

`MainWindow` (QMainWindow with QGridLayout 3 columns × 4 rows):

| Panel | Position | Purpose |
|-------|----------|---------|
| WatchlistPanel | top-left | Ticker table with signals, probabilities, consensus |
| PositionsPanel | mid-left | Open positions with PnL |
| OrdersPanel | bottom-left | Recent orders |
| ChartPanel | top-centre | Price chart for selected ticker |
| PipelinePanel | mid-centre | AI pipeline progress visualisation |
| SettingsPanel | bottom-centre | Config editor (thresholds, modes) |
| ChatPanel | top-right (spans 2) | Interactive Claude AI chat |
| NewsPanel | bottom-right | RSS news feed with sentiment |

## Key Classes

```python
class MainWindow(QMainWindow):  # desktop/app.py — wires all services + panels
    config: Dict[str, Any]
    state: AppState              # desktop/state.py
    ai_service: AiService
    broker_service: BrokerService
    auto_engine: AutoEngine
    pipeline_tracker: PipelineTracker
    news_agent: NewsAgent
    history_manager: HistoryManager
    _claude_client: ClaudeClient
```

## Background Workers

`RefreshWorker` runs the AI pipeline on a `QTimer` (configurable interval). `BackgroundTask` runs one-off operations (news fetch, manual refresh) in a thread to avoid blocking the UI.

## Theming

Bloomberg-dark QSS stylesheet from `desktop/theme.py` — dark background (#0D1117 equivalent), amber/green accent colours matching the Textual TUI palette.

## Keyboard Shortcuts

Configured via `QShortcut` in `MainWindow.__init__`. Core shortcuts mirror the TUI (refresh, add/remove ticker, chat focus, etc.).

## PyInstaller Compatibility

`desktop/main.py` calls `multiprocessing.freeze_support()` before anything else. `sys._MEIPASS` path injection ensures subprocesses spawned by ProcessPoolExecutor (MiroFish, backtesting) don't re-launch the full GUI.

## Dependencies

- `PySide6` (Qt6 bindings)
- All backend services: `ai_service`, `broker_service`, `news_agent`, `database`, `auto_engine`, `pipeline_tracker`
- `desktop/state.py` (AppState dataclass, init_state, load_config)
- `desktop/workers.py` (RefreshWorker, BackgroundTask)
- `desktop/panels/` (one module per panel)
