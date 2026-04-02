# Broker

## Goal
Provides a pluggable broker abstraction for order execution, account data, history, pies, and instrument metadata. LogBroker for development, Trading212Broker for live execution.

## Implementation
Abstract `Broker` base class with five core abstract methods (positions, orders, account, pending, cancel) and twelve extended methods with default empty implementations (history, dividends, transactions, pies CRUD, instruments, exchanges). `Trading212Broker` lives in `trading212.py` and implements the full T212 REST API v0. `BrokerService` is a facade that selects the concrete broker from config.

## Key Code
```python
class Broker(ABC):  # broker.py — core abstract + extended defaults
class LogBroker(Broker):  # broker.py — logs to JSONL
class Trading212Broker(Broker):  # trading212.py — full REST API v0
class BrokerService:  # broker_service.py — facade with is_live property
```

## Notes
- T212 uses Basic auth (base64-encoded api_key:secret_key); practice URL is demo.trading212.com, live is live.trading212.com
- Falls back to LogBroker if api_key env var is empty
- `BrokerService` supports multi-broker routing: different asset classes (stocks, crypto, polymarket) each get their own broker via `get_broker(asset_class)` or `register_broker(asset_class, broker)`
- Default `broker` property delegates to the stocks broker for backwards compatibility
- History endpoints use cursor-based pagination
- Pies support full CRUD (create/read/update/delete)
- `get_instruments()` returns all tradeable instruments with metadata
- `is_live` property returns True only when connected to Trading212Broker (not LogBroker)
