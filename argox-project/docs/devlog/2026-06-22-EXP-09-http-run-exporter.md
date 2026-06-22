# [EXP-09] Implement HttpRunExporter (ExporterBase to Collector /v1/runs)

- **Date:** 2026-06-22
- **PR:** #106  ·  **Branch:** feat/EXP-09-http-run-exporter
- **Status:** in-review

## What changed
- `argox-core/src/argox/exporters/http_run.py`: created `HttpRunExporter(ExporterBase)` that serializes metrics with `metrics.to_dict()` and POSTs them to the Collector's `/v1/runs` endpoint.
  - Supports configurable `timeout`, `max_retries`, and custom exponential backoff.
  - Handles 5xx response codes and `httpx.RequestError` network errors by retrying.
  - Isolates all HTTP errors and exceptions internally so they never propagate back into the main agent run loop; error details are logged and appended to `metrics.exporter_errors`.
  - Supports authorization headers (`Authorization: Bearer <api_key>`) and durability flags (`X-Argox-Durable: true` via `durable=True`).
  - Utilizes `httpx.Client` for predictable timeouts and connection pooling.
- `argox-core/src/argox/exporters/__init__.py`: exposed `HttpRunExporter` in the `argox.exporters` namespace.
- Added `tests/test_http_run_exporter.py`: unit tests verifying happy path, OTel span tracing behavior, retry limits, non-retriable error handling, backoff, and exception propagation isolation.
- Created `examples/demo_http_run_exporter.py`: a self-contained examples script showcasing how to instantiate and wire `HttpRunExporter` against a local Collector instance.

## Why
This implements the transport-level SDK counterpart to the Route B ingest endpoint (COL-11) of the Collector. It allows sending PII-scrubbed run summary metrics directly to the Collector's `/v1/runs` endpoint at the end of each run, enabling end-to-end telemetry ingestion for dashboard queries and metrics tracking without local disk/JSONL file limitations.

## Notes / follow-ups
- Future performance tuning can explore batching multiple runs across the transport layer if benchmarking justifies the complexity. Currently, one POST request is sent per run.
