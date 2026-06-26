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
- `OTLPSpanExporter` gains a matching `api_key` convenience argument
  (`argox-core/src/argox/observability/otlp.py`): it injects
  `Authorization: Bearer <api_key>` into the upstream exporter's headers (an
  explicit `Authorization` header wins), and warns over a non-HTTPS endpoint,
  resolving the effective endpoint from the `endpoint` argument or the
  `OTEL_EXPORTER_OTLP_*` env vars. This homogenizes auth across all three SDK
  clients that reach authenticated Collector endpoints.

## Why
- The Collector's `GET /api/v1/policies/bundle` requires the `policy-read` scope
  when auth is enabled (COL-09), but `RemotePolicyClient` previously issued
  unauthenticated GETs, so it could only reach a Collector with auth disabled.
- This closes the "SDK policy client does not attach the API key header"
  follow-up noted in the SDK overview, aligning the policy client with the
  existing `api_key` convention on `HttpRunExporter` (EXP-09).

## Notes / follow-ups
- All three SDK clients reaching authenticated Collector endpoints
  (`HttpRunExporter`, `RemotePolicyClient`, `OTLPSpanExporter`) now expose an
  `api_key` argument; auth wiring is homogeneous.
