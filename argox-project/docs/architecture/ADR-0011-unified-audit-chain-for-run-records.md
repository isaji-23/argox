# ADR-0011: One unified audit chain for run records and span batches

- **Status:** accepted
- **Date:** 2026-06-22
- **Ticket:** COL-14

## Context

The WORM audit log (ADR-0004) hash-chains governance events for AI Act Art. 12
retention. With Route B (ADR-0007), the content that Art. 12 (record-keeping)
and Art. 13 (transparency) actually require evidence for — prompt, final
output, per-tool detail, per-LLM-call tokens, policy-violation reasons — lives
in run records persisted by COL-11, not in the existing chain. Leaving them out
means DOC-01 cannot honestly claim coverage.

COL-14 had to choose between two shapes:

1. **Unified chain.** Run records and span batches share one `audit.jsonl`
   chain with a `kind` discriminator. One chain, one verification endpoint.
2. **Parallel chains.** Separate `runs_audit.jsonl` and `spans_audit.jsonl`
   with independent `prev_hash` linkage; the verifier walks both.

## Decision

Use a **single unified chain**. Every `AuditRecord` carries a `kind` field
(`run` | `span_batch` | `event`) that is hashed with the rest of the record, so
the discriminator is itself tamper-evident. This matches Art. 12's intent of
"one tamper-evident record of the system's behaviour".

Data flow: run ingest `_persist` appends a `kind="run"` entry **after** the
immutable blob write (post-ack, so a failed write never enters the chain),
`target=run_id`, `payload_digest` = digest of the stored blob bytes. The append
is idempotent and self-healing: it is gated on an `audited` flag on the run's
index row, not on whether the blob was newly written, so a re-ingest **retries**
the append for a run whose first attempt failed (transient storage error,
concurrent writer) instead of skipping it forever because the immutable blob
already exists. The flag is set only after the append succeeds, biasing toward a
duplicate audit entry over a missing one (over-recording is compliant; omission
is not). Any audit failure is logged, never re-raised — an already-persisted run
must not become a 503 or crash the background task.

`verify` cannot by itself prove a run *should* be in the chain (sequence numbers
are assigned at append time, not derived from runs), so a run whose only append
failed on an otherwise-successful request would stay absent — the client saw
success and never re-ingests, so the retry path cannot reach it. A startup
**reconciliation sweep** (`reconcile_run_audit`) closes that residual: it reads
every `audited = FALSE` run's immutable blob, appends it to the chain and marks
it audited, bounded per run-list page. Together the `audited` flag (retry on
re-ingest) and the sweep (heal on restart) guarantee a persisted run eventually
enters the chain.

The flag is deliberately **tri-state**, not a boolean: a COL-14-era run is
written `FALSE` (awaiting/failed chaining) and flipped `TRUE` once chained,
while the `audited` column is added to existing databases *without* a default,
so every run that predates COL-14 stays `NULL`. The sweep and the re-ingest
retry both act only on an explicit `FALSE`, so pre-COL-14 history is never
retroactively backfilled (a boolean defaulting `FALSE` would have swept the
entire back-catalogue on first startup) — and the first-startup cost stays
near-zero because genuine append failures are rare.

`verify` (and `GET /api/v1/audit/verify`) report the first broken record's
`kind`, `target` (`run_id` / `trace_id`) and zero-based `offset`, so an auditor
can page straight to it.

## Triggers for the next refactor

- When span-batch ingest needs to be auto-chained (today only the manual
  endpoint mints `span_batch`): wire an append into the OTLP ingest path,
  mirroring the run path.
- When retention rules must diverge per kind (e.g. runs kept longer than
  spans): revisit whether a single lifecycle policy on one chain still holds,
  or whether parallel chains become justified.
- If regulators require external timestamping (RFC 3161), that is a new chain
  property, not a re-chaining.
- The reconciliation sweep runs only at startup. If long-running deployments
  accumulate unaudited runs faster than restarts heal them, promote it to a
  periodic background task or expose the `audited=false` count for monitoring.

## What stays out of scope

- No retroactive backfill of runs ingested before COL-14. The reconcile sweep
  enforces this via the tri-state `audited` flag above: pre-COL-14 run rows are
  `NULL` and excluded from the sweep, so they are never chained after the fact.
- No retroactive re-hashing of audit entries written before COL-14. Such
  entries carry no `kind` and are hashed *without* a `kind` field
  (`signing_dict` omits it when `kind is None`), so the legacy chain keeps
  verifying byte-for-byte; only records written since COL-14 hash their kind.
- No external timestamping authority — deferred to a separate ticket.
- The SDK still does not write to the audit log; it remains Collector-side.
