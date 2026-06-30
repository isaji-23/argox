# Argox Docker stack (DEPLOY-01)

One Compose file, two targets:

- **Local** — Collector (FastAPI + DuckDB), Dashboard (Vite build on nginx) and
  **Azurite** (Azure Blob emulator), with an optional **OTel collector** sidecar.
- **Azure** — the same Collector and Dashboard images against a **real Azure
  Blob Storage** account, importable into **Azure Container Apps**.

Authentication (COL-09) is **on**: every endpoint except `/healthz` and
`/readyz` needs a bearer credential. The Collector stays private (published only
inside the Compose/ACA network); the browser only ever talks to the Dashboard,
which reverse-proxies the API same-origin.

## Quick start (local)

```bash
cd deploy/docker
cp .env.example .env                         # ships with Azurite dev defaults
docker compose --profile local up --build    # Azurite + Collector + Dashboard
docker compose --profile local --profile otel up --build   # + OTel sidecar
```

Open the Dashboard at <http://localhost:8080>. First build takes a few minutes.
Stop with `docker compose --profile local down`; add `-v` to also wipe the
DuckDB index and Azurite blobs.

> The `local` profile starts Azurite. Without it (`docker compose up`), the
> Collector expects a **real** Azure connection string in `.env` — see below.

## Configuration (`.env`)

All Collector settings are `ARGOX_*` variables (see
`argox-project/argox-collector/src/argox_collector/settings.py`). Copy
`.env.example` to `.env` and edit. `.env` is gitignored — never commit secrets.

| Variable | Local default | Azure |
|---|---|---|
| `ARGOX_STORAGE_AZURE_CONNECTION_STRING` | Azurite well-known dev string (public, not a secret) | Real Storage account string (wire as a secret on ACA) |
| `ARGOX_STORAGE_AZURE_CONTAINER` | `argox` | created lazily on first write |
| `ARGOX_BOOTSTRAP_ADMIN_KEY` | dev value | strong random value (`openssl rand -hex 32`) |
| `ARGOX_OIDC_ISSUER` / `_AUDIENCE` / `_JWKS_URI` | blank (API keys only) | Microsoft Entra ID values to enable dashboard SSO |
| `ARGOX_CORS_ORIGINS` | blank | blank unless a browser calls the Collector cross-origin |
| `COLLECTOR_UPSTREAM` | `http://collector:8000` | `http://collector` on ACA (internal ingress, port 80) |
| `DASHBOARD_PORT` / `DASHBOARD_BIND` | `8080` / `127.0.0.1` | — |

`ARGOX_STORAGE_BACKEND=azure` and `ARGOX_AUTH_ENABLED=true` are pinned in the
Compose file, not the `.env`.

## Services and ports

| Service | Exposure | What |
|---|---|---|
| dashboard | published on `${DASHBOARD_BIND}:${DASHBOARD_PORT}` (default `127.0.0.1:8080`) | UI; nginx proxies `/api/` and `/v1/` to the Collector |
| collector | **internal only** (`expose: 8000`, not host-published) | API: `/healthz`, `/readyz`, `/v1/traces` (OTLP ingest), `/api/v1/*`, `/docs` |
| azurite | `127.0.0.1:10000` (profile `local`) | Blob endpoint (`devstoreaccount1`, well-known dev key) |
| otel-collector | `127.0.0.1:4317`/`4318`/`13133` (profile `otel`) | OTLP gRPC/HTTP receivers + health probe |

The Collector is no longer published to the host by default. To reach it
directly for local debugging (e.g. the seed below), uncomment the loopback
`ports` mapping under `collector` in `compose.yaml`.

## Volumes

| Volume | Mount | Persists |
|---|---|---|
| `collector-data` | `/data` in collector | DuckDB trace index |
| `azurite-data` | `/data` in azurite | Blob payloads (profile `local` only) |

## Minting the first API key

Auth is on, so calls need a bearer token. The break-glass
`ARGOX_BOOTSTRAP_ADMIN_KEY` is accepted directly and can mint a real key
(key CRUD is admin-only). With the Collector's `ports` mapping uncommented:

