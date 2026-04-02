from __future__ import annotations

from typing import Any, List

from terminal.state import AppState

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal, VerticalScroll
from textual.widgets import DataTable, Static, Label, Input, Button, Select
from textual.screen import ModalScreen


def compute_verdict(prob: float, consensus_pct: float) -> str:
    """Return a verdict label based on ML probability and consensus percentage.

    Centralised so that both the watchlist renderer and AI chat context
    produce identical labels without duplicating the threshold logic.
    """
    if prob > 0.65 and consensus_pct >= 70:
        return "STR BUY"
    if prob > 0.55 and consensus_pct >= 60:
        return "BUY"
    if prob < 0.35 and consensus_pct >= 70:
        return "STR SELL"
    if prob < 0.45 and consensus_pct >= 60:
        return "SELL"
    return "NEUTRAL"


class Panel(Vertical):
    """A bordered container for a section."""
    DEFAULT_CSS = """
    Panel {
        border: solid #444444;
        background: #000000;
        height: 100%;
        padding: 0 1;
    }
    """
    def __init__(self, title: str, *children, id: str | None = None) -> None:
        super().__init__(*children, id=id)
        self.panel_title = title


# ═══════════════════════════════════════════════════════════════════════
#  WATCHLIST VIEW
# ═══════════════════════════════════════════════════════════════════════

