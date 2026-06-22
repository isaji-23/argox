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
    assert t1["status"] == "ok"
    assert t1["decision"] == "allow"
    assert t1["start_time"].tzinfo is not None
    assert t1["start_time"] < t1["end_time"]

    t2 = summaries[1]
    assert t2["status"] == "error"


def test_index_list_traces_filters_by_agent(index: DuckDBTraceIndex) -> None:
    summaries, total = index.list_traces(agent_name="agent-a")
    assert total == 1
    assert summaries[0]["trace_id"] == "t1"


def test_index_list_traces_filters_by_status(index: DuckDBTraceIndex) -> None:
    summaries, total = index.list_traces(status="error")
    assert total == 1
    assert summaries[0]["trace_id"] == "t2"


def test_index_list_traces_filters_by_decision(tmp_path: Path) -> None:
    idx = DuckDBTraceIndex(tmp_path / "decision.duckdb")
    idx.insert_spans(
        [
            SpanRecord(trace_id="t-allow", span_id="s1", start_time=NOW),
            SpanRecord(
                trace_id="t-block", span_id="s2", start_time=NOW,
                policy_decision="block",
            ),
            SpanRecord(
                trace_id="t-warn", span_id="s3", start_time=NOW,
                policy_decision="warn",
            ),
        ]
    )
    # Block filter
    summaries, total = idx.list_traces(decision="block")
    assert total == 1
    assert summaries[0]["trace_id"] == "t-block"
    
    # Allow filter (default)
    summaries, total = idx.list_traces(decision="allow")
    assert total == 1
    assert summaries[0]["trace_id"] == "t-allow"


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
    spans, truncated, duration_ms = index.get_trace("t1")
    assert truncated is False
    assert duration_ms == 60_000.0
    assert [s.span_id for s in spans] == ["s1", "s2"]
    assert spans[0].attributes == {"model": "gpt-4o"}
    assert spans[0].start_time.tzinfo is not None
    assert spans[1].parent_span_id == "s1"


def test_index_get_trace_unknown_returns_empty(index: DuckDBTraceIndex) -> None:
    assert index.get_trace("missing") == ([], False, None)


def test_index_get_trace_caps_span_count(index: DuckDBTraceIndex) -> None:
    spans, truncated, duration_ms = index.get_trace("t1", max_spans=1)
    assert truncated is True
    assert duration_ms == 60_000.0
    assert [s.span_id for s in spans] == ["s1"]


def test_index_get_trace_survives_corrupt_attributes(index: DuckDBTraceIndex) -> None:
    # DuckDB's JSON column rejects malformed JSON at write time, so the
    # storable corruption is valid JSON that is not an object. The span must
    # still be returned (with empty attributes) instead of failing the trace.
    with index._lock:
        index._conn.execute(
            "UPDATE spans SET attributes = '[1, 2]' WHERE span_id = 's1'"
        )
    spans, _, _ = index.get_trace("t1")
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
    assert data["items"][0]["status"] == "ok"
    assert data["items"][0]["decision"] == "allow"
    assert data["items"][1]["status"] == "error"


def test_list_traces_endpoint_filters(client: TestClient) -> None:
    # Filter by agent
    res = client.get("/api/v1/traces", params={"agent_name": "agent-a"})
    assert res.json()["total"] == 1
    assert res.json()["items"][0]["trace_id"] == "t1"

    # Filter by status
    res = client.get("/api/v1/traces", params={"status": "error"})
    assert res.json()["total"] == 1
    assert res.json()["items"][0]["trace_id"] == "t2"

    # Filter by decision
    res = client.get("/api/v1/traces", params={"decision": "block"})
    assert res.json()["total"] == 0  # No blocks in mock data

    # Invalid filter values
    assert client.get("/api/v1/traces", params={"status": "invalid"}).status_code == 422
    assert client.get("/api/v1/traces", params={"decision": "invalid"}).status_code == 422


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
    assert data["duration_ms"] == 60_000.0
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


