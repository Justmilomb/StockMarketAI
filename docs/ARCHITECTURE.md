# Architecture

## System Graph

```
                    ┌──────────────────────────────┐
                    │       ENTRY POINTS           │
                    │  ai.py │ terminal/app.py │ backtest.py │
                    └────┬────┴────────┬───────────┘
                         │             │
           ┌─────────────┘     ┌───────┘
           ▼                   ▼
      ┌──────────┐  ┌──────────────────────────┐
      │ AiService│  │  TradingTerminalApp       │
      │ (hub)    │  │  (Textual TUI — hub)      │
      │1000-     │  │  ┌──────────────────────┐ │
      │analyst   │  │  │ AppState (with       │ │
      │ensemble) │  │  │  regime, consensus,  │ │
      └──┬───────┘  │  │  ensemble metadata)  │ │
         │ ├─────┬──┼──┤ └──────────────────────┘ │
         │ │     │  │  │ ┌────┐  ┌──────────┐    │
         │ │     │  │  │ │views ─ │NewsAgent │   │
         │ │     │  │  │ ├────┤  │(bg thrd) │    │
         │ │     │  │  │ │charts  └──────────┘    │
         │ │     │  │  │ └──────┐                 │
         │ │     │  └──┼────────┘                 │
         │ │     │     ▼                          │
         │ │     │  ┌──────────────┐              │
         │ │     │  │BrokerService │              │
         │ │     │  │  (facade)    │              │
         │ │     │  └──┬───────┬───┘              │
         │ │     │     │       │                  │
         │ │     │     ▼       ▼                  │
         │ │     │  ┌────────┬────────┐           │
         │ │     │  │LogBrk. │T212Brk.│           │
         │ │     │  └────────┴────────┘           │
         │ │     │                                │
         │ │     └──────────────────────────────┘ │
         │ │                                      │
         └─┴──────────────────────────────────────┘

        ┌─────────────────────────────────────────────────────┐
        │              ML + Gemini Pipeline                    │
        │                                                      │
        │  data_loader ──► features_advanced (V2, 31 feat)    │
        │  (yfinance)       ├─ 6 analyst groups               │
        │                   │                                 │
        │                   ▼                                 │
        │                ensemble ──► timeframe (3 horizons)  │
        │                (12 models)   (1d/5d/20d)            │
        │                │                ▼                   │
        │                │           [36 ML signals]          │
        │                │                │                   │
        │                ├──► regime ────┐│                   │
        │                │   (macro det) ││                   │
        │                │                ││                   │
        │                ├──► gemini_personas ──┐ │           │
        │                │    (5 analysts)       │ │           │
        │                │                       │ │           │
        │                └──► consensus ◄───────┘ │           │
        │                     (committee)          │           │
        │                         │                │           │
        │                         ▼                │           │
        │                    [signals + conf]      │           │
        │                         │                │           │
        │                         ├──► strategy ◄─┘           │
        │                         │    (buy/sell/hold)        │
        │                         │                           │
        │                         ▼                           │
        │                  risk_manager                       │
        │                  (pos. sizing)                      │
        │                         │                           │
        │                         ▼                           │
        │                  [risk-managed orders]              │
        │                                                      │
        └──────────────────────► AutoEngine ──────────────────┘
                                  (execution)
```

## Signal Pipeline (8-Step Flow)

The system generates signals through a structured, multi-layered process:

1. **Fetch Universe Data** — `data_loader.fetch_universe_data()` retrieves OHLCV data from yfinance with CSV caching.

2. **Compute V2 Features** — `features_advanced.build_advanced_features()` calculates 31 technical indicators grouped into 6 analyst specialties (momentum, volatility, trend, valuation, macro, flow).

3. **Detect Market Regime** — `regime.RegimeDetector.detect()` classifies market conditions (bull, bear, range-bound, high-volatility) for macro context.

4. **Multi-Timeframe ML Ensemble** — `ensemble.EnsembleModel.predict_ensemble()` runs 12 diverse ML models across 3 horizons (1d, 5d, 20d), producing 36 independent signals with probabilities.

4a. **Statistical Forecasters** — `forecaster_statistical.StatisticalForecaster.fit_and_predict()` fits ARIMA(1,1,1) + Holt-Winters ETS per ticker per horizon, converting forecast distributions to P(up) via normal CDF.

4b. **Deep Learning Forecaster** — `forecaster_deep.DeepForecaster.fit_and_predict()` trains N-BEATS neural architecture on pooled return windows (optional, requires PyTorch). Gracefully skipped if torch unavailable.

4c. **Meta-Ensemble** — `meta_ensemble.MetaEnsemble.combine()` blends ML (50%), Statistical (25%), and Deep Learning (25%) probabilities. Auto-redistributes weights when a family is unavailable.

4d. **MiroFish Multi-Agent Simulation** — `mirofish.MiroFishOrchestrator.run_universe()` spawns ~1000 heterogeneous AI agents (9 types: momentum, mean-reversion, sentiment, fundamental, noise, contrarian, institutional, algorithmic, LLM-seeded) per ticker. Runs N Monte Carlo simulations in parallel across all CPU cores. Agents interact via herding/contrarian dynamics, producing emergent market behaviour. Extracts net sentiment, order flow, agreement index, and volatility predictions as `ModelSignal` entries for consensus.

5. **Gemini Persona Analysis** — `gemini_personas.GeminiPersonaAnalyzer.analyze_batch()` routes per-ticker features to 5 specialized analyst personas (technical, fundamental, sentiment, macro, risk), each producing a signal + confidence.

6. **Consensus Aggregation** — `consensus.ConsensusEngine.compute_all()` combines all model signals (ML + Statistical + Deep + Gemini), regime weighting, and horizon breakdown into a unified consensus score.

