"""DuckDB implementation of :class:`TraceIndex`."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import duckdb
import structlog

from argox_collector.index.base import SpanRecord, TraceIndex, TraceIndexError

logger = structlog.get_logger(__name__)

# Hard ceiling on spans returned per trace detail: bounds response size and
# memory for pathological traces. Callers learn about the cut via the
# ``truncated`` flag returned by :meth:`DuckDBTraceIndex.get_trace`.
_MAX_TRACE_SPANS = 5000

_INSERT_SQL = """
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
"""


def _to_naive_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if not dt:
        return None
    if dt.tzinfo:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _to_aware_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Re-attach UTC to a naive timestamp read back from the index."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc)


def _window_cutoff(window_hours: int) -> datetime:
    """Naive-UTC lower bound for a trailing window.

    Timestamps are stored naive UTC (see :func:`_to_naive_utc`), so the
    cutoff is computed in Python rather than with SQL ``CURRENT_TIMESTAMP``,
    which DuckDB evaluates in the session time zone and would skew the
    window by the local UTC offset.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        hours=window_hours
    )


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
            try:
                self._conn.executemany(_INSERT_SQL, data)
            except Exception:
                # A single malformed row (e.g. an unexpected attribute type)
                # would otherwise drop the whole batch. Fall back to per-row
                # inserts so good spans still land; the upsert keeps the retry
                # idempotent for any rows the batch had already written.
                logger.warning("duckdb_batch_insert_failed", count=len(data))
                self._insert_rows_individually(data)

    def _insert_rows_individually(self, rows: list) -> None:
        for row in rows:
            try:
                self._conn.execute(_INSERT_SQL, row)
            except Exception:
                logger.warning(
                    "duckdb_row_insert_skipped",
                    trace_id=row[0],
                    span_id=row[1],
                )

    def _read(self, query: str, params: tuple) -> list:
        """Run a read query on a dedicated cursor, off the writer lock.

        DuckDB cursors are duplicate connections to the same database and
        the documented way to use one database from multiple threads — the
        client API synchronizes cursor creation internally, and MVCC
        isolates readers from in-flight writes. Keeping reads off
        ``self._lock`` means a slow dashboard query can never stall ingest
        (``insert_spans`` holds the lock) and vice versa.
        """
        cursor = self._conn.cursor()
        try:
            return cursor.execute(query, params).fetchall()
        finally:
            cursor.close()

    def list_traces(self, *, skip: int = 0, limit: int = 50) -> tuple[list[dict], int]:
        # The agent columns prefer the root span and fall back to any span,
        # so partially-ingested traces (root not yet arrived) still get a name.
        query = """
            SELECT
                trace_id,
                MIN(start_time) AS trace_start,
                MAX(end_time) AS trace_end,
                SUM(duration_ms) AS total_duration_ms,
                SUM(run_cost) AS total_cost,
                COALESCE(
                    MAX(agent_name) FILTER (WHERE parent_span_id IS NULL),
                    MAX(agent_name)
                ) AS agent_name,
                COALESCE(
                    MAX(agent_version) FILTER (WHERE parent_span_id IS NULL),
                    MAX(agent_version)
                ) AS agent_version,
                COUNT(*) AS span_count
            FROM spans
            GROUP BY trace_id
            ORDER BY trace_start DESC NULLS LAST, trace_id
            LIMIT ? OFFSET ?
        """
        rows = self._read(query, (limit, skip))
        total = self._read("SELECT COUNT(DISTINCT trace_id) FROM spans", ())[0][0]

        summaries = [
            {
                "trace_id": row[0],
                "start_time": _to_aware_utc(row[1]),
                "end_time": _to_aware_utc(row[2]),
                "total_duration_ms": row[3],
                "total_cost": row[4],
                "agent_name": row[5],
                "agent_version": row[6],
                "span_count": row[7],
            }
            for row in rows
        ]
        return summaries, total

    def get_trace(
        self, trace_id: str, *, max_spans: int = _MAX_TRACE_SPANS
    ) -> tuple[list[SpanRecord], bool]:
        # LIMIT max_spans + 1 detects truncation without a second count
        # query; the extra row is dropped before returning.
        query = """
            SELECT
                trace_id, span_id, parent_span_id, name,
                start_time, end_time, duration_ms,
                agent_name, agent_version, policy_decision,
                run_cost, run_success, attributes
            FROM spans
            WHERE trace_id = ?
            ORDER BY start_time ASC NULLS LAST, span_id
            LIMIT ?
        """
        rows = self._read(query, (trace_id, max_spans + 1))
        truncated = len(rows) > max_spans
        spans = [
            SpanRecord(
                trace_id=row[0],
                span_id=row[1],
                parent_span_id=row[2],
                name=row[3],
                start_time=_to_aware_utc(row[4]),
                end_time=_to_aware_utc(row[5]),
                duration_ms=row[6],
                agent_name=row[7],
                agent_version=row[8],
                policy_decision=row[9],
                run_cost=row[10],
                run_success=row[11],
                attributes=self._decode_attributes(row[12], row[0], row[1]),
            )
            for row in rows[:max_spans]
        ]
        return spans, truncated

    @staticmethod
    def _decode_attributes(raw: Optional[str], trace_id: str, span_id: str) -> dict:
        """Decode the stored attributes JSON, degrading to ``{}`` on corruption.

        A single unreadable attributes blob must not turn the whole trace
        detail into a 500; the span still renders, just without attributes.
        DuckDB's JSON column already rejects malformed JSON at write time,
        so the realistic corruption is valid JSON that is not an object
        (hand-edited or written by a buggy tool).
        """
        if not raw:
            return {}
        try:
            decoded = json.loads(raw)
        except (ValueError, TypeError):
            decoded = None
        if not isinstance(decoded, dict):
            logger.warning(
                "duckdb_attributes_decode_failed",
                trace_id=trace_id,
                span_id=span_id,
            )
            return {}
        return decoded

    def get_metrics_cost(self, *, window_hours: int = 24) -> dict:
        # Cost sums over ALL spans, not just roots: run_cost is attached to
        # whichever span made the LLM call (usually a child), and enrichment
        # never duplicates one call's cost onto both a root and its child.
        # trace_count here means "traces with at least one span in window" —
        # a different denominator from the latency/success metrics, which
        # count root spans (see get_metrics_latency).
        query = """
            SELECT SUM(run_cost), COUNT(DISTINCT trace_id)
            FROM spans
            WHERE start_time >= ?
        """
        row = self._read(query, (_window_cutoff(window_hours),))[0]
        return {
            "window_hours": window_hours,
            "total_cost": row[0] if row[0] is not None else 0.0,
            "trace_count": row[1] or 0,
        }

    def get_metrics_latency(self, *, window_hours: int = 24) -> dict:
        # Root spans only: a trace's latency is its root span duration, and
        # summing or averaging child spans would double-count nested work.
        # quantile_cont keeps the p95 deterministic (approx_quantile is not).
        # trace_count is therefore "root spans in window", not the cost
        # metric's "traces with any span in window".
        query = """
            SELECT
                AVG(duration_ms),
                QUANTILE_CONT(duration_ms, 0.95),
                COUNT(*) FILTER (WHERE duration_ms IS NOT NULL)
            FROM spans
            WHERE start_time >= ? AND parent_span_id IS NULL
        """
        row = self._read(query, (_window_cutoff(window_hours),))[0]
        return {
            "window_hours": window_hours,
            "avg_latency_ms": row[0] if row[0] is not None else 0.0,
            "p95_latency_ms": row[1] if row[1] is not None else 0.0,
            "trace_count": row[2] or 0,
        }

    def get_metrics_success(self, *, window_hours: int = 24) -> dict:
        # Only root spans carry a meaningful run outcome; spans that never
        # reported run_success are excluded from the rate instead of being
        # counted as failures.
        query = """
            SELECT
                COUNT(*) FILTER (WHERE run_success IS NOT NULL),
                COUNT(*) FILTER (WHERE run_success = TRUE)
            FROM spans
            WHERE start_time >= ? AND parent_span_id IS NULL
        """
        row = self._read(query, (_window_cutoff(window_hours),))[0]
        total = row[0] or 0
        successful = row[1] or 0
        return {
            "window_hours": window_hours,
            "total_runs": total,
            "successful_runs": successful,
            "success_rate": (successful / total) if total else None,
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