def _search_sort_spans() -> list[SpanRecord]:
    """Diverse trace data specifically for testing prefix filtering, sorting and wildcard escaping."""
    return [
        # t1: newest trace, root + child. Cost only on the root span.
        SpanRecord(
            trace_id="t1-abc",
            span_id="s1",
            name="root-span-A",
            start_time=NOW - timedelta(minutes=5),
            end_time=NOW - timedelta(minutes=4),
            duration_ms=60_000.0,
            agent_name="agent-alpha",
            agent_version="1.0",
            run_cost=0.05,
            run_success=True,
            attributes={"model": "gpt-4o"},
            policy_decision="allow",
        ),
        SpanRecord(
            trace_id="t1-abc",
            span_id="s2",
            parent_span_id="s1",
            name="llm-call-A",
            start_time=NOW - timedelta(minutes=4, seconds=50),
            end_time=NOW - timedelta(minutes=4, seconds=10),
            duration_ms=40_000.0,
            agent_name="agent-alpha",
            agent_version="1.0",
            run_cost=0.02,
            policy_decision="allow",
        ),
        # t2: older trace, failed run.
        SpanRecord(
            trace_id="t2-xyz",
            span_id="s3",
            name="root-span-B",
            start_time=NOW - timedelta(minutes=30),
            end_time=NOW - timedelta(minutes=29),
            duration_ms=30_000.0,
            agent_name="agent-beta",
            agent_version="2.0",
            run_cost=0.10,
            run_success=False,
            policy_decision="block",
        ),
        # t3: trace with a specific pattern in ID, moderate duration/cost
        SpanRecord(
            trace_id="t3_pattern_1",
            span_id="s4",
            name="root-span-C",
            start_time=NOW - timedelta(minutes=15),
            end_time=NOW - timedelta(minutes=10),
            duration_ms=50_000.0,
            agent_name="agent-alpha",
            agent_version="1.1",
            run_cost=0.08,
            run_success=True,
            policy_decision="warn",
        ),
        # t4: another trace with pattern, longer duration, lower cost
        SpanRecord(
            trace_id="t4_pattern_2",
            span_id="s5",
            name="root-span-D",
            start_time=NOW - timedelta(minutes=20),
            end_time=NOW - timedelta(minutes=12),
            duration_ms=80_000.0,
            agent_name="agent-beta",
            agent_version="2.1",
            run_cost=0.03,
            run_success=True,
            policy_decision="allow",
        ),
        # t5: trace to test escaping of '_' and '%' in trace_id
        SpanRecord(
            trace_id="t5-with%wild_card",
            span_id="s6",
            name="root-span-E",
            start_time=NOW - timedelta(minutes=10),
            end_time=NOW - timedelta(minutes=8),
            duration_ms=20_000.0,
            agent_name="agent-gamma",
            agent_version="3.0",
            run_cost=0.01,
            run_success=True,
            policy_decision="allow",
        ),
        # t6: trace for pagination and further sorting tests (lowest cost, highest span count)
        SpanRecord(
            trace_id="t6-last",
            span_id="s7",
            name="root-span-F",
            start_time=NOW - timedelta(minutes=2),
            end_time=NOW - timedelta(minutes=1),
            duration_ms=10_000.0,
            agent_name="agent-delta",
            agent_version="4.0",
            run_cost=0.005,
            run_success=True,
            policy_decision="allow",
        ),
        SpanRecord(
            trace_id="t6-last",
            span_id="s8",
            parent_span_id="s7",
            name="child-F1",
            start_time=NOW - timedelta(minutes=1, seconds=40),
            end_time=NOW - timedelta(minutes=1, seconds=20),
            duration_ms=20_000.0,
            agent_name="agent-delta",
            agent_version="4.0",
            run_cost=0.001,
            policy_decision="allow",
        ),
        SpanRecord(
            trace_id="t6-last",
            span_id="s9",
            parent_span_id="s7",
            name="child-F2",
            start_time=NOW - timedelta(minutes=1, seconds=30),
            end_time=NOW - timedelta(minutes=1, seconds=10),
            duration_ms=20_000.0,
            agent_name="agent-delta",
            agent_version="4.0",
            run_cost=0.001,
            policy_decision="allow",
        ),
    ]


@pytest.fixture
def search_sort_index(tmp_path: Path) -> DuckDBTraceIndex:
    idx = DuckDBTraceIndex(tmp_path / "search_sort.duckdb")
    idx.insert_spans(_search_sort_spans())
    return idx


