# ADR-0002: Collector ingest acknowledgement semantics

- **Status:** accepted
- **Date:** 2026-06-08
- **Ticket:** COL-03

## Context

The Collector's `/v1/traces` endpoint (and the later `/v1/runs`, COL-11) receive
OTLP/run batches from SDK exporters on the hot path. Persisting each batch means
a blob write plus a DuckDB insert — DuckDB is single-writer behind a lock — so
doing all of it before responding would couple exporter latency to index
contention. SDK exporters are fire-and-forget telemetry clients that retry on
non-2xx; they do not need a per-span durability guarantee. A small set of callers
(tests, audit-sensitive producers) do need to know the data is committed before
they move on.

The standard OTLP/HTTP client treats any 2xx as success (`if resp.ok:`), so a
202 response is accepted without breaking the SDK's own exporter.

## Decision

Ingest endpoints **validate synchronously, persist asynchronously by default**:

1. Decode + validate the batch in the request handler. Reject undecodable bodies
   (400) and unsupported content types (415) before acknowledging.
2. Enqueue the blob write + index insert on FastAPI `BackgroundTasks` and return
   **202 Accepted** with an empty success response in the request's content type.
3. If the request carries `X-Argox-Durable: true`, run persistence inline and
   return **200 OK** only after the commit succeeds.

Persistence errors inside the background task are logged, never raised — the
caller has already been acknowledged. On the **durable** path the opposite
holds: a persistence failure is surfaced to the client as **503** so the batch
is never silently lost (returning 200 on failure would break the durability
guarantee the header promises). Enrichment runs inside the same persistence
step and must be idempotent so a retried batch is safe.

Requests are bounded before they reach this contract: a body-size guardrail
rejects payloads over `max_payload_size` (default 10 MiB) with **413**,
aborting during the read so an oversized or chunked upload cannot exhaust
memory ahead of the synchronous validation.

## Triggers for the next refactor

- When durability becomes the default expectation (e.g. a managed deployment SLA)
  rather than an opt-in header.
- When background-task loss under crash/restart is unacceptable and a durable
  queue (or write-ahead log) replaces `BackgroundTasks`.
- When a partial-success response (per-span rejection counts) is required by a
  client; the current contract only returns full-success envelopes.

## What stays out of scope

- Authentication / rate limiting (COL-09).
- The content and computation of enrichment (cost model, PII rules) — this ADR
  fixes *when* persistence is acknowledged, not *what* enrichment does.
- Cross-replica ordering or deduplication guarantees.
