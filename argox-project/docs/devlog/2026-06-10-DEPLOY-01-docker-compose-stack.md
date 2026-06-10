# [DEPLOY-01] Local Docker Compose stack

- **Date:** 2026-06-10
- **PR:** #130  ·  **Branch:** feat/DEPLOY-01-docker-compose-stack
- **Status:** in-review

## What changed

- `deploy/docker/compose.yaml`: single-command local stack — **Azurite**
  (blob emulator, `azurite-blob` only, `--skipApiVersionCheck`), the
  **Collector** (Azure storage backend pointed at Azurite via the well-known
  dev connection string, DuckDB index at `/data/index.duckdb` on the
  `collector-data` named volume) and the **Dashboard** (nginx). An optional
  **OTel collector sidecar** sits behind the `otel` profile for
  protocol-level inspection (OTLP on 4317/4318, spans dumped to stdout and
  forwarded to the Collector). Healthchecks gate startup order
  (azurite → collector → dashboard); host ports overridable through
  `DASHBOARD_PORT` (default 8080) and `COLLECTOR_PORT` (default 8000).
- `argox-dashboard/Dockerfile` (+ `nginx.conf`, `.dockerignore`): multi-stage
  build — pnpm 11.5.0 activated via corepack, `pnpm run build`, static files
  served by `nginx:1.27-alpine` with an SPA fallback. nginx reverse-proxies
  `/api/` and `/v1/` to `collector:8000`, so browser calls are same-origin
  and the stack needs no CORS (the compose file still sets
  `ARGOX_CORS_ORIGINS` for direct `localhost:8000` access from a Vite dev
  server).
- `argox-collector/Dockerfile`: pre-creates `/data` owned by the `argox`
  user so the named volume inherits writable ownership on first use —
  without it the non-root process cannot create the DuckDB index.
- `deploy/docker/otel/otel-collector-config.yaml`: OTLP receivers, `debug`
  exporter (verbose stdout) and `otlphttp` → `http://collector:8000` with
  `compression: none` (see errors log: the Collector rejects gzip bodies).
- `deploy/docker/seed/trace.json`: demo OTLP/JSON trace (root agent run +
  child LLM call) generated with the protobuf JSON mapping; README explains
  seeding, ports, env vars and volumes.

### Review hardening (post-review, commit 224c803)

- `deploy/docker/compose.yaml`: every published port now binds to
  `127.0.0.1` (collector, azurite, dashboard, otel `4317`/`4318`/`13133`) —
  the stack has no auth (COL-09), so the services must not be reachable from
  the LAN. Pinned the Azurite image to `3.35.0` (was `latest`) and added
  `restart: unless-stopped` to all services.
- `argox-dashboard/nginx.conf`: added `client_max_body_size 10m` so proxied
  OTLP batches match the Collector ingest limit
  (`ARGOX_MAX_PAYLOAD_SIZE`, 10 MB default) instead of being capped at
  nginx's 1 MB default and rejected with 413. The `collector` upstream is now
  resolved at request time via Docker's embedded DNS (`resolver 127.0.0.11`
  + variable `proxy_pass`), so a Collector restart with a new IP no longer
  leaves nginx serving a stale address.

## Why

Issue #96: a one-command stack for development and the TFM demo. Running the
Collector against Azurite rehearses the Azure deployment — same protocol and
SDK as real Blob Storage, so the cloud rollout only swaps the connection
string and provisions a persistent volume for DuckDB.

## Notes / follow-ups

- Verified end-to-end locally: boot on healthchecks, JSON ingest →
  Azurite blob + DuckDB index, query API direct and through the nginx proxy,
  OTLP protobuf through the sidecar, data survives `down`/`up` (volumes).
- The Collector's JSON ingest follows the protobuf JSON mapping (base64
  byte fields), while the OTLP/JSON spec mandates hex `traceId`/`spanId`.
  Spec-compliant JSON senders (e.g. the OTel collector exporter in JSON
  mode) would be rejected; protobuf senders are unaffected. Worth a
  follow-up ticket on COL-03's parser.
- Collector does not decompress gzip request bodies (400) — acceptable
  locally (sidecar sets `compression: none`), but SDK exporters often
  default to gzip; consider supporting `Content-Encoding: gzip` on ingest.
- No auth (COL-09) — stack is local-only by design and now enforced via
  loopback-only port bindings; the next step is the Azure deployment
  (Container Apps, ingress restricted until COL-09).
