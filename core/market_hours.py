"""Exchange metadata + regular-hours open/closed logic.

Given a Trading 212 ticker (``TSLA_US_EQ``, ``BPl_EQ``, ``SAP_DE_EQ``,
…), resolve which exchange it trades on and whether that exchange is
currently in its regular trading session. No holiday calendar, no
pre/post-market — we deliberately keep this small because the agent
only uses it to pick a sensible sleep cadence and to tell the user
which markets are live.

The registry covers every venue Trading 212 exposes on UK retail
(US, LSE, the European majors, TASE for dual-listed IL). Hours are
continuous-session regular hours in each exchange's local time, so
DST is handled automatically by ``zoneinfo``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date as _date
from datetime import datetime, time, timedelta
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

#: Monday=0 … Sunday=6. Default weekday mask used by every Western venue.
_MON_FRI: tuple[int, ...] = (0, 1, 2, 3, 4)

#: Tel Aviv runs Sunday-Thursday.
_SUN_THU: tuple[int, ...] = (6, 0, 1, 2, 3)


@dataclass(frozen=True)
class Exchange:
    """One trading venue with a fixed regular-session schedule.

    Hours are local (``timezone``) and assumed the same every trading
    day. ``weekdays`` is a tuple of Python weekday ints.
    """
    code: str
    name: str
    country: str
    timezone: str
    open_time: time
    close_time: time
    weekdays: tuple[int, ...] = _MON_FRI


#: Ordered registry. Order matters for the UI panel (US first, then
#: London, then the rest roughly by size).
_EXCHANGES: Dict[str, Exchange] = {
    "US": Exchange(
        "US", "NYSE / Nasdaq", "United States",
        "America/New_York", time(9, 30), time(16, 0),
    ),
    "LSE": Exchange(
        "LSE", "London Stock Exchange", "United Kingdom",
        "Europe/London", time(8, 0), time(16, 30),
    ),
    "XETRA": Exchange(
        "XETRA", "Deutsche Börse (XETRA)", "Germany",
        "Europe/Berlin", time(9, 0), time(17, 30),
    ),
    "EURONEXT_PARIS": Exchange(
        "EURONEXT_PARIS", "Euronext Paris", "France",
        "Europe/Paris", time(9, 0), time(17, 30),
    ),
    "EURONEXT_AMS": Exchange(
        "EURONEXT_AMS", "Euronext Amsterdam", "Netherlands",
        "Europe/Amsterdam", time(9, 0), time(17, 30),
    ),
    "BME": Exchange(
        "BME", "Bolsa de Madrid", "Spain",
        "Europe/Madrid", time(9, 0), time(17, 30),
    ),
    "BIT": Exchange(
        "BIT", "Borsa Italiana", "Italy",
        "Europe/Rome", time(9, 0), time(17, 30),
    ),
    "SIX": Exchange(
        "SIX", "SIX Swiss Exchange", "Switzerland",
        "Europe/Zurich", time(9, 0), time(17, 30),
    ),
    "STO": Exchange(
        "STO", "Nasdaq Stockholm", "Sweden",
        "Europe/Stockholm", time(9, 0), time(17, 30),
    ),
    "OSE": Exchange(
        "OSE", "Oslo Børs", "Norway",
        "Europe/Oslo", time(9, 0), time(16, 20),
    ),
    "CPH": Exchange(
        "CPH", "Nasdaq Copenhagen", "Denmark",
        "Europe/Copenhagen", time(9, 0), time(17, 0),
    ),
    "HEL": Exchange(
        "HEL", "Nasdaq Helsinki", "Finland",
        "Europe/Helsinki", time(10, 0), time(18, 30),
    ),
    "TASE": Exchange(
        "TASE", "Tel Aviv Stock Exchange", "Israel",
        "Asia/Jerusalem", time(9, 45), time(17, 25),
        weekdays=_SUN_THU,
    ),
}


#: T212 suffix → exchange code. Case-insensitive match on the raw
#: ticker. London tickers use a lowercase 'l' before ``_EQ`` (e.g.
#: ``BPl_EQ``, ``RRl_EQ``) — handled explicitly in
#: :func:`exchange_for_ticker`.
_SUFFIX_MAP: Dict[str, str] = {
    "_US_EQ": "US",
    "_UK_EQ": "LSE",
    "_GB_EQ": "LSE",
    "_DE_EQ": "XETRA",
    "_FR_EQ": "EURONEXT_PARIS",
    "_NL_EQ": "EURONEXT_AMS",
    "_ES_EQ": "BME",
    "_IT_EQ": "BIT",
    "_CH_EQ": "SIX",
    "_SE_EQ": "STO",
    "_NO_EQ": "OSE",
    "_DK_EQ": "CPH",
    "_FI_EQ": "HEL",
    "_IL_EQ": "TASE",
}


def all_exchanges() -> List[Exchange]:
    """Return every registered exchange in display order."""
    return list(_EXCHANGES.values())


def get_exchange(code: str) -> Optional[Exchange]:
    """Look up an exchange by its short code."""
    return _EXCHANGES.get(code.upper() if code else "")


def exchange_for_ticker(ticker: str) -> Optional[Exchange]:
    """Resolve a Trading 212 ticker to its exchange.

    Returns ``None`` if the suffix isn't recognised. Crypto and
    anything else we don't support lands here.
    """
    if not ticker:
        return None
    raw = ticker.strip()
    # London: `BPl_EQ`, `RRl_EQ` etc. — lowercase 'l' just before _EQ.
    if raw.lower().endswith("l_eq"):
        return _EXCHANGES["LSE"]
    upper = raw.upper()
    for suffix, code in _SUFFIX_MAP.items():
        if upper.endswith(suffix):
            return _EXCHANGES[code]
    return None


def _next_valid_day(start: _date, weekdays: tuple[int, ...]) -> _date:
    """Return ``start`` if it's already valid, else walk forward to the next."""
    day = start
    while day.weekday() not in weekdays:
        day += timedelta(days=1)
    return day


