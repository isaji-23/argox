# [POL-05] Authenticate RemotePolicyClient policy fetches with an API key

- **Date:** 2026-06-26
- **PR:** (pending)  ·  **Branch:** dev
- **Status:** in-review

## What changed
- `RemotePolicyClient.__init__` gains an optional `api_key` argument
  (`argox-core/src/argox/policies/remote_client.py`). When set, every policy
  fetch — eager fetch in `start()` and each `_poll_loop()` poll — sends
  `Authorization: Bearer <api_key>`.
- Added `_auth_headers()` helper returning the Bearer header (or `{}` when no
  key); `start()` now builds the `httpx.AsyncClient` with those headers so the
  single client carries auth across its lifetime.
- A non-HTTPS endpoint combined with an `api_key` logs a plaintext-exposure
  warning, mirroring `HttpRunExporter`.
- Tests: new `TestRemotePolicyClientAuth` covering header presence/absence,
  header propagation into the client, and the HTTPS/plaintext warning.

## Why
- The Collector's `GET /api/v1/policies/bundle` requires the `policy-read` scope
  when auth is enabled (COL-09), but `RemotePolicyClient` previously issued
  unauthenticated GETs, so it could only reach a Collector with auth disabled.
- This closes the "SDK policy client does not attach the API key header"
  follow-up noted in the SDK overview, aligning the policy client with the
  existing `api_key` convention on `HttpRunExporter` (EXP-09).

## Notes / follow-ups
- `OTLPSpanExporter` still has no convenience `api_key` argument; its
  `/v1/traces` ingest (`ingest` scope) must be authenticated via the OTel-native
  `headers=` kwarg or `OTEL_EXPORTER_OTLP_HEADERS`. Left as a deliberate gap to
  avoid wrapping the upstream exporter.
- Work was done directly on `dev` (uncommitted at doc time); move to a
  `fix/POL-05-...` branch before opening the PR.
