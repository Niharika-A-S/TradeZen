"""Upstox Market Data Feed V3 standalone service for TradeZen.

Provides real-time streaming quotes for the 5 supported NSE equities:
INFY, RELIANCE, TCS, HDFCBANK, and SBIN.

Decodes binary Protocol Buffer (Protobuf) feeds, maintains a thread-safe
in-memory quote cache, monitors quote freshness, and handles resilient
reconnection with bounded exponential backoff.
"""
from __future__ import annotations

import asyncio
import json
import logging
import ssl
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set
import httpx
import websockets

from app.config import settings
from app.database import SessionLocal
from app.models.price_bar import PriceBar
from sqlalchemy import text

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Verified Official Upstox Instrument Keys for NSE Equities
# Verified against official Upstox Instrument Master:
# https://assets.upstox.com/market-quote/instruments/exchange/NSE.csv.gz
# ---------------------------------------------------------------------------
VERIFIED_INSTRUMENTS: Dict[str, str] = {
    "INFY": "NSE_EQ|INE009A01021",
    "RELIANCE": "NSE_EQ|INE002A01018",
    "TCS": "NSE_EQ|INE467B01029",
    "HDFCBANK": "NSE_EQ|INE040A01034",
    "SBIN": "NSE_EQ|INE062A01020",
}

KEY_TO_SYMBOL: Dict[str, str] = {v: k for k, v in VERIFIED_INSTRUMENTS.items()}
SUPPORTED_SYMBOLS: List[str] = list(VERIFIED_INSTRUMENTS.keys())


class FeedConnectionStatus(str, Enum):
    """Feed connection and quote freshness states."""
    DISCONNECTED = "disconnected"
    CONNECTED_WITHOUT_QUOTES = "connected_without_quotes"
    CONNECTED_WITH_FRESH_QUOTES = "connected_with_fresh_quotes"


@dataclass
class UpstoxQuote:
    """Decoded market quote with pricing, timestamps, and optional OHLCV."""
    symbol: str
    instrument_key: str
    ltp: float
    exchange_timestamp: Optional[datetime] = None
    receipt_timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    close: Optional[float] = None
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    volume: Optional[int] = None

    def is_fresh(self, max_age_seconds: float = 15.0) -> bool:
        """Determines if the quote was received within max_age_seconds."""
        now = datetime.now(timezone.utc)
        age = (now - self.receipt_timestamp).total_seconds()
        return age <= max_age_seconds

    def to_dict(self) -> Dict[str, Any]:
        """Convert quote to dictionary representation."""
        return {
            "symbol": self.symbol,
            "instrument_key": self.instrument_key,
            "ltp": self.ltp,
            "exchange_timestamp": (
                self.exchange_timestamp.isoformat() if self.exchange_timestamp else None
            ),
            "receipt_timestamp": self.receipt_timestamp.isoformat(),
            "close": self.close,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "volume": self.volume,
            "is_fresh": self.is_fresh(),
        }


