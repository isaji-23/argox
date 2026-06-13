# ADR-0004: Audit log — WORM hash chain over the blob StorageBackend

- **Status:** accepted
- **Date:** 2026-06-13
- **Ticket:** COL-08

## Context

AI Act Art. 12 requires a tamper-evident, retained audit trail (architecture
§5.3/§5.4). The Collector already persists authoritative state through a single
blob `StorageBackend` abstraction (local filesystem in dev/CI, Azure Blob in
production). That abstraction overwrites whole objects atomically — it has no
native append and no server-side immutability primitive — and is the only
storage layer the rest of the service knows about. We need WORM (write-once,
read-many) semantics and tamper evidence without inventing a second storage
dependency.

## Decision

The audit log is an append-only sequence of records linked into a SHA-256 hash
chain, persisted as JSONL segments through the existing `StorageBackend`.

- **Record + chain.** Each record carries `seq` (monotonic, gap-free),
  `timestamp` (UTC ISO-8601), `actor`, `action`, `target` and a
  `payload_digest` (raw payloads are never stored). Its chain hash is
  `sha256(prev_hash || canonical_json(record))`, where `canonical_json` is
  key-sorted, whitespace-free, `ensure_ascii=False`, so digests are
  reproducible across processes and Python versions. The first record's
  `prev_hash` is `GENESIS_HASH` (64 zeros).
- **Segments.** Records are grouped into segments under
  `audit-log/{YYYY}/{MM}/{seq_start}-{seq_end}.jsonl`. The active segment is
  written as `{seq_start}-open.jsonl` and rewritten in full on every append
  (whole-blob overwrite is the only primitive available); when it reaches
  `max_segment_records` it is sealed under its final `{seq_start}-{seq_end}`
  name and the open marker is removed. The chain spans segment boundaries: the
  first record of a new segment carries the previous segment's last hash.
- **Verification.** `verify()` walks every segment in `seq` order and returns
  the first broken link — sequence gap, `prev_hash` mismatch, or a record whose
  recomputed hash differs from the stored one.
- **No delete.** `AuditLog` exposes no delete/remove operation. Retention is a
  lifecycle classification only (`lifecycle_tier`: hot 90d → cool 365d →
  archive), matching the Azure lifecycle policy with no delete tier.
- **Single writer.** Appends are serialised with an in-process lock; the
  Collector process is the sole writer. Tamper evidence does not depend on the
  lock — any out-of-band write is caught at verification time.

## Triggers for the next refactor

- A storage backend gains native append or server-enforced immutability
  (e.g. Azure immutable blobs / legal hold): drop the full-segment rewrite and
  lean on the backend guarantee.
- More than one writer is required (horizontal scale-out of the Collector):
  the in-process lock no longer suffices; move sequencing/sealing behind a
  shared coordinator or per-writer chains merged at read time.
- Chains grow large enough that whole-chain `verify()` is too slow for its
  callers: add anchored/paginated verification from a known-good checkpoint.

## What stays out of scope

- Authentication/authorisation of the audit endpoints (COL-09, #94).
- Extending the chain to cover run-record inputs/outputs — decided in
  follow-up #109 (COL-14), which chooses unified vs. parallel chains.
- Cryptographic signing of segments or external anchoring (e.g. notarising the
  head hash); the chain proves internal consistency, not third-party
  attestation.
