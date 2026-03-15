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
- T212 uses Basic auth (base64-encoded api_key:secret_key)
- Falls back to LogBroker if API key is empty
- History endpoints use cursor-based pagination
- Pies support full CRUD (create/read/update/delete)
- `get_instruments()` returns all tradeable instruments with metadata
