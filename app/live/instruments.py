"""
Single source of truth for the stocks TradeZen streams live.

TradeZen uses the short `symbol` (INFY, RELIANCE ...) everywhere: price_bars.instrument,
the frontend, the REST API. Upstox does NOT understand those. It needs the
`instrument_key` ("NSE_EQ|<ISIN>"). Keys below are the NSE cash-market keys.
If you ever add a stock, copy its instrument_key from Upstox's instrument master
(https://upstox.com/developer/api-documentation/instruments) - never type it from memory.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Instrument:
    symbol: str  # TradeZen name
    key: str     # Upstox instrument_key
    name: str


INSTRUMENTS: dict[str, Instrument] = {
    i.symbol: i
    for i in (
        Instrument("INFY", "NSE_EQ|INE009A01021", "Infosys Ltd"),
        Instrument("RELIANCE", "NSE_EQ|INE002A01018", "Reliance Industries Ltd"),
        Instrument("TCS", "NSE_EQ|INE467B01029", "Tata Consultancy Services Ltd"),
        Instrument("HDFCBANK", "NSE_EQ|INE040A01034", "HDFC Bank Ltd"),
        Instrument("SBIN", "NSE_EQ|INE062A01020", "State Bank of India"),
    )
}

KEY_TO_SYMBOL: dict[str, str] = {i.key: i.symbol for i in INSTRUMENTS.values()}

# Names people (and old code) might send. HDFC Ltd merged into HDFC Bank in 2023.
ALIASES: dict[str, str] = {
    "HDFC": "HDFCBANK",
    "HDFC BANK": "HDFCBANK",
    "SBI": "SBIN",
    "STATE BANK OF INDIA": "SBIN",
    "INFOSYS": "INFY",
    "RIL": "RELIANCE",
    "TATA CONSULTANCY SERVICES": "TCS",
}


def resolve_symbol(value: str | None) -> str | None:
    """Map whatever the caller sent to a supported TradeZen symbol, or None."""
    if not value:
        return None
    v = str(value).strip()
    if v in KEY_TO_SYMBOL:  # already an Upstox instrument key
        return KEY_TO_SYMBOL[v]
    v = v.upper()
    for prefix in ("NSE_EQ|", "NSE_EQ:", "NSE:", "NSE|"):
        if v.startswith(prefix):
            v = v[len(prefix):]
    v = v.removesuffix(".NS").removesuffix("-EQ").strip()
    v = ALIASES.get(v, v)
    return v if v in INSTRUMENTS else None


def all_keys() -> list[str]:
    return [i.key for i in INSTRUMENTS.values()]