# ---------------------------------------------------------------------------
# Protobuf Schema Definition (Upstox Market Data Feed V3)
# Built dynamically using standard google.protobuf runtime descriptors.
# ---------------------------------------------------------------------------
def _build_upstox_protobuf_classes():
    """Builds Upstox V3 Protobuf message classes dynamically from FileDescriptorProto."""
    from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

    fdp = descriptor_pb2.FieldDescriptorProto
    t_double = fdp.TYPE_DOUBLE
    t_int64 = fdp.TYPE_INT64
    t_int32 = fdp.TYPE_INT32
    t_string = fdp.TYPE_STRING
    t_bool = fdp.TYPE_BOOL
    t_msg = fdp.TYPE_MESSAGE

    file_proto = descriptor_pb2.FileDescriptorProto()
    file_proto.name = "MarketDataFeedV3.proto"
    file_proto.package = "com.upstox.marketdatafeederv3udapi.rpc.proto"
    file_proto.syntax = "proto3"

    # LTPC Message
    ltpc = file_proto.message_type.add(name="LTPC")
    ltpc.field.add(name="ltp", number=1, type=t_double)
    ltpc.field.add(name="ltt", number=2, type=t_int64)
    ltpc.field.add(name="ltq", number=3, type=t_int64)
    ltpc.field.add(name="cp", number=4, type=t_double)

    # OHLC Message
    ohlc = file_proto.message_type.add(name="OHLC")
    ohlc.field.add(name="interval", number=1, type=t_string)
    ohlc.field.add(name="open", number=2, type=t_double)
    ohlc.field.add(name="high", number=3, type=t_double)
    ohlc.field.add(name="low", number=4, type=t_double)
    ohlc.field.add(name="close", number=5, type=t_double)
    ohlc.field.add(name="vol", number=6, type=t_int64)
    ohlc.field.add(name="ts", number=7, type=t_int64)

    # MarketOHLC Message
    mohlc = file_proto.message_type.add(name="MarketOHLC")
    mohlc.field.add(
        name="ohlc",
        number=1,
        type=t_msg,
        type_name=".com.upstox.marketdatafeederv3udapi.rpc.proto.OHLC",
        label=fdp.LABEL_REPEATED,
    )

    # MarketFullFeed Message
    mff = file_proto.message_type.add(name="MarketFullFeed")
    mff.field.add(
        name="ltpc",
        number=1,
        type=t_msg,
        type_name=".com.upstox.marketdatafeederv3udapi.rpc.proto.LTPC",
    )
    mff.field.add(
        name="marketOHLC",
        number=4,
        type=t_msg,
        type_name=".com.upstox.marketdatafeederv3udapi.rpc.proto.MarketOHLC",
    )
    mff.field.add(name="atp", number=5, type=t_double)
    mff.field.add(name="vtt", number=6, type=t_int64)

    # IndexFullFeed Message
    iff = file_proto.message_type.add(name="IndexFullFeed")
    iff.field.add(
        name="ltpc",
        number=1,
        type=t_msg,
        type_name=".com.upstox.marketdatafeederv3udapi.rpc.proto.LTPC",
    )
    iff.field.add(
        name="marketOHLC",
        number=2,
        type=t_msg,
        type_name=".com.upstox.marketdatafeederv3udapi.rpc.proto.MarketOHLC",
    )

    # FullFeed Message
    ff = file_proto.message_type.add(name="FullFeed")
    ff.oneof_decl.add(name="FullFeedUnion")
    ff.field.add(
        name="marketFF",
        number=1,
        type=t_msg,
        type_name=".com.upstox.marketdatafeederv3udapi.rpc.proto.MarketFullFeed",
        oneof_index=0,
    )
    ff.field.add(
        name="indexFF",
        number=2,
        type=t_msg,
        type_name=".com.upstox.marketdatafeederv3udapi.rpc.proto.IndexFullFeed",
        oneof_index=0,
    )

    # FirstLevelWithGreeks Message
    fl = file_proto.message_type.add(name="FirstLevelWithGreeks")
    fl.field.add(
        name="ltpc",
        number=1,
        type=t_msg,
        type_name=".com.upstox.marketdatafeederv3udapi.rpc.proto.LTPC",
    )
    fl.field.add(name="vtt", number=4, type=t_int64)

    # Feed Message
    feed = file_proto.message_type.add(name="Feed")
    feed.oneof_decl.add(name="FeedUnion")
    feed.field.add(
        name="ltpc",
        number=1,
        type=t_msg,
        type_name=".com.upstox.marketdatafeederv3udapi.rpc.proto.LTPC",
        oneof_index=0,
    )
    feed.field.add(
        name="fullFeed",
        number=2,
        type=t_msg,
        type_name=".com.upstox.marketdatafeederv3udapi.rpc.proto.FullFeed",
        oneof_index=0,
    )
    feed.field.add(
        name="firstLevelWithGreeks",
        number=3,
        type=t_msg,
        type_name=".com.upstox.marketdatafeederv3udapi.rpc.proto.FirstLevelWithGreeks",
        oneof_index=0,
    )

    # FeedResponse Message
    fr = file_proto.message_type.add(name="FeedResponse")
    fr.field.add(name="type", number=1, type=t_int32)
    fr.field.add(name="currentTs", number=3, type=t_int64)

    entry = fr.nested_type.add(name="FeedsEntry")
    entry.options.map_entry = True
    entry.field.add(name="key", number=1, type=t_string)
    entry.field.add(
        name="value",
        number=2,
        type=t_msg,
        type_name=".com.upstox.marketdatafeederv3udapi.rpc.proto.Feed",
    )

    fr.field.add(
        name="feeds",
        number=2,
        type=t_msg,
        type_name=".com.upstox.marketdatafeederv3udapi.rpc.proto.FeedResponse.FeedsEntry",
        label=fdp.LABEL_REPEATED,
    )

    pool = descriptor_pool.DescriptorPool()
    file_desc = pool.Add(file_proto)

    return {
        "FeedResponse": message_factory.GetMessageClass(file_desc.message_types_by_name["FeedResponse"]),
        "Feed": message_factory.GetMessageClass(file_desc.message_types_by_name["Feed"]),
        "LTPC": message_factory.GetMessageClass(file_desc.message_types_by_name["LTPC"]),
        "FullFeed": message_factory.GetMessageClass(file_desc.message_types_by_name["FullFeed"]),
        "MarketFullFeed": message_factory.GetMessageClass(file_desc.message_types_by_name["MarketFullFeed"]),
        "IndexFullFeed": message_factory.GetMessageClass(file_desc.message_types_by_name["IndexFullFeed"]),
        "OHLC": message_factory.GetMessageClass(file_desc.message_types_by_name["OHLC"]),
        "MarketOHLC": message_factory.GetMessageClass(file_desc.message_types_by_name["MarketOHLC"]),
        "FirstLevelWithGreeks": message_factory.GetMessageClass(
            file_desc.message_types_by_name["FirstLevelWithGreeks"]
        ),
    }


