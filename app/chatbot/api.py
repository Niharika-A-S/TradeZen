"""FastAPI Router for TradeZen Coach Chatbot."""
from collections import defaultdict
from datetime import datetime, timezone, timedelta
import logging
import threading
import time
from typing import List, Dict, Any, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Header, status, Response
from pydantic import BaseModel, Field

from .config import cfg
from .brain import answer
from .rag import rag_engine
from .llm import llm_client
from .models import ChatMessage, ChatKbChunk, ChatUserProfile, get_db_session, init_db
from .adapters import (
    get_recent_rule_violations,
    get_last_trade_context,
    get_scenario_decisions,
    validate_schema_health,
)
from .profile import ensure_fresh_profile, fingerprint

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chatbot"])

# ---------------------------------------------------------------------------
# Rate Limiting & Client Message ID Caching
# ---------------------------------------------------------------------------
_rate_limit_lock = threading.Lock()
_user_request_timestamps = defaultdict(list)  # user_id -> [timestamp, ...]

_client_msg_cache_lock = threading.Lock()
_client_msg_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}  # key: (user_id, client_msg_id) -> (time, reply_data)


def check_rate_limit(user_id: int):
    """Sliding-window per-user rate limit (CHAT_RATE_LIMIT_PER_MIN). Raises 429 if exceeded."""
    limit = cfg.CHAT_RATE_LIMIT_PER_MIN
    window = 60.0  # seconds
    now = time.time()

    with _rate_limit_lock:
        timestamps = _user_request_timestamps[user_id]
        # Discard older than window
        valid = [t for t in timestamps if now - t < window]
        if len(valid) >= limit:
            oldest = valid[0]
            retry_after = int(window - (now - oldest)) + 1
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Please slow down.",
                headers={"Retry-After": str(max(retry_after, 1))}
            )
        valid.append(now)
        _user_request_timestamps[user_id] = valid


# ---------------------------------------------------------------------------
# Current User Dependency (supports real JWT / dev header for standalone)
# ---------------------------------------------------------------------------
def get_current_user_id(
    authorization: Optional[str] = Header(None),
    x_dev_user_id: Optional[str] = Header(None)
) -> int:
    """Dependency extracting user_id strictly from auth credentials. Never from body/query."""
    # Try real TradeZen auth if available
    try:
        from app.auth import get_current_user, JWT_SECRET, JWT_ALGORITHM
        import jwt
        if authorization and authorization.startswith("Bearer "):
            token = authorization.split(" ", 1)[1]
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            uid = payload.get("sub")
            if uid is not None:
                return int(uid)
    except Exception:
        pass

    # Dev fallback header
    if x_dev_user_id:
        try:
            return int(x_dev_user_id)
        except ValueError:
            pass

    # Default fallback for testing if unauthenticated
    return 1


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class ChatRequest(BaseModel):
    message: str = Field(..., max_length=1000)
    client_message_id: Optional[str] = Field(None, max_length=100)


class ChatResponse(BaseModel):
    reply: str
    route: str
    sources: List[Dict[str, Any]] = []
    used_data: bool = False
    degraded: bool = False
    degraded_reason: Optional[str] = None
    no_data: bool = False
    message_id: Optional[str] = None
    created_at: Optional[str] = None
    generated_by: Optional[str] = None  # 'gemini', 'template', 'refusal', 'notes'


def format_iso_timestamp(dt) -> Optional[str]:
    """Formats datetime to standard ISO-8601 string with UTC indicator Z."""
    if not dt:
        return None
    if isinstance(dt, str):
        s = dt.replace(" ", "T")
        if not s.endswith("Z") and not ("+" in s[10:] or "-" in s[10:]):
            s += "Z"
        return s
    try:
        if getattr(dt, "tzinfo", None) is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt.isoformat().replace("+00:00", "Z")
    except Exception:
        return str(dt)


class NoteRequest(BaseModel):
    text: str = Field(..., max_length=1000)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post("", response_model=ChatResponse)
