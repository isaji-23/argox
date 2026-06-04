"""Tests for the COL-03 /v1/traces OTLP ingest endpoint."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from argox_collector.app import create_app
from argox_collector.routers.ingest import (
    ExportTraceServiceRequest,
    KeyValue,
    Span,
    ResourceSpans,
    ScopeSpans,
)
from argox_collector.settings import CollectorSettings
from argox_collector.storage import LocalStorageBackend


def _settings(tmp_path: Path) -> CollectorSettings:
    return CollectorSettings(storage_local_root=tmp_path / "blobs")


@pytest.fixture
def settings(tmp_path: Path) -> CollectorSettings:
    return _settings(tmp_path)


@pytest.fixture
def client(settings: CollectorSettings) -> TestClient:
    """Build a TestClient against a fresh Collector app with ingest router."""
    return TestClient(create_app(settings))


@pytest.fixture
def sample_trace_payload() -> dict:
    """Generate a sample OTLP ExportTraceServiceRequest payload."""
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": "test-agent"},
                        {"key": "host.name", "value": "localhost"},
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "argox-sdk", "version": "0.1.0"},
                        "spans": [
                            {
                                "traceId": "0123456789abcdef0123456789abcdef",
                                "spanId": "0123456789abcdef",
                                "name": "llm.call",
                                "attributes": [
                                    {"key": "model", "value": "gpt-4"},
                                    {"key": "tokens", "value": 1024},
                                ],
                                "startTimeUnixNano": 1704067200000000000,
                                "endTimeUnixNano": 1704067201000000000,
                            }
                        ],
                    }
                ],
            }
        ]
    }


class TestIngestTracesEndpoint:
    """Tests for the /v1/traces OTLP ingest endpoint."""

    def test_endpoint_exists(self, client: TestClient) -> None:
        """Verify the /v1/traces endpoint is registered."""
        routes = {route.path for route in client.app.routes}
        assert "/v1/traces" in routes

    def test_post_to_traces_returns_200(
        self, client: TestClient, sample_trace_payload: dict
    ) -> None:
        """Fire-and-forget mode: POST /v1/traces returns 200 OK immediately."""
        response = client.post("/v1/traces", json=sample_trace_payload)
        assert response.status_code == 200
        assert response.json() == {}

    def test_fire_and_forget_mode_default(
        self, client: TestClient, sample_trace_payload: dict
    ) -> None:
        """Fire-and-forget is the default when x-argox-durable header is omitted."""
        response = client.post("/v1/traces", json=sample_trace_payload)
        assert response.status_code == 200
        assert response.json() == {}

    def test_fire_and_forget_mode_explicit_false(
        self, client: TestClient, sample_trace_payload: dict
    ) -> None:
        """Fire-and-forget mode when x-argox-durable: false."""
        response = client.post(
            "/v1/traces",
            json=sample_trace_payload,
            headers={"x-argox-durable": "false"},
        )
        assert response.status_code == 200
        assert response.json() == {}

    def test_durable_mode_with_header(
        self, client: TestClient, sample_trace_payload: dict
    ) -> None:
        """Durable mode: x-argox-durable: true returns 200 after processing."""
        response = client.post(
            "/v1/traces",
            json=sample_trace_payload,
            headers={"x-argox-durable": "true"},
        )
        assert response.status_code == 200
        assert response.json() == {}

    def test_durable_mode_case_insensitive(
        self, client: TestClient, sample_trace_payload: dict
    ) -> None:
        """Durable mode check is case-insensitive (e.g., 'True', 'TRUE')."""
        for header_value in ["True", "TRUE", "TrUe"]:
            response = client.post(
                "/v1/traces",
                json=sample_trace_payload,
                headers={"x-argox-durable": header_value},
            )
            assert response.status_code == 200
            assert response.json() == {}

    def test_payload_parsing_validates_schema(self, client: TestClient) -> None:
        """Invalid payloads are rejected with 422 Unprocessable Entity."""
        invalid_payload = {"invalid": "data"}
        response = client.post("/v1/traces", json=invalid_payload)
        assert response.status_code == 422

    def test_empty_resource_spans(self, client: TestClient) -> None:
        """Empty resourceSpans list is accepted (no traces to process)."""
        payload = {"resourceSpans": []}
        response = client.post("/v1/traces", json=payload)
        assert response.status_code == 200
        assert response.json() == {}

    def test_multiple_resources_in_payload(self, client: TestClient) -> None:
        """Multiple resources in a single request are accepted."""
        payload = {
            "resourceSpans": [
                {
                    "resource": {"attributes": []},
                    "scopeSpans": [
                        {
                            "scope": {"name": "lib1"},
                            "spans": [
                                {
                                    "traceId": "aaa",
                                    "spanId": "bbb",
                                    "name": "span1",
                                    "attributes": [],
                                    "startTimeUnixNano": 100,
                                    "endTimeUnixNano": 200,
                                }
                            ],
                        }
                    ],
                },
                {
                    "resource": {"attributes": []},
                    "scopeSpans": [
                        {
                            "scope": {"name": "lib2"},
                            "spans": [
                                {
                                    "traceId": "ccc",
                                    "spanId": "ddd",
                                    "name": "span2",
                                    "attributes": [],
                                    "startTimeUnixNano": 300,
                                    "endTimeUnixNano": 400,
                                }
                            ],
                        }
                    ],
                },
            ]
        }
        response = client.post("/v1/traces", json=payload)
        assert response.status_code == 200

    def test_persist_to_blob_storage(
        self, settings: CollectorSettings, sample_trace_payload: dict
    ) -> None:
        """Durable mode persists traces to blob storage with time-partitioned paths."""
        # Use durable mode to ensure synchronous processing
        client = TestClient(create_app(settings))
        response = client.post(
            "/v1/traces",
            json=sample_trace_payload,
            headers={"x-argox-durable": "true"},
        )

        assert response.status_code == 200

        # Verify blob was written (check storage directory)
        storage_root = settings.storage_local_root
        # Path pattern: spans/{YYYY}/{MM}/{DD}/{HH}/{uuid}.json
        span_dir = storage_root / "spans"
        assert span_dir.exists(), "Spans directory should be created"

        # List all blob files written
        import glob

        pattern = str(span_dir / "**" / "*.json")
        blobs = glob.glob(pattern, recursive=True)
        assert len(blobs) > 0, "At least one span batch should be persisted"

        # Verify the blob content matches the original payload
        with open(blobs[0], "r") as f:
            persisted_payload = json.load(f)
        assert persisted_payload == sample_trace_payload

    def test_background_tasks_not_awaited_in_fire_and_forget(
        self, client: TestClient, sample_trace_payload: dict
    ) -> None:
        """Fire-and-forget mode returns immediately; background task is queued."""
        # This is implicitly tested by the fast response time, but we can
        # mock the background task to ensure it's added.
        with patch(
            "argox_collector.routers.ingest._process_spans"
        ) as mock_process:
            response = client.post(
                "/v1/traces",
                json=sample_trace_payload,
                headers={"x-argox-durable": "false"},
            )
        assert response.status_code == 200
        # TestClient runs background tasks, so the mock should be called
        assert mock_process.called
        with patch(
            "argox_collector.routers.ingest._process_spans"
        ) as mock_process:
            response = client.post(
                "/v1/traces",
                json=sample_trace_payload,
                headers={"x-argox-durable": "true"},
            )
            assert response.status_code == 200
            # _process_spans should have been called (TestClient runs synchronously)
            assert mock_process.called

    def test_pydantic_models_serialize_correctly(self) -> None:
        """Pydantic models correctly parse and serialize OTLP payloads."""
        # Test that the Pydantic models work correctly
        span = Span(
            traceId="abc123",
            spanId="def456",
            name="test.span",
            attributes=[KeyValue(key="tag", value="value")],
            startTimeUnixNano=100,
            endTimeUnixNano=200,
        )
        assert span.traceId == "abc123"
        assert span.name == "test.span"

        scope = ScopeSpans(
            scope={"name": "test"}, spans=[span]
        )
        assert len(scope.spans) == 1

        resource = ResourceSpans(
            resource={"name": "test-resource"}, scopeSpans=[scope]
        )
        assert len(resource.scopeSpans) == 1

        request = ExportTraceServiceRequest(resourceSpans=[resource])
        assert len(request.resourceSpans) == 1

        # Verify model_dump works
        dumped = request.model_dump()
        assert dumped["resourceSpans"][0]["resource"]["name"] == "test-resource"
