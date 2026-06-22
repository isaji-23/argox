"""Tests for the COL-11 run-summary ingest endpoint (``POST /v1/runs``)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from argox.core.state import AgentRunMetrics, ApiCallRecord
from argox_collector.app import create_app
from argox_collector.ingest.otlp import CONTENT_TYPE_JSON
from argox_collector.settings import CollectorSettings
from fastapi.testclient import TestClient
from google.protobuf import json_format
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
)
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.trace.v1.trace_pb2 import ResourceSpans, ScopeSpans, Span

TRACE_ID_HEX = "0102030405060708090a0b0c0d0e0f10"


@pytest.fixture
def settings(tmp_path: Path) -> CollectorSettings:
    return CollectorSettings(
        storage_local_root=tmp_path / "blobs",
        index_duckdb_path=tmp_path / "index.duckdb",
    )


@pytest.fixture
def client(settings: CollectorSettings) -> TestClient:
    return TestClient(create_app(settings))


def _sample_run(
    run_id: str = "run-1",
    trace_id: str | None = None,
    model: str | None = None,
) -> dict:
    """Build an ``AgentRunMetrics.to_dict()`` payload, optionally with trace_id."""
    metrics = AgentRunMetrics(
        agent_name="demo-agent",
        run_id=run_id,
        agent_version="1.2.3",
        prompt="hello",
        final_output="world",
        success=True,
        api_calls=[
            ApiCallRecord(call_number=1, input_tokens=1000, output_tokens=500, total_tokens=1500)
        ],
    )
    metrics.end_time = metrics.start_time + 2.5
    payload = metrics.to_dict()
    if trace_id is not None:
        payload["trace_id"] = trace_id
    if model is not None:
        # AgentRunMetrics.to_dict() carries no model; the SDK adds it top-level
        # (extra="allow" preserves it) for the cost backfill to key on.
        payload["model"] = model
    return payload


def _fetch_run(client: TestClient, run_id: str):
    index = client.app.state.index
    return index.get_run(run_id)


def test_single_run_returns_202_and_indexes(client: TestClient) -> None:
    payload = _sample_run()
    resp = client.post("/v1/runs", json=payload)
    assert resp.status_code == 202

    record = _fetch_run(client, "run-1")
    assert record is not None
    assert record.agent_name == "demo-agent"
    assert record.agent_version == "1.2.3"
    assert record.success is True
    assert record.total_input_tokens == 1000
    assert record.total_output_tokens == 500
    assert record.duration_seconds == pytest.approx(2.5)
    assert record.cost_usd is None  # filled later by the enrichment worker
    assert record.blob_path.startswith("runs/")
    assert record.blob_path.endswith("/run-1.json")


def test_blob_matches_payload_byte_for_byte(client: TestClient) -> None:
    payload = _sample_run()
    body = json.dumps(payload).encode("utf-8")
    resp = client.post(
        "/v1/runs", content=body, headers={"content-type": CONTENT_TYPE_JSON}
    )
    assert resp.status_code == 202

    record = _fetch_run(client, "run-1")
    stored = client.app.state.storage.get(record.blob_path)
    assert stored.data == body


def test_batch_indexes_all_records(client: TestClient) -> None:
    batch = [_sample_run("run-a"), _sample_run("run-b")]
    resp = client.post("/v1/runs", json=batch)
    assert resp.status_code == 202

    assert _fetch_run(client, "run-a") is not None
    assert _fetch_run(client, "run-b") is not None
    # Each record gets its own immutable blob.
    rec_b = _fetch_run(client, "run-b")
    stored = client.app.state.storage.get(rec_b.blob_path)
    assert json.loads(stored.data)["run_id"] == "run-b"


def test_durable_header_commits_synchronously(client: TestClient) -> None:
    payload = _sample_run("run-durable")
    resp = client.post(
        "/v1/runs", json=payload, headers={"X-Argox-Durable": "true"}
    )
    assert resp.status_code == 200
    assert _fetch_run(client, "run-durable") is not None


def test_missing_run_id_is_rejected(client: TestClient) -> None:
    resp = client.post("/v1/runs", json={"agent_name": "no-id"})
    assert resp.status_code == 422


def test_reingest_is_idempotent(client: TestClient) -> None:
    client.post("/v1/runs", json=_sample_run("run-dup"))
    client.post("/v1/runs", json=_sample_run("run-dup"))
    index = client.app.state.index
    rows = index._read("SELECT COUNT(*) FROM runs WHERE run_id = ?", ("run-dup",))
    assert rows[0][0] == 1


@pytest.mark.parametrize("bad_id", ["a/b", "../escape", "..", "with space", ""])
def test_malformed_run_id_rejected_synchronously(client: TestClient, bad_id: str) -> None:
    resp = client.post("/v1/runs", json=_sample_run(bad_id))
    assert resp.status_code == 422
    # Nothing written: rejection happened before the 202/background task.
    assert not list(client.app.state.storage.list("runs/"))


def test_negative_tokens_rejected(client: TestClient) -> None:
    payload = _sample_run("run-neg")
    payload["tokens"]["input"] = -1
    resp = client.post("/v1/runs", json=payload)
    assert resp.status_code == 422


def test_missing_success_is_unknown_not_failed(client: TestClient) -> None:
    payload = _sample_run("run-nosuccess")
    del payload["success"]
    resp = client.post("/v1/runs", json=payload)
    assert resp.status_code == 202
    assert _fetch_run(client, "run-nosuccess").success is None


def test_reingest_does_not_overwrite_immutable_blob(client: TestClient) -> None:
    first = _sample_run("run-imm")
    first_body = json.dumps(first).encode("utf-8")
    client.post("/v1/runs", content=first_body, headers={"content-type": CONTENT_TYPE_JSON})

    divergent = _sample_run("run-imm")
    divergent["final_output"] = "tampered"
    divergent["tokens"]["input"] = 9999
    client.post("/v1/runs", json=divergent)

    record = _fetch_run(client, "run-imm")
    # Blob keeps the original bytes ...
    stored = client.app.state.storage.get(record.blob_path)
    assert stored.data == first_body
    # ... and the index row stays consistent with it (first-write-wins).
    assert record.total_input_tokens == 1000


def test_batch_dedups_run_id(client: TestClient) -> None:
    batch = [_sample_run("run-x"), _sample_run("run-x")]
    resp = client.post("/v1/runs", json=batch)
    assert resp.status_code == 202
    index = client.app.state.index
    rows = index._read("SELECT COUNT(*) FROM runs WHERE run_id = ?", ("run-x",))
    assert rows[0][0] == 1


def test_oversized_batch_rejected(client: TestClient) -> None:
    batch = [_sample_run(f"run-{i}") for i in range(1001)]
    resp = client.post("/v1/runs", json=batch)
    assert resp.status_code == 413


def _ingest_span(
    client: TestClient, trace_id_hex: str, model: str | None = None
) -> None:
    attributes = [
        KeyValue(key="argox.agent.name", value=AnyValue(string_value="demo-agent"))
    ]
    if model is not None:
        attributes.append(
            KeyValue(
                key="gen_ai.request.model", value=AnyValue(string_value=model)
            )
        )
    span = Span(
        trace_id=bytes.fromhex(trace_id_hex),
        span_id=bytes.fromhex("1112131415161718"),
        name="argox.agent.run",
        start_time_unix_nano=1_000_000_000,
        end_time_unix_nano=1_500_000_000,
        attributes=attributes,
    )
    request = ExportTraceServiceRequest(
        resource_spans=[ResourceSpans(scope_spans=[ScopeSpans(spans=[span])])]
    )
    body = json_format.MessageToJson(request).encode("utf-8")
    resp = client.post(
        "/v1/traces", content=body, headers={"content-type": CONTENT_TYPE_JSON}
    )
    assert resp.status_code == 202


def test_cost_backfilled_for_known_model(client: TestClient) -> None:
    """A run reporting a priced model gets cost_usd filled from token totals."""
    resp = client.post(
        "/v1/runs", json=_sample_run("run-cost", model="gpt-4o")
    )
    assert resp.status_code == 202

    record = _fetch_run(client, "run-cost")
    assert record.model == "gpt-4o"
    # gpt-4o: 1.0 * 0.0025 + 0.5 * 0.01 = 0.0075 (per-1k YAML prices).
    assert record.cost_usd == pytest.approx(0.0075)


def test_cost_unknown_model_leaves_null(client: TestClient) -> None:
    resp = client.post(
        "/v1/runs", json=_sample_run("run-unknown", model="mystery-model")
    )
    assert resp.status_code == 202
    record = _fetch_run(client, "run-unknown")
    assert record.model == "mystery-model"
    assert record.cost_usd is None


def test_cost_no_model_leaves_null(client: TestClient) -> None:
    resp = client.post("/v1/runs", json=_sample_run("run-nomodel"))
    assert resp.status_code == 202
    record = _fetch_run(client, "run-nomodel")
    assert record.model is None
    assert record.cost_usd is None


def test_cost_backfill_preserves_immutable_blob(client: TestClient) -> None:
    """The cost UPDATE must not rewrite the immutable run blob."""
    payload = _sample_run("run-cost-imm", model="gpt-4o")
    body = json.dumps(payload).encode("utf-8")
    resp = client.post(
        "/v1/runs", content=body, headers={"content-type": CONTENT_TYPE_JSON}
    )
    assert resp.status_code == 202

    record = _fetch_run(client, "run-cost-imm")
    assert record.cost_usd == pytest.approx(0.0075)
    stored = client.app.state.storage.get(record.blob_path)
    assert stored.data == body  # blob untouched by the cost backfill


def test_client_supplied_cost_is_not_overwritten(client: TestClient) -> None:
    """A cost already reported by the client is kept, not recomputed."""
    payload = _sample_run("run-precost", model="gpt-4o")
    payload["cost_usd"] = 1.23
    resp = client.post("/v1/runs", json=payload)
    assert resp.status_code == 202
    record = _fetch_run(client, "run-precost")
    assert record.cost_usd == pytest.approx(1.23)


def test_trace_id_join_span_to_run(client: TestClient) -> None:
    """A span and a run sharing a trace_id can be joined index-side."""
    _ingest_span(client, TRACE_ID_HEX)
    resp = client.post("/v1/runs", json=_sample_run("run-join", trace_id=TRACE_ID_HEX))
    assert resp.status_code == 202

    index = client.app.state.index
    # The span landed under this trace_id ...
    spans, _, _ = index.get_trace(TRACE_ID_HEX)
    assert spans and spans[0].trace_id == TRACE_ID_HEX
    # ... and the join recovers the matching run record.
    run = index.get_run_by_trace_id(TRACE_ID_HEX)
    assert run is not None
    assert run.run_id == "run-join"
    assert run.blob_path is not None


def test_cost_falls_back_to_span_model(client: TestClient) -> None:
    """A modelless run is priced from its span's gen_ai.request.model (PLUGIN-05)."""
    _ingest_span(client, TRACE_ID_HEX, model="gpt-4o")
    resp = client.post(
        "/v1/runs", json=_sample_run("run-fallback", trace_id=TRACE_ID_HEX)
    )
    assert resp.status_code == 202

    record = _fetch_run(client, "run-fallback")
    assert record.model is None  # run reported none; model came from the span
    assert record.cost_usd == pytest.approx(0.0075)


def test_cost_unpriced_self_model_falls_back_to_span(client: TestClient) -> None:
    """A self-reported model unknown to the table still prices from the span."""
    _ingest_span(client, TRACE_ID_HEX, model="gpt-4o")
    resp = client.post(
        "/v1/runs",
        json=_sample_run("run-typo", trace_id=TRACE_ID_HEX, model="gpt-4o-typo"),
    )
    assert resp.status_code == 202
    record = _fetch_run(client, "run-typo")
    # Self-reported model is kept as-is, but cost came from the span model.
    assert record.model == "gpt-4o-typo"
    assert record.cost_usd == pytest.approx(0.0075)


def test_cost_null_when_no_model_anywhere(client: TestClient) -> None:
    """No run model and no span model -> cost stays NULL (no crash)."""
    _ingest_span(client, TRACE_ID_HEX)  # span carries no model
    resp = client.post(
        "/v1/runs", json=_sample_run("run-nomodel-join", trace_id=TRACE_ID_HEX)
    )
    assert resp.status_code == 202
    assert _fetch_run(client, "run-nomodel-join").cost_usd is None
