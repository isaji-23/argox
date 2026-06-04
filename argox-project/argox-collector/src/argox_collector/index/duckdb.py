"""DuckDB implementation of :class:`TraceIndex`."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import duckdb

from argox_collector.index.base import SpanRecord, TraceIndex, TraceIndexError


def _to_naive_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if not dt:
        return None
    if dt.tzinfo:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


class DuckDBTraceIndex(TraceIndex):
    """Index spans in a local DuckDB file.
    
    DuckDB is optimized for OLAP queries, making it ideal for the dashboard's
    aggregations. Writes are protected by a thread lock to handle DuckDB's
    single-writer limitation.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path).resolve()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # DuckDB connections are not thread-safe for shared use, and 
        # concurrent writes to the same file require care. We use a 
        # single connection protected by a lock for all operations.
        self._conn = duckdb.connect(str(self._db_path))
        self._lock = threading.Lock()
        
        self._init_schema()

    def _init_schema(self) -> None:
        """Create the spans table if it doesn't exist."""
        with self._lock:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS spans (
                    trace_id VARCHAR,
                    span_id VARCHAR,
                    parent_span_id VARCHAR,
                    name VARCHAR,
                    start_time TIMESTAMP,
                    end_time TIMESTAMP,
                    duration_ms DOUBLE,
                    agent_name VARCHAR,
                    agent_version VARCHAR,
                    policy_decision VARCHAR,
                    run_cost DOUBLE,
                    run_success BOOLEAN,
                    attributes JSON,
                    PRIMARY KEY (trace_id, span_id)
                )
            """)
            # Create indexes for common query patterns
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_spans_start_time ON spans (start_time)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_spans_agent_name ON spans (agent_name)")

    def insert_span(self, record: SpanRecord) -> None:
        self.insert_spans([record])

    def insert_spans(self, records: list[SpanRecord]) -> None:
        if not records:
            return

        # Prepare data for DuckDB's executemany
        data = [
            (
                r.trace_id,
                r.span_id,
                r.parent_span_id,
                r.name,
                _to_naive_utc(r.start_time),
                _to_naive_utc(r.end_time),
                r.duration_ms,
                r.agent_name,
                r.agent_version,
                r.policy_decision,
                r.run_cost,
                r.run_success,
                json.dumps(r.attributes) if r.attributes else None,
            )
            for r in records
        ]

        with self._lock:
            self._conn.executemany("""
                INSERT INTO spans (
                    trace_id, span_id, parent_span_id, name, 
                    start_time, end_time, duration_ms,
                    agent_name, agent_version, policy_decision, 
                    run_cost, run_success, attributes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (trace_id, span_id) DO UPDATE SET
                    parent_span_id = COALESCE(excluded.parent_span_id, spans.parent_span_id),
                    name = COALESCE(NULLIF(excluded.name, ''), spans.name),
                    start_time = COALESCE(excluded.start_time, spans.start_time),
                    end_time = COALESCE(excluded.end_time, spans.end_time),
                    duration_ms = COALESCE(excluded.duration_ms, spans.duration_ms),
                    agent_name = COALESCE(excluded.agent_name, spans.agent_name),
                    agent_version = COALESCE(excluded.agent_version, spans.agent_version),
                    policy_decision = COALESCE(excluded.policy_decision, spans.policy_decision),
                    run_cost = COALESCE(excluded.run_cost, spans.run_cost),
                    run_success = COALESCE(excluded.run_success, spans.run_success),
                    attributes = COALESCE(excluded.attributes, spans.attributes)
            """, data)

    def list_traces(self, skip: int = 0, limit: int = 50) -> list[dict]:
        with self._lock:
            # Aggregate trace summary: root span info, trace total cost, duration
            query = """
                SELECT 
                    trace_id,
                    MIN(start_time) as start_time,
                    MAX(end_time) as end_time,
                    SUM(duration_ms) as total_duration_ms,
                    SUM(run_cost) as total_cost,
                    MAX(agent_name) as agent_name,
                    MAX(agent_version) as agent_version,
                    COUNT(span_id) as span_count
                FROM spans
                GROUP BY trace_id
                ORDER BY start_time DESC
                LIMIT ? OFFSET ?
            """
            result = self._conn.execute(query, (limit, skip)).fetchall()
            
        traces = []
        for row in result:
            traces.append({
                "trace_id": row[0],
                "start_time": row[1].isoformat() + "Z" if row[1] else None,
                "end_time": row[2].isoformat() + "Z" if row[2] else None,
                "total_duration_ms": row[3],
                "total_cost": row[4],
                "agent_name": row[5],
                "agent_version": row[6],
                "span_count": row[7]
            })
        return traces

    def get_trace(self, trace_id: str) -> list[SpanRecord]:
        with self._lock:
            query = """
                SELECT 
                    trace_id, span_id, parent_span_id, name, 
                    start_time, end_time, duration_ms,
                    agent_name, agent_version, policy_decision, 
                    run_cost, run_success, attributes
                FROM spans
                WHERE trace_id = ?
                ORDER BY start_time ASC
            """
            result = self._conn.execute(query, (trace_id,)).fetchall()
            
        spans = []
        for row in result:
            attr_dict = json.loads(row[12]) if row[12] else {}
            spans.append(SpanRecord(
                trace_id=row[0],
                span_id=row[1],
                parent_span_id=row[2],
                name=row[3],
                start_time=row[4].replace(tzinfo=timezone.utc) if row[4] else None,
                end_time=row[5].replace(tzinfo=timezone.utc) if row[5] else None,
                duration_ms=row[6],
                agent_name=row[7],
                agent_version=row[8],
                policy_decision=row[9],
                run_cost=row[10],
                run_success=row[11],
                attributes=attr_dict
            ))
        return spans

    def get_metrics_cost(self, window_hours: int = 24) -> dict:
        with self._lock:
            query = """
                SELECT SUM(run_cost) as total_cost, COUNT(DISTINCT trace_id) as trace_count
                FROM spans
                WHERE start_time >= CURRENT_TIMESTAMP - INTERVAL 1 HOUR * ?
            """
            result = self._conn.execute(query, (window_hours,)).fetchone()
            
        return {
            "window_hours": window_hours,
            "total_cost": result[0] or 0.0,
            "trace_count": result[1] or 0
        }

    def get_metrics_latency(self, window_hours: int = 24) -> dict:
        with self._lock:
            # P95 latency approximation using approx_quantile
            query = """
                SELECT 
                    avg(duration_ms) as avg_latency,
                    approx_quantile(duration_ms, 0.95) as p95_latency
                FROM spans
                WHERE start_time >= CURRENT_TIMESTAMP - INTERVAL 1 HOUR * ?
                  AND parent_span_id IS NULL -- Only consider root spans for trace latency
            """
            result = self._conn.execute(query, (window_hours,)).fetchone()
            
        return {
            "window_hours": window_hours,
            "avg_latency_ms": result[0] or 0.0,
            "p95_latency_ms": result[1] or 0.0
        }

    def get_metrics_success(self, window_hours: int = 24) -> dict:
        with self._lock:
            query = """
                SELECT 
                    COUNT(*) as total_runs,
                    SUM(CASE WHEN run_success = TRUE THEN 1 ELSE 0 END) as successful_runs
                FROM spans
                WHERE start_time >= CURRENT_TIMESTAMP - INTERVAL 1 HOUR * ?
                  AND parent_span_id IS NULL -- Only root spans determine run success
            """
            result = self._conn.execute(query, (window_hours,)).fetchone()
            
        total = result[0] or 0
        successes = result[1] or 0
        success_rate = (successes / total) if total > 0 else 0.0
        
        return {
            "window_hours": window_hours,
            "total_runs": total,
            "successful_runs": successes,
            "success_rate": success_rate
        }

    def health_check(self) -> None:
        try:
            with self._lock:
                self._conn.execute("SELECT 1").fetchone()
        except Exception as exc:
            raise TraceIndexError(f"DuckDB index health check failed: {exc}") from exc

    def close(self) -> None:
        """Close the DuckDB connection."""
        with self._lock:
            self._conn.close()