@pytest.fixture
def search_sort_client(search_sort_index: DuckDBTraceIndex, tmp_path: Path) -> TestClient:
    settings = CollectorSettings(
        storage_local_root=tmp_path / "blobs_search_sort",
        index_duckdb_path=tmp_path / "unused_search_sort.duckdb",
    )
    return TestClient(create_app(settings, index=search_sort_index))


def test_index_list_traces_filters_by_trace_id_prefix(search_sort_index: DuckDBTraceIndex) -> None:
    summaries, total = search_sort_index.list_traces(trace_id="t1-ab")
    assert total == 1
    assert summaries[0]["trace_id"] == "t1-abc"

    summaries, total = search_sort_index.list_traces(trace_id="t")
    assert total == 6
    assert {s["trace_id"] for s in summaries} == {"t1-abc", "t2-xyz", "t3_pattern_1", "t4_pattern_2", "t5-with%wild_card", "t6-last"}

    # Test with special LIKE characters in the search string (should be escaped)
    summaries, total = search_sort_index.list_traces(trace_id="t5-with%wild_card")
    assert total == 1
    assert summaries[0]["trace_id"] == "t5-with%wild_card"

    summaries, total = search_sort_index.list_traces(trace_id="t5-with_wild") # Should not match literal '%' in trace_id
    assert total == 0

    summaries, total = search_sort_index.list_traces(trace_id="t3_patter")
    assert total == 1
    assert summaries[0]["trace_id"] == "t3_pattern_1"


@pytest.mark.parametrize(
    "sort_key, sort_dir, expected_order",
    [
        ("start_time", "desc", ["t6-last", "t1-abc", "t5-with%wild_card", "t3_pattern_1", "t4_pattern_2", "t2-xyz"]),
        ("start_time", "asc", ["t2-xyz", "t4_pattern_2", "t3_pattern_1", "t5-with%wild_card", "t1-abc", "t6-last"]),
        ("duration", "desc", ["t1-abc", "t4_pattern_2", "t3_pattern_1", "t6-last", "t2-xyz", "t5-with%wild_card"]), # t1-abc is (60k+40k=100k)
        ("duration", "asc", ["t5-with%wild_card", "t2-xyz", "t3_pattern_1", "t6-last", "t4_pattern_2", "t1-abc"]), # t6-last is (10k+20k+20k=50k)
        ("cost", "desc", ["t2-xyz", "t3_pattern_1", "t1-abc", "t4_pattern_2", "t5-with%wild_card", "t6-last"]), # t1-abc is (0.05+0.02=0.07)
        ("cost", "asc", ["t6-last", "t5-with%wild_card", "t4_pattern_2", "t1-abc", "t3_pattern_1", "t2-xyz"]), # t6-last is (0.005+0.001+0.001=0.007)
        ("spans", "desc", ["t6-last", "t1-abc", "t2-xyz", "t3_pattern_1", "t4_pattern_2", "t5-with%wild_card"]), # t6-last is 3, t1-abc is 2, others are 1
        ("spans", "asc", ["t2-xyz", "t3_pattern_1", "t4_pattern_2", "t5-with%wild_card", "t1-abc", "t6-last"]),
    ],
)
def test_index_list_traces_sorts_by_column_and_direction(
    search_sort_index: DuckDBTraceIndex, sort_key: str, sort_dir: str, expected_order: list[str]
) -> None:
    summaries, total = search_sort_index.list_traces(sort=f"{sort_key}:{sort_dir}")
    assert total == 6
    assert [s["trace_id"] for s in summaries] == expected_order


