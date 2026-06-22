# [COL-17] Backfill runs.cost_usd from model and token totals

- **Date:** 2026-06-21
- **PR:** #151  ·  **Branch:** feat/COL-17-backfill-runs-cost
- **Status:** in-review

## What changed
- `argox-collector/src/argox_collector/enrichment/cost.py`: new
  `enrich_run_cost(record, pricing)` prices a `RunRecord` from its `model` and
  the promoted `total_input_tokens` / `total_output_tokens`. Mirrors the span
  enricher: a record with a `cost_usd` already set is returned unchanged, and a
  missing or unknown model logs `run_cost_unknown_model` and yields `None`
  (column stays NULL) — ingest never raises. The stale "deferred until COL-11"
  header comment is corrected.
- `argox-collector/src/argox_collector/enrichment/pricing.py`: prices come from
  a committed snapshot of the LiteLLM map (`pricing.yaml`), read at runtime via
  the shared `cached_pricing` loader — no fetch on the ingest path.
  `fetch_remote_pricing(url)` fetches LiteLLM's
  `model_prices_and_context_window.json` and normalises per-token prices to the
  bundled USD-per-1k shape; `filter_pricing` keeps only providers in use and
  `render_pricing_yaml` emits a deterministic, sorted YAML. These are
  refresh-time helpers, not called at ingest.
- `argox-collector/src/argox_collector/__main__.py`: new `refresh-pricing`
  subcommand regenerates the bundled `pricing.yaml` from LiteLLM (with
  `--provider` filters and a `--check` drift mode), mirroring `export-openapi`.
  The bundled `pricing.yaml` is regenerated to a 325-model LiteLLM snapshot.
- `.github/workflows/refresh-pricing.yml`: scheduled job that runs
  `refresh-pricing` and opens a PR when prices drift, so changes are reviewed.
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
- `argox-collector/src/argox_collector/routers/runs.py` resolves the price
  table via `cached_pricing(settings.pricing_table_path)`; the run backfill and
  the span enricher now share one cached loader (the per-pipeline cache was
  removed). No `app.state.pricing` / runtime provider.
- `openapi.json` regenerated for the new `RunRecordIn.model` field.
- Tests: `test_pricing.py` (remote normalisation, provider filter, YAML
  round-trip/determinism, `refresh-pricing` write/filter/check/fetch-failure);
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
`model` directly on `/v1/runs`. Prices come from a committed LiteLLM snapshot
rather than a runtime fetch: a governance tool needs a deterministic, auditable,
version-controlled cost basis, and ingest must not depend on the network. A
scheduled job regenerates the snapshot so new models are picked up via a
reviewed PR. See ADR-0008.

## Notes / follow-ups
- `runs.model` has no SDK producer yet — runs are priced via the span fallback
  until a future SDK ticket reports `model` on `/v1/runs`.
- The backfill stores `cost_usd` only; a model recovered via the span fallback
  is not written back into `runs.model`.
- Azure caveat (inherited from PLUGIN-05): deployment names may differ from the
  priced model id; mapping to a pricing key stays the operator's responsibility.
