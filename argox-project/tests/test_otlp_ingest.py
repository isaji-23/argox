"""Tests for the COL-03 OTLP/HTTP ingest endpoint (``POST /v1/traces``)."""

from __future__ import annotations

from pathlib import Path

import pytest
from argox_collector.app import create_app
from argox_collector.ingest.otlp import CONTENT_TYPE_JSON, CONTENT_TYPE_PROTOBUF
from argox_collector.settings import CollectorSettings
from fastapi.testclient import TestClient
from google.protobuf import json_format
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
)
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.trace.v1.trace_pb2 import ResourceSpans, ScopeSpans, Span

TRACE_ID = bytes.fromhex("0102030405060708090a0b0c0d0e0f10")
SPAN_ID = bytes.fromhex("1112131415161718")


def _attr(key: str, value) -> KeyValue:
    if isinstance(value, bool):
        any_value = AnyValue(bool_value=value)
    elif isinstance(value, int):
        any_value = AnyValue(int_value=value)
    elif isinstance(value, float):
        any_value = AnyValue(double_value=value)
    else:
        any_value = AnyValue(string_value=str(value))
    return KeyValue(key=key, value=any_value)


def _sample_request() -> ExportTraceServiceRequest:
    span = Span(
        trace_id=TRACE_ID,
        span_id=SPAN_ID,
        name="argox.agent.run",
        start_time_unix_nano=1_000_000_000,
        end_time_unix_nano=1_500_000_000,
        attributes=[
            _attr("argox.agent.name", "demo-agent"),
            _attr("argox.agent.version", "1.2.3"),
            _attr("argox.policy.decision", "ok"),
            _attr("argox.run.success", True),
            _attr("gen_ai.request.model", "gpt-4o"),
            _attr("gen_ai.usage.input_tokens", 1000),
            _attr("gen_ai.usage.output_tokens", 500),
        ],
    )
    return ExportTraceServiceRequest(
        resource_spans=[
            ResourceSpans(scope_spans=[ScopeSpans(spans=[span])])
        ]
    )


@pytest.fixture
def settings(tmp_path: Path) -> CollectorSettings:
    return CollectorSettings(
        storage_local_root=tmp_path / "blobs",
        index_duckdb_path=tmp_path / "index.duckdb",
    )


@pytest.fixture
def client(settings: CollectorSettings) -> TestClient:
    return TestClient(create_app(settings))


def _fetch_span(client: TestClient):
    index = client.app.state.index
    with index._lock:
        return index._conn.execute(
            "SELECT trace_id, span_id, name, agent_name, agent_version, "
            "policy_decision, run_cost, run_success, duration_ms FROM spans"
        ).fetchone()


def test_endpoint_is_registered(settings: CollectorSettings) -> None:
    app = create_app(settings)
    paths = {route.path for route in app.routes}
    assert "/v1/traces" in paths


def test_protobuf_ingest_persists_blob_and_indexes_span(client: TestClient) -> None:
    body = _sample_request().SerializeToString()
    response = client.post(
        "/v1/traces", content=body, headers={"content-type": CONTENT_TYPE_PROTOBUF}
    )

    assert response.status_code == 202

    # A raw blob was written under the traces/ prefix.
    storage = client.app.state.storage
    blobs = list(storage.list(prefix="traces/"))
    assert len(blobs) == 1
    assert blobs[0].metadata["span_count"] == "1"

    row = _fetch_span(client)
    assert row[0] == TRACE_ID.hex()
    assert row[1] == SPAN_ID.hex()
    assert row[2] == "argox.agent.run"
    assert row[3] == "demo-agent"
    assert row[4] == "1.2.3"
    assert row[5] == "ok"
    # gpt-4o: 1.0 * 0.0025 + 0.5 * 0.01 = 0.0075
    assert row[6] == pytest.approx(0.0075)
    assert row[7] is True
    assert row[8] == pytest.approx(500.0)


