# Argox local Docker stack (DEPLOY-01)

Single-command local stack for development and the TFM demo: the **Collector**
(FastAPI + DuckDB), the **Dashboard** (Vite build served by nginx) and
**Azurite** (Azure Blob Storage emulator), plus an optional **OTel collector**
sidecar for protocol-level inspection.

## Usage

```bash
cd deploy/docker
docker compose up --build              # core stack
docker compose --profile otel up --build   # core stack + OTel sidecar
```

First build takes a few minutes (Python deps for the Collector, pnpm install
for the Dashboard). Stop with `docker compose down`; add `-v` to also wipe the
persisted DuckDB index and Azurite blobs.

## Services and ports

All ports are published on `127.0.0.1` only — the stack has no authentication
(COL-09), so nothing is reachable beyond the host.

| Service | Host port | What |
|---|---|---|
| dashboard | `127.0.0.1:8080` (override: `DASHBOARD_PORT=8088 docker compose up`) | Dashboard UI; nginx also proxies `/api/` and `/v1/` to the Collector (same-origin, no CORS needed) |
| collector | `127.0.0.1:8000` (override: `COLLECTOR_PORT`) | Collector API: `/healthz`, `/readyz`, `/v1/traces` (OTLP ingest), `/api/v1/*` (query, policies), `/docs` (OpenAPI UI) |
| azurite | `127.0.0.1:10000` | Azurite blob endpoint (account `devstoreaccount1`, well-known dev key) |
| otel-collector | `127.0.0.1:4317` / `4318` | OTLP gRPC / HTTP receivers (profile `otel` only) |
| otel-collector | `127.0.0.1:13133` | health_check extension (the image is distroless, so probe from the host: `curl localhost:13133`) |

Startup order is enforced with `depends_on` + healthchecks:
azurite → collector → dashboard (and the otel sidecar after the collector).

## Environment variables

All Collector settings come from `ARGOX_*` variables (see
`argox-project/argox-collector/src/argox_collector/settings.py`). The compose
file sets:

| Variable | Value | Why |
|---|---|---|
| `ARGOX_STORAGE_BACKEND` | `azure` | Blobs go to Azurite — same protocol as real Azure Blob Storage, so the stack rehearses the cloud deployment |
| `ARGOX_STORAGE_AZURE_CONNECTION_STRING` | Azurite well-known dev credentials | Public documented values, not a secret; swap for a real connection string to target Azure |
| `ARGOX_STORAGE_AZURE_CONTAINER` | `argox` | Created lazily on first write |
| `ARGOX_INDEX_DUCKDB_PATH` | `/data/index.duckdb` | On the `collector-data` named volume so the index survives restarts |
| `ARGOX_CORS_ORIGINS` | `http://localhost:8080,http://localhost:5173` | Lets the dashboard (or a local Vite dev server) call `localhost:8000` directly, bypassing the nginx proxy |

## Volumes

| Volume | Mount | Persists |
|---|---|---|
| `collector-data` | `/data` in collector | DuckDB trace index |
| `azurite-data` | `/data` in azurite | Blob payloads (span batches, policies) |

## Seed data

`seed/trace.json` contains one OTLP/JSON trace (a root agent run plus a child
LLM call, generated with the OTLP protobuf JSON mapping — byte fields such as
`traceId` are base64, per the proto3 JSON spec). With the stack up:

```bash
curl -s -X POST http://localhost:8000/v1/traces \
  -H "Content-Type: application/json" \
  --data @seed/trace.json

curl -s http://localhost:8000/api/v1/traces | python3 -m json.tool
```

The trace then shows up in the dashboard at <http://localhost:8080> and the
span batch lands in Azurite under the `argox` container. For richer data, run
anything from `argox-project/examples/` with
`OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:8000` (or `:4318` to go through
the OTel sidecar and watch the spans in its stdout).

Note: `seed/trace.json` only works against the Collector's `/v1/traces`.
The OTel sidecar's receiver follows the OTLP/JSON spec (hex-encoded
`traceId`/`spanId`), while this file uses the protobuf JSON mapping (base64)
that the Collector parses — send OTLP protobuf (the SDK default) when going
through the sidecar.

## Notes

- **No authentication yet** (COL-09, #94): the stack is for local use only.
  Every port is bound to `127.0.0.1`, so the services are not reachable from
  the LAN; do not change the bindings to `0.0.0.0` until auth lands.
- The Collector runs a single replica by design — DuckDB allows one writer
  (multi-replica index is COL-15, #123).
- nginx resolves the `collector` hostname at request time via Docker's
  embedded DNS, so the dashboard container only works inside this compose
  network.