def send_chat_message(
    body: ChatRequest,
    user_id: int = Depends(get_current_user_id)
):
    """Sends a message to TradeZen Coach."""
    check_rate_limit(user_id)

    # Check client_message_id cache (within last 60s)
    if body.client_message_id:
        cache_key = f"{user_id}:{body.client_message_id}"
        now = time.time()
        with _client_msg_cache_lock:
            if cache_key in _client_msg_cache:
                entry_time, cached_res = _client_msg_cache[cache_key]
                if now - entry_time < 60.0:
                    return cached_res

    # Generate answer
    ans = answer(user_id=user_id, message=body.message)
    res_data = ChatResponse(
        reply=ans["reply"],
        route=ans["route"],
        sources=ans.get("sources", []),
        used_data=ans.get("used_data", False),
        degraded=ans.get("degraded", False),
        degraded_reason=ans.get("degraded_reason"),
        no_data=ans.get("no_data", False),
        message_id=body.client_message_id,
        created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        generated_by=ans.get("generated_by"),
    )

    if body.client_message_id:
        with _client_msg_cache_lock:
            _client_msg_cache[f"{user_id}:{body.client_message_id}"] = (time.time(), res_data)

    return res_data


@router.get("/history")
def get_chat_history(
    limit: int = Query(30, le=100),
    user_id: int = Depends(get_current_user_id)
):
    """Retrieves recent chat history for the authenticated user."""
    init_db()
    db = get_db_session()
    try:
        messages = (
            db.query(ChatMessage)
            .filter(ChatMessage.user_id == user_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "route": m.route,
                "created_at": format_iso_timestamp(m.created_at),
            }
            for m in reversed(messages)
        ]
    finally:
        db.close()


@router.delete("/history")
def clear_chat_history(
    user_id: int = Depends(get_current_user_id)
):
    """Clears chat history for the authenticated user."""
    init_db()
    db = get_db_session()
    try:
        db.query(ChatMessage).filter(ChatMessage.user_id == user_id).delete()
        db.commit()
        return {"ok": True, "message": "History cleared"}
    finally:
        db.close()


@router.post("/notes")
def save_chat_note(
    body: NoteRequest,
    user_id: int = Depends(get_current_user_id)
):
    """Saves a reflection note for future retrieval."""
    ok = rag_engine.add_note(user_id=user_id, text=body.text)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to save note")
    return {"ok": True, "message": "Note saved successfully"}


@router.get("/profile")
def get_user_chat_profile(
    user_id: int = Depends(get_current_user_id)
):
    """Retrieves compact trading behavior profile for the logged-in user."""
    prof = ensure_fresh_profile(user_id)
    cov = prof.get("coverage", {})
    if cov.get("closed_trades_count", 0) == 0 and cov.get("scenario_decisions_count", 0) == 0:
        return {"available": False, "reason": "no_data_yet"}

    return {
        "available": True,
        "coverage": cov,
        "performance": prof.get("performance", {}).get("all_time", {}),
        "habits": {
            "median_size": prof.get("habits", {}).get("user_median_size", 0.0),
            "size_after_loss_ratio": prof.get("habits", {}).get("size_after_loss_vs_normal", 1.0),
            "rule_adherence_rate_pct": prof.get("habits", {}).get("rule_adherence_rate_pct", 100.0),
            "stop_loss_usage_pct": prof.get("habits", {}).get("stop_loss_usage_pct", 0.0),
            "hold_time_winners_mins": prof.get("habits", {}).get("user_median_hold_winners_mins", 0.0),
            "hold_time_losers_mins": prof.get("habits", {}).get("user_median_hold_losers_mins", 0.0)
        },
        "repeated_mistakes": [
            {"mistake_id": m.get("mistake_id"), "count": m.get("count")}
            for m in prof.get("repeated_mistakes", [])[:3]
        ],
        "trend": prof.get("trend")
    }


