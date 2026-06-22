# [DASH-03] Metrics dashboard

- **Date:** 2026-06-22
- **PR:** #90  ·  **Branch:** feat/DASH-03-metrics-dashboard
- **Status:** in-review

## What changed
- Unified cost metrics: changed both the KPI summary and timeline/leaderboard charts to query the `runs` table and filter by `runs.ingested_at`, ensuring complete data consistency.
- Optimized binned latency aggregation: refactored `get_metrics_latency` into a single, atomic CTE query returning min, max, average, percentiles, and binned counts in a single read.
- Corrected blocked tool docs: updated `get_metrics_success` interface documentation to clarify that blocked tool metrics are counted over all child spans (not root runs).
- Enhanced success rate visual fidelity: mapped empty buckets to `null` and used `connectNulls` in the AreaChart to prevent artificial drops to 0%.
- Aligned KPI representation: changed empty window latency cards to show `"N/A"` instead of `"0ms"`.
- Expanded test coverage: added mock runs to tests and verified wide-window (`168h` / 7-day) paths to cover day-trunc bucket logic.
- Exported the updated FastAPI OpenAPI contract schema to `openapi.json` and regenerated TypeScript API client types in the dashboard.
- Implemented the `MetricsScreen` component using `recharts` to render the five responsive dashboard charts integrated with the global time-range selector.
- Wired the screen into the active route handler in `App.tsx`.

## Why
Ensures consistency across all cost metrics, prevents visual artifacts on charts during idle periods, eliminates race conditions on latency distribution calculations, and matches API documentation with code behavior.

## Notes / follow-ups
None.
