"""DuckDB implementation of :class:`TraceIndex`."""

from __future__ import annotations

import json
import math
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import duckdb
import structlog

from argox_collector import semconv
from argox_collector.index.base import (
    RunRecord,
    SpanRecord,
    TraceIndex,
    TraceIndexError,
)

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


_INSERT_RUN_SQL = """
    INSERT INTO runs (
        run_id, trace_id, agent_name, agent_version, timestamp,
        success, total_input_tokens, total_output_tokens,
        duration_seconds, cost_usd, blob_path, model, ingested_at, audited
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, FALSE)
    ON CONFLICT (run_id) DO NOTHING
"""

_RUN_COLUMNS = (
    "run_id, trace_id, agent_name, agent_version, timestamp, "
    "success, total_input_tokens, total_output_tokens, "
    "duration_seconds, cost_usd, blob_path, model"
)

# Pull the model id from a trace's spans for the run-cost fallback (COL-17).
# The attribute keys contain dots, so each is a double-quoted JSON path
# component rather than a nested lookup. Request model wins over response.
#
# Limitation: MAX() picks the lexicographically largest model, not "the" model.
# For a single-model run (the common case) that is the only model, so it is
# correct. For a genuinely multi-model run there is no single right answer here
# — pricing the run's token totals at one model's rate is approximate; exact
# per-call cost would need per-span pricing summed over the trace (see ADR-0008).



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


def _json_safe(value: Any) -> Any:
    """Coerce ``value`` into something the JSON column will accept.

    Two failure modes exist at write time: non-finite floats (NaN/Infinity),
    which ``json.dumps`` happily emits but DuckDB's JSON parser rejects, and
    objects that are not JSON-serialisable at all. Both are degraded to their
    string form so the rest of the attributes survive.
    """
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)