```bash
curl -s -X POST http://localhost:8000/api/v1/keys \
  -H "Authorization: Bearer $ARGOX_BOOTSTRAP_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"seed","scopes":["read","ingest"]}'
```

(See `argox-project/docs/collector/auth.md` for scopes and OIDC details.)

## Seed data

`seed/trace.json` is one OTLP/JSON trace (root agent run + child LLM call,
protobuf-JSON mapping — byte fields like `traceId` are base64). Ingest needs a
bearer token now. Through the Dashboard proxy (no Collector port needed):

```bash
curl -s -X POST http://localhost:8080/v1/traces \
  -H "Authorization: Bearer $ARGOX_BOOTSTRAP_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  --data @seed/trace.json
```

It then shows in the Dashboard at <http://localhost:8080> and the span batch
lands in Azurite under `argox`. For richer data, run anything in
`argox-project/examples/` with `OTEL_EXPORTER_OTLP_ENDPOINT` pointed at the
Collector and an auth header configured on the exporter.

Note: `seed/trace.json` only works against the Collector's `/v1/traces`. The
OTel sidecar's receiver expects OTLP/JSON (hex `traceId`/`spanId`); send OTLP
protobuf (the SDK default) when going through `:4318`.

## Deploy to Azure Container Apps

The default (no-profile) services are authored for ACA import. Azurite carries
the `local` profile, so it is left out.

```bash
az containerapp compose create \
  -g <resource-group> --environment <aca-environment> \
  -f compose.yaml \
  --registry-server <registry>.azurecr.io   # push the built images first
```

Import is **lossy** — it cannot express several things this stack needs. After
import, apply them with `az`:

1. **Persistent DuckDB index.** A named volume does not map to ACA. Create an
   Azure Files share, attach it to the environment, and mount it at `/data` on
   the `collector` app:
   ```bash
   az containerapp env storage set -g <rg> -n <env> --storage-name argox-data \
     --azure-file-account-name <acct> --azure-file-account-key <key> \
     --azure-file-share-name argox-index --access-mode ReadWrite
   # then add the volume + volumeMount to the collector app (YAML update).
   ```
   Without this the index is ephemeral and resets on every revision/restart.

2. **Single replica.** DuckDB allows one writer (multi-replica is COL-15), so
   pin the Collector and disable scale-to-zero:
   ```bash
   az containerapp update -g <rg> -n collector --min-replicas 1 --max-replicas 1
   ```

3. **Collector ingress = internal.** Keep the API off the public internet; only
   the Dashboard should reach it:
   ```bash
   az containerapp ingress update -g <rg> -n collector --type internal --target-port 8000
   az containerapp ingress update -g <rg> -n dashboard --type external --target-port 80
   ```
   Set `COLLECTOR_UPSTREAM=http://collector` on the Dashboard app so nginx
   proxies to the Collector's internal ingress (port 80, not 8000).

4. **Secrets.** Store the connection string, bootstrap key and any OIDC values
   as ACA secrets and reference them, instead of literal env values:
   ```bash
   az containerapp secret set -g <rg> -n collector \
     --secrets storage-conn=<string> admin-key=<key>
   az containerapp update -g <rg> -n collector --set-env-vars \
     ARGOX_STORAGE_AZURE_CONNECTION_STRING=secretref:storage-conn \
     ARGOX_BOOTSTRAP_ADMIN_KEY=secretref:admin-key
   ```

Notes:
- Apps in one ACA environment resolve each other by name (`http://collector`).
  nginx resolves `COLLECTOR_UPSTREAM` when it starts, so the `collector` app
  must exist for the Dashboard to boot; on first deploy the Dashboard restarts
  until the Collector is up (Compose enforces this locally via `depends_on`).
- Prefer a real Storage account connection string; **Managed Identity is not
  yet supported** by the Collector's storage backend (it only builds a client
  via `from_connection_string`).
- TLS/HTTPS is handled by ACA ingress automatically for the external Dashboard.
