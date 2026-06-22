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
are assigned at append time, not derived from runs), so a never-re-ingested run
that failed its only append would stay absent. The `audited` flag plus retry-on-
re-ingest is what closes that gap.

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

## What stays out of scope

- No retroactive backfill of runs ingested before COL-14. Pre-COL-14 audit
  entries that carry no `kind` are hashed *without* a `kind` field
  (`signing_dict` omits it when `kind is None`), so the legacy chain keeps
  verifying byte-for-byte; only records written since COL-14 hash their kind.
- No external timestamping authority — deferred to a separate ticket.
- The SDK still does not write to the audit log; it remains Collector-side.
