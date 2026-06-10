"""Tests for the COL-01 Collector skeleton: app factory and health endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest
from argox_collector import __version__
from argox_collector.app import create_app
from argox_collector.settings import CollectorSettings
from argox_collector.index.duckdb import DuckDBTraceIndex
from argox_collector.storage import LocalStorageBackend, StorageError
from fastapi.testclient import TestClient


def _settings(tmp_path: Path) -> CollectorSettings:
    return CollectorSettings(storage_local_root=tmp_path / "blobs")


@pytest.fixture
def settings(tmp_path: Path) -> CollectorSettings:
    return _settings(tmp_path)


@pytest.fixture
def client(settings: CollectorSettings) -> TestClient:
    """Build a TestClient against a fresh Collector app."""
    return TestClient(create_app(settings))


def test_app_factory_registers_health_routes(settings: CollectorSettings) -> None:
    app = create_app(settings)
    paths = {route.path for route in app.routes}
    assert "/healthz" in paths
    assert "/readyz" in paths


def test_app_factory_attaches_settings_to_state(settings: CollectorSettings) -> None:
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
    assert payload["checks"]["storage"] == "ok"


def test_openapi_schema_is_served(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "Argox Collector"
    assert "/healthz" in schema["paths"]
    assert "/readyz" in schema["paths"]


def test_health_endpoints_reflect_configured_service_name(tmp_path: Path) -> None:
    settings = CollectorSettings(
        service_name="argox-collector-canary",
        storage_local_root=tmp_path / "blobs",
    )
    client = TestClient(create_app(settings))
    assert client.get("/healthz").json()["service"] == "argox-collector-canary"
    assert client.get("/readyz").json()["service"] == "argox-collector-canary"


def test_default_settings_values() -> None:
    settings = CollectorSettings()
    assert settings.service_name == "argox-collector"
    assert settings.host == "0.0.0.0"
    assert settings.port == 8000
    assert settings.storage_backend == "local"


def test_readyz_returns_503_when_storage_health_check_fails(
    settings: CollectorSettings,
) -> None:
    class _BrokenBackend(LocalStorageBackend):
        def health_check(self) -> None:
            raise StorageError("outage at /var/secret/blobs")

    storage = _BrokenBackend(root=settings.storage_local_root)
    client = TestClient(create_app(settings, storage=storage))

    response = client.get("/readyz")
    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["checks"]["process"] == "ok"
    # The endpoint is unauthenticated: backend error text (which can embed
    # filesystem paths or container names) must never reach the response.
    assert payload["checks"]["storage"] == "unavailable"
    assert "/var/secret/blobs" not in response.text


def test_readyz_returns_503_when_index_health_check_fails(
    settings: CollectorSettings, tmp_path: Path
) -> None:
    index = DuckDBTraceIndex(tmp_path / "index.duckdb")
    index.close()
    client = TestClient(create_app(settings, index=index))

    response = client.get("/readyz")
    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["checks"]["index"] == "unavailable"
    assert str(tmp_path) not in response.text