def status(
    exchange: Exchange,
    now: Optional[datetime] = None,
) -> Dict[str, object]:
    """Snapshot of an exchange's state.

    Returns a JSON-safe dict with:

    * ``is_open`` — bool, true only during the regular session
    * ``next_open`` / ``next_close`` — ISO strings in local time
    * ``local_now`` — the moment we evaluated, also in local time
    * ``code`` / ``name`` / ``country`` / ``timezone`` — passthrough

    Weekends are closed. Holidays are **not** modelled — the broker
    is the source of truth for "the market rejected my order".
    """
    tz = ZoneInfo(exchange.timezone)
    if now is None:
        now = datetime.now(tz=ZoneInfo("UTC"))
    elif now.tzinfo is None:
        now = now.replace(tzinfo=ZoneInfo("UTC"))
    local = now.astimezone(tz)
    today = local.date()
    weekday = local.weekday()

    in_session = (
        weekday in exchange.weekdays
        and exchange.open_time <= local.time() < exchange.close_time
    )

    if in_session:
        next_close_local = datetime.combine(today, exchange.close_time, tzinfo=tz)
        # After this session closes the next open is the next valid weekday.
        next_open_day = _next_valid_day(today + timedelta(days=1), exchange.weekdays)
        next_open_local = datetime.combine(next_open_day, exchange.open_time, tzinfo=tz)
    else:
        # If we're still before today's open on a valid day, today is next.
        if weekday in exchange.weekdays and local.time() < exchange.open_time:
            next_day = today
        else:
            next_day = _next_valid_day(today + timedelta(days=1), exchange.weekdays)
        next_open_local = datetime.combine(next_day, exchange.open_time, tzinfo=tz)
        next_close_local = datetime.combine(next_day, exchange.close_time, tzinfo=tz)

    return {
        "code": exchange.code,
        "name": exchange.name,
        "country": exchange.country,
        "timezone": exchange.timezone,
        "is_open": in_session,
        "next_open": next_open_local.isoformat(timespec="minutes"),
        "next_close": next_close_local.isoformat(timespec="minutes"),
        "local_now": local.isoformat(timespec="minutes"),
    }
