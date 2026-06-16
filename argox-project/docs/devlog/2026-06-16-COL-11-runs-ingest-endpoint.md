# [COL-11] /v1/runs ingest endpoint and run-record storage

- **Date:** 2026-06-16
- **PR:** #141  ·  **Branch:** feat/COL-11-runs-ingest-endpoint
- **Status:** in-review

## What changed
- New endpoint `POST /v1/runs` (`argox-collector/src/argox_collector/routers/runs.py`):
  accepts one record or a batch of `AgentRunMetrics`-shaped JSON (schema mirrors
  `AgentRunMetrics.to_dict()`). Validates synchronously via Pydantic, returns
  `202 Accepted`, and delegates the blob write + index insert to
  `BackgroundTasks`. `X-Argox-Durable: true` runs persistence in the threadpool
  and returns `200 OK` only once committed — same acknowledgement contract as
  `/v1/traces` (ADR-0002).
- Storage layout: full record stored as an immutable blob at
  `runs/{YYYY-MM-DD}/{run_id}.json`. A single-record submission is stored
  byte-for-byte; a batch re-serialises each element to its own blob.
- New DuckDB `runs` table (`index/duckdb.py`): `run_id` PK, `trace_id`,
  `agent_name`, `agent_version`, `timestamp`, `success`, `total_input_tokens`,
  `total_output_tokens`, `duration_seconds`, `cost_usd` (nullable), `blob_path`.
  `trace_id` is indexed (`idx_runs_trace_id`). Upsert on `run_id` keeps
  re-ingest idempotent.
- New `RunRecord` dataclass and three `TraceIndex` methods (`insert_run`,
  `get_run`, `get_run_by_trace_id`); the last is the span→run join.
- Router registered in `app.py`; `openapi.json` and the dashboard TS client
  (`schema.ts`) regenerated for the new operation.

## Why
- Spans intentionally omit content (prompt, final output, per-call tokens, tool
  records, full policy violations), leaving the dashboard, WORM audit log and
  enrichment worker with no persisted inputs/outputs. A parallel run-summary
  path (Route B) closes the gap while keeping traces lightweight and allowing
  distinct retention for content vs. operational telemetry. See ADR-0007.
- `cost_usd` is left `None` at ingest and backfilled later by the enrichment
  worker (#92); `trace_id` is indexed so the follow-up Query API (COL-13) can
  join a span back to its run record.

## Notes / follow-ups
- No content scrubbing here — PII redaction stays in the SDK (#102).
- No durable-write guarantees beyond the opt-in header; auth gated by #94.
- Unblocks the matching SDK exporter (EXP-09), the run-record Query API
  (COL-13) and the audit-log extension (COL-14).
