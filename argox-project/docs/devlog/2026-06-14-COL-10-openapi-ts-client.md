# [COL-10] OpenAPI contract and typed TS client pipeline

- **Date:** 2026-06-14
- **PR:** #136  ·  **Branch:** feat/COL-10-openapi-ts-client
- **Status:** in-review

## What changed
- `create_app` now sets `generate_unique_id_function` (`app.py`) so every
  OpenAPI `operationId` equals its route handler's function name — stable,
  unique, and the source of the generated TS client method names.
- Every Collector endpoint gained an explicit tag and `summary`. The three
  non-JSON replies are documented with `response_class` + `responses`: the OTLP
  trace ingest (`routers/traces.py`), the YAML policy bundle
  (`routers/policies.py`), and the 204 key revoke (`routers/keys.py`).
- New `argox_collector/openapi_export.py` holds the canonical serializer
  (`render_openapi`, sorted keys + trailing newline) and the committed contract
  path, shared by the CLI and the test so they cannot disagree.
- New `export-openapi [--out] [--check]` CLI subcommand (`__main__.py`) writes
  or verifies `argox-collector/openapi.json` (committed, 1997 lines).
- New `tests/test_openapi_contract.py`: fails if the committed schema drifts
  from the live one, or if any operation lacks a unique id or a tag.
- Dashboard: added `openapi-typescript` dev dependency plus `gen:api` /
  `check:api` scripts; committed the generated `src/api/schema.ts` and an
  `src/api/index.ts` re-export.
- Contribution flow documented in `docs/collector/openapi.md`.

## Why
Locks the Collector ↔ Dashboard contract so the typed client cannot silently
drift from the API. The committed `openapi.json` is the single source of truth;
the dashboard build is hermetic (codegen reads the file, no running Collector).
Decision recorded in [ADR-0006](../architecture/ADR-0006-openapi-contract-and-ts-client.md).

## Notes / follow-ups
- The project runs no CI, so drift detection is local: `pytest` (collector) and
  `pnpm run check:api` (dashboard), with `export-openapi --check` on demand.
- Out of scope: a runtime fetch wrapper (e.g. `openapi-fetch`) and wiring
  dashboard screens off `mockData.ts` — they still use mock data.
