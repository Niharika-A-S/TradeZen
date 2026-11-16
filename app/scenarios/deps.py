"""Dependencies for scenarios and coaching modules."""
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
import jwt

from app.config import settings
from app.database import get_db
from app.models.user import User
from app.auth import get_current_user as auth_get_current_user, require_user, decode_token

security_scheme = HTTPBearer(auto_error=False)

_failed_login_attempts: Dict[str, List[datetime]] = {}
RATE_LIMIT_WINDOW_MINUTES = 15
MAX_FAILED_ATTEMPTS = 5


def check_login_rate_limit(ip: str, email: str) -> None:
    """Enforces 5 failed tries per 15 min per IP and email."""
    key = f"{ip}:{email.lower().strip()}"
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=RATE_LIMIT_WINDOW_MINUTES)
    attempts = [t for t in _failed_login_attempts.get(key, []) if t > cutoff]
    _failed_login_attempts[key] = attempts

    if len(attempts) >= MAX_FAILED_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Please try again in 15 minutes.",
        )


def record_failed_login(ip: str, email: str) -> None:
    key = f"{ip}:{email.lower().strip()}"
    now = datetime.now(timezone.utc)
    if key not in _failed_login_attempts:
        _failed_login_attempts[key] = []
    _failed_login_attempts[key].append(now)


def clear_failed_logins(ip: str, email: str) -> None:
    key = f"{ip}:{email.lower().strip()}"
    _failed_login_attempts.pop(key, None)


def get_current_user(
    request: Request = None,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Ensures user is authenticated and returns User entity. Falls back to default user if guest."""
    user = auth_get_current_user(request=request, credentials=credentials, db=db)
    if not user:
        user = db.query(User).filter(User.id == 1).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please log in.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
