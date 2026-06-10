import pytest
from datetime import datetime, timezone
import json
from pathlib import Path

from argox_collector.index.base import SpanRecord, TraceIndexError
from argox_collector.index.duckdb import DuckDBTraceIndex
from argox_collector.index.factory import build_index
from argox_collector.settings import CollectorSettings


@pytest.fixture
def index(tmp_path: Path) -> DuckDBTraceIndex:
    db_path = tmp_path / "test.duckdb"
    return DuckDBTraceIndex(db_path)


def test_duckdb_index_init_creates_schema(index: DuckDBTraceIndex):
    with index._lock:
        tables = index._conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_name = 'spans'"
        ).fetchone()
        assert tables is not None
        assert tables[0] == "spans"


def test_duckdb_index_insert_span(index: DuckDBTraceIndex):
    now = datetime.now(timezone.utc)
    record = SpanRecord(
        trace_id="trace-123",
        span_id="span-456",
        parent_span_id=None,
        name="root-span",
        start_time=now,
        end_time=now,
        duration_ms=123.45,
        agent_name="agent-alpha",
        agent_version="1.0.0",
        run_cost=0.001,
        run_success=True,
        attributes={"key": "value"}
    )

    index.insert_span(record)

    with index._lock:
        row = index._conn.execute("SELECT trace_id, span_id, name, start_time, end_time, duration_ms, agent_name, agent_version, run_cost, run_success, attributes FROM spans").fetchone()
        assert row is not None
        assert row[0] == "trace-123"
        assert row[1] == "span-456"
        assert row[2] == "root-span"
        # round-trip check
        assert row[3].replace(tzinfo=timezone.utc) == now
        assert row[4].replace(tzinfo=timezone.utc) == now
        assert row[5] == 123.45
        assert row[6] == "agent-alpha"
        assert row[7] == "1.0.0"
        assert row[8] == 0.001
        assert row[9] is True
        assert json.loads(row[10]) == {"key": "value"}


def test_duckdb_index_batch_insert(index: DuckDBTraceIndex):
    records = [
        SpanRecord(trace_id=f"t{i}", span_id=f"s{i}", name=f"span-{i}")
        for i in range(10)
    ]
    
    index.insert_spans(records)
    
    with index._lock:
        count = index._conn.execute("SELECT count(*) FROM spans").fetchone()[0]
        assert count == 10


def test_duckdb_index_upsert_behavior(index: DuckDBTraceIndex):
    record1 = SpanRecord(trace_id="t1", span_id="s1", name="first")
    index.insert_span(record1)
    
    record2 = SpanRecord(trace_id="t1", span_id="s1", name="updated", duration_ms=10.0)
    index.insert_span(record2)
    
    with index._lock:
        row = index._conn.execute("SELECT name, duration_ms FROM spans WHERE trace_id='t1'").fetchone()
        assert row[0] == "updated"
        assert row[1] == 10.0
        
        count = index._conn.execute("SELECT count(*) FROM spans").fetchone()[0]
        assert count == 1


def test_duckdb_index_upsert_partial(index: DuckDBTraceIndex):
    now = datetime.now(timezone.utc)
    record1 = SpanRecord(
        trace_id="t1", 
        span_id="s1", 
        name="original", 
        start_time=now,
        duration_ms=100.0
    )
    index.insert_span(record1)
    
    # Partial update: name and start_time are missing (None by default)
    record2 = SpanRecord(
        trace_id="t1", 
        span_id="s1", 
        duration_ms=200.0,
        run_success=True
    )
    index.insert_span(record2)
    
    with index._lock:
        row = index._conn.execute("SELECT name, start_time, duration_ms, run_success FROM spans WHERE trace_id='t1'").fetchone()
        assert row[0] == "original"  # Should NOT be None/empty
        assert row[1].replace(tzinfo=timezone.utc) == now  # Should NOT be overwritten
        assert row[2] == 200.0  # Should be updated
        assert row[3] is True  # Should be updated

    # Partial update with empty string for name
    record3 = SpanRecord(
        trace_id="t1", 
        span_id="s1", 
        name="",
        duration_ms=300.0
    )
    index.insert_span(record3)
    
    with index._lock:
        row = index._conn.execute("SELECT name, duration_ms FROM spans WHERE trace_id='t1'").fetchone()
        assert row[0] == "original"
        assert row[1] == 300.0