class WatchlistView(Panel):
    def __init__(self, state: AppState) -> None:
        super().__init__("WATCHLIST [Signals]", id="watchlist-panel")
        self.state = state
        self.table = DataTable(cursor_type="row")

    def compose(self) -> ComposeResult:
        title = f"WATCHLIST [{self.state.active_watchlist}]" if self.state.active_watchlist else "WATCHLIST"
        yield Label(title, classes="panel-title", id="watchlist-title")
        yield self.table

    _STOCK_COLS = ("Ticker", "Verdict", "Live Px", "Day %", "Prob", "Signal", "AI Rec", "Consensus", "Conf", "Sentiment", "Strategy")
    _POLY_COLS = ("Market", "Mkt Prob", "AI Prob", "Edge %", "Signal", "Volume", "Liquidity", "Resolves", "Conf", "Category")
    _CRYPTO_COLS = ("Pair", "Verdict", "Price", "24h %", "Prob", "Signal", "AI Rec", "Consensus", "Conf", "Vol", "Strategy")

    def _active_columns(self) -> tuple[str, ...]:
        asset = self.state.active_asset_class
        if asset == "polymarket":
            return self._POLY_COLS
        if asset == "crypto":
            return self._CRYPTO_COLS
        return self._STOCK_COLS

    def on_mount(self) -> None:
        self.table.add_columns(*self._active_columns())
        self._current_cols = self._active_columns()
        self.refresh_view()

    def refresh_view(self) -> None:
        asset = self.state.active_asset_class
        asset_label = {"stocks": "", "crypto": "CRYPTO ", "polymarket": "POLY "}.get(asset, "")
        title = f"{asset_label}WATCHLIST [{self.state.active_watchlist}]" if self.state.active_watchlist else f"{asset_label}WATCHLIST"
        try:
            self.query_one("#watchlist-title", Label).update(title)
        except Exception:
            pass

        # Rebuild columns if asset class changed
        needed = self._active_columns()
        if hasattr(self, '_current_cols') and self._current_cols != needed:
            self.table.clear(columns=True)
            self.table.add_columns(*needed)
            self._current_cols = needed
        else:
            self.table.clear()
        # Polymarket has its own rendering path
        if asset == "polymarket":
            self._render_polymarket_rows()
            return

        # Extract held tickers for highlighting (case-insensitive)
        held_tickers = {p.get("ticker"): p for p in self.state.positions}
        held_upper = {t.upper() for t in held_tickers if t}
        protected_upper = {t.upper() for t in self.state.protected_tickers}

        verdict_colors: dict[str, str] = {
            "STR BUY":  "#00ff00",
            "BUY":      "#22cc22",
            "NEUTRAL":  "#ffb000",
            "SELL":     "#cc4444",
            "STR SELL": "#ff0000",
        }

        if self.state.signals is not None and not self.state.signals.empty:
            for _, row in self.state.signals.head(30).iterrows():
                ticker = row['ticker']
                prob_up = float(row['prob_up'])
                signal = row['signal']

                # Is held / protected? (case-insensitive)
                is_held = ticker in held_tickers or ticker.upper() in held_upper
                is_protected = ticker.upper() in protected_upper

                # Ticker display: protected > held > normal
                if is_protected and is_held:
                    ticker_display = f"[reverse #ff8800][P]{ticker}*[/]"
                elif is_protected:
                    ticker_display = f"[#ff8800][P]{ticker}[/]"
                elif is_held:
                    ticker_display = f"[reverse #00ffff]{ticker}*[/]"
                else:
                    ticker_display = ticker

                # Live Data
                live_info = self.state.live_data.get(ticker, {})
                live_px = live_info.get("price", 0.0)
                day_pct = live_info.get("change_pct", 0.0)

                live_px_str = f"${live_px:.2f}" if live_px > 0 else "-"

                if day_pct > 0:
                    day_pct_str = f"[#00ff00]+{day_pct:.1f}%[/]"
                elif day_pct < 0:
                    day_pct_str = f"[#ff0000]{day_pct:.1f}%[/]"
                else:
                    day_pct_str = "-"

                # Signal color
                if signal.lower() == "buy":
                    signal_str = f"[#00ff00]{signal}[/]"
                elif signal.lower() == "sell":
                    signal_str = f"[#ff0000]{signal}[/]"
                else:
                    signal_str = f"[#ffb000]{signal}[/]"

                # AI Recommendation
                ai_rec = row.get("ai_rec", "")
                if ai_rec == "BUY":
                    ai_rec_str = "[#00ff00]BUY[/]"
                elif ai_rec == "SELL":
                    ai_rec_str = "[#ff0000]SELL[/]"
                elif ai_rec == "HOLD":
                    ai_rec_str = "[#ffb000]HOLD[/]"
                else:
                    ai_rec_str = "-"

                # Override signal and AI rec for protected tickers
                if is_protected:
                    signal_str = f"[#666666]LOCKED[/]"
                    ai_rec_str = f"[#666666]LOCKED[/]"

                # Consensus data
                cons = self.state.consensus_data.get(ticker)
                if cons:
                    cpct = cons.get("consensus_pct", 0) if isinstance(cons, dict) else getattr(cons, "consensus_pct", 0)
                    cconf = cons.get("confidence", 0) if isinstance(cons, dict) else getattr(cons, "confidence", 0)
                    # Use consensus probability when available; fall back to ML prob_up
                    cons_prob = cons.get("probability", prob_up) if isinstance(cons, dict) else getattr(cons, "probability", prob_up)
                    if cpct >= 80:
                        cons_str = f"[#00ff00]{cpct:.0f}%[/]"
                    elif cpct >= 60:
                        cons_str = f"[#ffb000]{cpct:.0f}%[/]"
                    else:
                        cons_str = f"[#ff0000]{cpct:.0f}%[/]"
                    conf_str = f"{cconf:.2f}"
                else:
                    cpct = 50.0
                    cons_prob = prob_up
                    cons_str = "-"
                    conf_str = "-"

                prob_str = f"{prob_up:.2f}"

                # News Sentiment
                news = self.state.news_sentiment.get(ticker)
                if news:
                    sent = news.sentiment if hasattr(news, 'sentiment') else news.get('sentiment', 0)
                    if sent > 0.2:
                        sent_str = f"[#00ff00]{sent:+.1f}[/]"
                    elif sent < -0.2:
                        sent_str = f"[#ff0000]{sent:+.1f}[/]"
                    else:
                        sent_str = f"[#ffb000]{sent:+.1f}[/]"
                else:
                    sent_str = "-"

                # Verdict — protected tickers are always LOCKED
                if is_protected:
                    verdict_str = "[#666666]LOCKED[/]"
                    row_bg = ""
                else:
                    verdict = compute_verdict(cons_prob, cpct)

                    # AI colour-grade override: external signal takes precedence
                    ai_grade = self.state.ai_color_grades.get(ticker, "").upper()
                    if ai_grade == "GREEN":
                        verdict = "STR BUY"
                    elif ai_grade == "RED":
                        verdict = "STR SELL"
                    elif ai_grade == "ORANGE":
                        verdict = "NEUTRAL"

                    if verdict in ("STR BUY", "BUY"):
                        row_bg = "#0a1a0a"
                    elif verdict in ("STR SELL", "SELL"):
                        row_bg = "#1a0a0a"
                    else:
                        row_bg = ""

                    # Verdict cell uses background for prominence (works on single cells)
                    if row_bg:
                        verdict_str = f"[bold {verdict_colors[verdict]} on {row_bg}] {verdict} [/]"
                    else:
                        verdict_str = f"[bold {verdict_colors[verdict]}]{verdict}[/]"

                # Strategy profile for this ticker
                _strat_colors: dict[str, str] = {
                    "conservative": "#888888",
                    "day_trader": "#00cccc",
                    "swing": "#cccc00",
                    "crisis_alpha": "#ff4444",
                    "trend_follower": "#00cc00",
                }
                strat_assign = self.state.strategy_assignments.get(ticker)
                if strat_assign:
                    sname = strat_assign.get("name", "") if isinstance(strat_assign, dict) else getattr(strat_assign, "profile", None) and strat_assign.profile.name or ""
                    scolor = _strat_colors.get(sname, "#aaaaaa")
                    strat_str = f"[{scolor}]{sname}[/]"
                else:
                    strat_str = "-"

                self.table.add_row(
                    ticker_display, verdict_str, live_px_str, day_pct_str,
                    prob_str, signal_str, ai_rec_str, cons_str, conf_str, sent_str, strat_str,
                )

        # Show held positions that aren't in the signals DF yet
        # (e.g. newly synced T212 positions before the pipeline re-runs)
        signal_tickers_upper = set()
        if self.state.signals is not None and hasattr(self.state.signals, 'empty') and not self.state.signals.empty:
            signal_tickers_upper = {str(t).upper() for t in self.state.signals["ticker"]}

        for pos in self.state.positions:
            ticker = pos.get("ticker", "")
            if not ticker or ticker.upper() in signal_tickers_upper:
                continue
            is_protected = ticker.upper() in protected_upper
            if is_protected:
                ticker_display = f"[reverse #ff8800][P]{ticker}*[/]"
            else:
                ticker_display = f"[reverse #00ffff]{ticker}*[/]"
            live_info = self.state.live_data.get(ticker, {})
            live_px = live_info.get("price", 0.0)
            day_pct = live_info.get("change_pct", 0.0)
            # Fallback to position price data
            if live_px == 0.0:
                live_px = pos.get("current_price", 0.0)
            live_px_str = f"${live_px:.2f}" if live_px > 0 else "-"
            if day_pct > 0:
                day_pct_str = f"[#00ff00]+{day_pct:.1f}%[/]"
            elif day_pct < 0:
                day_pct_str = f"[#ff0000]{day_pct:.1f}%[/]"
            else:
                day_pct_str = "-"
            signal_str = "[#666666]PENDING[/]"
            verdict_str = "[#666666]--[/]"
            self.table.add_row(
                ticker_display, verdict_str, live_px_str, day_pct_str, "-", signal_str,
                "-", "-", "-", "-",
            )

    def _render_polymarket_rows(self) -> None:
        """Render polymarket edge-based rows.

        Polymarket columns: Market | Mkt Prob | AI Prob | Edge % | Signal | Volume | Liquidity | Resolves | Conf | Category
        Data comes from consensus_data which stores edge detection results.
        """
        if self.state.signals is not None and not self.state.signals.empty:
            for _, row in self.state.signals.head(30).iterrows():
                question = str(row.get("ticker", row.get("question", "?")))
                # Truncate long questions
                if len(question) > 40:
                    question = question[:37] + "..."

                mkt_prob = float(row.get("market_prob", row.get("prob_up", 0.5)))
                ai_prob = float(row.get("ai_prob", mkt_prob))
                edge = float(row.get("edge_pct", (ai_prob - mkt_prob) * 100))
                signal = str(row.get("signal", "HOLD"))
                volume = float(row.get("volume", 0))
                liquidity = float(row.get("liquidity", 0))
                resolves = str(row.get("resolves", "-"))
                conf = float(row.get("confidence", 0))
                category = str(row.get("category", "-"))

                mkt_str = f"{mkt_prob:.0%}"
                ai_str = f"{ai_prob:.0%}"

                if edge > 3:
                    edge_str = f"[#00ff00]+{edge:.1f}%[/]"
                elif edge < -3:
                    edge_str = f"[#ff0000]{edge:.1f}%[/]"
                else:
                    edge_str = f"[#ffb000]{edge:+.1f}%[/]"

                if "BUY_YES" in signal.upper():
                    sig_str = "[#00ff00]BUY YES[/]"
                elif "BUY_NO" in signal.upper():
                    sig_str = "[#ff0000]BUY NO[/]"
                else:
                    sig_str = f"[#ffb000]{signal}[/]"

                vol_str = f"${volume:,.0f}" if volume > 0 else "-"
                liq_str = f"${liquidity:,.0f}" if liquidity > 0 else "-"
                conf_str = f"{conf:.2f}" if conf > 0 else "-"

                self.table.add_row(
                    question, mkt_str, ai_str, edge_str, sig_str,
                    vol_str, liq_str, resolves, conf_str, category,
                )
        elif not self.state.consensus_data:
            self.table.add_row("No markets loaded", "-", "-", "-", "-", "-", "-", "-", "-", "-")


