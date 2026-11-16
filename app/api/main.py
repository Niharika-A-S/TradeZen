"""FastAPI application for TradeZen."""
from contextlib import asynccontextmanager
from datetime import datetime
import logging
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import text

from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.database import get_db, engine
from app.clock.market_clock import (
    MarketClock,
    ClockMode,
    get_price,
    get_bar,
    parse_timestamp,
    PriceQuote
)
from app.models.price_bar import PriceBar
from app.models.paper import (
    Account,
    OrderSide,
    OrderType,
    ProductType,
    OrderStatus,
    ORDER_CHARGES,
    INITIAL_PAPER_CASH,
)
from app.models.user import User, UserProfile, default_trading_rules
from app.auth import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user,
    require_user,
)
from app.broker.paper_broker import PaperBroker
from app.live import install, price_or_http_error
from app.live.instruments import INSTRUMENTS, resolve_symbol

logger = logging.getLogger(__name__)

# Global market clock instance
market_clock = MarketClock(
    mode=ClockMode.REPLAY,
    replay_date="2022-03-10",
    start_time="09:15"
)

# Global paper trading broker instance
paper_broker = PaperBroker(clock=market_clock)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager to start and stop background services cleanly."""
    yield


app = FastAPI(
    title="TradeZen API",
    description="Paper-trading & behavioral coaching platform backend",
    version="0.2.0",
    lifespan=lifespan,
)

# Wire in app.live: installs /live routes and feeds lifecycle into FastAPI app
live_service = install(app, engine)

# Enable CORS for local browser frontend origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ClockStatusResponse(BaseModel):
    mode: str
    current_time: str
    is_market_open: bool
    replay_date: Optional[str] = None


class SwitchClockModeRequest(BaseModel):
    mode: ClockMode
    replay_date: Optional[str] = "2022-03-10"
    start_time: Optional[str] = "09:15"
    end_time: Optional[str] = "15:30"


class ClockTickRequest(BaseModel):
    minutes: int = Field(default=1, ge=1, le=375, description="Minutes to advance")


class PriceResponse(BaseModel):
    symbol: str
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: int


@app.get("/", tags=["General"])
def root():
    return {
        "app": "TradeZen",
        "version": "0.1.0",
        "status": "online",
        "step": 1,
        "step_name": "Data and Replay Clock"
    }


@app.get("/health", tags=["General"])
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1")).scalar()
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {str(e)}"
    return {
        "status": "healthy" if db_status == "connected" else "unhealthy",
        "database": db_status,
        "environment": settings.ENVIRONMENT
    }


@app.get("/clock", response_model=ClockStatusResponse, tags=["Clock"])
def get_clock_status():
    """Returns current state of the MarketClock."""
    ct = market_clock.current_time
    return ClockStatusResponse(
        mode=market_clock.mode.value,
        current_time=ct.strftime("%Y-%m-%d %H:%M:%S"),
        is_market_open=market_clock.is_market_open,
        replay_date=str(market_clock._replay_date) if market_clock._replay_date else None
    )


@app.post("/clock/mode", response_model=ClockStatusResponse, tags=["Clock"])
def switch_clock_mode(req: SwitchClockModeRequest):
    """Switches clock mode between LIVE and REPLAY."""
    market_clock.set_mode(
        mode=req.mode,
        replay_date=req.replay_date,
        start_time=req.start_time,
        end_time=req.end_time
    )
    return get_clock_status()


@app.post("/clock/tick", response_model=ClockStatusResponse, tags=["Clock"])
def tick_clock(req: ClockTickRequest = ClockTickRequest(), db: Session = Depends(get_db)):
    """Advances clock in REPLAY mode by specified minutes, processing pending orders and intraday square-offs."""
    if market_clock.mode != ClockMode.REPLAY:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot tick clock in LIVE mode. Switch to REPLAY mode first."
        )
    market_clock.tick(minutes=req.minutes)
    # Check limit orders and intraday auto-square-offs
    paper_broker.process_pending_orders(db)
    paper_broker.auto_square_off_intraday(db=db)
    return get_clock_status()


@app.get("/price", response_model=PriceResponse, tags=["Market Data"])
def get_historical_price(
    symbol: str = Query(..., description="Stock symbol (e.g., INFY, RELIANCE)"),
    timestamp: Optional[str] = Query(None, description="Optional timestamp (YYYY-MM-DD HH:MM). Defaults to current clock time."),
    db: Session = Depends(get_db)
):
    """Historical and live price lookup endpoint.
    
    If in LIVE mode (without timestamp), returns price_or_http_error(symbol) from app.live.
    If in REPLAY mode (or historical timestamp), returns price bar at simulated clock time.
    """
    sym = resolve_symbol(symbol) or symbol.strip().upper()
    if market_clock.mode == ClockMode.LIVE and not timestamp:
        data = price_or_http_error(sym)
        return PriceResponse(
            symbol=data["symbol"],
            timestamp=data.get("ltt") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            open=float(data.get("open", data.get("ltp", 0.0))),
            high=float(data.get("high", data.get("ltp", 0.0))),
            low=float(data.get("low", data.get("ltp", 0.0))),
            close=float(data.get("ltp", 0.0)),
            volume=int(data.get("volume", 0)),
        )

    try:
        if timestamp:
            quote = get_price(sym, timestamp, session=db)
        else:
            quote = market_clock.get_current_price(sym, session=db)
        return PriceResponse(
            symbol=quote.symbol,
            timestamp=quote.timestamp.strftime("%Y-%m-%d %H:%M:%S") if quote.timestamp else "",
            open=quote.open,
            high=quote.high,
            low=quote.low,
            close=quote.close,
            volume=quote.volume
        )
    except KeyError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@app.get("/bars", response_model=List[PriceResponse], tags=["Market Data"])
def get_price_bars(
    symbol: str = Query(..., description="Stock symbol"),
    start_time: str = Query(..., description="Start timestamp (YYYY-MM-DD HH:MM)"),
    end_time: str = Query(..., description="End timestamp (YYYY-MM-DD HH:MM)"),
    limit: int = Query(500, ge=1, le=5000),
    db: Session = Depends(get_db)
):
    """Fetches a sequence of price bars between start_time and end_time."""
    sym = symbol.strip().upper()
    start_dt = parse_timestamp(start_time)
    end_dt = parse_timestamp(end_time)

    bars = (
        db.query(PriceBar)
        .filter(
            PriceBar.symbol == sym,
            PriceBar.timestamp >= start_dt,
            PriceBar.timestamp <= end_dt
        )
        .order_by(PriceBar.timestamp.asc())
        .limit(limit)
        .all()
    )

    return [
        PriceResponse(
            symbol=b.symbol,
            timestamp=b.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            open=b.open,
            high=b.high,
            low=b.low,
            close=b.close,
            volume=b.volume
        )
        for b in bars
    ]


# ---------------------------------------------------------
# Authentication Models & Endpoints
# ---------------------------------------------------------
class SignupRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, description="Unique username")
    password: str = Field(..., min_length=6, description="Password (min 6 characters)")
    email: Optional[str] = Field(None, description="Optional email address")


class LoginRequest(BaseModel):
    username: str = Field(..., description="Username")
    password: str = Field(..., description="Password")


@app.post("/auth/signup", tags=["Authentication"], status_code=status.HTTP_201_CREATED)
def signup(req: SignupRequest, db: Session = Depends(get_db)):
    """Registers a new user, creates their isolated 10L paper account and risk profile."""
    username = req.username.strip()
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Username '{username}' is already taken."
        )

    if req.email and req.email.strip():
        email = req.email.strip()
        if db.query(User).filter(User.email == email).first():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Email '{email}' is already registered."
            )
    else:
        email = None

    user = User(
        username=username,
        email=email,
        hashed_password=hash_password(req.password)
    )
    db.add(user)
    db.flush()

    # Create default user profile with trading rules
    profile = UserProfile(user_id=user.id, rules_json=default_trading_rules())
    db.add(profile)

    # Create 10L fake cash paper account
    account = Account(
        user_id=user.id,
        cash_balance=INITIAL_PAPER_CASH,
        initial_cash=INITIAL_PAPER_CASH
    )
    db.add(account)
    db.commit()
    db.refresh(user)
    db.refresh(account)

    token = create_access_token({"sub": str(user.id), "username": user.username})
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": user.to_dict(),
        "account": account.to_dict()
    }


@app.post("/auth/login", tags=["Authentication"])
def login(req: LoginRequest, db: Session = Depends(get_db)):
    """Authenticates user with username & password, returning JWT access token."""
    username = req.username.strip()
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    account = paper_broker.get_or_create_account(user.id, db)
    token = create_access_token({"sub": str(user.id), "username": user.username})
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": user.to_dict(),
        "account": account.to_dict()
    }


@app.get("/auth/me", tags=["Authentication"])
def get_me(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Returns the authenticated user's profile, trading rules, and account summary."""
    account = paper_broker.get_account_summary(user.id, db)
    profile = db.query(UserProfile).filter_by(user_id=user.id).first()
    return {
        "user": user.to_dict(),
        "account": account,
        "rules": profile.rules_json if profile else default_trading_rules()
    }


