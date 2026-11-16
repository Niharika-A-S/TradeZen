"""FastAPI wiring: routes under /live plus install() which starts/stops the feed with your app."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import APIRouter, FastAPI, HTTPException, Query

from .feed import LivePriceUnavailable, LiveFeedService
from .instruments import INSTRUMENTS, resolve_symbol
from .store import BarStore

log = logging.getLogger("tradezen.live")
router = APIRouter(prefix="/live", tags=["live"])
_service: Optional[LiveFeedService] = None


def get_service() -> Optional[LiveFeedService]:
    return _service


def _symbol_or_404(symbol: str) -> str:
    sym = resolve_symbol(symbol)
    if sym is None:
        raise HTTPException(404, {"ok": False, "reason": "unknown_symbol",
                                  "detail": f"'{symbol}' is not supported.", "supported": list(INSTRUMENTS)})
    return sym


def price_or_http_error(symbol: str) -> dict:
    """Use this inside your existing /price handler when the clock is in LIVE mode."""
    sym = _symbol_or_404(symbol)
    svc = get_service()
    if svc is None:
        raise HTTPException(503, {"ok": False, "reason": "live_feed_not_installed", "symbol": sym,
                                  "detail": "Call install(app, engine) at startup."})
    try:
        return svc.get_price(sym)
    except LivePriceUnavailable as exc:
        raise HTTPException(503, {"ok": False, "reason": exc.reason, "detail": exc.detail, "symbol": sym,
                                  "feed_state": svc.state, "market_status": svc._market_label()})


@router.get("/price")
async def live_price(symbol: str = Query(..., description="INFY, RELIANCE, TCS, HDFCBANK or SBIN")):
    return price_or_http_error(symbol)


@router.get("/prices")
async def live_prices():
    svc = get_service()
    out = {}
    for sym in INSTRUMENTS:
        try:
            out[sym] = svc.get_price(sym) if svc else {"ok": False, "reason": "live_feed_not_installed"}
        except LivePriceUnavailable as exc:
            out[sym] = {"ok": False, "reason": exc.reason, "detail": exc.detail}
    return out


@router.get("/candles")
async def live_candles(symbol: str, limit: int = Query(300, ge=1, le=1000)):
    sym = _symbol_or_404(symbol)
    svc = get_service()
    if svc is None:
        raise HTTPException(503, {"ok": False, "reason": "live_feed_not_installed"})
    return {"symbol": sym, "candles": await svc.get_candles(sym, limit)}


@router.get("/status")
async def live_status():
    svc = get_service()
    return svc.status() if svc else {"enabled": False, "state": "not_installed"}


@router.get("/instruments")
async def live_instruments():
    return [{"symbol": i.symbol, "instrument_key": i.key, "name": i.name} for i in INSTRUMENTS.values()]


def install(app: FastAPI, engine=None, *, autostart: bool = True) -> LiveFeedService:
    """Register the routes and tie the feed's lifetime to the app's. Safe to call once at startup."""
    global _service
    svc = LiveFeedService(store=BarStore(engine) if engine is not None else None)
    _service = svc
    app.state.live_feed = svc
    app.include_router(router)
    if autostart:
        original = app.router.lifespan_context

        @asynccontextmanager
        async def combined(a):
            try:
                await svc.start()
            except Exception:
                log.exception("live feed failed to start - the API keeps running")
            try:
                async with original(a) as state:
                    yield state
            finally:
                try:
                    await svc.stop()
                except Exception:
                    log.exception("live feed did not stop cleanly")

        app.router.lifespan_context = combined
    return svc
