"""Health check and readiness endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.scenarios.deps import get_db
from app.config import settings
from app.services.data_health import check_data_health

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    """Basic service health check."""
    return {
        "status": "ok",
        "service": getattr(settings, "PROJECT_NAME", "TradeZen"),
        "environment": settings.ENVIRONMENT,
    }


@router.get("/ready")
def readiness(db: Session = Depends(get_db)):
    """Readiness probe checking database connectivity."""
    try:
        db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as exc:
        db_status = f"unreachable: {str(exc)}"

    return {
        "status": "ready" if db_status == "connected" else "degraded",
        "database": db_status,
        "service": getattr(settings, "PROJECT_NAME", "TradeZen"),
    }


@router.get("/admin/data-health")
def data_health(db: Session = Depends(get_db)):
    """Exposes market data and scenario pool health without exposing secrets."""
    return check_data_health(db=db)