# ---------------------------------------------------------
# Step 2: Paper-Trading Engine Endpoints
# ---------------------------------------------------------

class OrderCreateRequest(BaseModel):
    user_id: int = Field(default=settings.DEFAULT_USER_ID, description="User ID")
    symbol: str = Field(..., description="Stock symbol, e.g. INFY")
    side: OrderSide = Field(..., description="BUY or SELL")
    order_type: OrderType = Field(default=OrderType.MARKET, description="MARKET or LIMIT")
    quantity: int = Field(..., gt=0, description="Quantity of shares")
    price: Optional[float] = Field(None, description="Limit price (required for LIMIT orders)")
    product_type: ProductType = Field(default=ProductType.MIS, description="MIS (Intraday) or CNC (Delivery)")
    stop_loss: Optional[float] = Field(None, description="Optional stop-loss price")
    apply_slippage: bool = Field(default=True, description="Apply 0.05% slippage on MARKET orders")


@app.post("/paper/orders", tags=["Paper Trading"], status_code=status.HTTP_201_CREATED)
def place_paper_order(req: OrderCreateRequest, db: Session = Depends(get_db)):
    """Places a new paper order (MARKET or LIMIT).
    
    - Rejects orders that exceed cash (BUY)
    - Rejects orders that sell more than owned (SELL - no short selling)
    - Applies 0.05% slippage in adverse direction on MARKET orders
    - Deducts flat Rs 20 charges per executed order
    """
    if req.order_type == OrderType.LIMIT and (req.price is None or req.price <= 0):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Limit orders require a valid price > 0."
        )

    order = paper_broker.place_order(
        user_id=req.user_id,
        symbol=req.symbol,
        side=req.side.value,
        order_type=req.order_type.value,
        quantity=req.quantity,
        price=req.price,
        product_type=req.product_type.value,
        stop_loss=req.stop_loss,
        apply_slippage=req.apply_slippage,
        db=db
    )

    if order.status == OrderStatus.REJECTED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Order rejected: {order.rejection_reason}"
        )

    return order.to_dict()