7. **Strategy Signal Generation** — `strategy.generate_signals()` converts consensus scores into actionable buy/sell/hold decisions, bounded by position limits.

8. **Risk-Managed Order Sizing** — `risk_manager.RiskManager.generate_risk_enhanced_orders()` calculates position sizes via Kelly criterion, volatility adjustment, and portfolio concentration limits.

## Data Flow

```
yfinance  →  CSV cache  →  features_advanced (31 V2 indicators)
                                  │
                                  ▼
                          6 analyst groups
                                  │
                                  ▼
                    ensemble (12 models × 3 horizons)
                          [36 ML signals]
                                  │
                 ┌────────────────┼────────────────┐
                 │                │                │
                 ▼                ▼                ▼
           regime detect    gemini_personas  consensus
           (macro state)    (5 analysts)      (investment
                                              committee)
                                  │
                                  ▼
                            consensus score
                            + confidence
                                  │
                                  ▼
                            strategy signals
                            (buy/sell/hold)
                                  │
                                  ▼
                            risk_manager
                            (position sizing)
                                  │
                                  ▼
                        risk-managed orders
                                  │
                                  ▼
                            BrokerService
                            (log or T212)
```

## Subsystem Responsibilities

| System | Owns | Must NOT |
|--------|------|----------|
| data_loader | OHLCV download, CSV caching | Touch model or strategy logic |
| features | Technical indicator calculation, label creation | Import model or broker |
| features_advanced | 31 V2 indicators, 6 analyst groups, feature vectors | Touch model or ensemble directly |
| ensemble | Multi-model training/prediction, model serialisation | Know about tickers or strategy |
| timeframe | Horizon-specific ensembles (1d/5d/20d) | Aggregate signals beyond its horizon |
| regime | Market regime detection and classification | Make trading decisions |
| gemini_client | All Gemini API communication | Access broker or data_loader |
| gemini_personas | 5 analyst personas, per-ticker analysis routing | Make final trading decisions |
| consensus | Signal aggregation, investment committee logic | Call APIs or train models |
| risk_manager | Position sizing, portfolio risk calculations | Submit orders or modify state |
| forecaster_statistical | ARIMA/ETS baseline fitting and probability conversion | Know about ML ensemble or broker |
| forecaster_deep | N-BEATS architecture, training, and prediction | Know about other forecasters or broker |
| meta_ensemble | Three-family weighted combination | Train models or call APIs |
| mirofish | Multi-agent simulation, Monte Carlo orchestration, signal extraction | Call APIs, train ML models, or submit orders |
| backtesting/ | Walk-forward validation, trade simulation, performance metrics | Modify live config, submit real orders |
| pipeline_tracker | Thread-safe progress tracking for TUI | Know about TUI or AI logic |
| strategy | Probability → signal conversion, position limits | Train models or call APIs |
| broker / broker_service | Order submission, position/account queries | Know about ML or features |
| auto_engine | Automated signal → order loop, execution | Modify broker or AI logic directly |
| news_agent | RSS fetching, sentiment via Gemini | Submit orders or modify state directly |
| terminal/app | TUI lifecycle, action routing, view wiring | Implement business logic |
| terminal/state | Shared AppState dataclass | Contain methods or logic |
| terminal/views | UI rendering, user input | Call broker or AI directly |
| terminal/charts | Sparkline rendering | Fetch data directly |

## Key Types / Schemas

| Type | Location | Purpose |
|------|----------|---------|
| ConfigDict | `Dict[str, Any]` | Runtime config loaded from `config.json` |
| AppState | `terminal/state.py` | Shared TUI state (signals, positions, chat, regime, consensus, ensemble metadata) |
| AiService | `ai_service.py` | ML + Gemini orchestrator (1000-analyst ensemble) |
| BrokerService | `broker_service.py` | Broker-agnostic facade |
| Broker (ABC) | `broker.py` | Abstract broker interface |
| StrategyConfig | `strategy.py` | Buy/sell thresholds, position limits |
| ModelConfig | `model.py` | Legacy RF hyperparams, model path, train split |
| GeminiConfig | `gemini_client.py` | Model name, API key env var |
| TickerNews | `news_agent.py` | Per-ticker sentiment + headlines |
| FEATURE_COLUMNS | `features.py` | Legacy list (10 features) of model input |
| FEATURE_COLUMNS_V2 | `features_advanced.py` | V2 canonical list (31 features) + analyst grouping |
| FEATURE_GROUPS | `features_advanced.py` | Mapping of feature names to 6 analyst specialties |
| EnsembleModel | `ensemble.py` | Multi-model classifier with train/predict/save/load |
| TimeframeEnsemble | `timeframe.py` | Horizon-specific (1d/5d/20d) ensemble wrappers |
| RegimeState | `regime.py` | Market regime classification + confidence |
| ConsensusResult | `consensus.py` | Aggregated signal, confidence, component breakdown |
| GeminiPersonaSignal | `gemini_personas.py` | Per-persona ticker analysis + probability + reason |
| RiskManager | `risk_manager.py` | Position sizing, portfolio concentration logic |

## Phase Map

| Phase | Scope | Status |
|-------|-------|--------|
| 1 | Core ML pipeline: data → features → model → signals → broker | Done |
| 2 | TUI terminal, Gemini integration, news agent, Trading 212 | Done |
| 2.5 | Self-learning AI loops, SQLite persistence, chat history, 1000-analyst ensemble | Done |
| 3 | Testing, backtesting, walk-forward validation, advanced position sizing | In Progress |
| 4 | Production hardening, monitoring, deployment automation | Planned |
