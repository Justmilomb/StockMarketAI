"""Unit tests for core.alt_data.fred."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.alt_data import _cache, fred


def setup_function() -> None:
    _cache._store.clear()


def test_series_observations_missing_key() -> None:
    with patch.dict("os.environ", {"FRED_KEY": ""}, clear=False):
        result = fred.series_observations("DGS10")
    assert "error" in result
    assert "FRED_KEY" in result["error"]


def test_series_observations_happy_path() -> None:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "observations": [
            {"date": "2026-04-19", "value": "4.35"},
            {"date": "2026-04-18", "value": "4.30"},
            {"date": "2026-04-17", "value": "."},
            {"date": "2026-04-16", "value": "4.28"},
        ],
    }
    mock_resp.raise_for_status.return_value = None
    with patch.dict("os.environ", {"FRED_KEY": "test"}, clear=False), \
         patch("core.alt_data.fred.requests.get", return_value=mock_resp):
        result = fred.series_observations("DGS10")
    assert result["series_id"] == "DGS10"
    obs = result["observations"]
    assert len(obs) == 3
    assert all(o["value"] != "." for o in obs)
    assert obs[0]["value"] == "4.35"


def test_series_observations_surfaces_fred_error_message() -> None:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"error_message": "Bad series ID"}
    mock_resp.raise_for_status.return_value = None
    with patch.dict("os.environ", {"FRED_KEY": "test"}, clear=False), \
         patch("core.alt_data.fred.requests.get", return_value=mock_resp):
        result = fred.series_observations("NOPE")
    assert result == {"error": "Bad series ID"}


def test_macro_snapshot_computes_cpi_yoy() -> None:
    def fake_obs(series_id: str, limit: int = 5, ttl: int = 3600):
        if series_id == "CPIAUCSL":
            return {"series_id": series_id, "observations": [
                {"date": "2026-04-01", "value": "320.0"},
                *[{"date": f"2026-{m:02d}-01", "value": "315.0"} for m in range(3, 0, -1)],
                *[{"date": f"2025-{m:02d}-01", "value": "308.0"} for m in range(12, 3, -1)],
            ]}
        if series_id == "T10Y2Y":
            return {"series_id": series_id, "observations": [{"date": "2026-04-19", "value": "-0.12"}]}
        return {"series_id": series_id, "observations": [{"date": "2026-04-19", "value": "4.35"}]}

    with patch.dict("os.environ", {"FRED_KEY": "test"}, clear=False), \
         patch("core.alt_data.fred.series_observations", side_effect=fake_obs):
        snap = fred.macro_snapshot()
    cpi = snap["cpi"]
    assert cpi["yoy_pct"] == round((320.0 / 308.0 - 1) * 100, 2)
    assert snap["yield_curve"] == "inverted"