# ═══════════════════════════════════════════════════════════════════════
#  POSITIONS VIEW
# ═══════════════════════════════════════════════════════════════════════

class PositionsView(Panel):
    def __init__(self, state: AppState) -> None:
        super().__init__("POSITIONS", id="positions-panel")
        self.state = state
        self.table = DataTable(cursor_type="row")

    def compose(self) -> ComposeResult:
        yield Label(self.panel_title, classes="panel-title")
        yield self.table

    def on_mount(self) -> None:
        self.table.add_columns("Ticker", "Qty", "Avg Px", "Cur Px", "PnL")
        self.refresh_view()

    def refresh_view(self) -> None:
        self.table.clear()
        if not self.state.positions:
            self.table.add_row("No Positions", "-", "-", "-", "-")
            return

        for p in self.state.positions:
            ticker = p.get("ticker", "")
            qty = f"{p.get('quantity', 0):.2f}"
            avg = f"${p.get('avg_price', 0.0):.2f}"
            cur = f"${p.get('current_price', 0.0):.2f}"
            pnl = p.get("unrealised_pnl", 0.0)
            pnl_color = "[#00ff00]" if pnl >= 0 else "[#ff0000]"
            pnl_str = f"{pnl_color}${pnl:.2f}[/]"

            # Highlighting ticker in cyan
            ticker_str = f"[#00ffff]{ticker}[/]"
            self.table.add_row(ticker_str, qty, avg, cur, pnl_str)


