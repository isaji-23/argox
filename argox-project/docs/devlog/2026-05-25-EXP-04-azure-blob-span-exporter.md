# [EXP-04] Implement AzureBlobSpanExporter

- **Date:** 2026-05-25
- **PR:** #101  ·  **Branch:** feat/AzureBlobSpanExporter
- **Status:** merged

## What changed

- Added `AzureBlobSpanExporter` in
  `argox-exporters/argox-exporter-azure/src/argox_azure/exporter.py`.
  Implements OTel's `SpanExporter` interface — receives batches of
  `ReadableSpan` objects, serializes them as JSONL, and uploads each batch as
  a new blob at `spans/{YYYY}/{MM}/{DD}/{HH}/{batch_id}.jsonl`.
- Initialised via `BlobServiceClient.from_connection_string()`; a `ValueError`
  on bad connection strings is surfaced at construction time, setting
  `_healthy=False` so subsequent `export()` calls short-circuit with `FAILURE`.
- `shutdown()` closes the `BlobServiceClient`; `force_flush()` is a no-op
  (blobs are uploaded synchronously in `export()`).
- Added `argox-exporter-azure/README.md` with usage example.
- Added `tests/test_azure_exporter.py` covering success path, empty batch,
  init failure, Azure error, and shutdown.

## Why

Closes the gap from the prior skeleton: the Azure Blob backend was chosen as
the durable, cost-effective cold store for OTel span data in the reference
architecture (`argox-collector`). Having a real exporter lets users ship spans
from the SDK directly to Blob Storage without running the collector sidecar.