# Singleton protobuf classes container
_PB_CLASSES = _build_upstox_protobuf_classes()
FeedResponseClass = _PB_CLASSES["FeedResponse"]
FeedClass = _PB_CLASSES["Feed"]
LTPCClass = _PB_CLASSES["LTPC"]
FullFeedClass = _PB_CLASSES["FullFeed"]
MarketFullFeedClass = _PB_CLASSES["MarketFullFeed"]
OHLCClass = _PB_CLASSES["OHLC"]

def _persist_live_bar(symbol: str, ltp: float, ts: datetime, volume: int = 0):
    """Flushes/upserts a 1-minute historical price bar into PostgreSQL price_bars table.
    
    Ensures that streaming live quotes are saved into the same table for seamless
    switching between LIVE and REPLAY modes.
    """
    minute_ts = ts.replace(second=0, microsecond=0)
    try:
        with SessionLocal() as session:
            # Check if bar exists for this symbol and minute
            bar = session.query(PriceBar).filter_by(symbol=symbol, timestamp=minute_ts).first()
            if bar:
                bar.high = max(bar.high, ltp)
                bar.low = min(bar.low, ltp)
                bar.close = ltp
                bar.volume = (bar.volume or 0) + volume
            else:
                new_bar = PriceBar(
                    symbol=symbol,
                    timestamp=minute_ts,
                    open=ltp,
                    high=ltp,
                    low=ltp,
                    close=ltp,
                    volume=volume
                )
                session.add(new_bar)
            session.commit()
    except Exception as exc:
        logger.debug("Live bar persistence for %s skipped: %s", symbol, exc)



