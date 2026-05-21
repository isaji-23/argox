"""Tests for the COL-01 Collector skeleton: app factory and health endpoints."""

from __future__ import annotations

import pytest
from argox_collector import __version__, create_app
from argox_collector.settings import CollectorSettings
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> TestClient:
    """Build a TestClient against a fresh Collector app."""
    return TestClient(create_app(CollectorSettings()))


def test_app_factory_registers_health_routes() -> None:
    app = create_app(CollectorSettings())
    paths = {route.path for route in app.routes}
    assert "/healthz" in paths
    assert "/readyz" in paths


def test_app_factory_attaches_settings_to_state() -> None:
    settings = CollectorSettings()
    app = create_app(settings)
    assert app.state.settings is settings


def test_healthz_returns_ok(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "argox-collector"
    assert payload["version"] == __version__


def test_readyz_returns_ok_with_checks(client: TestClient) -> None:
    response = client.get("/readyz")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "argox-collector"
    assert payload["version"] == __version__
    assert payload["checks"]["process"] == "ok"


def test_openapi_schema_is_served(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "Argox Collector"
    assert "/healthz" in schema["paths"]
    assert "/readyz" in schema["paths"]


def test_default_settings_values() -> None:
    settings = CollectorSettings()
    assert settings.service_name == "argox-collector"
    assert settings.host == "0.0.0.0"
    assert settings.port == 8000
