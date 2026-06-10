# ADR-0003: Policy storage — content-addressed blobs committed via manifest CAS

- **Status:** accepted
- **Date:** 2026-06-10
- **Ticket:** COL-05

## Context

The Collector persists versioned policy documents in the `StorageBackend`
(Azure Blob in production, local files in dev). Blob stores offer no
transactions, and the Collector may run with several uvicorn workers or
instances, so an in-process lock cannot serialize writers. PR #114 went
through four review rounds chasing the same root problem from both sides:
writing data under versioned keys before committing the pointer caused
lost-update collisions (two writers computing the same `v{n+1}` key), while
committing the pointer first left permanently dangling manifest entries when
the data write failed. Policy distribution is an enforcement path — a corrupt
or dangling bundle degrades governance for every SDK consumer.

## Decision

Policy versions are immutable, content-addressed blobs; the manifest is the
single commit point, written with compare-and-swap.

- Version blob: `policies/{policy_id}/{content_hash}.yaml` where the hash is
  the SHA-256 of the serialized document. The version number is final before
  serialization, so the stored YAML is exactly what every later read returns.
  Same content → idempotent write; different content → different key. Writers
  can never clobber each other's data regardless of interleaving.
- Manifest: `policies/manifest.json` maps each policy id to `status`,
  `latest_version`, `active_version` (null unless status is `active`) and a
  `versions: {"<n>": "<hash>"}` table.
- Commit protocol, identical for create/update/archive:
  1. Write the version blob (unconditional — safe because content-addressed).
  2. Commit the manifest with `expected_etag` = the ETag observed when it was
     read, or the create-only sentinel `"*"` when it did not exist yet.
  3. On `ConditionNotMetError`, retry the whole read-build-commit cycle
     (bounded; exhaustion → 503). Version numbers are therefore reserved by
     winning the CAS, never by key choice.
- Readers trust the manifest only: a version exists iff the manifest
  references it. A crash between steps 1 and 2 leaves an unreachable orphan
  blob, never a dangling pointer. The one read path that can still see a
  dangling pointer (a manifest committed whose blob was later lost) fails
  per-policy: `/bundle` skips and logs the broken policy rather than denying
  the merged ruleset to the entire fleet.
- `StorageBackend.put(expected_etag=...)` carries the guard: `"*"` =
  create-only, any other value = ETag match. Backends must enforce it
  atomically or raise `StorageError` — silently degrading to an unconditional
  overwrite is forbidden (it would turn optimistic locking into lost updates).

## Triggers for the next refactor

- `/bundle` latency or storage egress becomes measurable: add a bundle cache
  keyed on the manifest ETag, or persist a precomputed bundle on write.
- The manifest becomes a write hotspot (many concurrent policy authors):
  shard the manifest per policy id, keeping CAS per shard.
- Orphaned blobs accumulate enough to matter: add a sweep that lists
  `policies/` and deletes blobs not referenced by the manifest.

## What stays out of scope

- Authentication/authorization of the policy API (COL-09).
- Garbage collection of orphaned blobs.
- Cross-policy rule-id namespacing in the merged bundle.
- Transactional multi-policy operations; the unit of atomicity is one
  manifest commit.
