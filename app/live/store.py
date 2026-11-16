"""
Saves live candles into the SAME price_bars table that replay mode uses.

* Plain SELECT -> UPDATE/INSERT (no unique index needed, so it can't fail on old duplicate rows).
* Merging is idempotent: restarting the server mid-minute or backfilling never corrupts a bar.
* Column / table names and the timestamp convention are configurable (see env below) because
  they must match how your Step-1 loader stored the Kaggle data.

Env:
  PRICE_BARS_TABLE    default "price_bars"
  PRICE_BARS_TS_MODE  ist_naive (default) | utc_naive | ist_aware | utc_aware
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from sqlalchemy import text

from .parsing import IST, Candle

_VALID_MODES = {"ist_naive", "utc_naive", "ist_aware", "utc_aware"}


class BarStore:
    def __init__(self, engine, table: Optional[str] = None, ts_mode: Optional[str] = None) -> None:
        self.engine = engine
        self.table = table or os.getenv("PRICE_BARS_TABLE", "price_bars")
        self.ts_mode = (ts_mode or os.getenv("PRICE_BARS_TS_MODE", "ist_naive")).lower()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", self.table):
            raise ValueError(f"unsafe table name: {self.table!r}")
        if self.ts_mode not in _VALID_MODES:
            raise ValueError(f"PRICE_BARS_TS_MODE must be one of {sorted(_VALID_MODES)}")

        sym_col = os.getenv("PRICE_BARS_SYMBOL_COL")
        ts_col = os.getenv("PRICE_BARS_TS_COL")
        if (not sym_col or not ts_col) and self.engine is not None:
            try:
                from sqlalchemy import inspect as sa_inspect
                insp = sa_inspect(self.engine)
                cols_present = {c["name"] for c in insp.get_columns(self.table)}
                if "instrument" in cols_present and "ts" in cols_present:
                    sym_col = sym_col or "instrument"
                    ts_col = ts_col or "ts"
                elif "symbol" in cols_present and "timestamp" in cols_present:
                    sym_col = sym_col or "symbol"
                    ts_col = ts_col or "timestamp"
            except Exception:
                pass

        self.sym_col = sym_col or os.getenv("PRICE_BARS_SYMBOL_COL", "symbol")
        self.ts_col = ts_col or os.getenv("PRICE_BARS_TS_COL", "timestamp")
        t = self.table
        cols = '"open","high","low","close","volume"'
        self._sel = text(f'SELECT {cols} FROM {t} WHERE "{self.sym_col}"=:i AND "{self.ts_col}"=:t')
        self._ins = text(
            f'INSERT INTO {t} ("{self.sym_col}","{self.ts_col}","open","high","low","close","volume") '
            f"VALUES (:i,:t,:o,:h,:l,:c,:v)"
        )
        self._upd = text(
            f'UPDATE {t} SET "high"=:h,"low"=:l,"close"=:c,"volume"=:v WHERE "{self.sym_col}"=:i AND "{self.ts_col}"=:t'
        )
        self._recent = text(
            f'SELECT "{self.ts_col}",{cols} FROM {t} WHERE "{self.sym_col}"=:i AND "{self.ts_col}">=:since ORDER BY "{self.ts_col}" DESC LIMIT :n'
        )
        self._latest = text(f'SELECT "{self.ts_col}",{cols} FROM {t} WHERE "{self.sym_col}"=:i ORDER BY "{self.ts_col}" DESC LIMIT 1')

    # ---- timestamp conversion (the one place that knows the DB convention) ----
    def to_db(self, dt: datetime) -> datetime:
        if self.ts_mode == "ist_naive":
            return dt.astimezone(IST).replace(tzinfo=None)
        if self.ts_mode == "utc_naive":
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        if self.ts_mode == "ist_aware":
            return dt.astimezone(IST)
        return dt.astimezone(timezone.utc)

    def from_db(self, ts) -> datetime:
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc if self.ts_mode.startswith("utc") else IST)
        return ts.astimezone(IST)

    # ---- writes ----
    def check(self) -> None:
        """Raises if the table/columns don't match - called once at startup."""
        with self.engine.connect() as conn:
            conn.execute(text(f'SELECT "{self.sym_col}","{self.ts_col}","open","high","low","close","volume" FROM {self.table} LIMIT 1'))

    def upsert_many(self, candles: Iterable[Candle]) -> int:
        n = 0
        with self.engine.begin() as conn:
            for c in candles:
                p = {"i": c.symbol, "t": self.to_db(c.minute)}
                row = conn.execute(self._sel, p).fetchone()
                vol = int(c.volume)
                if row is None:
                    conn.execute(self._ins, {**p, "o": c.open, "h": c.high, "l": c.low, "c": c.close, "v": vol})
                else:
                    _o, h, l, _c, v = row
                    conn.execute(
                        self._upd,
                        {**p, "h": max(float(h), c.high), "l": min(float(l), c.low), "c": c.close,
                         "v": max(int(v or 0), vol)},
                    )
                n += 1
        return n

    def insert_missing(self, candles: Iterable[Candle]) -> int:
        """Backfill: only add minutes that don't exist yet; never touch existing bars."""
        n = 0
        with self.engine.begin() as conn:
            for c in candles:
                p = {"i": c.symbol, "t": self.to_db(c.minute)}
                if conn.execute(self._sel, p).fetchone() is None:
                    conn.execute(self._ins, {**p, "o": c.open, "h": c.high, "l": c.low, "c": c.close, "v": int(c.volume)})
                    n += 1
        return n

    # ---- reads ----
    @staticmethod
    def _row_to_dict(self_, r) -> dict:
        ts, o, h, l, c, v = r
        return {"time": self_.from_db(ts), "open": float(o), "high": float(h), "low": float(l),
                "close": float(c), "volume": int(v or 0)}

    def recent_bars(self, symbol: str, since: datetime, limit: int = 500) -> list[dict]:
        with self.engine.connect() as conn:
            rows = conn.execute(self._recent, {"i": symbol, "since": self.to_db(since), "n": int(limit)}).fetchall()
        return [self._row_to_dict(self, r) for r in reversed(rows)]

    def latest_bar(self, symbol: str, max_age: timedelta = timedelta(days=4)) -> Optional[dict]:
        """Newest stored bar, but ONLY if it is recent. Old replay data must never pose as 'live'."""
        with self.engine.connect() as conn:
            r = conn.execute(self._latest, {"i": symbol}).fetchone()
        if r is None:
            return None
        bar = self._row_to_dict(self, r)
        if datetime.now(IST) - bar["time"] > max_age:
            return None
        return bar