# ═══════════════════════════════════════════════════════════════════════
#  ORDERS VIEW
# ═══════════════════════════════════════════════════════════════════════

class OrdersView(Panel):
    def __init__(self, state: AppState) -> None:
        super().__init__("ORDERS", id="orders-panel")
        self.state = state
        self.table = DataTable(cursor_type="row")

    def compose(self) -> ComposeResult:
        yield Label(self.panel_title, classes="panel-title")
        yield self.table

    def on_mount(self) -> None:
        self.table.add_columns("Ticker", "Side", "Qty", "Type", "Status")
        self.refresh_view()

    def refresh_view(self) -> None:
        self.table.clear()
        if self.state.recent_orders:
            for order in self.state.recent_orders[-20:]:
                ticker = order.get('ticker', 'N/A')
                side = order.get('side', 'N/A')
                qty = order.get('quantity', 0)
                otype = order.get('order_type', 'market')
                status = order.get('status', 'FILLED')

                if side.upper() == 'BUY':
                    side_str = f"[#00ff00]BUY[/]"
                elif side.upper() == 'SELL':
                    side_str = f"[#ff0000]SELL[/]"
                else:
                    side_str = side

                self.table.add_row(ticker, side_str, str(qty), otype, status)
        else:
            self.table.add_row("No Orders", "-", "-", "-", "-")


# ═══════════════════════════════════════════════════════════════════════
#  METRICS / SETTINGS VIEW
# ═══════════════════════════════════════════════════════════════════════

class SettingsView(Panel):
    def __init__(self, state: AppState) -> None:
        super().__init__("TERMINAL METRICS", id="settings-panel")
        self.state = state
        self.metrics_label = Label()

    def compose(self) -> ComposeResult:
        yield Label(self.panel_title, classes="panel-title")
        yield self.metrics_label

    def on_mount(self) -> None:
        self.refresh_view()

    def refresh_view(self) -> None:
        mode_color = "[#00ff00]" if self.state.mode == "full_auto_limited" else "[#ffb000]"
        upnl = self.state.unrealised_pnl
        upnl_color = "[#00ff00]" if upnl >= 0 else "[#ff0000]"

        acct = self.state.account_info
        balance = acct.get("free", self.state.capital)
        invested = acct.get("invested", 0.0)
        total = acct.get("total", self.state.capital)

        regime = self.state.current_regime
        regime_colors = {
            "trending_up": "#00ff00", "trending_down": "#ff0000",
            "mean_reverting": "#ffb000", "high_volatility": "#ff4444",
            "unknown": "#666666",
        }
        regime_color = regime_colors.get(regime, "#666666")

        # Active strategy for current regime
        _strat_colors: dict[str, str] = {
            "conservative": "#888888", "day_trader": "#00cccc",
            "swing": "#cccc00", "crisis_alpha": "#ff4444",
            "trend_follower": "#00cc00",
        }
        regime_strat = self.state.regime_strategy_map.get(regime, "")
        strat_color = _strat_colors.get(regime_strat, "#aaaaaa")

        _asset_colors: dict[str, str] = {
            "stocks": "#00ff00", "crypto": "#ff9900", "polymarket": "#00bbff",
        }
        asset = self.state.active_asset_class
        asset_color = _asset_colors.get(asset, "#ffffff")

        lines = [
            f"Asset:      [{asset_color}]{asset.upper()}[/]",
            f"Mode:       {mode_color}{self.state.mode}[/]",
            f"Regime:     [{regime_color}]{regime}[/] ({self.state.regime_confidence:.0%})",
            f"Strategy:   [{strat_color}]{regime_strat or '-'}[/]",
            f"Models:     [#ffffff]{self.state.ensemble_model_count}[/]",
            f"Balance:    [#ffffff]${balance:,.2f}[/]",
            f"Invested:   [#ffffff]${invested:,.2f}[/]",
            f"Total:      [#ffffff]${total:,.2f}[/]",
            f"Unrlzd PnL: {upnl_color}${upnl:,.2f}[/]",
            f"Max Loss:   [#ffffff]{self.state.max_daily_loss * 100:.1f}%[/]",
        ]
        self.metrics_label.update("\n".join(lines))


# ═══════════════════════════════════════════════════════════════════════
#  AI INSIGHTS VIEW
# ═══════════════════════════════════════════════════════════════════════

class AiInsightsView(Panel):
    def __init__(self, state: AppState) -> None:
        super().__init__("AI INSIGHTS", id="ai-insights-panel")
        self.state = state
        self.insights_label = Label(self.state.ai_insights)

    def compose(self) -> ComposeResult:
        yield Label(self.panel_title, classes="panel-title")
        yield self.insights_label

    def refresh_view(self) -> None:
        self.insights_label.update(self.state.ai_insights)


