import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timezone, timedelta

from argox_collector.index.base import SpanRecord
from argox_collector.index.duckdb import DuckDBTraceIndex
from pathlib import Path

@pytest.fixture
def index(tmp_path: Path) -> DuckDBTraceIndex:
    db_path = tmp_path / "test.duckdb"
    return DuckDBTraceIndex(db_path)

@pytest.fixture
def populated_index(index):
    now = datetime.now(timezone.utc)
    spans = [
        # Trace 1
        SpanRecord(trace_id="t1", span_id="s1", parent_span_id=None, start_time=now - timedelta(minutes=5), end_time=now - timedelta(minutes=4), duration_ms=60000, agent_name="agent-a", agent_version="1.0", run_cost=0.05, run_success=True),
        SpanRecord(trace_id="t1", span_id="s2", parent_span_id="s1", start_time=now - timedelta(minutes=4, seconds=50), end_time=now - timedelta(minutes=4), duration_ms=50000, agent_name="agent-a", agent_version="1.0"),
        
        # Trace 2
        SpanRecord(trace_id="t2", span_id="s3", parent_span_id=None, start_time=now - timedelta(minutes=10), end_time=now - timedelta(minutes=9), duration_ms=60000, agent_name="agent-b", agent_version="2.0", run_cost=0.1, run_success=False),
    ]
    index.insert_spans(spans)
    return index


@pytest.fixture
def client_with_index(populated_index):
    from argox_collector.app import create_app
    from argox_collector.settings import CollectorSettings
    
    settings = CollectorSettings(
        environment="test",
        # Use an ephemeral in-memory duckdb for testing query app, or populated_index has it
    )
    app = create_app(settings=settings, index=populated_index)
    return TestClient(app)


def test_list_traces(client_with_index):
    response = client_with_index.get("/api/v1/traces")
    assert response.status_code == 200
    data = response.json()
    assert data["limit"] == 50
    assert data["skip"] == 0
    assert len(data["items"]) == 2
    
    # Ordered by start_time DESC, so t1 should be first (it's newer)
    assert data["items"][0]["trace_id"] == "t1"
    assert data["items"][0]["total_cost"] == 0.05
    assert data["items"][0]["span_count"] == 2
    assert data["items"][0]["agent_name"] == "agent-a"
    
    assert data["items"][1]["trace_id"] == "t2"
    assert data["items"][1]["total_cost"] == 0.1
    assert data["items"][1]["span_count"] == 1


def test_get_trace(client_with_index):
    response = client_with_index.get("/api/v1/traces/t1")
    assert response.status_code == 200
    data = response.json()
    assert data["trace_id"] == "t1"
    assert len(data["spans"]) == 2
    # Check spans are ordered by start_time ASC
    assert data["spans"][0]["span_id"] == "s1"
    assert data["spans"][1]["span_id"] == "s2"


def test_get_trace_not_found(client_with_index):
    response = client_with_index.get("/api/v1/traces/non_existent")
    assert response.status_code == 404


def test_get_metrics_cost(client_with_index):
    response = client_with_index.get("/api/v1/metrics/cost?window_hours=24")
    assert response.status_code == 200
    data = response.json()
    assert data["window_hours"] == 24
    assert data["total_cost"] == pytest.approx(0.15)
    assert data["trace_count"] == 2


def test_get_metrics_latency(client_with_index):
    response = client_with_index.get("/api/v1/metrics/latency?window_hours=24")
    assert response.status_code == 200
    data = response.json()
    assert data["window_hours"] == 24
    assert data["avg_latency_ms"] == 60000.0  # Only root spans are considered
    assert data["p95_latency_ms"] == 60000.0


def test_get_metrics_success(client_with_index):
    response = client_with_index.get("/api/v1/metrics/success?window_hours=24")
    assert response.status_code == 200
    data = response.json()
    assert data["window_hours"] == 24
    assert data["total_runs"] == 2
    assert data["successful_runs"] == 1
    assert data["success_rate"] == 0.5
