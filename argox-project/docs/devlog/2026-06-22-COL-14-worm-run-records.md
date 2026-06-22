# [COL-14] Chain run records into the WORM audit log

- **Date:** 2026-06-22
- **PR:** #158  ·  **Branch:** feat/COL-14-worm-run-records
- **Status:** in-review

## What changed
- `AuditRecord` (`audit/chain.py`) gains a `kind` field (`run` | `span_batch` |
  `event`), hashed with the rest of the record so the discriminator is itself
  tamper-evident. Backward compatible: a legacy entry with no `kind` is read as
  `kind=None` and `signing_dict` omits the field, so the pre-COL-14 chain keeps
  verifying byte-for-byte.
- `AuditLog.append` (`audit/log.py`) accepts `kind=` (default `event`).
  `AuditVerificationResult` and `verify` now also report `broken_offset`
  (zero-based position), `broken_kind`, and `broken_target` for the first
  broken record. Added `AUDIT_KIND_RUN` / `AUDIT_KIND_SPAN_BATCH` /
  `AUDIT_KIND_EVENT` constants.
- Run ingest `_persist` (`routers/runs.py`) appends a `kind="run"` audit entry
  with `target=run_id` and `payload_digest` = digest of the immutable blob
  bytes. The append is idempotent and gated on a new `audited` flag on the run
  index row, not on whether the blob was newly written, so a re-ingest retries
  a run whose first append failed instead of skipping it forever. Any audit
  failure is logged and swallowed (the run is already durable), never a 503 or
  a crashed background task.
- `TraceIndex` gains `is_run_audited` / `mark_run_audited`; the DuckDB backend
  adds an `audited BOOLEAN` column (with `ADD COLUMN IF NOT EXISTS` migration).
- `POST /api/v1/audit` accepts an optional `kind`; `GET /api/v1/audit/verify`
  and the entry/list responses expose the new `kind` / break fields
  (`kind` nullable for legacy entries). `openapi.json` regenerated.

## Why
Route B run records carry the prompt, final output, per-call tokens and policy
violations — the evidence AI Act Art. 12/13 require. Keeping them out of the
hash chain would let DOC-01 (#98) only partially claim coverage. The unified
single-chain design (one `audit.jsonl`, one verification endpoint) was chosen
over parallel chains, matching Art. 12's "one tamper-evident record".

## Notes / follow-ups
- Span-batch ingest is not auto-chained yet; the `span_batch` kind exists and
  is exercised via the manual endpoint, ready for a future ingest-side hook.
- No external timestamping (RFC 3161) and no retroactive backfill, per the
  ticket non-goals.