# ═══════════════════════════════════════════════════════════════════════
#  NEWS SENTIMENT VIEW
# ═══════════════════════════════════════════════════════════════════════

class NewsView(Panel):
    def __init__(self, state: AppState) -> None:
        super().__init__("NEWS SENTIMENT", id="news-panel")
        self.state = state
        self.news_label = Label("Fetching news...")

    def compose(self) -> ComposeResult:
        yield Label(self.panel_title, classes="panel-title")
        yield VerticalScroll(self.news_label, id="news-scroll")

    def refresh_view(self) -> None:
        if not self.state.news_sentiment:
            self.news_label.update("No news data yet. Agent running in background...")
            return

        lines = []
        for ticker, nd in self.state.news_sentiment.items():
            if hasattr(nd, 'sentiment'):
                sent = nd.sentiment
                summary = nd.summary
                headlines = nd.headlines[:3]
            elif isinstance(nd, dict):
                sent = nd.get('sentiment', 0)
                summary = nd.get('summary', '')
                headlines = nd.get('headlines', [])[:3]
            else:
                continue

            if sent > 0.2:
                color = "#00ff00"
            elif sent < -0.2:
                color = "#ff0000"
            else:
                color = "#ffb000"

            lines.append(f"[{color}]■[/] {ticker} ({sent:+.2f}): {summary}")
            for h in headlines:
                lines.append(f"  • {h[:60]}")
            lines.append("")

        self.news_label.update("\n".join(lines) if lines else "No news data.")


# ═══════════════════════════════════════════════════════════════════════
#  RESEARCH VIEW
# ═══════════════════════════════════════════════════════════════════════

class ResearchView(Panel):
    """Shows autoresearch experiment history, scores, and current config."""

    def __init__(self, state: AppState) -> None:
        super().__init__("RESEARCH LAB", id="research-panel")
        self.state = state
        self.content_label = Label("Loading research data...")

    def compose(self) -> ComposeResult:
        yield Label(self.panel_title, classes="panel-title")
        yield VerticalScroll(self.content_label, id="research-scroll")

    def on_mount(self) -> None:
        self.refresh_view()

    def refresh_view(self) -> None:
        experiments = self.state.research_experiments
        best = self.state.research_best_score
        total = self.state.research_total_experiments
        cfg = self.state.research_current_config
        running = self.state.research_is_running
        live = self.state.research_live_progress

        lines: list[str] = []

        # Status header
        if running:
            status_color = "#00ff00"
            status_text = "RUNNING"
        elif live.get("status") == "complete":
            status_color = "#00bfff"
            status_text = "LAST RUN COMPLETE"
        else:
            status_color = "#666666"
            status_text = "IDLE"
        lines.append(f"Status: [{status_color}]{status_text}[/]  |  "
                      f"Experiments: [#ffffff]{total}[/]  |  "
                      f"Best: [#00ff00]{best:.1f}[/]")

        # Live progress detail
        if running and live:
            elapsed = live.get("elapsed_seconds", 0)
            detail = live.get("detail", "")
            live_cfg = live.get("config", {})
            lines.append(
                f"  [#00bfff]>>> Evaluating:[/] {detail}"
                f"  [#666666]({elapsed:.0f}s elapsed"
                f"  buy={live_cfg.get('threshold_buy', '?')}"
                f"  sell={live_cfg.get('threshold_sell', '?')})[/]"
            )
        lines.append("")

        # Current config summary (from train.py)
        if cfg:
            strat = cfg.get("strategy", {})
            risk = cfg.get("risk", {})
            lines.append("[#ffb000]Best Config (train.py):[/]")
            lines.append(
                f"  Buy={strat.get('threshold_buy', '?')}"
                f"  Sell={strat.get('threshold_sell', '?')}"
                f"  Pos={strat.get('max_positions', '?')}"
                f"  Size={strat.get('position_size_fraction', '?')}"
            )
            lines.append(
                f"  Stop={risk.get('atr_stop_multiplier', '?')}×ATR"
                f"  TP={risk.get('atr_profit_multiplier', '?')}×ATR"
                f"  Universe={cfg.get('universe', '?')}"
            )
            lines.append("")

        # Experiment log
        if experiments:
            lines.append("[#ffb000]Recent Experiments:[/]")
            for exp in experiments[:15]:
                score = exp.get("score")
                msg = exp.get("message", "")
                time_str = exp.get("time", "")
                commit_hash = exp.get("hash", "")

                if score is not None:
                    if score >= 60:
                        s_color = "#00ff00"
                    elif score >= 45:
                        s_color = "#ffb000"
                    else:
                        s_color = "#ff0000"
                    score_str = f"[{s_color}]{score:5.1f}[/]"
                else:
                    score_str = "[#666666]  ---[/]"

                # Truncate message, strip "exp: " prefix
                display_msg = msg
                if display_msg.lower().startswith("exp:"):
                    display_msg = display_msg[4:].strip()
                # Strip score from display (already shown separately)
                display_msg = _SCORE_STRIP_RE.sub("", display_msg).strip()
                if len(display_msg) > 50:
                    display_msg = display_msg[:47] + "..."

                lines.append(
                    f"  [#666666]{commit_hash}[/] {score_str}  {display_msg}"
                )
        else:
            lines.append("[#666666]No experiments yet. Start autoresearch to begin.[/]")

        self.content_label.update("\n".join(lines))


