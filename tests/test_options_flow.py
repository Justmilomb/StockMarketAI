from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd

from core.scrapers.options_flow import unusual_activity


def _fake_option_chain():
    calls = pd.DataFrame({
        "strike": [100.0, 105.0, 110.0, 115.0],
        "volume": [10, 2000, 50, 10],
        "openInterest": [500, 100, 800, 400],
        "impliedVolatility": [0.3, 0.5, 0.32, 0.31],
    })
    puts = pd.DataFrame({
        "strike": [100.0],
        "volume": [10],
        "openInterest": [500],
        "impliedVolatility": [0.3],
    })
    chain = MagicMock()
    chain.calls = calls
    chain.puts = puts

    ticker_obj = MagicMock()
    from datetime import datetime, timedelta, timezone
    future = (datetime.now(timezone.utc).date() + timedelta(days=14)).strftime("%Y-%m-%d")
    ticker_obj.options = [future]
    ticker_obj.option_chain = MagicMock(return_value=chain)
    ticker_obj.history = MagicMock(return_value=pd.DataFrame({"Close": [104.0]}))
    return ticker_obj


def test_unusual_activity_flags_spike():
    with patch("yfinance.Ticker", return_value=_fake_option_chain()):
        hits = unusual_activity("TSLA")
    assert any(h["side"] == "call" and h["strike"] == 105.0 for h in hits)
    assert hits[0]["vol_oi_ratio"] >= 3.0


def test_unusual_activity_empty_on_no_yfinance():
    with patch("yfinance.Ticker", side_effect=Exception("boom")):
        hits = unusual_activity("TSLA")
    assert hits == []
