# [COL-04] Harden DuckDB indexing layer (errors and security review)

- **Date:** 2026-06-10
- **PR:** #131  ·  **Branch:** `fix/COL-04-duckdb-index-hardening`
- **Status:** in-review

## What changed

- `ingest/otlp.py` — `_as_float` now rejects non-finite floats: OTLP doubles
  (and strings such as `"nan"`) could carry NaN/Infinity into `run_cost`;
  non-finite values degrade to `None`.
- `index/duckdb.py`:
  - Attribute encoding moved into a defensive `_encode_attributes` helper.
    Previously `json.dumps(r.attributes)` ran during batch preparation —
    before the per-row `executemany` fallback — so a single non-serializable
    attribute value dropped the entire batch. Separately, `json.dumps` emits
    bare `NaN` literals that DuckDB's JSON parser rejects at insert time,
    silently discarding the row. Problematic values now degrade to their
    string form via `_json_safe`; a span never loses its row over a bad
    attribute.
  - `run_cost` and `duration_ms` pass through `_finite_or_none` at the write
    path, and the cost/latency aggregates filter with `isfinite(...)` so rows
    written before sanitisation cannot poison `SUM`/`AVG`/`QUANTILE_CONT`
    into NaN (which the JSON response layer cannot encode → 500 on
    `/api/v1/metrics/*`).
  - `health_check` no longer embeds the raw DuckDB exception text — which can
    contain the database filesystem path — in the `TraceIndexError` message
    that `/readyz` forwards verbatim to unauthenticated callers. The message
    is now generic; full detail goes to the structured log.
- Tests: new coverage in `tests/test_index.py` (NaN / unserializable
  attributes keep their row and batch, non-finite doubles stored as NULL,
  metrics ignore poisoned rows, health check message stays generic) and
  `tests/test_otlp_ingest.py` (non-finite `argox.run.cost` dropped at ingest).

## Why

Issue #49 (COL-04) was closed by PR #113, but the user requested a re-review
of the implementation for errors and security issues. The audit confirmed the
DuckDB backend design is sound (it had survived three review rounds plus
COL-03/COL-06 hardening) and found three remaining defects: non-finite value
poisoning of metrics aggregates, whole-batch loss on attribute encoding
failures, and filesystem path disclosure through the readiness probe.

## Review hardening

PR review flagged that the path-disclosure fix only covered the index branch
of `/readyz`: the storage branch still forwarded `StorageError` text verbatim,
and the local backend embeds raw `OSError` messages (filesystem paths) while
the Azure backend can embed container names. Sanitisation moved to the readyz
handler itself (`routers/health.py`): degraded checks report a bare
`"unavailable"` and full detail goes to the structured log, covering every
current and future backend. The `_json_safe` key-collision edge case (`1` vs
`"1"`) was reviewed and accepted: OTLP attribute keys are always strings.

## Notes / follow-ups

- Defense is layered: ingest rejects non-finite promoted floats, the index
  write path re-checks, and the read-side aggregates filter — any one layer
  alone left a gap (e.g. pre-existing rows).
- The `close()`-during-background-write race at shutdown remains: a batch in
  flight when the lifespan hook closes the connection is logged and lost.
  Acceptable for now since the client already received its `202`.