import re as _re
_SCORE_STRIP_RE = _re.compile(r"score\s*=\s*[\d.]+", _re.IGNORECASE)


# ═══════════════════════════════════════════════════════════════════════
#  CHAT VIEW
# ═══════════════════════════════════════════════════════════════════════

class ChatView(Panel):
    def __init__(self, state: AppState) -> None:
        super().__init__("AI ASSISTANT", id="chat-panel")
        self.state = state
        self.messages_label = Label("Type a message and press Enter to chat with AI.\n", id="chat-messages")
        self.chat_input = Input(placeholder="Ask AI anything...", id="chat-input")

    def compose(self) -> ComposeResult:
        yield Label(self.panel_title, classes="panel-title")
        yield VerticalScroll(self.messages_label, id="chat-scroll")
        yield self.chat_input

    def refresh_view(self) -> None:
        lines = []
        for msg in self.state.chat_history[-20:]:
            role = msg.get("role", "user")
            text = msg.get("text", "")
            if role == "user":
                lines.append(f"[#00bfff]You:[/] {text}")
            else:
                lines.append(f"[#ffb000]AI:[/] {text}")
            lines.append("")
        if lines:
            self.messages_label.update("\n".join(lines))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "chat-input" and event.value.strip():
            # Dispatch to app
            self.app.handle_chat_message(event.value.strip())
            event.input.value = ""


# ═══════════════════════════════════════════════════════════════════════
#  ADD TICKER MODAL
# ═══════════════════════════════════════════════════════════════════════

class AddTickerModal(ModalScreen):
    BINDINGS = [("escape", "dismiss_modal", "Cancel")]
    DEFAULT_CSS = """
    AddTickerModal {
        align: center middle;
    }
    #add-ticker-dialog {
        width: 50;
        height: 14;
        border: solid #ffb000;
        background: #111111;
        padding: 1 2;
    }
    """
    def compose(self) -> ComposeResult:
        with Vertical(id="add-ticker-dialog"):
            yield Label("[#ffb000]ADD TICKER[/]", classes="panel-title")
            yield Label("[#666666](Press Esc to cancel)[/]")
            yield Input(placeholder="Enter ticker symbol (e.g., NVDA)", id="ticker-input")
            with Horizontal():
                yield Button("Add", variant="success", id="btn-add")
                yield Button("Cancel", variant="error", id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-add":
            inp = self.query_one("#ticker-input", Input)
            ticker = inp.value.strip().upper()
            if ticker:
                self.dismiss(ticker)
            else:
                self.dismiss(None)
        else:
            self.dismiss(None)

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)


# ═══════════════════════════════════════════════════════════════════════
#  TRADE MODAL
# ═══════════════════════════════════════════════════════════════════════

class TradeModal(ModalScreen):
    BINDINGS = [("escape", "dismiss_modal", "Cancel")]
    DEFAULT_CSS = """
    TradeModal {
        align: center middle;
    }
    #trade-dialog {
        width: 55;
        height: 24;
        border: solid #ffb000;
        background: #111111;
        padding: 1 2;
    }
    .trade-row {
        height: 3;
        margin-bottom: 1;
    }
    """
    def __init__(self, ticker: str = "") -> None:
        super().__init__()
        self._ticker = ticker

    def compose(self) -> ComposeResult:
        with Vertical(id="trade-dialog"):
            yield Label(f"[#ffb000]TRADE – {self._ticker}[/]", classes="panel-title")
            yield Label("[#666666](Press Esc to cancel)[/]")

            # Side
            yield Label("Side:")
            yield Select(
                [("BUY", "BUY"), ("SELL", "SELL")],
                value="BUY",
                id="trade-side",
            )

            # Quantity
            yield Label("Quantity:")
            yield Input(placeholder="1.0", id="trade-qty", type="number")

            # Order type
            yield Label("Order Type:")
            yield Select(
                [("Market", "market"), ("Limit", "limit"), ("Stop", "stop")],
                value="market",
                id="trade-type",
            )

            # Limit / Stop price
            yield Label("Price (for limit/stop):")
            yield Input(placeholder="Leave empty for market", id="trade-price", type="number")

            with Horizontal():
                yield Button("Submit Order", variant="success", id="btn-submit-trade")
                yield Button("Cancel", variant="error", id="btn-cancel-trade")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-submit-trade":
            side = self.query_one("#trade-side", Select).value
            qty_raw = self.query_one("#trade-qty", Input).value.strip()
            otype = self.query_one("#trade-type", Select).value
            price_raw = self.query_one("#trade-price", Input).value.strip()

            try:
                qty = float(qty_raw) if qty_raw else 1.0
            except ValueError:
                qty = 1.0

            price = None
            try:
                if price_raw:
                    price = float(price_raw)
            except ValueError:
                pass

            self.dismiss({
                "ticker": self._ticker,
                "side": side,
                "quantity": qty,
                "order_type": otype,
                "price": price,
            })
        else:
            self.dismiss(None)

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)


