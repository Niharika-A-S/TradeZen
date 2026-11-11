"""Tests for Authentication System (Signup, Login, JWT, User Isolation)."""
import uuid
import pytest
from fastapi.testclient import TestClient
from app.models.user import User, UserProfile
from app.models.paper import Account, INITIAL_PAPER_CASH


def test_signup_success(client: TestClient, db_session):
    """Verifies user signup creates user, 10L paper account, risk profile, and JWT token."""
    uid = uuid.uuid4().hex[:8]
    username = f"trader_{uid}"
    payload = {
        "username": username,
        "password": "secure_password_123",
        "email": f"{username}@example.com"
    }
    response = client.post("/auth/signup", json=payload)
    assert response.status_code == 201
    data = response.json()

    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["username"] == username
    assert data["account"]["cash_balance"] == INITIAL_PAPER_CASH

    # Verify password is not saved in plaintext in DB
    user_in_db = db_session.query(User).filter_by(username=username).first()
    assert user_in_db is not None
    assert user_in_db.hashed_password != "secure_password_123"
    assert ":" in user_in_db.hashed_password or user_in_db.hashed_password.startswith("$argon2")


def test_signup_duplicate_username(client: TestClient):
    """Verifies signup rejects duplicate usernames."""
    uid = uuid.uuid4().hex[:8]
    username = f"dup_{uid}"
    payload = {"username": username, "password": "password123"}
    resp1 = client.post("/auth/signup", json=payload)
    assert resp1.status_code == 201

    resp2 = client.post("/auth/signup", json=payload)
    assert resp2.status_code == 400
    assert "already taken" in resp2.json()["detail"]


def test_login_success(client: TestClient):
    """Verifies login returns access token on correct credentials."""
    uid = uuid.uuid4().hex[:8]
    username = f"login_{uid}"
    password = "correct_password"
    client.post("/auth/signup", json={"username": username, "password": password})

    login_resp = client.post("/auth/login", json={"username": username, "password": password})
    assert login_resp.status_code == 200
    data = login_resp.json()
    assert "access_token" in data
    assert data["user"]["username"] == username


def test_login_invalid_password(client: TestClient):
    """Verifies login rejects wrong password with 401."""
    uid = uuid.uuid4().hex[:8]
    username = f"login_fail_{uid}"
    client.post("/auth/signup", json={"username": username, "password": "right_password"})

    login_resp = client.post("/auth/login", json={"username": username, "password": "WRONG_password"})
    assert login_resp.status_code == 401
    assert "Invalid username or password" in login_resp.json()["detail"]


def test_auth_me_endpoint(client: TestClient):
    """Verifies GET /auth/me returns current user profile and account using Bearer token."""
    uid = uuid.uuid4().hex[:8]
    username = f"me_{uid}"
    signup_resp = client.post("/auth/signup", json={"username": username, "password": "password123"})
    assert signup_resp.status_code == 201
    token = signup_resp.json()["access_token"]

    headers = {"Authorization": f"Bearer {token}"}
    me_resp = client.get("/auth/me", headers=headers)
    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert me_data["user"]["username"] == username
    assert me_data["account"]["cash_balance"] == INITIAL_PAPER_CASH
    assert "max_trades_per_day" in me_data["rules"]


def test_auth_me_unauthorized(client: TestClient):
    """Verifies GET /auth/me fails when no token or invalid token is supplied."""
    resp1 = client.get("/auth/me")
    assert resp1.status_code == 401

    resp2 = client.get("/auth/me", headers={"Authorization": "Bearer invalid_token_123"})
    assert resp2.status_code == 401