@app.get("/paper/account", tags=["Paper Trading"])
def get_paper_account(user_id: int = Query(settings.DEFAULT_USER_ID), db: Session = Depends(get_db)):
    """Retrieves account summary: cash balance, portfolio value, realized P&L, and unrealized P&L."""
    return paper_broker.get_account_summary(user_id, db=db)


@app.get("/paper/positions", tags=["Paper Trading"])
def get_paper_positions(
    user_id: int = Query(settings.DEFAULT_USER_ID),
    open_only: bool = Query(True, description="Filter for only open positions (quantity > 0)"),
    db: Session = Depends(get_db)
):
    """Retrieves positions with weighted average entry prices, live market prices, and unrealized P&L."""
    return paper_broker.get_positions(user_id, open_only=open_only, db=db)


@app.get("/paper/trades", tags=["Paper Trading"])
def get_paper_trades(
    user_id: int = Query(settings.DEFAULT_USER_ID),
    symbol: Optional[str] = Query(None, description="Optional symbol filter"),
    db: Session = Depends(get_db)
):
    """Retrieves trade execution history."""
    return paper_broker.get_trades(user_id, symbol=symbol, db=db)


@app.delete("/paper/orders/{order_id}", tags=["Paper Trading"])
def cancel_paper_order(
    order_id: int,
    user_id: int = Query(settings.DEFAULT_USER_ID),
    db: Session = Depends(get_db)
):
    """Cancels a pending limit order."""
    try:
        order = paper_broker.cancel_order(order_id, user_id=user_id, db=db)
        return {"message": f"Order #{order_id} cancelled successfully", "order": order.to_dict()}
    except KeyError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@app.post("/paper/square-off", tags=["Paper Trading"])