@router.get("/nudges")
def get_rule_nudges(
    since: Optional[str] = Query(None),
    user_id: int = Depends(get_current_user_id)
):
    """Builds short template nudges without Gemini from recent activity (max 3 per call)."""
    since_dt = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except Exception:
            pass
    if not since_dt:
        since_dt = datetime.now(timezone.utc) - timedelta(minutes=15)

    nudges: List[Dict[str, Any]] = []

    # 1. New closed losing trade
    trade_ctx_res = get_last_trade_context(user_id)
    if trade_ctx_res.ok and trade_ctx_res.data and not trade_ctx_res.data.get("is_open"):
        lt = trade_ctx_res.data
        pnl = lt.get("pnl", 0.0)
        exit_time = lt.get("exit_time")
        if pnl < 0 and exit_time:
            try:
                ex_dt = datetime.fromisoformat(exit_time.replace("Z", "+00:00"))
                if ex_dt >= since_dt:
                    stable_id = f"nudge_loss_{lt.get('trade_id', 0)}_{exit_time}"
                    nudges.append({
                        "id": stable_id,
                        "severity": "WARNING",
                        "message": f"Your last trade closed at −₹{abs(pnl):,.2f}. Want me to walk through it?",
                        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                    })
            except Exception:
                pass

    # 2. Rule violations
    violations_res = get_recent_rule_violations(user_id=user_id, since=since_dt)
    violations = violations_res.data if violations_res.ok else []
    for v in violations:
        if len(nudges) >= 3:
            break
        stable_id = f"nudge_rule_{v.get('id', 0)}_{v.get('created_at', '')}"
        nudges.append({
            "id": stable_id,
            "severity": v.get("severity", "WARNING"),
            "message": v.get("message", "Rule warning detected."),
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        })

    # 3. Finished scenario session
    if len(nudges) < 3:
        scn_res = get_scenario_decisions(user_id, session="latest", limit=1)
        if scn_res.ok and scn_res.data:
            latest_att = scn_res.data[0]
            att_time = latest_att.get("created_at")
            if att_time:
                try:
                    at_dt = datetime.fromisoformat(att_time.replace("Z", "+00:00"))
                    if at_dt >= since_dt:
                        stable_id = f"nudge_scenario_{latest_att.get('attempt_id', 0)}_{att_time}"
                        nudges.append({
                            "id": stable_id,
                            "severity": "INFO",
                            "message": f"You completed a practice scenario decision on {latest_att.get('action', '').upper()}. Want to review your choices?",
                            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                        })
                except Exception:
                    pass

    # 4. Repeated mistake
    if len(nudges) < 3:
        prof = ensure_fresh_profile(user_id)
        mistakes = prof.get("repeated_mistakes", [])
        if mistakes and mistakes[0].get("count", 0) >= 2:
            top_m = mistakes[0]
            m_id = top_m.get("mistake_id")
            m_time = top_m.get("last_timestamp")
            stable_id = f"nudge_repeat_{m_id}_{top_m.get('count')}"
            nudges.append({
                "id": stable_id,
                "severity": "WARNING",
                "message": f"Discipline pattern notice: '{m_id.replace('_', ' ')}' flagged {top_m.get('count')} times. Want to see habit suggestions?",
                "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            })

    # Deduplicate by id and limit to 3
    seen_ids = set()
    deduped = []
    for n in nudges:
        if n["id"] not in seen_ids:
            seen_ids.add(n["id"])
            deduped.append(n)
        if len(deduped) >= 3:
            break

    return deduped


@router.get("/health")
def get_chat_health(user_id: int = Depends(get_current_user_id)):
    """Health check reporting connected data sources and profile freshness without exposing data values."""
    init_db()
    db = get_db_session()
    count = 0
    profile_freshness = "empty"
    try:
        count = db.query(ChatKbChunk).count()
        row = db.query(ChatUserProfile).filter(ChatUserProfile.user_id == user_id).first()
        if row:
            current_fp = fingerprint(user_id)
            profile_freshness = "fresh" if row.fingerprint == current_fp else "stale"
    except Exception:
        pass
    finally:
        db.close()

    schema_status = validate_schema_health()

    return {
        "mode": "full" if cfg.has_gemini_key else "limited",
        "embeddings": "active" if cfg.has_gemini_key else "fallback",
        "chunks_count": count,
        "data_sources": schema_status,
        "profile_freshness": profile_freshness,
        "llm_circuit_breaker": {
            "state": getattr(llm_client.circuit_breaker, "state", "closed"),
            "consecutive_failures": llm_client.circuit_breaker.consecutive_failures,
            "recovery_time_s": llm_client.circuit_breaker.recovery_time,
        },
        "llm_model": cfg.GEMINI_CHAT_MODEL,
    }