def _finite_or_none(value: Optional[float]) -> Optional[float]:
    """Keep NaN/Infinity out of the DOUBLE columns.

    A non-finite ``run_cost`` or ``duration_ms`` would poison every
    aggregate it enters (``SUM``/``AVG``/``QUANTILE_CONT`` all propagate
    NaN), and NaN is not representable in the JSON metrics responses.
    """
    if value is None:
        return None
    return value if math.isfinite(value) else None


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

            # Run summaries (COL-11). The full record lives in the blob store;
            # this table holds the flat, queryable projection. cost_usd is
            # nullable and backfilled from model + token totals (COL-17).
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    run_id VARCHAR PRIMARY KEY,
                    trace_id VARCHAR,
                    agent_name VARCHAR,
                    agent_version VARCHAR,
                    timestamp VARCHAR,
                    success BOOLEAN,
                    total_input_tokens BIGINT,
                    total_output_tokens BIGINT,
                    duration_seconds DOUBLE,
                    cost_usd DOUBLE,
                    blob_path VARCHAR,
                    model VARCHAR,
                    ingested_at TIMESTAMP,
                    audited BOOLEAN
                )
            """)
            # Add the model column to runs tables created before COL-17 so the
            # cost backfill can read it on an upgraded database.
            self._conn.execute("ALTER TABLE runs ADD COLUMN IF NOT EXISTS model VARCHAR")
            # Track whether a run has entered the WORM chain (COL-14). Tri-state
            # on purpose: ``insert_run`` writes FALSE for every COL-14-era run
            # (awaiting/failed chaining), TRUE once chained. The column is added
            # WITHOUT a default, so pre-COL-14 rows stay NULL — "out of scope,
            # never attempted" — and the reconcile sweep (``audited = FALSE``)
            # skips them, honouring the no-retroactive-backfill non-goal.
            self._conn.execute(
                "ALTER TABLE runs ADD COLUMN IF NOT EXISTS audited BOOLEAN"
            )
            # Likewise add ingested_at for runs tables created before it was
            # promoted, so the COL-13 list index and ordering bind on an
            # upgraded database.
            self._conn.execute("ALTER TABLE runs ADD COLUMN IF NOT EXISTS ingested_at TIMESTAMP")
            # trace_id is indexed so the Query API can join from a span back
            # to its run record (COL-13).
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_trace_id ON runs (trace_id)")
            # The run list sorts/paginates on ingest time, so that column is
            # indexed to keep the list query within the P95 SLO on large
            # datasets (COL-13). agent_name is deliberately not indexed: it is
            # low-cardinality (few agents), so a secondary index buys little on
            # read while adding write and startup cost.
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_ingested_at ON runs (ingested_at)")

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
                _finite_or_none(r.duration_ms),
                r.agent_name,
                r.agent_version,
                r.policy_decision,
                _finite_or_none(r.run_cost),
                r.run_success,
                self._encode_attributes(r),
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

    @staticmethod
    def _encode_attributes(record: SpanRecord) -> Optional[str]:
        """Serialise attributes for the JSON column, degrading instead of raising.

        This runs during batch preparation, before any row is written: an
        exception here would drop the whole batch without ever reaching the
        per-row fallback. ``allow_nan=False`` matters because ``json.dumps``
        otherwise emits ``NaN``/``Infinity`` literals that DuckDB's JSON
        parser rejects at insert time, silently discarding the row.
        """
        if not record.attributes:
            return None
        try:
            return json.dumps(record.attributes, allow_nan=False)
        except (TypeError, ValueError):
            pass
        try:
            return json.dumps(_json_safe(dict(record.attributes)), allow_nan=False)
        except (TypeError, ValueError):
            logger.warning(
                "duckdb_attributes_encode_failed",
                trace_id=record.trace_id,
                span_id=record.span_id,
            )
            return None

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

    def list_traces(
        self,
        *,
        skip: int = 0,
        limit: int = 50,
        trace_id: Optional[str] = None,
        agent_name: Optional[str] = None,
        status: Optional[str] = None,
        decision: Optional[str] = None,
        sort: Optional[str] = None,
        window_hours: Optional[int] = None,
    ) -> tuple[list[dict], int]:
        # Pre-filter by trace_id and window_hours on the raw spans table if possible to speed up aggregation.
        spans_where_parts = []
        base_params = []
        if trace_id:
            spans_where_parts.append(r"trace_id LIKE ? ESCAPE '\'")
            base_params.append(f"{self._escape_like_wildcards(trace_id)}%")
        if window_hours is not None:
            spans_where_parts.append("start_time >= ?")
            base_params.append(_window_cutoff(window_hours))

        spans_where = ""
        if spans_where_parts:
            spans_where = " WHERE " + " AND ".join(spans_where_parts)

        # Base query to aggregate traces.
        base_query = f"""
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
                COUNT(*) AS span_count,
                CASE 
                    WHEN COUNT(*) FILTER (WHERE run_success = FALSE) > 0 THEN 'error'
                    ELSE 'ok'
                END AS status,
                COALESCE(
                    MAX(policy_decision) FILTER (WHERE policy_decision = 'block'),
                    MAX(policy_decision) FILTER (WHERE policy_decision = 'warn'),
                    'allow'
                ) AS decision
            FROM spans
            {spans_where}
            GROUP BY trace_id
        """

        # Construct the filters clause dynamically once (Finding 5)
        filters = []
        filter_params = []
        if agent_name:
            filters.append("agent_name = ?")
            filter_params.append(agent_name)
        if status:
            filters.append("status = ?")
            filter_params.append(status)
        if decision:
            filters.append("decision = ?")
            filter_params.append(decision)

        filter_clause = ""
        if filters:
            filter_clause = " AND " + " AND ".join(filters)

        # Wrap in a subquery to allow filtering on aggregated columns.
        # We use COUNT(*) OVER () AS _total_count to calculate the total matching count
        # in a single query execution pass, avoiding double aggregation.
        query = f"SELECT *, COUNT(*) OVER () AS _total_count FROM ({base_query}) AS t WHERE 1=1{filter_clause}"
        params = base_params + filter_params

        # Sorting
        # Keep this mapping synchronized with the route validation in the collector api.
        # Router uses: pattern="^(start_time|duration|cost|spans):(asc|desc)$"
        sort_map = {
            "start_time": "trace_start",
            "duration": "total_duration_ms",
            "cost": "total_cost",
            "spans": "span_count",
        }
        
        if sort:
            if ":" in sort:
                parts = sort.split(":", 1)
                field, direction = parts[0], parts[1]
            else:
                field, direction = "start_time", "desc"
            sql_field = sort_map.get(field, "trace_start")
            sql_dir = "ASC" if direction.lower() == "asc" else "DESC"
            query += f" ORDER BY {sql_field} {sql_dir} NULLS LAST, trace_id"
        else:
            query += " ORDER BY trace_start DESC NULLS LAST, trace_id"

        query += " LIMIT ? OFFSET ?"
        
        rows = self._read(query, tuple(params + [limit, skip]))
        
        # If rows are returned, we extract total from the window column in the first row.
        # If no rows are returned and skip > 0, we fallback to a lightweight count query
        # to find the total count past the offset.
        if rows:
            total = rows[0][-1]
        else:
            if skip == 0:
                total = 0
            else:
                count_query = f"SELECT COUNT(*) FROM ({base_query}) AS t WHERE 1=1{filter_clause}"
                count_params = base_params + filter_params
                total = self._read(count_query, tuple(count_params))[0][0]

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
                "status": row[8],
                "decision": row[9],
            }
            for row in rows
        ]
        return summaries, total

    def get_trace(
        self, trace_id: str, *, max_spans: int = _MAX_TRACE_SPANS
    ) -> tuple[list[SpanRecord], bool, Optional[float]]:
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

        duration_ms = None
        if spans:
            if truncated:
                # Compute total duration over all spans of the trace (since it's truncated)
                bound_row = self._read(
                    "SELECT MIN(start_time), MAX(end_time) FROM spans WHERE trace_id = ?",
                    (trace_id,),
                )
                if bound_row and bound_row[0][0] is not None and bound_row[0][1] is not None:
                    start_dt = bound_row[0][0]
                    end_dt = bound_row[0][1]
                    duration_ms = (end_dt - start_dt).total_seconds() * 1000.0
            else:
                # Compute duration over the fetched rows
                valid_starts = [row[4] for row in rows if row[4] is not None]
                valid_ends = [row[5] for row in rows if row[5] is not None]
                if valid_starts and valid_ends:
                    start_dt = min(valid_starts)
                    end_dt = max(valid_ends)
                    duration_ms = (end_dt - start_dt).total_seconds() * 1000.0

        return spans, truncated, duration_ms

    @staticmethod
    def _escape_like_wildcards(s: str) -> str:
        """Escape SQL LIKE wildcards '%' and '_' and the escape char '\\'."""
        return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

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
        # Cost is aggregated from the spans table to capture all traces
        cutoff = _window_cutoff(window_hours)
        query = """
            SELECT
                SUM(run_cost) FILTER (WHERE isfinite(run_cost)),
                COUNT(DISTINCT trace_id)
            FROM spans
            WHERE start_time >= ?
        """
        row = self._read(query, (cutoff,))[0]

        # Stacked cost over time by model: aggregated from spans and joined with runs for model name fallbacks
        bucket_unit = "hour" if window_hours <= 72 else "day"
        query_timeline = """
            SELECT
                date_trunc(?, s.start_time) AS bucket,
                COALESCE(
                    r.model,
                    json_extract_string(s.attributes, ?),
                    json_extract_string(s.attributes, ?),
                    json_extract_string(s.attributes, '$.model'),
                    'unknown'
                ) AS model,
                SUM(s.run_cost) FILTER (WHERE isfinite(s.run_cost)) AS cost
            FROM spans s
            LEFT JOIN (
                SELECT DISTINCT ON (trace_id) trace_id, model
                FROM runs
                WHERE trace_id IS NOT NULL
                ORDER BY trace_id, ingested_at DESC, run_id DESC
            ) r ON s.trace_id = r.trace_id
            WHERE s.start_time >= ?
            GROUP BY 1, 2
            ORDER BY 1 ASC, 2 ASC
        """
        rows_timeline = self._read(
            query_timeline,
            (
                bucket_unit,
                f'$.\"{semconv.GEN_AI_REQUEST_MODEL}\"',
                f'$.\"{semconv.GEN_AI_RESPONSE_MODEL}\"',
                cutoff,
            ),
        )
        timeline = []
        for r in rows_timeline:
            timeline.append({
                "bucket": r[0],
                "model": r[1],
                "cost": r[2] if r[2] is not None else 0.0,
            })

        # Top agents by spend: aggregated from spans table
        query_agents = """
            SELECT
                COALESCE(agent_name, 'unknown') AS agent_name,
                SUM(run_cost) FILTER (WHERE isfinite(run_cost)) AS spend
            FROM spans
            WHERE start_time >= ?
            GROUP BY 1
            ORDER BY 2 DESC
            LIMIT 10
        """
        rows_agents = self._read(query_agents, (cutoff,))
        top_agents = []
        for r in rows_agents:
            top_agents.append({
                "agent_name": r[0],
                "spend": r[1] if r[1] is not None else 0.0,
            })

        return {
            "window_hours": window_hours,
            "total_cost": row[0] if row[0] is not None else 0.0,
            "trace_count": row[1] or 0,
            "timeline": timeline,
            "top_agents": top_agents,
        }

    def get_metrics_latency(self, *, window_hours: int = 24) -> dict:
        cutoff = _window_cutoff(window_hours)
        query = """
            WITH stats AS (
                SELECT
                    MIN(duration_ms) FILTER (WHERE isfinite(duration_ms)) AS min_val,
                    MAX(duration_ms) FILTER (WHERE isfinite(duration_ms)) AS max_val,
                    AVG(duration_ms) FILTER (WHERE isfinite(duration_ms)) AS avg_val,
                    QUANTILE_CONT(duration_ms, 0.50) FILTER (WHERE isfinite(duration_ms)) AS p50_val,
                    QUANTILE_CONT(duration_ms, 0.95) FILTER (WHERE isfinite(duration_ms)) AS p95_val,
                    QUANTILE_CONT(duration_ms, 0.99) FILTER (WHERE isfinite(duration_ms)) AS p99_val,
                    COUNT(*) FILTER (WHERE isfinite(duration_ms)) AS trace_count
                FROM spans
                WHERE start_time >= ? AND parent_span_id IS NULL
            ),
            bins AS (
                SELECT
                    CAST(
                        CASE
                            WHEN stats.max_val = stats.min_val THEN 0
                            ELSE LEAST(14, FLOOR(15 * (duration_ms - stats.min_val) / (stats.max_val - stats.min_val)))
                        END AS INTEGER
                    ) AS bin_idx,
                    COUNT(*) AS bin_count
                FROM spans, stats
                WHERE start_time >= ? AND parent_span_id IS NULL AND isfinite(duration_ms)
                GROUP BY 1
            )
            SELECT
                stats.min_val,
                stats.max_val,
                stats.avg_val,
                stats.p50_val,
                stats.p95_val,
                stats.p99_val,
                stats.trace_count,
                bins.bin_idx,
                bins.bin_count
            FROM stats
            LEFT JOIN bins ON TRUE
            ORDER BY bins.bin_idx
        """
        rows = self._read(query, (cutoff, cutoff))

        if not rows or rows[0][6] == 0:
            return {
                "window_hours": window_hours,
                "avg_latency_ms": 0.0,
                "p95_latency_ms": 0.0,
                "trace_count": 0,
                "percentiles": {"p50": 0.0, "p95": 0.0, "p99": 0.0},
                "histogram": [],
            }

        first = rows[0]
        min_val = first[0]
        max_val = first[1]
        avg_val = first[2] or 0.0
        p50_val = first[3] or 0.0
        p95_val = first[4] or 0.0
        p99_val = first[5] or 0.0
        trace_count = first[6] or 0

        bin_counts = {}
        for r in rows:
            if r[7] is not None:
                bin_counts[r[7]] = r[8] or 0

        percentiles = {
            "p50": p50_val,
            "p95": p95_val,
            "p99": p99_val,
        }

        histogram = []
        if max_val == min_val or max_val - min_val < 1e-5:
            histogram = [{
                "bin_min": min_val,
                "bin_max": max_val + 1000.0,
                "count": trace_count,
            }]
        else:
            N = 15
            w = (max_val - min_val) / N
            for i in range(N):
                histogram.append({
                    "bin_min": min_val + i * w,
                    "bin_max": min_val + (i + 1) * w,
                    "count": bin_counts.get(i, 0),
                })

        return {
            "window_hours": window_hours,
            "avg_latency_ms": avg_val,
            "p95_latency_ms": p95_val,
            "trace_count": trace_count,
            "percentiles": percentiles,
            "histogram": histogram,
        }

    def get_metrics_success(self, *, window_hours: int = 24) -> dict:
        cutoff = _window_cutoff(window_hours)
        query = """
            SELECT
                COUNT(*) FILTER (WHERE run_success IS NOT NULL),
                COUNT(*) FILTER (WHERE run_success = TRUE)
            FROM spans
            WHERE start_time >= ? AND parent_span_id IS NULL
        """
        row = self._read(query, (cutoff,))[0]
        total = row[0] or 0
        successful = row[1] or 0

        # Success ratio over time timeline: aggregated by bucket from spans
        bucket_unit = "hour" if window_hours <= 72 else "day"
        query_timeline = """
            SELECT
                date_trunc(?, start_time) AS bucket,
                COUNT(*) FILTER (WHERE run_success IS NOT NULL) AS total_runs,
                COUNT(*) FILTER (WHERE run_success = TRUE) AS successful_runs
            FROM spans
            WHERE start_time >= ? AND parent_span_id IS NULL
            GROUP BY 1
            ORDER BY 1 ASC
        """
        rows_timeline = self._read(query_timeline, (bucket_unit, cutoff))
        timeline = []
        for r in rows_timeline:
            t = r[1] or 0
            s = r[2] or 0
            timeline.append({
                "bucket": r[0],
                "total_runs": t,
                "successful_runs": s,
                "success_rate": (s / t) if t > 0 else None,
            })

        # Top blocked tools: policy_decision = 'block'
        query_blocked = """
            SELECT
                name AS tool_name,
                COUNT(*) AS blocked_count
            FROM spans
            WHERE start_time >= ? AND policy_decision = 'block'
            GROUP BY 1
            ORDER BY 2 DESC
            LIMIT 10
        """
        rows_blocked = self._read(query_blocked, (cutoff,))
        top_blocked_tools = []
        for r in rows_blocked:
            top_blocked_tools.append({
                "tool_name": r[0],
                "blocked_count": r[1],
            })

        return {
            "window_hours": window_hours,
            "total_runs": total,
            "successful_runs": successful,
            "success_rate": (successful / total) if total else None,
            "timeline": timeline,
            "top_blocked_tools": top_blocked_tools,
        }

    def insert_run(self, record: RunRecord) -> None:
        row = (
            record.run_id,
            record.trace_id,
            record.agent_name,
            record.agent_version,
            record.timestamp,
            record.success,
            int(record.total_input_tokens or 0),
            int(record.total_output_tokens or 0),
            _finite_or_none(record.duration_seconds),
            _finite_or_none(record.cost_usd),
            record.blob_path,
            record.model,
            datetime.now(timezone.utc).replace(tzinfo=None),
        )
        with self._lock:
            self._conn.execute(_INSERT_RUN_SQL, row)

    def set_run_cost(self, run_id: str, cost_usd: Optional[float]) -> None:
        # A standalone UPDATE, not part of insert_run's first-write-wins
        # INSERT: cost is collector-derived, so backfilling it must not touch
        # the immutable client-reported columns. _finite_or_none keeps a
        # NaN/Infinity out of the DOUBLE column and its aggregates.
        with self._lock:
            self._conn.execute(
                "UPDATE runs SET cost_usd = ? WHERE run_id = ?",
                (_finite_or_none(cost_usd), run_id),
            )

    def is_run_audited(self, run_id: str) -> bool:
        rows = self._read("SELECT audited FROM runs WHERE run_id = ?", (run_id,))
        if not rows:
            return False
        # Tri-state: only an explicit FALSE means "COL-14 run still to chain".
        # TRUE (already chained) and NULL (pre-COL-14, out of scope) both report
        # audited so neither the re-ingest retry nor the sweep touches them.
        return rows[0][0] is not False

    def list_unaudited_runs(self, *, limit: int) -> list[RunRecord]:
        rows = self._read(
            f"SELECT {_RUN_COLUMNS} FROM runs WHERE audited = FALSE "
            "ORDER BY ingested_at NULLS FIRST, run_id LIMIT ?",
            (limit,),
        )
        return [self._row_to_run(row) for row in rows]

    def mark_run_audited(self, run_id: str) -> None:
        # Standalone UPDATE like set_run_cost: ``audited`` is a collector-side
        # bookkeeping flag, not client content, so it never touches the
        # first-write-wins immutable columns. Marking an unknown run is a no-op.
        with self._lock:
            self._conn.execute(
                "UPDATE runs SET audited = TRUE WHERE run_id = ?", (run_id,)
            )

    def get_run_model_from_trace(self, trace_id: str) -> Optional[str]:
        query = """
            SELECT COALESCE(
                MAX(json_extract_string(attributes, ?)),
                MAX(json_extract_string(attributes, ?))
            ) FROM spans WHERE trace_id = ?
        """
        rows = self._read(
            query,
            (
                f'$.\"{semconv.GEN_AI_REQUEST_MODEL}\"',
                f'$.\"{semconv.GEN_AI_RESPONSE_MODEL}\"',
                trace_id,
            ),
        )
        return rows[0][0] if rows and rows[0][0] else None

    def list_runs(
        self,
        *,
        skip: int = 0,
        limit: int = 50,
        agent_name: Optional[str] = None,
        success: Optional[bool] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> tuple[list[RunRecord], int]:
        # Build the WHERE clause from the supplied filters only, so an absent
        # filter neither narrows the result nor changes the query plan.
        clauses: list[str] = []
        params: list[Any] = []
        if agent_name is not None:
            clauses.append("agent_name = ?")
            params.append(agent_name)
        if success is not None:
            clauses.append("success = ?")
            params.append(success)
        if start is not None:
            clauses.append("ingested_at >= ?")
            params.append(_to_naive_utc(start))
        if end is not None:
            # Half-open interval: the upper bound is exclusive so adjacent
            # windows do not double-count a run on the boundary.
            clauses.append("ingested_at < ?")
            params.append(_to_naive_utc(end))
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""

        rows = self._read(
            f"SELECT {_RUN_COLUMNS} FROM runs{where} "
            "ORDER BY ingested_at DESC NULLS LAST, run_id LIMIT ? OFFSET ?",
            (*params, limit, skip),
        )
        total = self._read(
            f"SELECT COUNT(*) FROM runs{where}", tuple(params)
        )[0][0]
        return [self._row_to_run(row) for row in rows], total

    def get_run(self, run_id: str) -> Optional[RunRecord]:
        rows = self._read(
            f"SELECT {_RUN_COLUMNS} FROM runs WHERE run_id = ?", (run_id,)
        )
        return self._row_to_run(rows[0]) if rows else None

    def get_run_by_trace_id(self, trace_id: str) -> Optional[RunRecord]:
        # Order by the collector-assigned ingest time, not the client-supplied
        # ``timestamp`` (a free-form VARCHAR whose lexicographic order need not
        # match chronology), so a re-used trace_id resolves to the run ingested
        # most recently.
        rows = self._read(
            f"SELECT {_RUN_COLUMNS} FROM runs WHERE trace_id = ? "
            "ORDER BY ingested_at DESC NULLS LAST LIMIT 1",
            (trace_id,),
        )
        return self._row_to_run(rows[0]) if rows else None

    @staticmethod
    def _row_to_run(row: tuple) -> RunRecord:
        return RunRecord(
            run_id=row[0],
            trace_id=row[1],
            agent_name=row[2],
            agent_version=row[3],
            timestamp=row[4],
            success=row[5],
            total_input_tokens=row[6] or 0,
            total_output_tokens=row[7] or 0,
            duration_seconds=row[8],
            cost_usd=row[9],
            blob_path=row[10],
            model=row[11],
        )

    def health_check(self) -> None:
        try:
            with self._lock:
                self._conn.execute("SELECT 1").fetchone()
        except Exception as exc:
            # The raw exception text can embed the database filesystem path,
            # and readyz forwards this message verbatim to unauthenticated
            # callers. Log the detail, surface a generic message.
            logger.error("duckdb_health_check_failed", error=str(exc))
            raise TraceIndexError("DuckDB index health check failed") from exc

    def close(self) -> None:
        """Close the DuckDB connection."""
        with self._lock:
            self._conn.close()