def auto_square_off_mis(
    user_id: Optional[int] = Query(None, description="Optional user ID filter"),
    db: Session = Depends(get_db)
):
    """Manually triggers or tests auto-square-off of intraday (MIS) positions."""
    orders = paper_broker.auto_square_off_intraday(user_id=user_id, db=db)
    return {
        "squared_off_count": len(orders),
        "orders": [o.to_dict() for o in orders]
    }


# ---------------------------------------------------------
# Step 3: Rule Engine & Alerts Endpoints
# ---------------------------------------------------------

from fastapi import WebSocket, WebSocketDisconnect
from app.api.websocket import alert_manager
from app.rules.rule_engine import pre_trade_check
from app.models.alert import Alert
from app.models.user import UserProfile
from app.models.paper import Account


@app.post("/paper/orders/pre-check", tags=["Rule Engine"])
def pre_trade_order_check(req: OrderCreateRequest, db: Session = Depends(get_db)):
    """Pre-trade check endpoint: Returns warnings if the proposed order breaks user rules.
    
    The user can review warnings to cancel or proceed to place the order.
    """
    sym = req.symbol.strip().upper()
    try:
        cur_price = req.price if req.price and req.price > 0 else paper_broker.get_current_market_price(sym, db)
    except Exception as e:
        cur_price = req.price or 1000.0

    profile = db.query(UserProfile).filter_by(user_id=req.user_id).first()
    account = db.query(Account).filter_by(user_id=req.user_id).first()

    warnings = pre_trade_check(
        user_id=req.user_id,
        symbol=sym,
        side=req.side.value,
        quantity=req.quantity,
        entry_price=cur_price,
        stop_loss=req.stop_loss,
        user_profile=profile,
        account=account,
        db=db,
        clock=market_clock
    )
    return {
        "symbol": sym,
        "has_warnings": len(warnings) > 0,
        "warnings_count": len(warnings),
        "warnings": warnings
    }


@app.get("/alerts/{user_id}", tags=["Rule Engine"])
def get_user_alerts(
    user_id: int,
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db)
):
    """Retrieves saved behavioral and rule violation alerts for a user."""
    alerts = (
        db.query(Alert)
        .filter_by(user_id=user_id)
        .order_by(Alert.created_at.desc())
        .limit(limit)
        .all()
    )
    return [a.to_dict() for a in alerts]


@app.websocket("/ws/alerts/{user_id}")
async def websocket_alerts_endpoint(websocket: WebSocket, user_id: int):
    """WebSocket endpoint streaming live alerts to user in real time."""
    await alert_manager.connect(user_id, websocket)
    try:
        while True:
            # Keeps connection alive and receives any client ping
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        alert_manager.disconnect(user_id, websocket)


