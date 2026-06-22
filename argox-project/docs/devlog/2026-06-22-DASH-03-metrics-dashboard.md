# [DASH-03] Metrics dashboard

- **Date:** 2026-06-22
- **PR:** #90  ·  **Branch:** feat/DASH-03-metrics-dashboard
- **Status:** in-review

## What changed
- Added five chart datasets to the Metrics index and API endpoints:
  - Extended `/api/v1/metrics/cost` with a stacked cost-by-model timeline and agent spend leaderboard aggregated from the `runs` DuckDB table.
  - Extended `/api/v1/metrics/latency` with P50/P95/P99 latency percentiles and dynamic linear duration histograms aggregated from the root spans of the `spans` DuckDB table.
  - Extended `/api/v1/metrics/success` with a success-rate timeline and top policy blocked tools aggregated from the root spans of the `spans` DuckDB table.
- Extended the base `TraceIndex` interface and implemented the DuckDB aggregations in `duckdb.py`.
- Updated the Query API router responses and Pydantic schemas in `query.py`.
- Added unit tests in `test_query_api.py` targeting empty-index bounds and full-database metrics queries.
- Exported the updated FastAPI OpenAPI contract schema to `openapi.json` and regenerated TypeScript API client types in the dashboard.
- Implemented the `MetricsScreen` component using `recharts` to render the five responsive dashboard charts integrated with the global time-range selector.
- Wired the screen into the active route handler in `App.tsx`.

## Why
Provides the dashboard landing screen with high-fidelity, real-time metrics dashboards covering cost, latency distribution, and policy block rates.

## Notes / follow-ups
None.