def test_json_ingest_persists_span(client: TestClient) -> None:
    body = json_format.MessageToJson(_sample_request()).encode("utf-8")
    response = client.post(
        "/v1/traces", content=body, headers={"content-type": CONTENT_TYPE_JSON}
    )

    assert response.status_code == 202
    row = _fetch_span(client)
    assert row[0] == TRACE_ID.hex()
    assert row[3] == "demo-agent"


def test_durable_header_persists_synchronously(client: TestClient) -> None:
    body = _sample_request().SerializeToString()
    response = client.post(
        "/v1/traces",
        content=body,
        headers={
            "content-type": CONTENT_TYPE_PROTOBUF,
            "x-argox-durable": "true",
        },
    )

    assert response.status_code == 200
    assert _fetch_span(client) is not None


def test_unsupported_content_type_returns_415(client: TestClient) -> None:
    response = client.post(
        "/v1/traces", content=b"x", headers={"content-type": "text/plain"}
    )
    assert response.status_code == 415


def test_malformed_protobuf_returns_400(client: TestClient) -> None:
    response = client.post(
        "/v1/traces",
        content=b"\xff\xff not-a-protobuf \xff",
        headers={"content-type": CONTENT_TYPE_PROTOBUF},
    )
    assert response.status_code == 400


def test_empty_batch_succeeds_with_no_rows(client: TestClient) -> None:
    body = ExportTraceServiceRequest().SerializeToString()
    response = client.post(
        "/v1/traces", content=body, headers={"content-type": CONTENT_TYPE_PROTOBUF}
    )
    assert response.status_code == 202
    assert _fetch_span(client) is None


def test_durable_persist_failure_returns_503(client: TestClient) -> None:
    # The durable contract is to return 200 only once the batch is committed.
    # A storage failure must surface as a 5xx so the client can retry rather
    # than silently losing the batch.
    client.app.state.storage.put = lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("disk full")
    )
    body = _sample_request().SerializeToString()
    response = client.post(
        "/v1/traces",
        content=body,
        headers={
            "content-type": CONTENT_TYPE_PROTOBUF,
            "x-argox-durable": "true",
        },
    )

    assert response.status_code == 503
    assert _fetch_span(client) is None


def test_payload_over_limit_returns_413(tmp_path: Path) -> None:
    settings = CollectorSettings(
        storage_local_root=tmp_path / "blobs",
        index_duckdb_path=tmp_path / "index.duckdb",
        max_payload_size=1024,
    )
    client = TestClient(create_app(settings))

    response = client.post(
        "/v1/traces",
        content=b"x" * 2048,
        headers={"content-type": CONTENT_TYPE_PROTOBUF},
    )

    assert response.status_code == 413


def test_deeply_nested_json_returns_400_not_500(client: TestClient) -> None:
    depth = 20000
    body = ("{" + '"a":{' * depth + "}" * depth + "}").encode("utf-8")
    response = client.post(
        "/v1/traces", content=body, headers={"content-type": CONTENT_TYPE_JSON}
    )
    assert response.status_code == 400


def test_run_success_string_attribute_is_coerced(client: TestClient) -> None:
    span = Span(
        trace_id=TRACE_ID,
        span_id=SPAN_ID,
        name="argox.agent.run",
        attributes=[_attr("argox.run.success", "true")],
    )
    request = ExportTraceServiceRequest(
        resource_spans=[ResourceSpans(scope_spans=[ScopeSpans(spans=[span])])]
    )
    response = client.post(
        "/v1/traces",
        content=request.SerializeToString(),
        headers={"content-type": CONTENT_TYPE_PROTOBUF},
    )

    assert response.status_code == 202
    assert _fetch_span(client)[7] is True


def test_payload_under_limit_is_accepted(tmp_path: Path) -> None:
    settings = CollectorSettings(
        storage_local_root=tmp_path / "blobs",
        index_duckdb_path=tmp_path / "index.duckdb",
        max_payload_size=1024 * 1024,
    )
    client = TestClient(create_app(settings))

    body = _sample_request().SerializeToString()
    response = client.post(
        "/v1/traces", content=body, headers={"content-type": CONTENT_TYPE_PROTOBUF}
    )

    assert response.status_code == 202
