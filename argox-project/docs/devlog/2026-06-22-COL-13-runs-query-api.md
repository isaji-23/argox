# [COL-13] Query API extension for run records

- **Date:** 2026-06-22
- **PR:** #157  ·  **Branch:** feat/COL-13-runs-query-api
- **Status:** in-review

## What changed
- Added three read-only endpoints to `routers/query.py`:
  - `GET /api/v1/runs` — paginated, newest-first run list with `agent`, `from`,
    `to`, `success`, `page`, `page_size` filters. Rows are lightweight
    (`RunSummary`): no `prompt` / `final_output` payload, no internal
    `blob_path`.
  - `GET /api/v1/runs/{run_id}` — full run record, returned byte-for-byte from
    the immutable blob written at ingest (COL-11), with the DuckDB index row as
    a fallback when the blob is missing/unreadable. 404 when the run is unknown.
  - `GET /api/v1/runs/by-trace/{trace_id}` — span-to-run join via
    `get_run_by_trace_id`; 404 when no run was exported for the trace.
- Added `TraceIndex.list_runs(skip, limit, agent_name, success, start, end)`
  (abstract in `index/base.py`, implemented in `index/duckdb.py`) returning a
  `(runs, total)` tuple with a dynamically built WHERE clause.
- New DuckDB indexes `idx_runs_ingested_at` and `idx_runs_agent_name`; plus an
  `ALTER TABLE runs ADD COLUMN IF NOT EXISTS ingested_at TIMESTAMP` so the list
  query binds on databases created before `ingested_at` was promoted.
- Regenerated the committed `openapi.json` for the new operations.
- New `tests/test_runs_query_api.py` (index + HTTP layers).

## Why
- Route B (COL-11 + EXP-09) persists run-shaped records carrying prompt, final
  output, per-tool detail, per-call tokens and policy violations. COL-06 (#51)
  only exposed traces and aggregate metrics; this adds the read surface for runs
  so the dashboard can render content. Unblocks DASH-05 and feeds the generated
  TS client pipeline (#95).
- Sorting and the `from`/`to` window bind on the collector-assigned
  `ingested_at` (a real `TIMESTAMP`), not the free-form client `timestamp`,
  which is not guaranteed chronological. The window is half-open `[from, to)` so
  adjacent windows do not double-count a boundary run.
- The detail endpoints return blob bytes verbatim to satisfy the byte-equivalent
  contract; the index-row fallback keeps an indexed run resolvable even when its
  blob is unavailable, rather than masking it as a 404.

## Notes / follow-ups
- No full-text search across `prompt` / `final_output` in v1 (deferred until
  DuckDB FTS vs. an external index is decided), per the issue non-goals.
- P95 < 300ms SLO on a 1M-run list is addressed structurally via the new
  indexes; no load test was run in this change.
