# [COL-06] Query API for traces and metrics

- **Date:** 2026-06-10
- **PR:** #127  ·  **Branch:** feat/COL-06-query-api
- **Status:** in-review

## What changed

- `TraceIndex` (`argox-collector/src/argox_collector/index/base.py`) gained
  five abstract read methods: `list_traces` (paginated summaries plus total
  trace count), `get_trace` (all spans of a trace, ordered by start time),
  and `get_metrics_cost` / `get_metrics_latency` / `get_metrics_success`
  (trailing-window aggregations).
- `DuckDBTraceIndex` (`index/duckdb.py`) implements them:
  - Trace summaries aggregate per `trace_id` (start/end, summed cost and
    duration, span count) sorted newest first; the agent name/version prefer
    the root span via `FILTER (WHERE parent_span_id IS NULL)` with a fallback
    to any span, so partially-ingested traces still get a name.
  - Window cutoffs are computed in Python as naive UTC (`_window_cutoff`)
    because stored timestamps are naive UTC while DuckDB's
    `CURRENT_TIMESTAMP` is session-time-zone-aware — filtering with it would
    skew the window by the local UTC offset.
  - P95 latency uses `QUANTILE_CONT` (deterministic) rather than
    `approx_quantile`. Latency and success aggregate **root spans only**:
    a trace's latency is its root span duration, and averaging child spans
    would double-count nested work.
  - Naive timestamps read back from DuckDB are re-attached to UTC
    (`_to_aware_utc`) so the API serializes explicit-offset ISO-8601.
- New router `routers/query.py`, wired into `app.py`, with Pydantic response
  models:
  - `GET /api/v1/traces` — paginated summaries (`skip` ≥ 0, `limit` 1..1000),
    response includes `total` like the policies list.
  - `GET /api/v1/traces/{trace_id}` — full span waterfall; unknown id → **404**.
  - `GET /api/v1/metrics/cost|latency|success` — `window_hours` 1..720
    (default 24). `success_rate` is `null` when no runs reported an outcome,
    so an idle deployment is distinguishable from a failing one; spans that
    never set `run_success` are excluded from the rate, not counted as
    failures.
  - Handlers are sync `def` so FastAPI runs the blocking DuckDB queries in
    its threadpool, mirroring readyz and the policy handlers.
- Root `.gitignore` now ignores `var/` so local runtime data (DuckDB index,
  blob storage) can never be committed.
- Tests: `tests/test_query_api.py` (27 tests) covering both the index layer
  (aggregation, pagination, root-span preference, window filtering, empty
  index) and the HTTP layer (payloads, 404, parameter validation).

## Why

Issue #51: the dashboard needs read-only endpoints for paginated trace
lists, trace detail views and aggregated cost/latency metrics. This
supersedes PR #117, which was conflicting with `dev` and carried defects
this implementation avoids: the `CURRENT_TIMESTAMP` time-zone skew in window
filtering, non-deterministic `approx_quantile` p95, committed binary
`index.duckdb` files, `MAX(agent_name)` picking an arbitrary span's agent,
latency averaged over all spans, and list responses without a `total` count.

## Notes / follow-ups

- `list_traces` runs a full `GROUP BY` over the spans table per request; if
  the dashboard list becomes hot at large span counts, consider a
  materialized trace-summary table maintained at ingest time.
- No filtering beyond pagination (e.g. by agent, time range or status) on
  `GET /traces` yet; add query parameters when the dashboard needs them.
- Auth remains out of scope until COL-09 (#94); the query API is
  unauthenticated.