# ═══════════════════════════════════════════════════════════════════════
#  SEARCH TICKER MODAL
# ═══════════════════════════════════════════════════════════════════════

class SearchTickerModal(ModalScreen):
    BINDINGS = [("escape", "dismiss_modal", "Close")]
    DEFAULT_CSS = """
    SearchTickerModal {
        align: center middle;
    }
    #search-dialog {
        width: 70;
        height: 22;
        border: solid #ffb000;
        background: #111111;
        padding: 1 2;
    }
    """
    def compose(self) -> ComposeResult:
        with Vertical(id="search-dialog"):
            yield Label("[#ffb000]SEARCH TICKERS[/]", classes="panel-title")
            yield Label("[#666666](Press Esc to close)[/]")
            yield Label("Search by name, sector, or theme (e.g. 'AI companies', 'semiconductors')")
            yield Input(placeholder="Type to search...", id="search-input")
            yield Label("", id="search-status")
            self._results_table = DataTable(cursor_type="row", id="search-results")
            yield self._results_table
            with Horizontal():
                yield Button("Add Selected", variant="success", id="btn-search-add")
                yield Button("Close", variant="error", id="btn-search-close")

    def on_mount(self) -> None:
        self._results_table.add_columns("Ticker", "Company", "Sector")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search-input" and event.value.strip():
            query = event.value.strip()
            self.query_one("#search-status", Label).update("[#ffb000]Searching...[/]")
            self.app.search_tickers_for_modal(query, self._on_results)

    def _on_results(self, results: list) -> None:
        self._results_table.clear()
        if results:
            for r in results:
                self._results_table.add_row(
                    r.get("ticker", ""),
                    r.get("name", ""),
                    r.get("sector", ""),
                )
            self.query_one("#search-status", Label).update(
                f"[#00ff00]Found {len(results)} results.[/]"
            )
        else:
            self.query_one("#search-status", Label).update(
                "[#ff0000]No results found.[/]"
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-search-add":
            try:
                row_idx = self._results_table.cursor_row
                row_data = self._results_table.get_row_at(row_idx)
                if row_data:
                    self.dismiss(str(row_data[0]))
                    return
            except Exception:
                pass
            self.dismiss(None)
        else:
            self.dismiss(None)

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)


# ═══════════════════════════════════════════════════════════════════════
#  AI RECOMMEND TICKERS MODAL
# ═══════════════════════════════════════════════════════════════════════

class AiRecommendModal(ModalScreen):
    BINDINGS = [("escape", "dismiss_modal", "Close")]
    DEFAULT_CSS = """
    AiRecommendModal {
        align: center middle;
    }
    #recommend-dialog {
        width: 75;
        height: 22;
        border: solid #ffb000;
        background: #111111;
        padding: 1 2;
    }
    """
    def compose(self) -> ComposeResult:
        with Vertical(id="recommend-dialog"):
            yield Label("[#ffb000]AI TICKER RECOMMENDATIONS[/]", classes="panel-title")
            yield Label("[#666666](Press Esc to close)[/]")
            yield Label("Optional: specify a category (e.g. 'AI', 'biotech', 'dividends'):")
            yield Input(placeholder="Leave blank for general recommendations", id="rec-category")
            yield Button("Get Recommendations", variant="primary", id="btn-get-recs")
            yield Label("", id="rec-status")
            self._rec_table = DataTable(cursor_type="row", id="rec-results")
            yield self._rec_table
            with Horizontal():
                yield Button("Add Selected", variant="success", id="btn-rec-add")
                yield Button("Add All", variant="warning", id="btn-rec-add-all")
                yield Button("Close", variant="error", id="btn-rec-close")

    def on_mount(self) -> None:
        self._rec_table.add_columns("Ticker", "Reason")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-get-recs":
            category = self.query_one("#rec-category", Input).value.strip()
            self.query_one("#rec-status", Label).update("[#ffb000]AI is thinking...[/]")
            self.app.get_ai_recommendations(category, self._on_results)

        elif event.button.id == "btn-rec-add":
            try:
                row_idx = self._rec_table.cursor_row
                row_data = self._rec_table.get_row_at(row_idx)
                if row_data:
                    self.dismiss({"mode": "single", "ticker": str(row_data[0])})
                    return
            except Exception:
                pass
            self.dismiss(None)

        elif event.button.id == "btn-rec-add-all":
            tickers = []
            for i in range(self._rec_table.row_count):
                try:
                    row = self._rec_table.get_row_at(i)
                    if row:
                        tickers.append(str(row[0]))
                except Exception:
                    pass
            if tickers:
                self.dismiss({"mode": "all", "tickers": tickers})
            else:
                self.dismiss(None)

        elif event.button.id == "btn-rec-close":
            self.dismiss(None)

    def _on_results(self, results: list) -> None:
        self._rec_table.clear()
        if results:
            for r in results:
                self._rec_table.add_row(
                    r.get("ticker", ""),
                    r.get("reason", ""),
                )
            self.query_one("#rec-status", Label).update(
                f"[#00ff00]AI recommended {len(results)} tickers.[/]"
            )
        else:
            self.query_one("#rec-status", Label).update(
                "[#ff0000]Could not generate recommendations.[/]"
            )

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)


