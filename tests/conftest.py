"""Pytest fixtures for TradeZen test suite."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from unittest.mock import patch

from app.database import SessionLocal, engine, Base
from app.api.main import app
from app.models import User, UserProfile, PriceBar


@pytest.fixture(scope="session", autouse=True)
def ensure_db_tables():
    """Ensures database tables are created before running tests."""
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture(scope="function")
def db_session():
    """Provides a transactional database session rolled back or cleaned up after tests."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="module")
def client():
    """Test client for FastAPI app."""
    with patch("app.live.feed.LiveFeedService.start"):
        with TestClient(app) as test_client:
            yield test_client

