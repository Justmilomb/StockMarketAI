"""Unit tests for core.alt_data.open_insider cluster scraper."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.alt_data import _cache, open_insider


def setup_function() -> None:
    _cache._store.clear()


def _row(filing: str, trade: str, ticker: str, company: str, insider: str,
         title: str, ttype: str, price: str, qty: str, owned: str, delta: str,
         value: str) -> str:
    cells = ["", filing, trade, ticker, company, insider, title, ttype, price,
             qty, owned, delta, value]
    return "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"


def test_fetch_failure_returns_error() -> None:
    with patch("core.alt_data.open_insider.requests.get", side_effect=RuntimeError("down")):
        result = open_insider.insider_activity("AAPL")
    assert "error" in result


def test_insider_activity_parses_buys_and_sells() -> None:
    rows = [
        _row("2026-04-15", "2026-04-14", "AAPL", "Apple", "Alice CEO",
             "CEO", "P - Purchase", "$200.00", "1000", "5000", "+25", "$200,000"),
        _row("2026-04-10", "2026-04-09", "AAPL", "Apple", "Bob CFO",
             "CFO", "S - Sale", "$210.00", "500", "4500", "-10", "$105,000"),
        _row("2026-04-05", "2026-04-04", "AAPL", "Apple", "Alice CEO",
             "CEO", "P - Purchase", "$195.00", "500", "4000", "+14", "$97,500"),
        _row("2026-04-01", "2026-03-31", "AAPL", "Apple", "Eve Dir",
             "Director", "A - Award", "$0", "100", "100", "+100", "$0"),
    ]
    html = "<html><body><table>" + "".join(rows) + "</table></body></html>"
    mock_resp = MagicMock()
    mock_resp.text = html
    mock_resp.raise_for_status.return_value = None
    with patch("core.alt_data.open_insider.requests.get", return_value=mock_resp):
        result = open_insider.insider_activity("AAPL")

    assert result["ticker"] == "AAPL"
    assert result["total_transactions"] == 3  # award excluded
    assert result["buy_count"] == 2
    assert result["sell_count"] == 1
    assert result["total_buy_value_usd"] == 297_500
    assert result["total_sell_value_usd"] == 105_000
    assert result["net_bias"] == "buy-heavy"
    top_names = [row["name"] for row in result["top_insiders"]]
    assert top_names[0] == "Alice CEO"


def test_no_transactions_reports_no_activity() -> None:
    mock_resp = MagicMock()
    mock_resp.text = "<html><body>no table here</body></html>"
    mock_resp.raise_for_status.return_value = None
    with patch("core.alt_data.open_insider.requests.get", return_value=mock_resp):
        result = open_insider.insider_activity("ZZZZ")
    assert result["total_transactions"] == 0
    assert result["net_bias"] == "no_activity"
    assert "note" in result