# ---------------------------------------------------------
# Step 5: Behavioral Risk Model Prediction Endpoints
# ---------------------------------------------------------

class RiskPredictionRequest(BaseModel):
    user_id: int = 1
    now: Optional[str] = None
    create_alert: bool = True


@app.post("/paper/risk/predict", tags=["ML Coaching"])
def predict_user_risk_endpoint(req: RiskPredictionRequest, db: Session = Depends(get_db)):
    """Predicts behavioral violation risk for user_id using the trained XGBoost model.
    
    If risk >= threshold, creates a MODEL_RISK alert with coaching reasons and streams via WebSocket.
    """
    from app.ml.predictor import predict_violation_risk
    eval_time = parse_timestamp(req.now) if req.now else market_clock.current_time
    try:
        return predict_violation_risk(
            user_id=req.user_id,
            now=eval_time,
            db=db,
            create_alert=req.create_alert
        )
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e)
        )


# ---------------------------------------------------------
# Step 6: Rules Setup & Market Helpers Endpoints
# ---------------------------------------------------------

class RulesUpdateRequest(BaseModel):
    max_trades_per_day: Optional[int] = Field(None, ge=1, le=50)
    max_risk_per_trade_pct: Optional[float] = Field(None, ge=0.1, le=10.0)
    max_daily_loss: Optional[float] = Field(None, gt=0)
    max_consecutive_losses: Optional[int] = Field(None, ge=1, le=10)
    require_stop_loss: Optional[bool] = None
    intraday_cutoff_time: Optional[str] = None


@app.get("/rules/{user_id}", tags=["Rule Engine"])
def get_user_rules(user_id: int, db: Session = Depends(get_db)):
    """Retrieves user trading rules configuration."""
    from app.models.user import UserProfile, default_trading_rules
    profile = db.query(UserProfile).filter_by(user_id=user_id).first()
    if not profile or not profile.rules_json:
        return default_trading_rules()
    return profile.rules_json


@app.put("/rules/{user_id}", tags=["Rule Engine"])
def update_user_rules(user_id: int, req: RulesUpdateRequest, db: Session = Depends(get_db)):
    """Updates user trading rules configuration."""
    from app.models.user import UserProfile, default_trading_rules
    profile = db.query(UserProfile).filter_by(user_id=user_id).first()
    if not profile:
        profile = UserProfile(user_id=user_id, rules_json=default_trading_rules())
        db.add(profile)
        db.flush()

    current_rules = dict(profile.rules_json or default_trading_rules())
    updates = req.model_dump(exclude_unset=True)
    current_rules.update(updates)

    profile.rules_json = current_rules
    db.commit()
    db.refresh(profile)
    return profile.rules_json


@app.get("/market/symbols", tags=["Market Data"])
def get_tradable_symbols():
    """Returns list of tradable universe stocks."""
    return list(INSTRUMENTS.keys())



# ---------------------------------------------------------------------------
# Mount TradeZen Coach Chatbot Module
# ---------------------------------------------------------------------------
try:
    from app.chatbot.api import router as chatbot_router
    from app.chatbot.rag import rag_engine
    import threading

    app.include_router(chatbot_router)
    threading.Thread(target=lambda: rag_engine.ingest(force=False), daemon=True).start()
    logger.info("TradeZen Coach chatbot mounted successfully.")
except Exception as _cb_err:
    logger.warning("Could not mount chatbot router: %s", _cb_err)


# ---------------------------------------------------------------------------
# Mount Scenario Simulation Module
# ---------------------------------------------------------------------------
try:
    from app.scenarios.v1 import api_router as scenarios_router
    app.include_router(scenarios_router, prefix="/api/v1")
    app.include_router(scenarios_router, prefix="/v1")
    logger.info("TradeZen Scenarios API mounted successfully.")
except Exception as _sc_err:
    logger.warning("Could not mount scenarios router: %s", _sc_err)
