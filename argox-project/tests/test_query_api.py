"""Tests for the COL-06 Query API: trace lists, trace detail and metrics."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from argox_collector.app import create_app
from argox_collector.index.base import SpanRecord
from argox_collector.index.duckdb import DuckDBTraceIndex
from argox_collector.settings import CollectorSettings
from fastapi.testclient import TestClient

NOW = datetime.now(timezone.utc)


def _spans() -> list[SpanRecord]:
    """Two recent traces plus one outside any 24h window."""
    return [
        # t1: newest trace, root + child. Cost only on the root span.
        SpanRecord(
            trace_id="t1",
            span_id="s1",
            name="root",
            start_time=NOW - timedelta(minutes=5),
            end_time=NOW - timedelta(minutes=4),
            duration_ms=60_000.0,
            agent_name="agent-a",
            agent_version="1.0",
            run_cost=0.05,
            run_success=True,
            attributes={"model": "gpt-4o"},
        ),
        # Child span carries its own cost: the cost contract sums ALL spans,
        # so this must land in trace and window totals alongside the root's.
        SpanRecord(
            trace_id="t1",
            span_id="s2",
            parent_span_id="s1",
            name="llm-call",
            start_time=NOW - timedelta(minutes=4, seconds=50),
            end_time=NOW - timedelta(minutes=4, seconds=10),
            duration_ms=40_000.0,
            agent_name="agent-a",
            agent_version="1.0",
            run_cost=0.02,
        ),
        # t2: older trace, failed run.
        SpanRecord(
            trace_id="t2",
            span_id="s3",
            name="root",
            start_time=NOW - timedelta(minutes=30),
            end_time=NOW - timedelta(minutes=29),
            duration_ms=30_000.0,
            agent_name="agent-b",
            agent_version="2.0",
            run_cost=0.10,
            run_success=False,
        ),
        # t3: outside the default 24h metrics window.
        SpanRecord(
            trace_id="t3",
            span_id="s4",
            name="root",
            start_time=NOW - timedelta(days=3),
            end_time=NOW - timedelta(days=3) + timedelta(minutes=1),
            duration_ms=10_000.0,
            agent_name="agent-old",
            run_cost=9.99,
            run_success=True,
        ),
    ]


@pytest.fixture
def index(tmp_path: Path) -> DuckDBTraceIndex:
    idx = DuckDBTraceIndex(tmp_path / "test.duckdb")
    idx.insert_spans(_spans())
    return idx


@pytest.fixture
def client(index: DuckDBTraceIndex, tmp_path: Path) -> TestClient:
    settings = CollectorSettings(
        storage_local_root=tmp_path / "blobs",
        index_duckdb_path=tmp_path / "unused.duckdb",
    )
    return TestClient(create_app(settings, index=index))


# ---------------------------------------------------------------------------
# Index layer
# ---------------------------------------------------------------------------


def test_index_list_traces_aggregates_and_sorts(index: DuckDBTraceIndex) -> None:
    summaries, total = index.list_traces()
    assert total == 3
    assert [s["trace_id"] for s in summaries] == ["t1", "t2", "t3"]

    t1 = summaries[0]
    assert t1["span_count"] == 2
    # Root (0.05) + child (0.02): trace cost sums all spans.
    assert t1["total_cost"] == pytest.approx(0.07)
    assert t1["total_duration_ms"] == pytest.approx(100_000.0)
    assert t1["agent_name"] == "agent-a"
    assert t1["agent_version"] == "1.0"
    assert t1["start_time"].tzinfo is not None
    assert t1["start_time"] < t1["end_time"]


def test_index_list_traces_paginates(index: DuckDBTraceIndex) -> None:
    summaries, total = index.list_traces(skip=1, limit=1)
    assert total == 3
    assert [s["trace_id"] for s in summaries] == ["t2"]


def test_index_list_traces_prefers_root_span_agent(tmp_path: Path) -> None:
    idx = DuckDBTraceIndex(tmp_path / "agent.duckdb")
    idx.insert_spans(
        [
            SpanRecord(
                trace_id="t", span_id="root", agent_name="agent-root",
                start_time=NOW,
            ),
            SpanRecord(
                trace_id="t", span_id="child", parent_span_id="root",
                # Sorts after "agent-root"; MAX() alone would pick this one.
                agent_name="agent-zzz", start_time=NOW,
            ),
        ]
    )
    summaries, _ = idx.list_traces()
    assert summaries[0]["agent_name"] == "agent-root"


def test_index_get_trace_orders_spans_and_roundtrips(index: DuckDBTraceIndex) -> None:
    spans, truncated = index.get_trace("t1")
    assert truncated is False
    assert [s.span_id for s in spans] == ["s1", "s2"]
    assert spans[0].attributes == {"model": "gpt-4o"}
    assert spans[0].start_time.tzinfo is not None
    assert spans[1].parent_span_id == "s1"


def test_index_get_trace_unknown_returns_empty(index: DuckDBTraceIndex) -> None:
    assert index.get_trace("missing") == ([], False)


def test_index_get_trace_caps_span_count(index: DuckDBTraceIndex) -> None:
    spans, truncated = index.get_trace("t1", max_spans=1)
    assert truncated is True
    assert [s.span_id for s in spans] == ["s1"]


def test_index_get_trace_survives_corrupt_attributes(index: DuckDBTraceIndex) -> None:
    # DuckDB's JSON column rejects malformed JSON at write time, so the
    # storable corruption is valid JSON that is not an object. The span must
    # still be returned (with empty attributes) instead of failing the trace.
    with index._lock:
        index._conn.execute(
            "UPDATE spans SET attributes = '[1, 2]' WHERE span_id = 's1'"
        )
    spans, _ = index.get_trace("t1")
    assert [s.span_id for s in spans] == ["s1", "s2"]
    assert spans[0].attributes == {}


def test_index_reads_do_not_hold_writer_lock(index: DuckDBTraceIndex) -> None:
    # Reads run on their own cursors so a held writer lock (an in-flight
    # insert_spans) cannot stall dashboard queries — and vice versa.
    import threading

    result: dict = {}

    def read() -> None:
        result["summaries"] = index.list_traces()

    with index._lock:
        thread = threading.Thread(target=read, daemon=True)
        thread.start()
        thread.join(timeout=5)
    assert "summaries" in result, "read blocked on the writer lock"


def test_index_metrics_cost_respects_window(index: DuckDBTraceIndex) -> None:
    metrics = index.get_metrics_cost(window_hours=24)
    # 0.05 (t1 root) + 0.02 (t1 child) + 0.10 (t2 root): all spans count.
    assert metrics["total_cost"] == pytest.approx(0.17)
    assert metrics["trace_count"] == 2

    wide = index.get_metrics_cost(window_hours=720)
    assert wide["total_cost"] == pytest.approx(10.16)
    assert wide["trace_count"] == 3


def test_index_metrics_latency_uses_root_spans_only(index: DuckDBTraceIndex) -> None:
    metrics = index.get_metrics_latency(window_hours=24)
    # Root durations are 60s (t1) and 30s (t2); the 40s child is ignored.
    assert metrics["avg_latency_ms"] == pytest.approx(45_000.0)
    assert metrics["p95_latency_ms"] == pytest.approx(58_500.0)
    assert metrics["trace_count"] == 2


def test_index_metrics_success_rate(index: DuckDBTraceIndex) -> None:
    metrics = index.get_metrics_success(window_hours=24)
    assert metrics["total_runs"] == 2
    assert metrics["successful_runs"] == 1
    assert metrics["success_rate"] == pytest.approx(0.5)


def test_index_metrics_on_empty_index(tmp_path: Path) -> None:
    idx = DuckDBTraceIndex(tmp_path / "empty.duckdb")
    assert idx.get_metrics_cost() == {
        "window_hours": 24, "total_cost": 0.0, "trace_count": 0,
    }
    latency = idx.get_metrics_latency()
    assert latency["avg_latency_ms"] == 0.0
    assert latency["p95_latency_ms"] == 0.0
    success = idx.get_metrics_success()
    assert success["total_runs"] == 0
    assert success["success_rate"] is None


# ---------------------------------------------------------------------------
# HTTP layer
# ---------------------------------------------------------------------------


def test_list_traces_endpoint(client: TestClient) -> None:
    response = client.get("/api/v1/traces")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert data["skip"] == 0
    assert data["limit"] == 50
    assert [item["trace_id"] for item in data["items"]] == ["t1", "t2", "t3"]
    assert data["items"][0]["span_count"] == 2
    assert data["items"][0]["total_cost"] == pytest.approx(0.07)


def test_list_traces_endpoint_pagination(client: TestClient) -> None:
    response = client.get("/api/v1/traces", params={"skip": 2, "limit": 1})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert [item["trace_id"] for item in data["items"]] == ["t3"]


def test_list_traces_endpoint_validates_pagination(client: TestClient) -> None:
    assert client.get("/api/v1/traces", params={"skip": -1}).status_code == 422
    assert client.get("/api/v1/traces", params={"limit": 0}).status_code == 422
    assert client.get("/api/v1/traces", params={"limit": 1001}).status_code == 422


def test_get_trace_endpoint(client: TestClient) -> None:
    response = client.get("/api/v1/traces/t1")
    assert response.status_code == 200
    data = response.json()
    assert data["trace_id"] == "t1"
    assert data["truncated"] is False
    assert [span["span_id"] for span in data["spans"]] == ["s1", "s2"]
    assert data["spans"][0]["attributes"] == {"model": "gpt-4o"}
    assert data["spans"][1]["parent_span_id"] == "s1"
    # Timestamps serialize as ISO-8601 with explicit UTC offset.
    assert data["spans"][0]["start_time"].endswith(("Z", "+00:00"))


def test_get_trace_endpoint_404(client: TestClient) -> None:
    response = client.get("/api/v1/traces/does-not-exist")
    assert response.status_code == 404


def test_metrics_cost_endpoint(client: TestClient) -> None:
    response = client.get("/api/v1/metrics/cost")
    assert response.status_code == 200
    data = response.json()
    assert data["window_hours"] == 24
    assert data["total_cost"] == pytest.approx(0.17)
    assert data["trace_count"] == 2


def test_metrics_latency_endpoint(client: TestClient) -> None:
    response = client.get("/api/v1/metrics/latency", params={"window_hours": 12})
    assert response.status_code == 200
    data = response.json()
    assert data["window_hours"] == 12
    assert data["avg_latency_ms"] == pytest.approx(45_000.0)
    assert data["trace_count"] == 2


def test_metrics_success_endpoint(client: TestClient) -> None:
    response = client.get("/api/v1/metrics/success")
    assert response.status_code == 200
    data = response.json()
    assert data["total_runs"] == 2
    assert data["successful_runs"] == 1
    assert data["success_rate"] == pytest.approx(0.5)


def test_metrics_validate_window_bounds(client: TestClient) -> None:
    for path in ("cost", "latency", "success"):
        url = f"/api/v1/metrics/{path}"
        assert client.get(url, params={"window_hours": 0}).status_code == 422
        assert client.get(url, params={"window_hours": 721}).status_code == 422
