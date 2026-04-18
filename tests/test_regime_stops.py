from __future__ import annotations

from core.risk_manager import RiskManager


def test_regime_multiplier_low_vol():
    rm = RiskManager()
    mult = rm.regime_atr_multiplier(atr=0.5, price=100.0)
    assert abs(mult - 2.0) < 1e-6


def test_regime_multiplier_mid_vol():
    rm = RiskManager()
    mult = rm.regime_atr_multiplier(atr=2.0, price=100.0)
    assert abs(mult - 3.0) < 1e-6


def test_regime_multiplier_high_vol():
    rm = RiskManager()
    mult = rm.regime_atr_multiplier(atr=5.0, price=100.0)
    assert abs(mult - 4.0) < 1e-6


def test_regime_multiplier_zero_price_fallback():
    rm = RiskManager()
    assert rm.regime_atr_multiplier(atr=1.0, price=0.0) == rm._atr_stop_multiplier
    assert rm.regime_atr_multiplier(atr=0.0, price=100.0) == rm._atr_stop_multiplier


def test_compute_stop_loss_uses_regime_when_requested():
    rm = RiskManager()
    stop = rm.compute_stop_loss(entry_price=100.0, atr=5.0, side="BUY", regime_adjust=True)
    assert abs(stop - 80.0) < 1e-6

    stop_low = rm.compute_stop_loss(entry_price=100.0, atr=0.5, side="BUY", regime_adjust=True)
    assert abs(stop_low - 99.0) < 1e-6


def test_compute_stop_loss_default_unchanged():
    rm = RiskManager()
    stop = rm.compute_stop_loss(entry_price=100.0, atr=5.0, side="BUY")
    assert abs(stop - 90.0) < 1e-6


def test_compute_take_profit_regime_widens_target():
    rm = RiskManager()
    tp = rm.compute_take_profit(entry_price=100.0, atr=5.0, side="BUY", regime_adjust=True)
    assert abs(tp - 130.0) < 1e-6


def test_compute_stop_loss_sell_side():
    rm = RiskManager()
    stop = rm.compute_stop_loss(entry_price=100.0, atr=5.0, side="SELL", regime_adjust=True)
    assert abs(stop - 120.0) < 1e-6
