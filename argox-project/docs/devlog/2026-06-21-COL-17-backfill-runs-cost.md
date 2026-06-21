# [COL-17] Backfill runs.cost_usd from model and token totals

- **Date:** 2026-06-21
- **PR:** pending  ·  **Branch:** feat/COL-17-backfill-runs-cost
- **Status:** in-review

## What changed
- `argox-collector/src/argox_collector/enrichment/cost.py`: new
  `enrich_run_cost(record, pricing)` prices a `RunRecord` from its `model` and
  the promoted `total_input_tokens` / `total_output_tokens`. Mirrors the span
  enricher: a record with a `cost_usd` already set is returned unchanged, and a
  missing or unknown model logs `run_cost_unknown_model` and yields `None`
  (column stays NULL) — ingest never raises. The stale "deferred until COL-11"
  header comment is corrected.
- `argox-collector/src/argox_collector/enrichment/pricing.py`: new
  `fetch_remote_pricing(url)` fetches LiteLLM's
  `model_prices_and_context_window.json` and normalises per-token prices to the
  bundled table's USD-per-1k shape. New `PricingProvider` wraps it with an
  in-memory TTL cache and a graceful fallback to the bundled YAML on any fetch
  failure or empty result. Thread-safe (ingest prices from background tasks and
  the durable threadpool).
- `argox-collector/src/argox_collector/index/base.py` and `index/duckdb.py`:
  - `RunRecord` gains a `model` field; the `runs` table gains a `model VARCHAR`
    column with an idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
    migration for databases created before this ticket.
  - new `set_run_cost(run_id, cost_usd)`: a standalone `UPDATE` that backfills
    the collector-derived cost without touching the immutable blob or the
    client-reported columns.
  - new `get_run_model_from_trace(trace_id)`: reads `gen_ai.request.model`
    (falling back to `gen_ai.response.model`) from the run's spans, the
    span-side fallback for pricing.
- `argox-collector/src/argox_collector/routers/runs.py`: `RunRecordIn` gains an
  optional `model`; ingest now backfills cost after `insert_run` on both the
  background and durable paths. The model is resolved from the run record first,
  then from its spans via `trace_id`; a client-supplied `cost_usd` is left
  as-is. Pricing is only resolved once a model is found, so runs with neither a
  model nor a matching span never trigger a remote fetch. Backfill failures are
  logged and swallowed — the run is already persisted.
- `argox-collector/src/argox_collector/app.py` and `settings.py`: wire
  `app.state.pricing` from new settings `pricing_remote_enabled`,
  `pricing_remote_url` (LiteLLM map), and `pricing_remote_ttl_seconds`
  (default 6h). Remote can be disabled to serve only the bundled table.
- `openapi.json` regenerated for the new `RunRecordIn.model` field.
- Tests: `test_pricing.py` (remote normalisation, cache TTL, fallback paths);
  run-cost cases in `test_enrichment.py` and `test_runs_ingest.py` (known model,
  unknown model, no model, immutable-blob preservation, client cost kept,
  span-model fallback by trace_id).

## Why
COL-11 (#141) landed the `runs` table with a nullable `cost_usd` written `None`
at ingest, and COL-07 (#132) only priced spans (`spans.run_cost`). No code wrote
`runs.cost_usd`, so the column stayed NULL forever. This adds the writer.

Runs carry no model of their own today, so the price lookup resolves the model
from the run record first and falls back to the model the spans carry
(`gen_ai.request.model`, set by PLUGIN-05) joined by `trace_id`. This makes cost
priced today via the span fallback while staying ready for an SDK that reports
`model` directly on `/v1/runs`. Prices come from a live LiteLLM map so new
models are priced without a code change, with the bundled YAML as a safe
offline fallback.

## Notes / follow-ups
- `runs.model` has no SDK producer yet — runs are priced via the span fallback
  until a future SDK ticket reports `model` on `/v1/runs`.
- The backfill stores `cost_usd` only; a model recovered via the span fallback
  is not written back into `runs.model`.
- Azure caveat (inherited from PLUGIN-05): deployment names may differ from the
  priced model id; mapping to a pricing key stays the operator's responsibility.
