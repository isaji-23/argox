# [COL-03] OTLP/HTTP trace ingest endpoint

- **Date:** 2026-06-08
- **PR:** #122  ·  **Branch:** feat/COL-03-otlp-ingest-endpoint
- **Status:** in-review

## What changed

- New endpoint `POST /v1/traces` (`argox-collector/src/argox_collector/routers/traces.py`)
  accepting OTLP `ExportTraceServiceRequest` over both `application/x-protobuf`
  and `application/json`. Wired into the app factory (`app.py`).
- Acknowledgement contract: validate synchronously, then delegate the raw blob
  write + DuckDB index insert to a FastAPI `BackgroundTasks` and return
  **202 Accepted**. An opt-in `X-Argox-Durable: true` header runs persistence
  synchronously and returns **200 OK** once committed. Unsupported content type
  → 415; undecodable body → 400; empty batch → success with no rows.
- OTLP decode module (`ingest/otlp.py`): `decode_request` (protobuf +
  JSON-with-hex-id normalisation) and `request_to_span_records`, flattening
  `resource_spans → scope_spans → spans` into `SpanRecord` rows. Argox/GenAI
  attributes are promoted into dedicated columns (agent name/version, policy
  decision, run success, cost); `AnyValue` is decoded to JSON-safe Python.
- Basic, idempotent ingest-time enrichment (`enrichment/`):
  - `cost.py` computes `run_cost` from GenAI token counts and a seed model
    price table (`pricing.yaml`); unknown models warn and skip; records that
    already carry a cost are left untouched.
  - `pii.py` tags spans with `argox.pii.residual_detected` when a
    high-confidence regex matches a string attribute. Tag-only — no redaction.
  - `pipeline.enrich()` applies cost then PII, gated by `enrichment_enabled`.
- Settings: `enrichment_enabled` (default True) and `pricing_table_path`
  (`settings.py`). Deps added: `opentelemetry-proto`, `protobuf`, `pyyaml`.
- Collector-local `semconv.py` mirrors the SDK attribute keys so the Collector
  keeps no runtime dependency on `argox-core`.

### Hardening (2026-06-09)

- Durable contract now enforced: `_persist` raises on failure and the durable
  path returns **503** instead of a silent 200, so `X-Argox-Durable: true`
  callers learn when a batch was lost. The background path keeps the
  log-and-swallow behaviour (client already acknowledged). See ADR-0002.
- New `PayloadSizeLimitMiddleware` (`middleware.py`, pure ASGI) rejects bodies
  over `max_payload_size` (default 10 MiB) with **413**, aborting *during* the
  read so chunked uploads without `Content-Length` cannot exhaust memory.
- OTLP decode hardened: hex-id normalisation is now iterative (no recursion
  limit) and a deep-nesting `RecursionError` is mapped to **400** rather than a
  500. JSON/415/400/503 error bodies go through a single JSON-safe helper.
- DuckDB ingest resilience: `run.success` attributes are coerced to bool, and
  `insert_spans` falls back to per-row inserts when a batch fails, so one
  malformed span no longer drops the whole batch (the upsert keeps retries
  idempotent).

## Why

The Collector had storage (COL-02) and a DuckDB index (COL-04) but no ingest
path — nothing wrote spans. `/v1/traces` is the producer the Query API,
dashboard and audit log consume, and a hard dependency of the COL-07 enrichment
worker and the COL-11 `/v1/runs` endpoint. The 202 + background-write contract
is locked in ADR-0002.

## Notes / follow-ups

- Deferred to **COL-07 (#92)**: full per-model cost attribution joining run
  records, GenAI attribute normalisation, residual-PII over event payloads. Our
  cost calc and PII scan are deliberately small and idempotent so COL-07 can
  re-run over the same spans.
- Auth is out of scope until **COL-09 (#94)**.
- OTLP/JSON is best-effort: strict hex-encoded `trace_id`/`span_id` are
  normalised to base64 for `json_format`. Protobuf is the lossless transport.
  Known limitation (commented in `_hex_to_b64`): a base64 id that is
  coincidentally all-hex and even-length is misconverted; low impact while
  protobuf stays primary.
- `host` defaults to `0.0.0.0` (commented in `settings.py`): intended for
  containerised deploys but exposed until auth lands in COL-09.
