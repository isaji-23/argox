# [COL-16] Install azure extra in Docker image and add configurable CORS

- **Date:** 2026-06-10
- **PR:** #129  ·  **Branch:** fix/COL-16-docker-azure-extra-cors
- **Status:** in-review

## What changed

- `argox-collector/Dockerfile` now installs `".[azure]"` instead of `.`, so
  the image bundles `azure-storage-blob`. Before this, a container started
  with `ARGOX_STORAGE_BACKEND=azure` failed at startup with
  `StorageError: azure-storage-blob is required` because the SDK is an
  optional extra and the lazy import in `storage/azure.py` had nothing to
  import.
- `CollectorSettings` (`settings.py`) gained `cors_origins: str = ""`
  (env var `ARGOX_CORS_ORIGINS`), a comma-separated list of allowed browser
  origins. It is kept as a plain string — not `list[str]` — so the value maps
  to a single environment variable without pydantic-settings' JSON decoding
  rules; the parsed form is exposed as the `cors_origin_list` property
  (splits on commas, strips whitespace, drops blanks).
- `create_app` (`app.py`) adds Starlette's `CORSMiddleware` only when at
  least one origin is configured, with `allow_methods=["*"]` and
  `allow_headers=["*"]` restricted to the listed origins. The empty default
  keeps same-origin deployments free of any CORS headers, and credentials
  remain disallowed (middleware default) since auth will use bearer
  headers, not cookies (COL-09).
- Tests: `tests/test_cors.py` (10 tests) covering origin parsing
  (whitespace, blanks, blank-like values), disabled-by-default behaviour,
  preflight accept and reject, and the simple-request response header.

## Why

Both defects block any non-local deployment (the immediate goal is Azure
Container Apps): the published image could not talk to Azure Blob Storage
at all, and a dashboard served from a different origin — `localhost:5173`
during development or a static host later — cannot call the API without
CORS headers.

## Notes / follow-ups

- Auth (COL-09, #94) is still the remaining blocker for exposing the
  Collector publicly; until it lands, remote deployments must restrict
  ingress (IP allowlist or internal-only).
- The DuckDB index file still requires a persistent volume and a single
  replica in remote deployments (multi-replica index is COL-15, #123).
- DEPLOY-01 (#96, local Docker Compose stack) can reuse the fixed image and
  the `ARGOX_CORS_ORIGINS` contract unchanged.
