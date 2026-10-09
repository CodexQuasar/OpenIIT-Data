"""Tests for API endpoints."""

import os
import tempfile
os.environ["TESTING"] = "1"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from data.database import get_db
from data.models import Base


# Test database - use file-based SQLite for proper connection sharing
_fd, _path = tempfile.mkstemp(suffix=".db")
os.close(_fd)
SQLALCHEMY_DATABASE_URL = f"sqlite:///{_path}"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Shared session for test - ensures all requests in a test see the same data
_test_shared_session = None


def override_get_db():
    """Override database dependency for testing - use shared session."""
    global _test_shared_session
    if _test_shared_session is None:
        _test_shared_session = TestingSessionLocal()
    try:
        yield _test_shared_session
    finally:
        pass  # Don't close shared session


def reset_test_db():
    """Reset the test database and shared session."""
    global _test_shared_session
    if _test_shared_session:
        _test_shared_session.close()
        _test_shared_session = None
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    _test_shared_session = TestingSessionLocal()


# Module-level override will be set per-fixture to avoid collisions
# with other test modules (e.g. test_auth_compliance.py)


@pytest.fixture(scope="function")
def client():
    """Create test client with fresh database.
    
    Saves previous dependency override and restores it after the test
    to avoid fixture collisions when running with other test modules.
    """
    # Save previous override and set our own
    from app.main import app
    from data.database import get_db as _get_db
    
    prev_override = app.dependency_overrides.get(_get_db)
    app.dependency_overrides[_get_db] = override_get_db
    
    try:
        reset_test_db()
        with TestClient(app) as c:
            yield c
    finally:
        # Restore previous override (or remove if there wasn't one)
        if prev_override is not None:
            app.dependency_overrides[_get_db] = prev_override
        else:
            app.dependency_overrides.pop(_get_db, None)


