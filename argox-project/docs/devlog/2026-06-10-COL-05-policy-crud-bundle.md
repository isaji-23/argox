# [COL-05] Policy CRUD API and bundle endpoint

- **Date:** 2026-06-10
- **PR:** #126  ·  **Branch:** feat/COL-05-policy-crud-bundle
- **Status:** in-review

## What changed

- New router `argox-collector/src/argox_collector/routers/policies.py`, wired
  into the app factory (`app.py`):
  - `GET /api/v1/policies` — summaries served from the manifest alone (no blob
    fan-out), sorted by id; `skip`/`limit` validated (`ge=0`, `1..100`).
  - `GET /api/v1/policies/{id}` — the active version. A policy without an
    active version (draft or archived) is **404**, never served stale.
  - `GET /api/v1/policies/{id}/v{n}` — a specific committed version, resolved
    through the manifest only, so blobs from lost races are unreachable.
  - `POST /api/v1/policies` — creates v1; duplicate id → **409**.
  - `PUT /api/v1/policies/{id}` — commits v{n+1}; `active_version` follows the
    new head and is cleared when the status moves away from `active`.
  - `DELETE /api/v1/policies/{id}` — archives by committing a new `archived`
    version; history is preserved and the call is idempotent.
  - `GET /api/v1/policies/bundle` — merges the rules of all active policies
    (sorted by id) into a single SDK-parseable `PolicyDocument` YAML. Strong
    ETag = SHA-256 of the body; `If-None-Match` answers **304**. GET never
    writes. A dangling manifest pointer skips (and loudly logs) just that
    policy instead of failing the bundle for the whole fleet.
- Storage model: each policy version is an immutable content-addressed blob
  (`policies/{id}/{hash}.yaml`); a single `policies/manifest.json` maps ids to
  status, `latest_version`, `active_version` and the version→hash table.
  Mutations write the blob first, then commit the manifest with
  compare-and-swap on its ETag (retried). Locked in ADR-0003.
- `StorageBackend.put` gained an `expected_etag` guard (`"*"` = create-only,
  value = CAS) raising the new `ConditionNotMetError`. Local backend checks
  the guard under its write lock; Azure maps it to `overwrite=False` /
  `MatchConditions.IfNotModified` and fails loudly rather than degrading to an
  unconditional overwrite when `azure-core` is missing.
- All handlers are sync `def` (FastAPI threadpool) because storage I/O blocks;
  policy and rule ids are pattern-validated (`^[a-zA-Z0-9_-]+$`) at the edge so
  the storage layer's key `ValueError` path is unreachable from these
  endpoints; YAML is always `safe_dump`/`safe_load`.
- Tests: `tests/test_policy_crud.py` (lifecycle, pagination, bundle merge and
  ETag semantics, SDK parser compatibility, dangling-pointer resilience) and
  conditional-write tests for both backends in `tests/test_storage_backend.py`.

## Why

Issue #50: the SDK's `RemotePolicyClient` (POL-04) polls a Collector endpoint
for its policy bundle, but the Collector had no policy storage or API. This
supersedes PR #114 — same scope, rebuilt on current `dev` with the storage
architecture that emerged from that review (content-addressed blobs + manifest
CAS) and with all findings from its four review rounds addressed: no manifest
read-modify-write races, no pointer-before-data ordering, no `version: null`
blobs, no GET side effects, no `storage.head()` call, no global bundle failure
on a single dangling pointer.

## Notes / follow-ups

- Bundle generation reads every active policy blob per request (after a 304
  miss). If `/bundle` becomes hot with many policies, add a server-side cache
  keyed on the manifest ETag.
- Orphaned content-addressed blobs from lost CAS races are unreachable but
  never garbage-collected; a cleanup sweep can compare blob listings against
  the manifest if storage growth ever matters.
- Auth remains out of scope until COL-09 (#94); the policy API is unauthenticated.
- Merged bundle rule ids are not namespaced per policy; two policies can ship
  the same rule id. Acceptable while policy authorship is centralized.
