"""Market Clock and Historical Price Lookup module for TradeZen.

Provides:
- ClockMode: LIVE vs REPLAY
- MarketClock: State machine advancing time minute by minute or reading live market
- PriceQuote: Float-compatible bar representation (allows direct float comparisons and bar attribute access)
- get_price: Historical price lookup function
- get_bar: Historical PriceBar model lookup function
"""
from datetime import datetime, date, time, timedelta
from enum import Enum
import logging
from typing import Optional, Union, Dict, Any

from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.price_bar import PriceBar

logger = logging.getLogger(__name__)

# Standard Indian equity market regular hours (NSE / BSE)
MARKET_OPEN_TIME = time(9, 15)
MARKET_CLOSE_TIME = time(15, 30)


class ClockMode(str, Enum):
    LIVE = "LIVE"
    REPLAY = "REPLAY"


class LiveQuoteUnavailableError(KeyError):
    """Raised when a live quote is unavailable in LIVE mode.
    
    Inherits from KeyError for backward compatibility with existing KeyError handlers,
    while carrying structured details about the symbol and failure reason (disconnected,
    missing quote, or stale data).
    """
    def __init__(self, symbol: str, reason: str):
        self.symbol = symbol.upper()
        self.reason = reason
        super().__init__(f"Live quote unavailable for symbol '{self.symbol}': {self.reason}")


class PriceQuote(float):
    """A float subclass representing an OHLCV price bar or real-time quote.
    
    Behaves as a standard float (evaluating to the close price) for all arithmetic
    and comparisons (e.g., `price == 1818.0`), while also offering access to full bar
    attributes (.open, .high, .low, .close, .volume, .timestamp, .symbol, .is_live).
    """
    def __new__(
        cls,
        close: float,
        open: Optional[float] = None,
        high: Optional[float] = None,
        low: Optional[float] = None,
        volume: Optional[int] = None,
        timestamp: Optional[datetime] = None,
        symbol: Optional[str] = None,
        is_live: bool = False,
    ):
        instance = super().__new__(cls, float(close))
        instance.close = float(close)
        instance.open = float(open if open is not None else close)
        instance.high = float(high if high is not None else close)
        instance.low = float(low if low is not None else close)
        instance.volume = int(volume or 0)
        instance.timestamp = timestamp
        instance.symbol = symbol.upper() if symbol else None
        instance.is_live = is_live
        return instance

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "is_live": getattr(self, "is_live", False),
        }

    def __str__(self) -> str:
        return str(self.close)

    def __repr__(self) -> str:
        ts_str = self.timestamp.strftime("%Y-%m-%d %H:%M:%S") if self.timestamp else "N/A"
        return (
            f"<PriceQuote {self.symbol} [{ts_str}] "
            f"Close={self.close:.2f} Open={self.open:.2f} High={self.high:.2f} Low={self.low:.2f} Vol={self.volume}>"
        )


def parse_timestamp(timestamp: Union[str, datetime, date]) -> datetime:
    """Parses various timestamp representations into a standardized datetime object."""
    if isinstance(timestamp, datetime):
        return timestamp
    if isinstance(timestamp, date):
        return datetime.combine(timestamp, MARKET_OPEN_TIME)

    ts_str = str(timestamp).strip()
    # Support multiple common formats
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            parsed = datetime.strptime(ts_str, fmt)
            if fmt == "%Y-%m-%d":
                parsed = datetime.combine(parsed.date(), MARKET_OPEN_TIME)
            return parsed
        except ValueError:
            continue

    raise ValueError(f"Could not parse timestamp string '{timestamp}'. Expected format YYYY-MM-DD HH:MM[:SS].")


def get_bar(
    symbol: str,
    timestamp: Union[str, datetime],
    session: Optional[Session] = None,
    allow_nearest: bool = False
) -> Optional[PriceBar]:
    """Retrieves the PriceBar database model for a given symbol and timestamp."""
    sym = symbol.strip().upper()
    dt = parse_timestamp(timestamp)

    def _query(db: Session) -> Optional[PriceBar]:
        stmt = (
            select(PriceBar)
            .where(PriceBar.symbol == sym, PriceBar.timestamp == dt)
        )
        bar = db.execute(stmt).scalar_one_or_none()

        if bar is None and allow_nearest:
            # Fall back to nearest preceding bar within same trading day
            day_start = datetime.combine(dt.date(), MARKET_OPEN_TIME)
            stmt_nearest = (
                select(PriceBar)
                .where(
                    PriceBar.symbol == sym,
                    PriceBar.timestamp >= day_start,
                    PriceBar.timestamp <= dt
                )
                .order_by(desc(PriceBar.timestamp))
                .limit(1)
            )
            bar = db.execute(stmt_nearest).scalar_one_or_none()

        return bar

    if session is not None:
        return _query(session)

    with SessionLocal() as db:
        return _query(db)


