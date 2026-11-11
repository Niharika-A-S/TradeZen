"""Tests for TradeZen FastAPI endpoints."""
from fastapi.testclient import TestClient


def test_root_endpoint(client: TestClient):
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["app"] == "TradeZen"
    assert data["step"] == 1


def test_health_endpoint(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["database"] == "connected"


def test_clock_endpoints(client: TestClient):
    # Set mode to replay 2022-03-10 10:00
    resp = client.post("/clock/mode", json={
        "mode": "REPLAY",
        "replay_date": "2022-03-10",
        "start_time": "10:00"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "REPLAY"
    assert "2022-03-10 10:00" in data["current_time"]

    # Tick clock by 15 minutes to reach 10:15
    tick_resp = client.post("/clock/tick", json={"minutes": 15})
    assert tick_resp.status_code == 200
    tick_data = tick_resp.json()
    assert "2022-03-10 10:15" in tick_data["current_time"]

    # Query price at current clock time
    price_resp = client.get("/price?symbol=INFY")
    assert price_resp.status_code == 200
    pdata = price_resp.json()
    assert pdata["symbol"] == "INFY"
    assert pdata["close"] == 1818.0
    assert pdata["open"] == 1821.0
    assert pdata["high"] == 1821.1
    assert pdata["low"] == 1817.2
    assert pdata["volume"] == 21359


def test_historical_price_with_explicit_timestamp(client: TestClient):
    resp = client.get("/price?symbol=INFY&timestamp=2022-03-10%2010:15")
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "INFY"
    assert data["close"] == 1818.0
    assert data["volume"] == 21359


def test_missing_stock_price(client: TestClient):
    resp = client.get("/price?symbol=NONEXISTENT&timestamp=2022-03-10%2010:15")
    assert resp.status_code == 404