# ═══════════════════════════════════════════════════════════════════════
#  HELP MODAL
# ═══════════════════════════════════════════════════════════════════════

class HelpModal(ModalScreen):
    BINDINGS = [
        ("escape", "dismiss_modal", "Close"),
        ("question_mark", "dismiss_modal", "Close"),
    ]
    DEFAULT_CSS = """
    HelpModal {
        align: center middle;
    }
    #help-dialog {
        width: 72;
        height: 38;
        border: solid #ffb000;
        background: #111111;
        padding: 1 2;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="help-dialog"):
            yield Label("[#ffb000 bold]TERMINAL HELP — KEYBOARD SHORTCUTS[/]", classes="panel-title")
            yield Label("[#666666]Press ? or Esc to close[/]\n")
            yield VerticalScroll(Label(self._help_text(), id="help-content"), id="help-scroll")
            yield Button("Close", variant="error", id="btn-help-close")

    @staticmethod
    def _help_text() -> str:
        return (
            "[#00bfff bold]─── ASSET CLASS ───[/]\n"
            "  [#ffffff]1[/]         Switch to Stocks\n"
            "  [#ffffff]2[/]         Switch to Polymarket\n"
            "  [#ffffff]3[/]         Switch to Crypto\n"
            "\n"
            "[#00bfff bold]─── NAVIGATION ───[/]\n"
            "  [#ffffff]?[/]         Show this help screen\n"
            "  [#ffffff]q[/]         Quit terminal\n"
            "  [#ffffff]r[/]         Force refresh data & signals\n"
            "  [#ffffff]w[/]         Cycle through watchlists\n"
            "  [#ffffff]g[/]         Show price chart for selected ticker\n"
            "  [#ffffff]c[/]         Focus chat input\n"
            "\n"
            "[#00bfff bold]─── TRADING ───[/]\n"
            "  [#ffffff]a[/]         Toggle mode (Advisor / Auto-Trade)\n"
            "  [#ffffff]t[/]         Open trade dialog for selected ticker\n"
            "  [#ffffff]l[/]         Lock/unlock ticker (prevent AI trading)\n"
            "\n"
            "[#00bfff bold]─── WATCHLIST ───[/]\n"
            "  [#ffffff]+  (=)[/]    Add ticker to watchlist\n"
            "  [#ffffff]-[/]         Remove selected ticker\n"
            "  [#ffffff]/[/]         Search tickers (AI-powered)\n"
            "  [#ffffff]d[/]         AI recommend tickers to add\n"
            "\n"
            "[#00bfff bold]─── AI & ANALYSIS ───[/]\n"
            "  [#ffffff]s[/]         AI suggest a new ticker\n"
            "  [#ffffff]i[/]         Generate AI portfolio insights\n"
            "  [#ffffff]o[/]         Run AI optimizer (tune weights)\n"
            "  [#ffffff]n[/]         Refresh news sentiment\n"
            "\n"
            "[#00bfff bold]─── BROKER / HISTORY ───[/]\n"
            "  [#ffffff]h[/]         Show order history\n"
            "  [#ffffff]p[/]         Show pies\n"
            "  [#ffffff]e[/]         Browse instruments\n"
            "\n"
            "[#00bfff bold]─── WATCHLIST COLUMNS ───[/]\n"
            "  [#ffffff]Verdict[/]   Hierarchical AI judgment (STR BUY→STR SELL)\n"
            "  [#ffffff]Live Px[/]   Real-time price (T212 / yfinance)\n"
            "  [#ffffff]Day %[/]     Daily change percentage\n"
            "  [#ffffff]Prob[/]      ML ensemble probability (0-1)\n"
            "  [#ffffff]Signal[/]    BUY / SELL / HOLD\n"
            "  [#ffffff]AI Rec[/]    Claude persona recommendation\n"
            "  [#ffffff]Consensus[/] % agreement across 12 models\n"
            "  [#ffffff]Conf[/]      Signal confidence score\n"
            "  [#ffffff]Sentiment[/] News sentiment (-1 to +1)\n"
            "\n"
            "[#00bfff bold]─── SYMBOLS ───[/]\n"
            "  [#ff8800][P][/]        Locked ticker (trading disabled)\n"
            "  [#00ffff]*[/]         Ticker with open position\n"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-help-close":
            self.dismiss(None)

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)
