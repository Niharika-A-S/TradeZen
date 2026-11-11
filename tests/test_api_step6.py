"""Tests for Step 6 API extensions (Rules endpoints and CORS/Market helpers)."""
import pytest
from fastapi.testclient import TestClient
from app.api.main import app

client = TestClient(app)


def test_cors_headers_present():
    """Verify CORS headers are returned for explicit local frontend origins."""
    for origin in ["http://localhost:5173", "http://localhost:3000"]:
        response = client.options(
            "/clock",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET"
            }
        )
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == origin
        assert response.headers.get("access-control-allow-credentials") == "true"

    # Unauthorized origin should not receive allow-origin header
    unauthorized = client.options(
        "/clock",
        headers={
            "Origin": "http://evil-site.com",
            "Access-Control-Request-Method": "GET"
        }
    )
    assert unauthorized.headers.get("access-control-allow-origin") is None


def test_get_tradable_symbols():
    """Verify tradable symbols endpoint returns all 5 universe stocks."""
    response = client.get("/market/symbols")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    for sym in ["INFY", "RELIANCE", "TCS", "HDFCBANK", "SBIN"]:
        assert sym in data


def test_get_and_update_user_rules():
    """Verify getting and updating user rules for UI rules configuration."""
    # User 1 rules
    response = client.get("/rules/1")
    assert response.status_code == 200
    rules = response.json()
    assert "max_trades_per_day" in rules
    assert "max_risk_per_trade_pct" in rules
    assert "require_stop_loss" in rules

    # Update rules
    update_payload = {
        "max_trades_per_day": 8,
        "max_risk_per_trade_pct": 1.5,
        "require_stop_loss": True,
        "max_consecutive_losses": 2
    }
    put_resp = client.put("/rules/1", json=update_payload)
    assert put_resp.status_code == 200
    updated_rules = put_resp.json()
    assert updated_rules["max_trades_per_day"] == 8
    assert updated_rules["max_risk_per_trade_pct"] == 1.5
    assert updated_rules["max_consecutive_losses"] == 2

    # Fetch again to verify persistence
    get_resp = client.get("/rules/1")
    assert get_resp.status_code == 200
    persisted = get_resp.json()
    assert persisted["max_trades_per_day"] == 8
    assert persisted["max_risk_per_trade_pct"] == 1.5
