# Terminal

## Goal
Terminal-style Textual TUI providing a 3-column grid layout with real-time data, interactive trading, and AI chat.

## Implementation
`TradingTerminalApp` (Textual App) manages lifecycle, keybindings, and data refresh. 3×3 CSS grid: left column (metrics, positions, orders), centre (watchlist spanning 2 rows, chart), right (chat spanning 2 rows, news). `AppState` dataclass holds all shared state. Views read state in `refresh_view()`. Modals for adding tickers, trading, searching, and AI recommendations.

## Key Code
```python
class TradingTerminalApp(App):  # terminal/app.py — hub
class AppState:  # terminal/state.py — shared state
class WatchlistView, PositionsView, OrdersView, ...  # terminal/views.py
class PriceChartView:  # terminal/charts.py — sparkline
```

## Notes
- Keybindings: q=quit, r=refresh, a=mode, w=watchlist, s=suggest, i=insights, n=news, c=chat, g=chart, t=trade, +=add, -=remove, /=search, d=AI recs, o=optimise, h=history
- Background work via `@work(thread=True)` decorator
- UTF-8 forced on Windows via `PYTHONUTF8=1` and `chcp 65001`
- Chat uses AIClient (Claude CLI subprocess) for all AI interactions