def decode_feed_response(buffer: bytes) -> Dict[str, UpstoxQuote]:
    """Decodes a binary Upstox V3 Protobuf frame into a mapping of symbol -> UpstoxQuote.
    
    Ignores unverified or unmapped instrument keys.
    """
    quotes: Dict[str, UpstoxQuote] = {}
    try:
        response = FeedResponseClass()
        response.ParseFromString(buffer)
    except Exception as exc:
        logger.warning("Failed to decode Upstox V3 protobuf message: %s", exc)
        return quotes

    now = datetime.now(timezone.utc)

    for instrument_key, feed in response.feeds.items():
        symbol = KEY_TO_SYMBOL.get(instrument_key)
        if not symbol:
            # Unverified or unexpected instrument key, skip safely
            continue

        ltp: Optional[float] = None
        ltt: Optional[int] = None
        cp: Optional[float] = None
        open_val: Optional[float] = None
        high_val: Optional[float] = None
        low_val: Optional[float] = None
        close_val: Optional[float] = None
        volume_val: Optional[int] = None

        union_case = feed.WhichOneof("FeedUnion")

        if union_case == "ltpc" and feed.HasField("ltpc"):
            ltpc = feed.ltpc
            ltp = float(ltpc.ltp)
            ltt = int(ltpc.ltt) if ltpc.ltt else None
            cp = float(ltpc.cp) if ltpc.cp else None

        elif union_case == "fullFeed" and feed.HasField("fullFeed"):
            ff = feed.fullFeed
            ff_case = ff.WhichOneof("FullFeedUnion")

            if ff_case == "marketFF" and ff.HasField("marketFF"):
                mff = ff.marketFF
                if mff.HasField("ltpc"):
                    ltp = float(mff.ltpc.ltp)
                    ltt = int(mff.ltpc.ltt) if mff.ltpc.ltt else None
                    cp = float(mff.ltpc.cp) if mff.ltpc.cp else None
                if mff.vtt:
                    volume_val = int(mff.vtt)

                if mff.HasField("marketOHLC") and len(mff.marketOHLC.ohlc) > 0:
                    first_ohlc = mff.marketOHLC.ohlc[0]
                    open_val = float(first_ohlc.open) if first_ohlc.open else None
                    high_val = float(first_ohlc.high) if first_ohlc.high else None
                    low_val = float(first_ohlc.low) if first_ohlc.low else None
                    close_val = float(first_ohlc.close) if first_ohlc.close else None
                    if first_ohlc.vol:
                        volume_val = int(first_ohlc.vol)

            elif ff_case == "indexFF" and ff.HasField("indexFF"):
                iff = ff.indexFF
                if iff.HasField("ltpc"):
                    ltp = float(iff.ltpc.ltp)
                    ltt = int(iff.ltpc.ltt) if iff.ltpc.ltt else None

        elif union_case == "firstLevelWithGreeks" and feed.HasField("firstLevelWithGreeks"):
            fl = feed.firstLevelWithGreeks
            if fl.HasField("ltpc"):
                ltp = float(fl.ltpc.ltp)
                ltt = int(fl.ltpc.ltt) if fl.ltpc.ltt else None
                cp = float(fl.ltpc.cp) if fl.ltpc.cp else None
            if fl.vtt:
                volume_val = int(fl.vtt)

        if ltp is not None:
            exchange_dt: Optional[datetime] = None
            if ltt and ltt > 0:
                try:
                    # Upstox timestamps are milliseconds epoch
                    exchange_dt = datetime.fromtimestamp(ltt / 1000.0, tz=timezone.utc)
                except Exception:
                    exchange_dt = None

            quotes[symbol] = UpstoxQuote(
                symbol=symbol,
                instrument_key=instrument_key,
                ltp=ltp,
                exchange_timestamp=exchange_dt,
                receipt_timestamp=now,
                close=close_val or cp,
                open=open_val,
                high=high_val,
                low=low_val,
                volume=volume_val,
            )

    return quotes


