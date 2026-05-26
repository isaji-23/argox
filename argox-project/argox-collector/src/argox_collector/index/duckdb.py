"""DuckDB implementation of :class:`TraceIndex`."""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import duckdb

from argox_collector.index.base import SpanRecord, TraceIndex, TraceIndexError


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
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_spans_trace_id ON spans (trace_id)")
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
                r.start_time,
                r.end_time,
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
                INSERT OR REPLACE INTO spans (
                    trace_id, span_id, parent_span_id, name, 
                    start_time, end_time, duration_ms,
                    agent_name, agent_version, policy_decision, 
                    run_cost, run_success, attributes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, data)

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
