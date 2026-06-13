# [COL-08] WORM audit log with hash chain

- **Date:** 2026-06-13
- **PR:** #134  ·  **Branch:** feat/COL-08-audit-hash-chain
- **Status:** in-review

## What changed

- New `argox_collector.audit` package:
  - `chain.py` — hash-chain primitives. `canonical_json` (sorted keys, no
    whitespace, `ensure_ascii=False`) gives a reproducible encoding;
    `digest_payload` hashes a payload (canonicalised, or raw bytes) to a
    SHA-256 hex digest. `AuditRecord` holds the signed fields (`seq`,
    `timestamp`, `actor`, `action`, `target`, `payload_digest`, `prev_hash`)
    and computes `hash = sha256(prev_hash || canonical_json(record))` per
    architecture §5.3. `AuditEntry` pairs a record with its hash;
    `GENESIS_HASH` (64 zeros) is the first record's `prev_hash`.
  - `log.py` — `AuditLog` over the existing blob `StorageBackend`:
    - `append(actor, action, target, payload | payload_digest)` assigns the
      next gap-free `seq`, links `prev_hash` to the previous entry, seals the
      record and persists it. Only the payload **digest** is stored, never the
      raw payload.
    - Append-only JSONL segments under
      `audit-log/{YYYY}/{MM}/{seq_start}-{seq_end}.jsonl`, capped at
      `max_segment_records`. An open segment is named `{seq_start}-open.jsonl`
      and rewritten on each append (the blob API overwrites whole objects);
      when full it is sealed under its `{seq_start}-{seq_end}.jsonl` name and
      the open marker removed. The chain continues seamlessly across the
      rollover — the first record of a new segment carries the previous
      segment's last hash.
    - `verify()` walks every segment in sequence order and returns the first
      broken link: a sequence gap, a `prev_hash` mismatch, or a record whose
      recomputed hash differs from the stored one.
    - `lifecycle_tier(timestamp)` maps entry age to `hot` (<90d), `cool`
      (<365d) then `archive` (§5.4). No delete/remove method is exposed.
    - State (last seq, last hash, open segment) is recovered lazily from
      storage on first use, so a fresh process resumes the chain.
- New router `routers/audit.py`, wired into `app.py`:
  - `POST /api/v1/audit` — append, returns the sealed entry (**201**).
  - `GET /api/v1/audit/verify` — chain verification result.
  - `GET /api/v1/audit` — first `limit` entries (1..1000) in sequence order.
  - Handlers are sync `def` so the blocking blob I/O runs in the threadpool,
    mirroring the query and policy routers. `create_app` builds an `AuditLog`
    over `app.state.storage` and accepts an injectable `audit_log`.
- `settings.py`: `audit_log_prefix` (default `audit-log`) and
  `audit_segment_max_records` (default 1000).
- Tests: `tests/test_audit_log.py` (15 tests) — recorded fields and digest,
  genesis/linking, happy-path verify, tampering (payload edit, self-consistent
  re-hash, record deletion), chain continuity across rollover, sealed-segment
  tamper detection, state recovery by a new instance, lifecycle tiers, absence
  of a delete API, and the HTTP endpoints.

## Why

Issue #93: AI Act Art. 12 record-keeping requires a tamper-evident audit
trail. The SHA-256 hash chain makes any retroactive edit, reorder or deletion
detectable, and the no-delete lifecycle keeps audit data for the lifetime of
the deployment. The decision to build WORM semantics on top of the
whole-blob-rewrite `StorageBackend` (seal-on-rollover, chain continuity, no
delete) is locked in
[ADR-0004](../architecture/ADR-0004-audit-log-worm-hash-chain.md).

## Notes / follow-ups

- A single writer (the Collector process) is assumed; appends are serialised
  with an in-process lock. The chain itself detects any out-of-band write at
  verification time, but concurrent writers would race on the segment blob.
- Rewriting the open segment on every append is O(segment size); the per-
  segment cap bounds it. A future backend with native append could drop the
  rewrite.
- `GET /api/v1/audit/verify` walks the whole chain; it is not wired into
  `readyz` (which must stay cheap). Add a paginated/anchored verification when
  chains grow large.
- Follow-up #109 (COL-14) extends this chain to cover run records (#105,
  COL-11); the unified-vs-parallel-chain choice is decided there.
- Auth remains out of scope until COL-09 (#94); these endpoints are
  unauthenticated.
