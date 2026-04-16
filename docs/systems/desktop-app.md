# Desktop App

PySide6 terminal-dark desktop GUI. Phase 4+ rewrite — the pipeline
refresh chain is gone; panels now update live from `AgentRunner` Qt
signals as tool calls stream back from the Claude Code subprocess.

## Entry points

```
python desktop/main_desktop.py
```

`desktop/main.py` is the shared bootstrap — handles PyInstaller
`freeze_support()`, `.env` loading, license check, setup wizard,
and applies the terminal-dark QSS stylesheet before launching
`MainWindow`.

## Layout

`MainWindow` (QMainWindow with panel grid):

| Panel | Purpose |
|-------|---------|
| WatchlistPanel | Active tickers for the current watchlist |
| PositionsPanel | Open positions with PnL (from broker tool reads) |
| OrdersPanel | Recent / pending orders |
| ChartPanel | Price chart for selected ticker |
| AgentLogPanel | Live tool-call feed + start/stop/kill buttons + paper badge |
| SettingsPanel | Account + agent status readout (no controls) |
| ChatPanel | User chat — routes into the running agent loop |
| NewsPanel | RSS news feed (legacy `news_agent` sentiment) |

## Key attributes on MainWindow

```python
class MainWindow(QMainWindow):  # desktop/app.py
    config: Dict[str, Any]
    state: AppState               # from desktop/state.py
    broker_service: BrokerService
    history_manager: HistoryManager
    news_agent: NewsAgent         # legacy panel sentiment
    agent_runner: Optional[AgentRunner]   # lazy
    scraper_runner: Optional[ScraperRunner]
    _ai_client: Optional[AIClient]  # chat / ticker-search helper
```

## Agent lifecycle

1. **Start** — Agent menu → `start_agent()`. Constructs `AgentRunner`,
   connects signals, calls `start()`.
2. **Stream** — tool calls and text chunks fan out to panels via
   `Qt.QueuedConnection` slots (safe to touch widgets).
3. **Chat** — `ChatPanel` submits are forwarded to
   `AgentRunner.send_user_message` and interrupt any current sleep.
4. **Stop / Kill** — Agent menu or `AgentLogPanel` buttons call
   `request_stop()`; kill also waits 3 s then `terminate()`.
5. **Close** — `closeEvent` stops both runners cleanly before
   letting Qt quit.

## Scraper lifecycle

Started at boot in `_start_scraper_runner()`:

```python
self.scraper_runner = ScraperRunner(
    db=self.history_manager,
    watchlist_provider=self._get_active_tickers,
    cadence_seconds=int(self.config["news"]["scraper_cadence_seconds"]),
)
self.scraper_runner.start()
```

`ScraperRunner` is a plain `threading.Thread` (daemon), so `core/`
stays free of PySide6 imports. Stopped in `closeEvent` via
`scraper_runner.stop()`.

## Theming

Terminal-dark QSS from `desktop/theme.py`. Sharp corners, hard
amber/green accents — no rounded corners, no soft shadows (see
`feedback_terminal_ui` memory).

## PyInstaller notes

`desktop/main.py` calls `multiprocessing.freeze_support()` before
anything else. `sys._MEIPASS` path injection keeps spawned
subprocesses (backtesting workers) from re-launching the GUI.

## Dependencies

- `PySide6` (Qt6)
- `core/agent/runner.py` — agent QThread
- `core/scrapers/runner.py` — scraper daemon
- `core/broker_service.py`, `core/trading212.py`
- `core/database.py` — sqlite persistence
- `core/news_agent.py` — legacy panel sentiment
- `core/claude_client.py` — chat / ticker-search helper
- `desktop/state.py`, `desktop/panels/`, `desktop/dialogs/`
