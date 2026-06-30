"""Tests for COL-16: configurable CORS middleware on the Collector app."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from argox_collector.app import create_app
from argox_collector.settings import CollectorSettings
from fastapi.testclient import TestClient


def _settings(tmp_path: Path, **overrides: object) -> CollectorSettings:
    return CollectorSettings(
        storage_local_root=tmp_path / "blobs",
        index_duckdb_path=tmp_path / "index.duckdb",
        **overrides,
    )


def _preflight(client: TestClient, origin: str) -> httpx.Response:
    return client.options(
        "/healthz",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
        },
    )


class TestCorsOriginParsing:
    def test_empty_string_yields_no_origins(self) -> None:
        settings = CollectorSettings(cors_origins="")
        assert settings.cors_origin_list == []

    def test_single_origin(self) -> None:
        settings = CollectorSettings(cors_origins="https://dash.example.com")
        assert settings.cors_origin_list == ["https://dash.example.com"]

    def test_multiple_origins_with_whitespace_and_blanks(self) -> None:
        settings = CollectorSettings(
            cors_origins=" https://dash.example.com , http://localhost:5173 ,,"
        )
        assert settings.cors_origin_list == [
            "https://dash.example.com",
            "http://localhost:5173",
        ]


class TestCorsMiddleware:
    def test_disabled_by_default(self, tmp_path: Path) -> None:
        client = TestClient(create_app(_settings(tmp_path)))
        response = _preflight(client, "http://localhost:5173")
        assert "access-control-allow-origin" not in response.headers

    def test_allowed_origin_passes_preflight(self, tmp_path: Path) -> None:
        settings = _settings(
            tmp_path,
            cors_origins="https://dash.example.com,http://localhost:5173",
        )
        client = TestClient(create_app(settings))
        response = _preflight(client, "http://localhost:5173")
        assert response.status_code == 200
        assert (
            response.headers["access-control-allow-origin"]
            == "http://localhost:5173"
        )

    def test_unlisted_origin_is_rejected(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path, cors_origins="https://dash.example.com")
        client = TestClient(create_app(settings))
        response = _preflight(client, "https://evil.example.com")
        assert response.status_code == 400

    def test_simple_request_gets_cors_header(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path, cors_origins="https://dash.example.com")
        client = TestClient(create_app(settings))
        response = client.get(
            "/healthz", headers={"Origin": "https://dash.example.com"}
        )
        assert response.status_code == 200
        assert (
            response.headers["access-control-allow-origin"]
            == "https://dash.example.com"
        )


@pytest.mark.parametrize("value", ["", "   ", ",,,"])
def test_blank_like_values_do_not_enable_cors(value: str) -> None:
    settings = CollectorSettings(cors_origins=value)
    assert settings.cors_origin_list == []