def test_list_traces_endpoint_filters_by_trace_id_prefix(search_sort_client: TestClient) -> None:
    res = search_sort_client.get("/api/v1/traces", params={"trace_id": "t1-ab"})
    assert res.status_code == 200
    assert res.json()["total"] == 1
    assert res.json()["items"][0]["trace_id"] == "t1-abc"

    res = search_sort_client.get("/api/v1/traces", params={"trace_id": "t"})
    assert res.status_code == 200
    assert res.json()["total"] == 6
    assert {item["trace_id"] for item in res.json()["items"]} == {"t1-abc", "t2-xyz", "t3_pattern_1", "t4_pattern_2", "t5-with%wild_card", "t6-last"}

    # Test with special LIKE characters in the search string (should be escaped)
    res = search_sort_client.get("/api/v1/traces", params={"trace_id": "t5-with%wild_card"})
    assert res.status_code == 200
    assert res.json()["total"] == 1
    assert res.json()["items"][0]["trace_id"] == "t5-with%wild_card"

    res = search_sort_client.get("/api/v1/traces", params={"trace_id": "t5-with_wild"})
    assert res.status_code == 200
    assert res.json()["total"] == 0

    res = search_sort_client.get("/api/v1/traces", params={"trace_id": "t3_patter"})
    assert res.status_code == 200
    assert res.json()["total"] == 1
    assert res.json()["items"][0]["trace_id"] == "t3_pattern_1"


@pytest.mark.parametrize(
    "sort_key, sort_dir, expected_order",
    [
        ("start_time", "desc", ["t6-last", "t1-abc", "t5-with%wild_card", "t3_pattern_1", "t4_pattern_2", "t2-xyz"]),
        ("start_time", "asc", ["t2-xyz", "t4_pattern_2", "t3_pattern_1", "t5-with%wild_card", "t1-abc", "t6-last"]),
        ("duration", "desc", ["t1-abc", "t4_pattern_2", "t3_pattern_1", "t6-last", "t2-xyz", "t5-with%wild_card"]),
        ("duration", "asc", ["t5-with%wild_card", "t2-xyz", "t3_pattern_1", "t6-last", "t4_pattern_2", "t1-abc"]),
        ("cost", "desc", ["t2-xyz", "t3_pattern_1", "t1-abc", "t4_pattern_2", "t5-with%wild_card", "t6-last"]),
        ("cost", "asc", ["t6-last", "t5-with%wild_card", "t4_pattern_2", "t1-abc", "t3_pattern_1", "t2-xyz"]),
        ("spans", "desc", ["t6-last", "t1-abc", "t2-xyz", "t3_pattern_1", "t4_pattern_2", "t5-with%wild_card"]),
        ("spans", "asc", ["t2-xyz", "t3_pattern_1", "t4_pattern_2", "t5-with%wild_card", "t1-abc", "t6-last"]),
    ],
)
def test_list_traces_endpoint_sorts_by_column_and_direction(
    search_sort_client: TestClient, sort_key: str, sort_dir: str, expected_order: list[str]
) -> None:
    res = search_sort_client.get("/api/v1/traces", params={"sort": f"{sort_key}:{sort_dir}"})
    assert res.status_code == 200
    assert res.json()["total"] == 6
    assert [item["trace_id"] for item in res.json()["items"]] == expected_order


def test_list_traces_endpoint_malformed_sort_string_returns_422(search_sort_client: TestClient) -> None:
    res = search_sort_client.get("/api/v1/traces", params={"sort": "invalid"})
    assert res.status_code == 422
    res = search_sort_client.get("/api/v1/traces", params={"sort": "start_time:invalid_dir"})
    assert res.status_code == 422
    res = search_sort_client.get("/api/v1/traces", params={"sort": "invalid_field:asc"})
    assert res.status_code == 422


def test_index_list_traces_filters_by_window_hours(tmp_path: Path) -> None:
    from datetime import timedelta
    idx = DuckDBTraceIndex(tmp_path / "window.duckdb")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    idx.insert_spans(
        [
            SpanRecord(trace_id="t-recent", span_id="s1", start_time=now - timedelta(minutes=10)),
            SpanRecord(trace_id="t-old", span_id="s2", start_time=now - timedelta(hours=5)),
        ]
    )
    # 2 hours window should only return recent trace
    summaries, total = idx.list_traces(window_hours=2)
    assert total == 1
    assert summaries[0]["trace_id"] == "t-recent"

    # 10 hours window should return both
    summaries, total = idx.list_traces(window_hours=10)
    assert total == 2


def test_list_traces_endpoint_filters_by_window_hours(client: TestClient) -> None:
    res = client.get("/api/v1/traces", params={"window_hours": 24})
    assert res.status_code == 200

