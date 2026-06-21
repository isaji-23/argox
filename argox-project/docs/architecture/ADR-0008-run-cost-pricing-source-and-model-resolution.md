# ADR-0008: Run-cost pricing source and model resolution

- **Status:** accepted
- **Date:** 2026-06-21
- **Ticket:** COL-17

## Context

The `runs` table (COL-11, ADR-0007) shipped with a nullable `cost_usd` written
`None` at ingest, but nothing wrote it. Pricing a run needs two things the run
record did not provide: a model to key a price table, and a price table that
keeps pace with new models. Two constraints shaped the decision:

- The run record is immutable (first-write-wins blob and index row); cost is a
  collector-derived field, not client content, so writing it must not reopen
  that immutability.
- Runs carry no model of their own today. The model is captured on spans by
  PLUGIN-05 (`gen_ai.request.model`), and a run joins its spans by `trace_id`.

## Decision

`runs.cost_usd` is backfilled by a dedicated `TraceIndex.set_run_cost(run_id,
cost_usd)` `UPDATE`, kept separate from `insert_run`'s first-write-wins
`INSERT`. The backfill runs after `insert_run` on both the background and
durable ingest paths, and its failures are logged and swallowed — the run is
already persisted.

The model is resolved in order: the run record's own `model` field (optional on
`RunRecordIn`, persisted to a `runs.model` column), then a fallback to the model
its spans carry via `get_run_model_from_trace(trace_id)` (`gen_ai.request.model`
then `gen_ai.response.model`). A client-supplied `cost_usd` is left untouched.
The price table is only resolved once a model is found, so runs with neither a
model nor a matching span trigger no price lookup.

Prices come from `PricingProvider`: a TTL-cached fetch of LiteLLM's
`model_prices_and_context_window.json` (per-token prices normalised to the
bundled table's USD-per-1k shape), falling back to the bundled `pricing.yaml` on
any fetch failure or empty result. The remote source is configurable
(`pricing_remote_enabled`, `pricing_remote_url`, `pricing_remote_ttl_seconds`)
and can be disabled to serve only the bundled table.

## Triggers for the next refactor

- When an SDK ticket reports `model` directly on `/v1/runs`, the span fallback
  becomes a backstop rather than the primary path; revisit whether the join is
  still worth its query.
- When a run needs per-call pricing across mixed models (different models within
  one run's `tokens.by_api_call`), the single run-level model assumption breaks
  and pricing must move per-call.
- When a second consumer needs live prices (e.g. the span enricher), promote the
  `PricingProvider` to the shared pricing entry point instead of `load_pricing`.

## What stays out of scope

- Populating `runs.model` from the SDK — no producer exists yet; runs are priced
  via the span fallback in the meantime.
- Writing a fallback-resolved model back into `runs.model`: the backfill stores
  `cost_usd` only.
- Mapping Azure deployment names to priced model ids — inherited operator
  responsibility from PLUGIN-05.
- Re-pricing already-costed runs when the pricing table changes (no sweep over
  `cost_usd IS NULL`; backfill is inline at ingest).