class UpstoxLiveFeed:
    """Dedicated, read-only Upstox Market Data Feed V3 service.
    
    Subscribes to INFY, RELIANCE, TCS, HDFCBANK, and SBIN via WebSocket.
    Maintains a concurrency-safe cache of latest quotes, tracks connection
    status and data freshness, and reconnects with exponential backoff.
    """

    def __init__(
        self,
        token: Optional[str] = None,
        symbols: Optional[List[str]] = None,
        freshness_threshold_seconds: float = 15.0,
        initial_backoff: float = 1.0,
        max_backoff: float = 30.0,
        backoff_factor: float = 2.0,
        ws_url: Optional[str] = None,
    ):
        # Resolve token from settings if not explicitly provided
        self._token: Optional[str] = token if token is not None else settings.UPSTOX_ACCESS_TOKEN
        self.freshness_threshold_seconds = freshness_threshold_seconds
        self.initial_backoff = initial_backoff
        self.max_backoff = max_backoff
        self.backoff_factor = backoff_factor
        self.custom_ws_url = ws_url

        # Filter and verify target symbols
        requested = symbols if symbols is not None else SUPPORTED_SYMBOLS
        self.symbols: List[str] = [s for s in requested if s in VERIFIED_INSTRUMENTS]

        # In-memory quote cache guarded by lock
        self._cache: Dict[str, UpstoxQuote] = {}
        self._lock = threading.Lock()

        # Connection lifecycle state
        self._is_connected: bool = False
        self._stop_event = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self._reconnect_attempts: int = 0
        self._last_error: Optional[str] = None

    @property
    def is_connected(self) -> bool:
        """Indicates if the WebSocket connection is actively connected."""
        return self._is_connected

    def get_instrument_keys(self) -> List[str]:
        """Returns the verified Upstox instrument keys for configured symbols."""
        return [VERIFIED_INSTRUMENTS[s] for s in self.symbols if s in VERIFIED_INSTRUMENTS]

    def build_subscription_payload(self, mode: str = "full") -> str:
        """Constructs the Upstox V3 JSON subscription message."""
        payload = {
            "guid": "tradezen_sub",
            "method": "sub",
            "data": {
                "mode": mode,
                "instrumentKeys": self.get_instrument_keys(),
            },
        }
        return json.dumps(payload)

    def get_latest_quote(self, symbol: str) -> Optional[UpstoxQuote]:
        """Retrieves the latest cached quote for a symbol in a thread-safe manner."""
        with self._lock:
            return self._cache.get(symbol)

    def get_all_quotes(self) -> Dict[str, UpstoxQuote]:
        """Returns a snapshot copy of all currently cached quotes."""
        with self._lock:
            return dict(self._cache)

    def update_quote(self, quote: UpstoxQuote) -> None:
        """Stores or updates a quote in the in-memory cache."""
        with self._lock:
            self._cache[quote.symbol] = quote

    def update_quotes(self, quotes: Dict[str, UpstoxQuote]) -> None:
        """Stores or updates multiple quotes in the in-memory cache."""
        with self._lock:
            self._cache.update(quotes)

    def is_fresh(self, symbol: str, max_age_seconds: Optional[float] = None) -> bool:
        """Checks if the cached quote for a symbol is fresh."""
        quote = self.get_latest_quote(symbol)
        if not quote:
            return False
        threshold = (
            max_age_seconds if max_age_seconds is not None else self.freshness_threshold_seconds
        )
        return quote.is_fresh(threshold)

    def get_status(self) -> FeedConnectionStatus:
        """Determines the current feed connection and quote freshness status.
        
        Distinguishes:
        - DISCONNECTED: Feed not connected or stopped
        - CONNECTED_WITHOUT_QUOTES: Connected, but no quotes received or all quotes stale
        - CONNECTED_WITH_FRESH_QUOTES: Connected and at least one quote is fresh
        """
        if not self._is_connected:
            return FeedConnectionStatus.DISCONNECTED

        with self._lock:
            if not self._cache:
                return FeedConnectionStatus.CONNECTED_WITHOUT_QUOTES

            has_fresh = any(
                q.is_fresh(self.freshness_threshold_seconds) for q in self._cache.values()
            )
            if has_fresh:
                return FeedConnectionStatus.CONNECTED_WITH_FRESH_QUOTES
            return FeedConnectionStatus.CONNECTED_WITHOUT_QUOTES

    def get_status_details(self) -> Dict[str, Any]:
        """Returns an operational summary of feed status and per-symbol freshness."""
        status = self.get_status()
        with self._lock:
            cache_snapshot = {s: q.to_dict() for s, q in self._cache.items()}

        fresh_count = sum(1 for q in cache_snapshot.values() if q["is_fresh"])

        return {
            "status": status.value,
            "is_connected": self._is_connected,
            "configured_symbols": self.symbols,
            "cached_symbols_count": len(cache_snapshot),
            "fresh_quotes_count": fresh_count,
            "freshness_threshold_seconds": self.freshness_threshold_seconds,
            "reconnect_attempts": self._reconnect_attempts,
            "quotes": cache_snapshot,
        }

    async def get_authorized_ws_url(self) -> str:
        """Obtains authorized WebSocket redirect URI from Upstox API.
        
        Never logs or exposes the access token.
        """
        if self.custom_ws_url:
            return self.custom_ws_url

        if not self._token:
            raise ValueError(
                "UPSTOX_ACCESS_TOKEN is not configured. Live Market Data Feed cannot start."
            )

        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.upstox.com/v3/feed/market-data-feed/authorize",
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            redirect_uri = data.get("data", {}).get("authorizedRedirectUri")
            if not redirect_uri:
                raise RuntimeError("Upstox authorize response did not return authorizedRedirectUri")
            return redirect_uri

    async def _handle_message(self, message: Any) -> None:
        """Processes an incoming WebSocket frame."""
        if isinstance(message, bytes):
            decoded_quotes = decode_feed_response(message)
            if decoded_quotes:
                self.update_quotes(decoded_quotes)
                for sym, q in decoded_quotes.items():
                    ts = q.exchange_timestamp or q.receipt_timestamp or datetime.now(timezone.utc)
                    _persist_live_bar(sym, q.ltp, ts, q.volume or 0)
        elif isinstance(message, str):
            # Text frames (keep-alive, status info, or confirmations)
            logger.debug("Received text frame on Upstox feed: %s", message[:100])

    async def _connection_loop(self) -> None:
        """Manages WebSocket connection and automatic reconnection with backoff."""
        self._stop_event.clear()
        attempt = 0

        while not self._stop_event.is_set():
            try:
                ws_url = await self.get_authorized_ws_url()

                # Connect via WebSocket
                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE

                async with websockets.connect(
                    ws_url,
                    ssl=ssl_context if ws_url.startswith("wss://") else None,
                    ping_interval=20,
                    ping_timeout=10,
                ) as ws:
                    self._is_connected = True
                    attempt = 0
                    self._reconnect_attempts = 0
                    logger.info("Upstox Market Data Feed connected successfully.")

                    # Send subscription payload
                    sub_message = self.build_subscription_payload(mode="full")
                    await ws.send(sub_message)
                    logger.info(
                        "Subscribed to %d instruments on Upstox Feed.", len(self.symbols)
                    )

                    # Stream messages
                    while not self._stop_event.is_set():
                        try:
                            # Use timeout so we can periodically check stop_event
                            msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                            await self._handle_message(msg)
                        except asyncio.TimeoutError:
                            continue
                        except websockets.ConnectionClosed:
                            break

            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._last_error = str(type(exc).__name__)
                logger.warning(
                    "Upstox feed connection encounter error (%s). Reconnecting...",
                    type(exc).__name__,
                )
            finally:
                self._is_connected = False

            if self._stop_event.is_set():
                break

            # Calculate bounded exponential backoff
            delay = min(
                self.initial_backoff * (self.backoff_factor ** attempt),
                self.max_backoff,
            )
            attempt += 1
            self._reconnect_attempts = attempt
            logger.info("Waiting %.1fs before Upstox feed reconnect attempt %d...", delay, attempt)

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass

    def start(self) -> asyncio.Task:
        """Starts the feed streaming in the background.
        
        Fails cleanly if UPSTOX_ACCESS_TOKEN is missing without affecting Replay Mode.
        """
        if not self._token and not self.custom_ws_url:
            raise ValueError(
                "UPSTOX_ACCESS_TOKEN is not configured or empty. Upstox Live Mode cannot start."
            )

        if self._task and not self._task.done():
            logger.warning("Upstox Live Feed is already running.")
            return self._task

        self._stop_event.clear()
        self._task = asyncio.create_task(self._connection_loop())
        return self._task

    async def stop(self) -> None:
        """Stops the live feed and closes all connections."""
        self._stop_event.set()
        self._is_connected = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Upstox Live Feed stopped.")

    def clear_cache(self) -> None:
        """Clears all cached quotes."""
        with self._lock:
            self._cache.clear()


# Global singleton instance for optional use
_feed_instance: Optional[UpstoxLiveFeed] = None


def get_upstox_feed() -> UpstoxLiveFeed:
    """Retrieves or initializes the global UpstoxLiveFeed service instance."""
    global _feed_instance
    if _feed_instance is None:
        _feed_instance = UpstoxLiveFeed()
    return _feed_instance
