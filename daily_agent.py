from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import numpy as np

from broker import LogBroker, LogBrokerConfig
from data_loader import fetch_universe_data
from features import build_universe_dataset, latest_feature_rows_per_ticker
from model import ModelConfig, load_model, train_model
from strategy import StrategyConfig, generate_signals


def load_config(path: Path | str = "config.json") -> Dict[str, Any]:
    cfg_path = Path(path)
    with cfg_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    config = load_config()

    tickers = config["tickers"]
    start_date = config["start_date"]
    end_date = config["end_date"]
    data_dir = Path(config.get("data_dir", "data"))
    model_path = Path(config.get("model_path", "models/rf_tomorrow_up.joblib"))

    print(f"[agent] Universe: {tickers}")
    print(f"[agent] Date range: {start_date} -> {end_date}")

    # 1) Load raw data for all tickers
    universe_data = fetch_universe_data(
        tickers=tickers,
        start_date=start_date,
        end_date=end_date,
        data_dir=data_dir,
        use_cache=True,
    )

    # 2) Build training dataset
    X, y, meta = build_universe_dataset(universe_data)

    # 3) Train or load model
    model_cfg = ModelConfig(model_path=model_path)
    if model_path.exists():
        print(f"[agent] Loading existing model from {model_path}")
        clf = load_model(model_path)
    else:
        print("[agent] Training new model...")
        clf = train_model(X, y, meta, config=model_cfg)

    # 4) Compute latest feature row per ticker for today’s signals
    latest_features_df, latest_meta_df = latest_feature_rows_per_ticker(universe_data)
    latest_X = latest_features_df.to_numpy(dtype=float)

    # 5) Predict probability that tomorrow's close will be higher
    prob_up = clf.predict_proba(latest_X)[:, 1]

    strat_cfg_raw = config.get("strategy", {})
    strat_cfg = StrategyConfig(
        threshold_buy=strat_cfg_raw.get("threshold_buy", 0.6),
        threshold_sell=strat_cfg_raw.get("threshold_sell", 0.4),
        max_positions=strat_cfg_raw.get("max_positions", 5),
        position_size_fraction=strat_cfg_raw.get("position_size_fraction", 0.2),
    )

    signals_df = generate_signals(prob_up, latest_meta_df, strat_cfg)
    print("[agent] Today's signals:")
    print(signals_df)

    # 6) Route buy signals through broker abstraction (LogBroker for now)
    capital = float(config.get("capital", 100_000))
    broker = LogBroker(LogBrokerConfig())

    buy_signals = signals_df[signals_df["signal"] == "buy"]
    if buy_signals.empty:
        print("[agent] No buy signals for today.")
        return

    position_size = capital * strat_cfg.position_size_fraction
    print(f"[agent] Using notional position size per trade: {position_size}")

    for _, row in buy_signals.iterrows():
        ticker = row["ticker"]
        # In a real system we would fetch the latest price to size quantity.
        # For now we submit a unit quantity as a placeholder.
        broker.submit_order(
            ticker=ticker,
            side="buy",
            quantity=1.0,
            order_type="market",
        )


if __name__ == "__main__":
    main()

