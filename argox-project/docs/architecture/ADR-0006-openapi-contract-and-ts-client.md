# ADR-0006: OpenAPI contract as the source of the dashboard's typed TS client

- **Status:** accepted
- **Date:** 2026-06-14
- **Ticket:** COL-10

## Context

The Dashboard consumes the Collector's read APIs. FastAPI emits OpenAPI by
default, but its default `operationId`s embed the path and method, so they churn
on unrelated route edits — any code-generated client method names would be
unstable. The project also runs no CI, so the contract's stability and the
client's freshness cannot be enforced by a pipeline; the original COL-10 plan
(artifact upload, CI diff job) does not apply.

## Decision

The committed `argox-project/argox-collector/openapi.json` is the single source
of truth for the Collector ↔ Dashboard contract.

- `create_app` sets `generate_unique_id_function = route.name`, so each
  `operationId` is its handler's function name — unique across routers and
  stable across unrelated edits. These names become the TS client's method
  names.
- Every endpoint declares a tag, a `summary`, and either a response model or,
  for non-JSON replies (OTLP ingest, YAML bundle, 204 revoke), an explicit
  `response_class` + documented `responses`.
- `argox_collector/openapi_export.py` defines the canonical serialization
  (sorted keys, trailing newline) used by both the `argox-collector
  export-openapi` CLI and the contract test, so they never disagree.
- The dashboard regenerates `src/api/schema.ts` from the committed JSON with
  `openapi-typescript` (`pnpm run gen:api`); the file is committed so the build
  is hermetic.
- Drift is caught locally instead of in CI: a `pytest` contract test
  (`tests/test_openapi_contract.py`) fails on schema drift or a missing
  id/tag; `export-openapi --check` and `pnpm run check:api` verify on demand.

## Triggers for the next refactor

- CI is introduced — move the `--check` / `check:api` guards into a pipeline job
  and emit `openapi.json` as a build artifact, as the original ticket envisioned.
- The dashboard needs runtime calls — add a typed fetch layer (e.g.
  `openapi-fetch`) over `schema.ts`; revisit how the base URL is configured.
- Two handlers need the same function name — set an explicit `operation_id` on
  the colliding route rather than abandoning the name-based generator.

## What stays out of scope

- A runtime HTTP client and any wiring of dashboard screens away from
  `mockData.ts`.
- Versioning or backward-compatibility policy for the schema itself.