def test_duckdb_index_batch_survives_one_bad_row(index: DuckDBTraceIndex):
    # A single row with a type DuckDB rejects (string in the BOOLEAN column)
    # must not drop the whole batch: good rows still land via the per-row
    # fallback, the bad row is skipped.
    good_before = SpanRecord(trace_id="t-good-1", span_id="s1", name="ok")
    bad = SpanRecord(trace_id="t-bad", span_id="s1", run_success="not-a-bool")
    good_after = SpanRecord(trace_id="t-good-2", span_id="s1", name="ok")

    index.insert_spans([good_before, bad, good_after])

    with index._lock:
        rows = index._conn.execute("SELECT trace_id FROM spans ORDER BY trace_id").fetchall()
    trace_ids = {r[0] for r in rows}
    assert trace_ids == {"t-good-1", "t-good-2"}


def test_duckdb_index_nan_attributes_do_not_drop_row(index: DuckDBTraceIndex):
    # json.dumps would emit a bare NaN literal, which DuckDB's JSON parser
    # rejects at insert time. The row must still land, with the non-finite
    # value degraded to its string form.
    record = SpanRecord(
        trace_id="t-nan",
        span_id="s1",
        name="span",
        attributes={"score": float("nan"), "kept": "yes"},
    )

    index.insert_spans([record])

    spans, _ = index.get_trace("t-nan")
    assert len(spans) == 1
    assert spans[0].attributes["kept"] == "yes"
    assert spans[0].attributes["score"] == "nan"


def test_duckdb_index_unserializable_attributes_do_not_drop_batch(
    index: DuckDBTraceIndex,
):
    # Attribute encoding happens during batch preparation, before any row is
    # written: an exception there would lose the whole batch. Objects that
    # json cannot encode degrade to their string form instead.
    bad = SpanRecord(
        trace_id="t-bad-attrs",
        span_id="s1",
        attributes={"blob": b"\x00\x01", "nested": {"when": datetime(2026, 1, 1)}},
    )
    good = SpanRecord(trace_id="t-good", span_id="s1", name="ok")

    index.insert_spans([bad, good])

    spans, _ = index.get_trace("t-bad-attrs")
    assert len(spans) == 1
    assert spans[0].attributes["blob"] == str(b"\x00\x01")
    good_spans, _ = index.get_trace("t-good")
    assert len(good_spans) == 1


def test_duckdb_index_non_finite_doubles_stored_as_null(index: DuckDBTraceIndex):
    record = SpanRecord(
        trace_id="t-inf",
        span_id="s1",
        duration_ms=float("inf"),
        run_cost=float("nan"),
    )

    index.insert_span(record)

    spans, _ = index.get_trace("t-inf")
    assert spans[0].duration_ms is None
    assert spans[0].run_cost is None


def test_duckdb_index_metrics_ignore_non_finite_rows(index: DuckDBTraceIndex):
    # Rows written before write-side sanitisation existed may hold NaN.
    # Aggregates must not propagate it into the metrics payloads.
    now = datetime.now(timezone.utc)
    index.insert_span(
        SpanRecord(
            trace_id="t1",
            span_id="s1",
            start_time=now,
            duration_ms=100.0,
            run_cost=0.5,
        )
    )
    with index._lock:
        index._conn.execute(
            "INSERT INTO spans (trace_id, span_id, start_time, duration_ms, run_cost)"
            " VALUES ('t2', 's1', ?, 'nan'::DOUBLE, 'nan'::DOUBLE)",
            (now.replace(tzinfo=None),),
        )

    cost = index.get_metrics_cost(window_hours=24)
    assert cost["total_cost"] == 0.5
    latency = index.get_metrics_latency(window_hours=24)
    assert latency["avg_latency_ms"] == 100.0
    assert latency["trace_count"] == 1


def test_duckdb_index_health_check(index: DuckDBTraceIndex):
    # Should not raise
    index.health_check()

    index.close()
    with pytest.raises(TraceIndexError) as excinfo:
        index.health_check()
    # readyz forwards this message verbatim to unauthenticated callers, so it
    # must stay generic and never embed the database filesystem path.
    assert str(excinfo.value) == "DuckDB index health check failed"
    assert str(index._db_path) not in str(excinfo.value)


def test_factory_build_index_duckdb(tmp_path: Path):
    settings = CollectorSettings(index_backend="duckdb", index_duckdb_path=tmp_path / "factory.duckdb")
    idx = build_index(settings)
    assert isinstance(idx, DuckDBTraceIndex)


def test_factory_build_index_unknown():
    settings = CollectorSettings(index_backend="unknown_backend")
    with pytest.raises(ValueError, match="unknown index backend"):
        build_index(settings)