def get_price(
    symbol: str,
    timestamp: Union[str, datetime],
    session: Optional[Session] = None,
    allow_nearest: bool = False
) -> PriceQuote:
    """Historical price lookup function.
    
    Returns a PriceQuote for the specified symbol and timestamp.
    Raises KeyError if no historical price bar is found.
    """
    sym = symbol.strip().upper()
    dt = parse_timestamp(timestamp)
    bar = get_bar(sym, dt, session=session, allow_nearest=allow_nearest)

    if bar is None:
        raise KeyError(
            f"No price bar found for symbol '{sym}' at {dt.strftime('%Y-%m-%d %H:%M:%S')}. "
            f"Ensure historical data has been loaded."
        )

    return PriceQuote(
        close=bar.close,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        volume=bar.volume,
        timestamp=bar.timestamp,
        symbol=bar.symbol
    )


class MarketClock:
    """Market Clock supporting LIVE and REPLAY modes.
    
    - In REPLAY mode:
        Initialized with a past date (and optional start time).
        Advances minute-by-minute via .tick() or .advance(minutes).
    - In LIVE mode:
        Tracks current wall-clock time or latest bar available in DB.
    """
    def __init__(
        self,
        mode: Union[ClockMode, str] = ClockMode.LIVE,
        replay_date: Optional[Union[str, date]] = None,
        start_time: Optional[Union[str, time]] = MARKET_OPEN_TIME,
        end_time: Optional[Union[str, time]] = MARKET_CLOSE_TIME,
        step_minutes: int = 1,
        feed: Optional[Any] = None,
        max_quote_age_seconds: float = 15.0,
        auto_attach_feed: bool = True,
    ):
        self.mode = ClockMode(mode)
        self.step_minutes = step_minutes
        self.max_quote_age_seconds = max_quote_age_seconds

        # Live feed service injection
        self._feed = feed
        if self._feed is None and auto_attach_feed:
            try:
                from app.data.upstox_feed import get_upstox_feed
                self._feed = get_upstox_feed()
            except Exception:
                self._feed = None

        # Replay configuration
        if isinstance(start_time, str):
            h, m = map(int, start_time.split(":")[:2])
            start_time = time(h, m)
        if isinstance(end_time, str):
            h, m = map(int, end_time.split(":")[:2])
            end_time = time(h, m)

        self._start_time = start_time or MARKET_OPEN_TIME
        self._end_time = end_time or MARKET_CLOSE_TIME

        if self.mode == ClockMode.REPLAY:
            if replay_date is None:
                # Default to target test date if not provided
                replay_date = date(2022, 3, 10)
            elif isinstance(replay_date, str):
                replay_date = datetime.strptime(replay_date.strip()[:10], "%Y-%m-%d").date()

            self._replay_date = replay_date
            self._current_time = datetime.combine(self._replay_date, self._start_time)
            self._end_datetime = datetime.combine(self._replay_date, self._end_time)
        else:
            self._replay_date = None
            self._current_time = None
            self._end_datetime = None

    @property
    def current_time(self) -> datetime:
        """Returns the current simulated datetime in REPLAY mode or wall-clock time in LIVE mode."""
        if self.mode == ClockMode.REPLAY:
            return self._current_time
        return datetime.now()

    @property
    def is_market_open(self) -> bool:
        """Checks whether current clock time falls within regular trading hours (09:15 - 15:30 on weekdays)."""
        ct = self.current_time
        if ct.weekday() >= 5:  # Saturday or Sunday
            return False
        return self._start_time <= ct.time() <= self._end_time

    def set_mode(
        self,
        mode: Union[ClockMode, str],
        replay_date: Optional[Union[str, date]] = None,
        start_time: Optional[Union[str, time]] = None,
        end_time: Optional[Union[str, time]] = None,
    ):
        """Switches clock mode between LIVE and REPLAY."""
        self.mode = ClockMode(mode)
        if self.mode == ClockMode.REPLAY:
            if replay_date:
                if isinstance(replay_date, str):
                    self._replay_date = datetime.strptime(replay_date.strip()[:10], "%Y-%m-%d").date()
                else:
                    self._replay_date = replay_date
            elif self._replay_date is None:
                self._replay_date = date(2022, 3, 10)

            if start_time:
                if isinstance(start_time, str):
                    h, m = map(int, start_time.split(":")[:2])
                    self._start_time = time(h, m)
                else:
                    self._start_time = start_time

            if end_time:
                if isinstance(end_time, str):
                    h, m = map(int, end_time.split(":")[:2])
                    self._end_time = time(h, m)
                else:
                    self._end_time = end_time

            self._current_time = datetime.combine(self._replay_date, self._start_time)
            self._end_datetime = datetime.combine(self._replay_date, self._end_time)

    def tick(self, minutes: Optional[int] = None) -> datetime:
        """Advances the clock forward in REPLAY mode by `minutes` (default step_minutes)."""
        if self.mode != ClockMode.REPLAY:
            raise RuntimeError("Cannot tick clock in LIVE mode.")

        step = minutes if minutes is not None else self.step_minutes
        self._current_time += timedelta(minutes=step)
        return self._current_time

    def advance(self, minutes: int = 1) -> datetime:
        """Alias for tick()."""
        return self.tick(minutes)

    def set_time(self, new_time: Union[datetime, str, time]):
        """Explicitly sets current simulated time in REPLAY mode."""
        if self.mode != ClockMode.REPLAY:
            raise RuntimeError("Cannot set time in LIVE mode.")

        if isinstance(new_time, time):
            self._current_time = datetime.combine(self._replay_date, new_time)
        elif isinstance(new_time, str):
            if ":" in new_time and len(new_time) <= 8 and " " not in new_time:
                h, m = map(int, new_time.split(":")[:2])
                self._current_time = datetime.combine(self._replay_date, time(h, m))
            else:
                self._current_time = parse_timestamp(new_time)
                self._replay_date = self._current_time.date()
                self._end_datetime = datetime.combine(self._replay_date, self._end_time)
        elif isinstance(new_time, datetime):
            self._current_time = new_time
            self._replay_date = new_time.date()
            self._end_datetime = datetime.combine(self._replay_date, self._end_time)

    def rewind(self):
        """Resets replay clock back to market open time for the current replay date."""
        if self.mode != ClockMode.REPLAY:
            raise RuntimeError("Cannot rewind in LIVE mode.")
        self._current_time = datetime.combine(self._replay_date, self._start_time)

    def has_next(self) -> bool:
        """Checks if current replay time is before session close."""
        if self.mode != ClockMode.REPLAY:
            return True
        return self._current_time <= self._end_datetime

    def set_feed(self, feed: Optional[Any]) -> None:
        """Injects or updates the live feed service instance."""
        self._feed = feed

    @property
    def feed(self) -> Optional[Any]:
        """Returns the configured live feed service instance, if any."""
        return self._feed

    def get_live_quote(
        self,
        symbol: str,
        max_age_seconds: Optional[float] = None
    ) -> Optional[PriceQuote]:
        """In LIVE mode, retrieves the latest fresh Upstox quote for a symbol as a PriceQuote.
        
        Returns None if:
        - Feed service is not attached or is disconnected
        - No quote exists for the symbol in the feed cache
        - The cached quote is stale (> max_age_seconds)
        """
        sym = symbol.strip().upper()
        feed = self._feed
        if feed is None or not getattr(feed, "is_connected", False):
            return None

        upstox_q = feed.get_latest_quote(sym)
        if upstox_q is None:
            return None

        threshold = max_age_seconds if max_age_seconds is not None else self.max_quote_age_seconds
        if not upstox_q.is_fresh(threshold):
            return None

        return PriceQuote(
            close=upstox_q.ltp,
            open=upstox_q.open if upstox_q.open is not None else upstox_q.ltp,
            high=upstox_q.high if upstox_q.high is not None else upstox_q.ltp,
            low=upstox_q.low if upstox_q.low is not None else upstox_q.ltp,
            volume=upstox_q.volume or 0,
            timestamp=upstox_q.exchange_timestamp or upstox_q.receipt_timestamp,
            symbol=upstox_q.symbol,
            is_live=True,
        )

    def check_live_quote_status(
        self,
        symbol: str,
        max_age_seconds: Optional[float] = None
    ) -> Dict[str, Any]:
        """Returns diagnostic details regarding live quote availability for a symbol."""
        sym = symbol.strip().upper()
        threshold = max_age_seconds if max_age_seconds is not None else self.max_quote_age_seconds
        feed = self._feed

        if feed is None:
            return {
                "symbol": sym,
                "is_available": False,
                "reason": "Feed service is not attached",
                "feed_attached": False,
                "feed_connected": False,
                "has_cached_quote": False,
                "is_fresh": False,
                "quote": None,
            }

        is_conn = getattr(feed, "is_connected", False)
        if not is_conn:
            return {
                "symbol": sym,
                "is_available": False,
                "reason": "Feed is disconnected",
                "feed_attached": True,
                "feed_connected": False,
                "has_cached_quote": False,
                "is_fresh": False,
                "quote": None,
            }

        upstox_q = feed.get_latest_quote(sym)
        if upstox_q is None:
            return {
                "symbol": sym,
                "is_available": False,
                "reason": f"No quote exists in feed cache for '{sym}'",
                "feed_attached": True,
                "feed_connected": True,
                "has_cached_quote": False,
                "is_fresh": False,
                "quote": None,
            }

        fresh = upstox_q.is_fresh(threshold)
        if not fresh:
            return {
                "symbol": sym,
                "is_available": False,
                "reason": f"Quote for '{sym}' is stale (exceeded {threshold}s freshness limit)",
                "feed_attached": True,
                "feed_connected": True,
                "has_cached_quote": True,
                "is_fresh": False,
                "quote": upstox_q.to_dict() if hasattr(upstox_q, "to_dict") else None,
            }

        pq = self.get_live_quote(sym, max_age_seconds=threshold)
        return {
            "symbol": sym,
            "is_available": True,
            "reason": "Quote is live and fresh",
            "feed_attached": True,
            "feed_connected": True,
            "has_cached_quote": True,
            "is_fresh": True,
            "quote": pq.to_dict() if pq else None,
        }

    def get_current_bar(
        self,
        symbol: str,
        session: Optional[Session] = None,
        allow_nearest: bool = True
    ) -> Optional[PriceBar]:
        """Gets current PriceBar model for symbol at the clock's current time.
        
        In REPLAY mode: returns historical PriceBar from database.
        In LIVE mode: returns None. Historical database bars are never returned
        while in LIVE mode to prevent claiming historical data is live.
        """
        sym = symbol.strip().upper()
        if self.mode == ClockMode.REPLAY:
            return get_bar(sym, self._current_time, session=session, allow_nearest=allow_nearest)
        else:
            return None

    def get_current_price(
        self,
        symbol: str,
        session: Optional[Session] = None,
        allow_nearest: bool = True
    ) -> PriceQuote:
        """Gets current PriceQuote for symbol at the clock's current time.
        
        In REPLAY mode:
            Retrieves historical price bar from database at simulated replay time.
        In LIVE mode:
            Resolves latest fresh quote from UpstoxLiveFeed.
            Raises LiveQuoteUnavailableError if disconnected, missing, or stale.
            NEVER silently falls back to historical database prices.
        """
        sym = symbol.strip().upper()
        if self.mode == ClockMode.LIVE:
            quote = self.get_live_quote(sym)
            if quote is None:
                diag = self.check_live_quote_status(sym)
                raise LiveQuoteUnavailableError(symbol=sym, reason=diag["reason"])
            return quote

        # REPLAY mode
        bar = self.get_current_bar(sym, session=session, allow_nearest=allow_nearest)
        if bar is None:
            raise KeyError(f"No price bar available for symbol '{symbol}' at current clock time {self.current_time}")
        return PriceQuote(
            close=bar.close,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            volume=bar.volume,
            timestamp=bar.timestamp,
            symbol=bar.symbol
        )

    def __repr__(self) -> str:
        if self.mode == ClockMode.REPLAY:
            return f"<MarketClock REPLAY date={self._replay_date} current_time='{self._current_time.strftime('%Y-%m-%d %H:%M:%S')}'>"
        return f"<MarketClock LIVE current_time='{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}'>"
