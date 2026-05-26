import pytest
from datetime import datetime, timezone
from pathlib import Path

from argox_collector.index.base import SpanRecord
from argox_collector.index.duckdb import DuckDBTraceIndex


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
        agent_name="agent-alpha",
        agent_version="1.0.0",
        run_success=True,
        attributes={"key": "value"}
    )

    index.insert_span(record)

    with index._lock:
        row = index._conn.execute("SELECT * FROM spans").fetchone()
        assert row is not None
        assert row[0] == "trace-123"
        assert row[1] == "span-456"
        assert row[3] == "root-span"
        assert row[7] == "agent-alpha"
        assert row[8] == "1.0.0"
        assert row[11] is True


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
    
    record2 = SpanRecord(trace_id="t1", span_id="s1", name="updated")
    index.insert_span(record2)
    
    with index._lock:
        row = index._conn.execute("SELECT name FROM spans WHERE trace_id='t1'").fetchone()
        assert row[0] == "updated"
        
        count = index._conn.execute("SELECT count(*) FROM spans").fetchone()[0]
        assert count == 1


def test_duckdb_index_health_check(index: DuckDBTraceIndex):
    # Should not raise
    index.health_check()
    
    index.close()
    with pytest.raises(Exception):
        index.health_check()
