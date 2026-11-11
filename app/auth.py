"""Unified Authentication module for TradeZen: Dual-Hash Verifier (PBKDF2 & Argon2), JWT Tokens, and User Dependencies."""
import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from sqlalchemy import or_, func

from app.config import settings
from app.database import get_db
from app.models.user import User

# Argon2 hasher instance for modern hashes
try:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError, VerificationError
    _hasher = PasswordHasher()
except ImportError:
    _hasher = None

# JWT Secret and algorithm configuration
JWT_SECRET = getattr(settings, "JWT_SECRET", "tradezen_secret_jwt_key_secure_2026")
JWT_ALGORITHM = getattr(settings, "JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = getattr(settings, "ACCESS_TOKEN_EXPIRE_MINUTES", 60 * 24 * 7)
REFRESH_TOKEN_EXPIRE_DAYS = getattr(settings, "REFRESH_TOKEN_EXPIRE_DAYS", 7)


def hash_password(password: str) -> str:
    """Hashes a password with Argon2 if available, falling back to PBKDF2-HMAC-SHA256."""
    if _hasher:
        return _hasher.hash(password)
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        100000
    ).hex()
    return f"{salt}:{key}"


def verify_password(plain_password: str, hashed_password: Optional[str]) -> bool:
    """Verifies a plain password against Argon2 hash, PBKDF2 salt:hash, or plain string."""
    if not hashed_password:
        return False

    # Check Argon2 format ($argon2...)
    if hashed_password.startswith("$argon2"):
        if _hasher:
            try:
                return _hasher.verify(hashed_password, plain_password)
            except Exception:
                return False
        return False

    # Check PBKDF2 format (salt:hash)
    if ":" in hashed_password:
        try:
            salt, expected_key = hashed_password.split(":", 1)
            computed_key = hashlib.pbkdf2_hmac(
                "sha256",
                plain_password.encode("utf-8"),
                salt.encode("utf-8"),
                100000
            ).hex()
            return secrets.compare_digest(expected_key, computed_key)
        except Exception:
            return False

    # Fallback comparison if raw string
    return secrets.compare_digest(plain_password, hashed_password)


def create_access_token(data_or_sub: Any, expires_delta: Optional[timedelta] = None) -> str:
    """Generates a signed JWT access token supporting both dict payloads and subject strings."""
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    if isinstance(data_or_sub, dict):
        to_encode = data_or_sub.copy()
        to_encode.setdefault("iat", now)
        to_encode.setdefault("exp", expire)
        to_encode.setdefault("type", "access")
    else:
        to_encode = {
            "sub": str(data_or_sub),
            "exp": expire,
            "iat": now,
            "type": "access",
        }
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_refresh_token(subject: str, expires_delta: Optional[timedelta] = None) -> str:
    """Creates a signed JWT refresh token."""
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    to_encode: Dict[str, Any] = {
        "sub": str(subject),
        "exp": expire,
        "iat": now,
        "type": "refresh",
    }
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> Dict[str, Any]:
    """Decodes and validates a JWT token."""
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


# HTTP Bearer scheme
security = HTTPBearer(auto_error=False)


def get_current_user(
    request: Request = None,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db)
) -> Optional[User]:
    """Extracts user from Bearer JWT token in Authorization header or httpOnly cookie; returns None if unauthenticated."""
    token = None
    if credentials and credentials.credentials:
        token = credentials.credentials
    elif request:
        token = request.cookies.get("tradezen_access_token")

    if not token:
        return None

    try:
        payload = decode_token(token)
        sub = payload.get("sub") or payload.get("user_id")
        if sub is None:
            return None
        if str(sub).isdigit():
            user = db.query(User).filter(User.id == int(sub)).first()
            if user:
                return user
        user = db.query(User).filter(User.username == str(sub)).first()
        if user:
            return user
        return db.query(User).filter(User.email == str(sub)).first()
    except Exception:
        return None


def require_user(
    request: Request = None,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """FastAPI dependency that enforces authentication and raises 401 if missing."""
    user = get_current_user(request=request, credentials=credentials, db=db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please log in.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
