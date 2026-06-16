# ADR-0007: Run-summary ingest as a parallel path, separate from spans

- **Status:** accepted
- **Date:** 2026-06-16
- **Ticket:** COL-11

## Context

Spans ingested via `/v1/traces` carry token totals, policy decisions, blocked
tools and processor events, but intentionally NOT the prompt, the final output,
per-LLM-call token breakdowns, per-tool call records, or full policy violation
reasons. That content lives only in `AgentRunMetrics` on the SDK side and never
reached the Collector. As a result the dashboard could not render content, the
WORM audit log could not evidence inputs/outputs, the enrichment worker had no
per-call data to attribute cost against, and the AI Act mapping could not back
its claims with persisted data.

Two options existed. **Route A**: promote content onto the span itself
(`gen_ai.prompt` / `gen_ai.completion`). **Route B**: a separate run-summary
ingest path with its own storage layout.

## Decision

Adopt **Route B**. A parallel endpoint `POST /v1/runs` accepts one or a batch
of `AgentRunMetrics`-shaped JSON records (schema mirrors
`AgentRunMetrics.to_dict()`). It reuses the `/v1/traces` acknowledgement
contract (ADR-0002): validate synchronously, return `202`, persist in a
`BackgroundTasks` job; `X-Argox-Durable: true` makes persistence synchronous and
returns `200` only once committed.

Storage is deliberately distinct from spans:

- Full record as an immutable blob at `runs/{YYYY-MM-DD}/{run_id}.json`.
- A flat projection in a DuckDB `runs` table keyed by `run_id`, with an indexed
  `trace_id` column so a span can be joined back to its run record
  (`get_run_by_trace_id`). `cost_usd` is nullable, backfilled by the enrichment
  worker.

Route A was rejected to keep traces lightweight, allow distinct retention for
content vs. operational telemetry, and avoid span-attribute size pressure.

## Triggers for the next refactor

- If a consumer needs content inline with a span at query time and the
  span→run join proves too slow, revisit promoting a content pointer onto the
  span.
- If run records grow beyond a single-blob-per-run model (e.g. streaming or
  partial runs), revisit the blob layout.
- If batch submissions need per-record byte-for-byte fidelity, revisit the
  current batch behaviour (single records are stored verbatim; batch elements
  are re-serialised).

## What stays out of scope

- Content scrubbing — PII redaction stays in the SDK (`PiiRedactionProcessor`);
  the Collector accepts what arrives.
- Durable-write guarantees beyond the opt-in `X-Argox-Durable` header.
- Authentication — gated separately (ADR-0005 / #94).
- The run-record Query API (COL-13) and the SDK exporter that populates
  `trace_id` (EXP-09).
