# [COL-07] Enrichment worker: GenAI normalisation, cost calc, event PII scan

- **Date:** 2026-06-10
- **PR:** #132  ·  **Branch:** feat/COL-07-enrichment-worker
- **Status:** in-review

## What changed

- New `argox_collector/enrichment/normalize.py`: copies variant GenAI
  semantic-convention attributes onto the canonical keys before cost
  calculation — legacy OTel `gen_ai.usage.prompt_tokens` /
  `gen_ai.usage.completion_tokens` and OpenInference `llm.model_name` /
  `llm.token_count.prompt` / `llm.token_count.completion`. Canonical keys
  always win; variant keys are left in place to preserve the span as received.
- `SpanRecord` gained an `events` field (tuple of name/timestamp/attributes
  mappings). `ingest/otlp.py` now decodes OTLP span events into it. Events are
  not written to the index — the raw blob already preserves them — they exist
  only so enrichment can inspect event payloads.
- The residual PII scan (`enrichment/pii.py`) now covers event payloads in
  addition to span attributes when deciding to tag
  `argox.pii.residual_detected`.
- The bundled pricing table (`enrichment/pricing.yaml`) grew from 5 to 15
  models: gpt-4.1 family, gpt-4, o3/o3-mini/o4-mini, text-embedding-3-small/
  -large, and Azure-style gpt-35-turbo-16k. Still overridable via
  `ARGOX_PRICING_TABLE_PATH`; unknown models log a warning and skip cost calc.
- Pipeline order is now normalise → cost → PII; every stage is idempotent so
  re-running enrichment on the same span is safe.
- New semconv constants for the variant keys in `argox_collector/semconv.py`.
- Tests: normalisation (legacy and OpenInference shapes, canonical-wins,
  no-op), PII in event payloads (unit and end-to-end through `/v1/traces`),
  custom pricing YAML load, and full-pipeline idempotency.

## Why

Issue #92 (architecture §4.6): the ingest-time enrichment shipped with COL-03
only read canonical attribute keys and only scanned span attributes. Plugins
emit slightly different GenAI shapes (cost silently skipped for those spans),
and PII can hide in event payloads such as `gen_ai.content.completion` events.

## Review hardening

PR review flagged the event PII scan as a DoS surface: event payloads carry
full LLM content and arrive attacker-influenced. The scan is now bounded —
at most 100 events per span, each string truncated to 16 KiB before the
regexes run — and covers only event payload attributes (event names and
timestamps would only feed false positives). The tag-only threat model is now
stated explicitly: ``argox.pii.residual_detected`` marks content for
downstream handling; the raw blob keeps it unredacted (redaction is the SDK's
job).

## Notes / follow-ups

- The Route B run-record join from the #92 update (writing `cost_usd` into the
  `runs` DuckDB row from `api_calls[]`) is blocked on COL-11 (#105), which has
  not landed the `/v1/runs` endpoint or the `runs` table. `ApiCallRecord` also
  carries no per-call model field, so per-call per-model attribution needs an
  SDK-side change first. Per-span cost already equals the sum over `api_calls`
  because the manager sums per-call tokens into the span totals.
- Normalisation covers two known variant families; extend `_KEY_ALIASES` as
  new instrumentation sources appear.
