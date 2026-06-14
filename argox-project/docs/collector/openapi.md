# Collector OpenAPI contract & TypeScript client

The Collector ↔ Dashboard contract is locked by a committed OpenAPI schema and a
typed TypeScript client generated from it. Both files are checked into the
repository so the dashboard build is hermetic (no running Collector required) and
the contract can never drift silently.

| Artifact | Path | Role |
|---|---|---|
| OpenAPI schema | `argox-project/argox-collector/openapi.json` | Single source of truth |
| Typed TS client | `argox-dashboard/src/api/schema.ts` | Generated types (`paths`, `components`, `operations`) |
| Client exports | `argox-dashboard/src/api/index.ts` | Re-exports the generated types |

> **No CI.** This project intentionally runs no CI pipeline. The drift checks
> below are run locally before opening a PR. The collector check also rides the
> mandatory `pytest` gate.

## Schema stability

- **Operation IDs** are derived from each route handler's function name via
  `generate_unique_id_function` in `create_app` (`src/argox_collector/app.py`).
  They become the TypeScript client's method names, so they stay stable across
  unrelated code edits — the client only changes when the contract really does.
- **Every endpoint** carries an explicit response model (or documented
  `responses` for non-JSON replies such as the OTLP trace ingest, the YAML
  policy bundle, and the 204 key revoke), a tag, and a summary.

## Contribution flow

When you add or change a Collector endpoint:

1. Annotate the endpoint: response model, tag, and `summary`. Give the handler a
   unique, descriptive function name (it becomes the `operationId`).
2. Regenerate the committed schema:
   ```bash
   cd argox-project/argox-collector
   argox-collector export-openapi
   ```
3. Regenerate the typed client:
   ```bash
   cd argox-dashboard
   pnpm run gen:api
   ```
4. Commit `openapi.json` and `src/api/schema.ts` together in the same change.

## Drift guards

- **Collector** — `pytest` runs `tests/test_openapi_contract.py`, which fails if
  `openapi.json` is out of sync with the live schema, or if any operation lacks a
  unique `operationId` or a tag. A non-test check is also available:
  ```bash
  argox-collector export-openapi --check   # exit 1 on drift, writes nothing
  ```
- **Dashboard** — verify the committed client matches the schema:
  ```bash
  cd argox-dashboard
  pnpm run check:api   # regenerates to a temp file and diffs; non-zero on drift
  ```