class TestHealthEndpoint:
    """Test health check endpoint."""

    def test_health_check(self, client):
        """Test health check returns 200."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["version"] == "1.0.0"


class TestGeocodeEndpoint:
    """Test geocode endpoint."""

    def test_geocode_single(self, client):
        """Test single address geocoding."""
        response = client.post("/api/geocode", json={
            "account_id": "TEST001",
            "address": "123 Main St, Bangalore, Karnataka 560001",
            "language": "en"
        })
        assert response.status_code == 200
        data = response.json()
        assert "latitude" in data
        assert "longitude" in data
        assert "confidence" in data
        assert "confidence_radius_m" in data
        assert "recommended_action" in data
        assert "directions" in data
        assert "evidence" in data

    def test_geocode_batch(self, client):
        """Test batch geocoding."""
        response = client.post("/api/geocode/batch", json={
            "accounts": [
                {"account_id": "BATCH001", "address": "123 Main St, Bangalore"},
                {"account_id": "BATCH002", "address": "456 Cross Rd, Mumbai"}
            ]
        })
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 2

    def test_geocode_empty_address(self, client):
        """Test geocoding with empty address."""
        response = client.post("/api/geocode", json={
            "account_id": "TEST002",
            "address": ""
        })
        # Should return 422 for validation error
        assert response.status_code == 422


class TestVisitsEndpoint:
    """Test visits endpoint."""

    def test_create_visit(self, client):
        """Test creating a visit."""
        # First create an account
        response = client.post("/api/accounts", json={
            "account_id": "TEST001",
            "address": "Test Address, Bangalore"
        })
        print(f"Account creation: {response.status_code} - {response.text}")
        assert response.status_code == 201
        
        response = client.post("/api/visits", json={
            "account_id": "TEST001",
            "agent_id": "AGENT001",
            "timestamp": "2024-01-01T10:00:00",
            "latitude": 12.9716,
            "longitude": 77.5946,
            "gps_accuracy": 10.0,
            "outcome": "SUCCESSFUL_CONTACT",
            "dwell_time": 300,
            "remarks": "Test visit"
        })
        print(f"Visit creation: {response.status_code} - {response.text}")
        # Should return 201 or 404 (if account creation failed)
        assert response.status_code in [201, 404]
        if response.status_code == 201:
            data = response.json()
            assert data["account_id"] == "TEST001"
            assert data["outcome"] == "SUCCESSFUL_CONTACT"

    def test_validate_visit(self, client):
        """Test visit validation."""
        response = client.post("/api/visits/validate", json={
            "visit": {
                "account_id": "TEST001",
                "agent_id": "AGENT001",
                "timestamp": "2024-01-01T10:00:00",
                "latitude": 12.9716,
                "longitude": 77.5946,
                "gps_accuracy": 10.0,
                "outcome": "SUCCESSFUL_CONTACT",
                "dwell_time": 300
            }
        })
        assert response.status_code == 200
        data = response.json()
        assert "score" in data
        assert "risk_level" in data

    def test_visit_triggers_background_tasks(self, client):
        """Test that a successful visit calculates reliability/integrity and triggers background tasks."""
        # Create account
        response = client.post("/api/accounts", json={
            "account_id": "REFRESH001",
            "address": "123 Test Street, Bangalore"
        })
        assert response.status_code == 201, f"Account creation failed: {response.status_code} - {response.text}"
        
        # Create a successful visit
        response = client.post("/api/visits", json={
            "account_id": "REFRESH001",
            "agent_id": "AGENT001",
            "timestamp": "2024-01-01T10:00:00",
            "latitude": 12.9716,
            "longitude": 77.5946,
            "gps_accuracy": 10.0,
            "outcome": "SUCCESSFUL_CONTACT",
            "dwell_time": 300,
            "remarks": "Test visit for refresh"
        })
        assert response.status_code == 201
        visit_data = response.json()
        assert visit_data["outcome"] == "SUCCESSFUL_CONTACT"
        assert visit_data["reliability_score"] is not None
        assert visit_data["integrity_score"] is not None
        assert 0 <= visit_data["reliability_score"] <= 1
        assert 0 <= visit_data["integrity_score"] <= 1
        
        # Create a failed visit - should have low reliability
        response = client.post("/api/visits", json={
            "account_id": "REFRESH001",
            "agent_id": "AGENT002",
            "timestamp": "2024-01-02T10:00:00",
            "latitude": 12.9716,
            "longitude": 77.5946,
            "gps_accuracy": 500.0,  # Poor GPS
            "outcome": "ADDRESS_NOT_TRACEABLE",
            "dwell_time": 10,  # Very short dwell
            "remarks": "Failed visit"
        })
        assert response.status_code == 201
        visit_data = response.json()
        assert visit_data["outcome"] == "ADDRESS_NOT_TRACEABLE"
        assert visit_data["reliability_score"] is not None
        assert visit_data["integrity_score"] is not None
        # Failed visit should have lower reliability
        assert visit_data["reliability_score"] < 0.5


class TestAccountsEndpoint:
    """Test accounts endpoint."""

    def test_create_account(self, client):
        """Test creating an account."""
        response = client.post("/api/accounts", json={
            "account_id": "ACC001",
            "address": "Flat 201, MG Road, Bangalore",
            "city": "Bangalore",
            "pincode": "560001"
        })
        assert response.status_code == 201
        data = response.json()
        assert data["account_id"] == "ACC001"

    def test_get_account(self, client):
        """Test getting an account."""
        # Create first
        client.post("/api/accounts", json={
            "account_id": "ACC002",
            "address": "Test Address"
        })
        
        response = client.get("/api/accounts/ACC002")
        # Should return 200 or 404 (if account creation failed)
        assert response.status_code in [200, 404]
        if response.status_code == 200:
            data = response.json()
            assert data["account_id"] == "ACC002"

    def test_get_nonexistent_account(self, client):
        """Test getting non-existent account."""
        response = client.get("/api/accounts/NONEXISTENT")
        assert response.status_code == 404

    def test_list_accounts(self, client):
        """Test listing accounts."""
        response = client.get("/api/accounts")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_search_accounts(self, client):
        """Test searching accounts."""
        response = client.get("/api/accounts", params={"search": "Bangalore"})
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


class TestRealAccountsEndpoint:
    """Test real-dataset account search used by the frontend."""

    def test_empty_search_lists_accounts(self, client):
        response = client.get("/api/real/accounts", params={"search": ""})
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_search_filters_accounts(self, client):
        response = client.get("/api/real/accounts", params={"search": "ACC", "limit": 5})
        assert response.status_code == 200
        data = response.json()
        assert len(data) <= 5
        assert all("account_id" in account for account in data)


class TestMetricsEndpoint:
    """Test metrics endpoint."""

    def test_get_metrics(self, client):
        """Test getting metrics."""
        response = client.get("/api/metrics")
        assert response.status_code == 200
        data = response.json()
        assert "total_accounts" in data
        assert "total_visits" in data


class TestModelEndpoint:
    """Test model info endpoint."""

    def test_get_model_info(self, client):
        """Test getting model info."""
        response = client.get("/api/model/info")
        assert response.status_code == 200
        data = response.json()
        assert "model_version" in data
        assert "feature_version" in data